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

    # Market feed — only starts when Dhan credentials are configured
    tick_router_task = None
    if settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN:
        from pdp.market.dhan_ws import DhanTickerAdapter
        from pdp.market.router import TickRouter

        adapter = DhanTickerAdapter(settings.DHAN_CLIENT_ID, settings.DHAN_ACCESS_TOKEN)
        app.state.dhan_adapter = adapter
        async with get_session_maker()() as session:
            await adapter.start(session)
        tick_router = TickRouter()
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
            app.state.tick_router.stop()
            tick_router_task.cancel()
            try:
                await tick_router_task
            except asyncio.CancelledError:
                pass
        await app.state.redis.aclose()
        await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="PDP", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)

    from pdp.instruments.routes import router as instruments_router
    from pdp.market.routes import router as market_router

    app.include_router(instruments_router)
    app.include_router(market_router)

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
