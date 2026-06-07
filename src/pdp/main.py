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
from pdp.mongo.client import connect as mongo_connect
from pdp.mongo.client import disconnect as mongo_disconnect
from pdp.mongo.collections import init_collections
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
    mongo_client, mongo_db = mongo_connect(settings)
    app.state.mongo_client = mongo_client
    app.state.mongo_db = mongo_db
    await init_collections(mongo_db, settings)
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
    from pdp.options.hub import OptionsHub
    from pdp.orders.ws import OrdersHub
    from pdp.portfolio.hub import PortfolioHub
    from pdp.portfolio.service import PortfolioService

    ws_hub = WSHub()
    app.state.ws_hub = ws_hub
    orders_hub = OrdersHub()
    app.state.orders_hub = orders_hub
    options_hub = OptionsHub()
    app.state.options_hub = options_hub
    portfolio_hub = PortfolioHub()
    app.state.portfolio_hub = portfolio_hub

    # Paper broker + order router — always started (no external credentials needed)
    from pdp.orders.paper import PaperBroker
    from pdp.orders.router import OrderRouter

    paper_broker = PaperBroker(get_session_maker(), settings.PAPER_SLIPPAGE_BPS)
    paper_broker.set_hub(orders_hub)
    await paper_broker.start(app.state.redis)

    # Live Dhan broker — only when explicitly enabled and credentialed (paper-first).
    dhan_broker = None
    if settings.LIVE and settings.BROKER == "dhan" and settings.DHAN_CLIENT_ID:
        from pdp.orders.dhan_broker import DhanBroker

        dhan_broker = DhanBroker(get_session_maker(), settings)
        dhan_broker.set_hub(orders_hub)
        await dhan_broker.start(app.state.redis)
        log.info("dhan_broker_enabled", client_id=settings.DHAN_CLIENT_ID)
    else:
        log.info(
            "dhan_broker_disabled",
            live=settings.LIVE,
            broker=settings.BROKER,
            has_credentials=bool(settings.DHAN_CLIENT_ID),
        )

    order_router = OrderRouter(settings, paper_broker, dhan_broker)
    app.state.order_router = order_router

    # Strategy host — always started; loads YAML configs from ./strategies/
    from pathlib import Path

    from pdp.strategy.host import StrategyHost

    strategy_host = StrategyHost(
        strategies_dir=Path("strategies"),
        order_router=order_router,
        session_maker=get_session_maker(),
    )
    strategy_host.load_registry()
    app.state.strategy_host = strategy_host

    # Market feed — only starts when Dhan credentials are configured
    tick_router_task = None
    bar_writer = None
    if settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN:
        from pdp.market.bar_writer import BarWriter
        from pdp.market.bars import BarAggregator
        from pdp.market.dhan_ws import DhanTickerAdapter
        from pdp.market.router import TickRouter

        bar_aggregator = BarAggregator()
        bar_writer = BarWriter(app.state.mongo_db["market_bars"])
        await bar_writer.start()

        adapter = DhanTickerAdapter(settings.DHAN_CLIENT_ID, settings.DHAN_ACCESS_TOKEN)
        app.state.dhan_adapter = adapter
        async with get_session_maker()() as session:
            await adapter.start(session)
        tick_router = TickRouter(
            bar_aggregator=bar_aggregator,
            bar_writer=bar_writer,
            ws_hub=ws_hub,
            strategy_host=strategy_host,
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

    # Portfolio service — always started (works in paper and live mode)
    portfolio_service = PortfolioService(
        redis=app.state.redis,
        engine=get_engine(),
        hub=portfolio_hub,
        settings=settings,
        mongo_db=mongo_db,
    )
    await portfolio_service.start()
    app.state.portfolio_service = portfolio_service
    portfolio_service.subscribe_fill_events(orders_hub)
    strategy_host.subscribe_fill_events(orders_hub)

    # Options chain poller — only when live and credentialed
    options_poller = None
    if settings.LIVE and settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN:
        from pdp.options.poller import OptionsChainPoller

        options_poller = OptionsChainPoller(
            collection=app.state.mongo_db["option_chains"],
            hub=options_hub,
            settings=settings,
        )
        app.state.options_poller = options_poller
        await options_poller.start()
        log.info("options_poller_enabled")
    else:
        app.state.options_poller = None
        log.info("options_poller_disabled", live=settings.LIVE, has_credentials=bool(settings.DHAN_CLIENT_ID))

    try:
        yield
    finally:
        log.info("app_shutting_down")
        await portfolio_service.stop()
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
        if options_poller is not None:
            await options_poller.stop()
        if dhan_broker is not None:
            await dhan_broker.stop()
        await paper_broker.stop()
        await app.state.redis.aclose()
        mongo_disconnect(app.state.mongo_client)
        await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="PDP", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)

    from pdp.instruments.routes import router as instruments_router
    from pdp.market.routes import router as market_router
    from pdp.market.ws import ws_router
    from pdp.options.routes import router as options_router
    from pdp.options.ws import options_ws_router
    from pdp.orders.routes import router as orders_router
    from pdp.orders.ws import orders_ws_router
    from pdp.portfolio.routes import router as portfolio_router
    from pdp.portfolio.ws import portfolio_ws_router
    from pdp.strategy.routes import router as strategy_router

    app.include_router(instruments_router)
    app.include_router(market_router)
    app.include_router(ws_router)
    app.include_router(options_router)
    app.include_router(options_ws_router)
    app.include_router(orders_router)
    app.include_router(orders_ws_router)
    app.include_router(portfolio_router)
    app.include_router(portfolio_ws_router)
    app.include_router(strategy_router)

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
        from fastapi.responses import JSONResponse

        db_state = "ok"
        redis_state = "ok"
        mongo_state = "ok"
        try:
            async with get_engine().begin() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            db_state = f"error: {exc.__class__.__name__}"
        try:
            await app.state.redis.ping()
        except Exception as exc:
            redis_state = f"error: {exc.__class__.__name__}"
        try:
            await app.state.mongo_db.command("ping")
        except Exception as exc:
            mongo_state = f"error: {exc.__class__.__name__}"
        all_ok = db_state == "ok" and redis_state == "ok" and mongo_state == "ok"
        return JSONResponse(
            status_code=200 if all_ok else 503,
            content={
                "status": "ready" if all_ok else "degraded",
                "db": db_state,
                "redis": redis_state,
                "mongo": mongo_state,
            },
        )

    return app


app = create_app()
