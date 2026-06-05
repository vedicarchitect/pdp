from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import redis.asyncio as redis_asyncio
import structlog
from fastapi import FastAPI
from sqlalchemy import text

from pdp.db.session import dispose_engine, get_engine, get_session_maker
from pdp.logging import RequestIdMiddleware, configure_logging
from pdp.settings import Settings, get_settings

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    started_at = datetime.now(UTC)
    app.state.started_at = started_at
    app.state.settings = settings
    app.state.redis = redis_asyncio.from_url(settings.REDIS_URL, decode_responses=True)
    log.info(
        "app_starting",
        app=settings.APP_NAME,
        env=settings.ENV,
        live=settings.LIVE,
        broker=settings.BROKER,
        git_sha=settings.GIT_SHA,
    )

    # WebSocket hubs — always available
    from pdp.market.ws import WSHub
    from pdp.orders.ws import OrdersHub

    ws_hub = WSHub()
    app.state.ws_hub = ws_hub
    orders_hub = OrdersHub()
    app.state.orders_hub = orders_hub

    # Paper broker + order router — always started (no external credentials needed)
    from pdp.orders.paper import PaperBroker
    from pdp.orders.router import OrderRouter

    paper_broker = PaperBroker(get_session_maker(), settings.PAPER_SLIPPAGE_BPS)
    paper_broker.set_hub(orders_hub)
    order_router = OrderRouter(settings, paper_broker)
    app.state.order_router = order_router

    await paper_broker.start(app.state.redis)

    # Market feed — only starts when Dhan credentials are configured
    tick_router_task = None
    bar_writer = None
    if settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN:
        from pdp.market.bar_writer import BarWriter
        from pdp.market.bars import BarAggregator
        from pdp.market.dhan_ws import DhanTickerAdapter
        from pdp.market.router import TickRouter

        bar_aggregator = BarAggregator()
        # Convert SQLAlchemy asyncpg URL → raw asyncpg DSN
        asyncpg_dsn = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
        bar_writer = BarWriter(asyncpg_dsn)
        await bar_writer.start()

        adapter = DhanTickerAdapter(settings.DHAN_CLIENT_ID, settings.DHAN_ACCESS_TOKEN)
        app.state.dhan_adapter = adapter
        async with get_session_maker()() as session:
            await adapter.start(session)
        tick_router = TickRouter(
            bar_aggregator=bar_aggregator,
            bar_writer=bar_writer,
            ws_hub=ws_hub,
        )
        app.state.tick_router = tick_router
        tick_router_task = asyncio.create_task(
            tick_router.run(adapter.queue, app.state.redis),
            name="tick-router",
        )
        log.info("market_feed_started", client_id=settings.DHAN_CLIENT_ID)
    else:
        app.state.dhan_adapter = None
        log.info("market_feed_skipped", reason="DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN not set")

    try:
        yield
    finally:
        log.info("app_shutting_down")
        if tick_router_task is not None:
            adapter = app.state.dhan_adapter
            if adapter:
                await adapter.stop()
            await app.state.tick_router.stop()
            tick_router_task.cancel()
            try:
                await tick_router_task
            except asyncio.CancelledError:
                pass
        if bar_writer is not None:
            await bar_writer.stop()
        await paper_broker.stop()
        await app.state.redis.aclose()
        await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="PDP", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)

    from pdp.instruments.routes import router as instruments_router
    from pdp.market.routes import router as market_router
    from pdp.market.ws import ws_router
    from pdp.orders.routes import router as orders_router
    from pdp.orders.ws import orders_ws_router

    app.include_router(instruments_router)
    app.include_router(market_router)
    app.include_router(ws_router)
    app.include_router(orders_router)
    app.include_router(orders_ws_router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        settings = get_settings()
        return {
            "status": "ok",
            "app": settings.APP_NAME,
            "git_sha": settings.GIT_SHA,
            "started_at": app.state.started_at.isoformat(),
        }

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        db_state = "ok"
        redis_state = "ok"
        try:
            async with get_engine().begin() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            db_state = f"error: {exc.__class__.__name__}"
        try:
            await app.state.redis.ping()
        except Exception as exc:
            redis_state = f"error: {exc.__class__.__name__}"
        status_code = 200 if db_state == "ok" and redis_state == "ok" else 503
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ready" if status_code == 200 else "degraded",
                "db": db_state,
                "redis": redis_state,
            },
        )

    return app


app = create_app()
