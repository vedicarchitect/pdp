from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import redis.asyncio as redis_asyncio
import structlog
from fastapi import FastAPI
from sqlalchemy import text

from pdp.db.session import dispose_engine, get_engine, get_session_maker
from pdp.logging import RequestIdMiddleware, configure_logging, truncate_errors_jsonl
from pdp.mongo.client import connect as mongo_connect
from pdp.mongo.client import disconnect as mongo_disconnect
from pdp.mongo.collections import init_collections
from pdp.settings import Settings, get_settings

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from pdp.runtime.groups import GROUPS_BY_ROLE

    # Emitted before any group starts (and before configure_logging() re-configures structlog's
    # processors), so a restart is attributable from `app_start` alone — no /healthz polling.
    log.info(
        "app_start",
        started_at=datetime.now(UTC).isoformat(),
        reload="--reload" in sys.argv,
    )

    settings = get_settings()
    role = getattr(settings, "PDP_ROLE", "all")
    group_classes = GROUPS_BY_ROLE.get(role, GROUPS_BY_ROLE["all"])
    
    groups = [g() for g in group_classes]
    started = []
    
    for group in groups:
        try:
            log.info("starting_group", group=group.name)
            await group.start(app)
            started.append(group)
        except Exception as exc:
            required = getattr(group, "required", False)
            log.error("group_start_failed", group=group.name, required=required, exc=str(exc))
            if required:
                # A live-trading group is dead. Serving traffic now yields a healthy-looking API
                # with a silently broken subsystem — refuse to start instead.
                for g in reversed(started):
                    try:
                        await g.stop(app)
                    except Exception as stop_exc:
                        log.error("group_stop_failed", group=g.name, exc=str(stop_exc))
                raise
            # Non-critical groups stay fault-isolated.


    try:
        yield
    finally:
        for group in reversed(started):
            try:
                log.info("stopping_group", group=group.name)
                await group.stop(app)
            except Exception as exc:
                log.error("group_stop_failed", group=group.name, exc=str(exc))


def create_app() -> FastAPI:
    import structlog as _sl
    from fastapi import Request
    from fastapi.responses import JSONResponse

    _exc_log = _sl.get_logger()

    app = FastAPI(title="PDP", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(Exception)
    async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        import traceback

        request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID", "")
        _exc_log.error(
            "unhandled_exception",
            exc_type=type(exc).__name__,
            exc_message=str(exc),
            request_id=request_id,
            path=str(request.url.path),
            traceback=traceback.format_exc(),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "request_id": request_id,
                }
            },
        )

    from pdp.alerts.routes import router as alerts_router
    from pdp.alerts.ws import alerts_ws_router
    from pdp.backtest.routes import router as backtest_router
    from pdp.backtest.warehouse_routes import router as strangle_bt_router
    from pdp.broker_sync.routes import router as broker_sync_router
    from pdp.events.routes import events_ws_router
    from pdp.events.routes import router as events_router
    from pdp.housekeeping.routes import router as housekeeping_router
    from pdp.instruments.routes import router as instruments_router
    from pdp.intel.dashboard_routes import router as dashboard_router
    from pdp.intel.routes import router as intel_router
    from pdp.jobs.routes import router as jobs_router
    from pdp.jobs.ws import router as jobs_ws_router
    from pdp.journal.routes import router as journal_router
    from pdp.market.routes import router as market_router
    from pdp.market.ws import ws_router
    from pdp.ml.routes import router as ml_router
    from pdp.observability.ingest import router as logs_ingest_router
    from pdp.observability.routes import router as observability_router
    from pdp.options.routes import router as options_router
    from pdp.options.ws import options_ws_router
    from pdp.orders.routes import router as orders_router
    from pdp.orders.ws import orders_ws_router
    from pdp.portfolio.routes import router as portfolio_router
    from pdp.portfolio.ws import portfolio_ws_router
    from pdp.positional.routes import router as positional_router
    from pdp.risk.routes import risk_router, settings_router
    from pdp.screener.routes import screener_router
    from pdp.strategy.routes import levels_router, strangle_router
    from pdp.strategy.routes import router as strategy_router
    from pdp.warehouse.routes import router as coverage_router

    app.include_router(alerts_router)
    app.include_router(alerts_ws_router)
    app.include_router(events_router)
    app.include_router(events_ws_router)
    app.include_router(instruments_router)
    app.include_router(journal_router)
    app.include_router(market_router)
    app.include_router(ws_router)
    app.include_router(options_router)
    app.include_router(options_ws_router)
    app.include_router(orders_router)
    app.include_router(orders_ws_router)
    app.include_router(portfolio_router)
    app.include_router(portfolio_ws_router)
    app.include_router(positional_router)
    app.include_router(risk_router)
    app.include_router(settings_router)
    app.include_router(strategy_router)
    app.include_router(strangle_router)
    app.include_router(levels_router)
    app.include_router(backtest_router)
    app.include_router(strangle_bt_router)
    app.include_router(jobs_router, prefix="/api/v1/jobs", tags=["Jobs"])
    app.include_router(jobs_ws_router, prefix="/ws/jobs", tags=["Jobs WS"])
    app.include_router(ml_router, prefix="/api/v1/ml", tags=["ML"])
    app.include_router(housekeeping_router, prefix="/api/v1/housekeeping", tags=["Housekeeping"])
    app.include_router(broker_sync_router)
    app.include_router(intel_router, prefix="/api/v1/intel", tags=["Intel"])
    app.include_router(dashboard_router)
    app.include_router(logs_ingest_router)
    app.include_router(observability_router)
    app.include_router(screener_router)
    app.include_router(coverage_router)

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
        engine_state = "unknown"
        try:
            async with get_engine().begin() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            db_state = f"error: {exc.__class__.__name__}"
        try:
            await app.state.redis.ping()
            val = await app.state.redis.get("engine:status")
            engine_state = val if val else "down"
        except Exception as exc:
            redis_state = f"error: {exc.__class__.__name__}"
        try:
            await app.state.mongo_db.command("ping")
        except Exception as exc:
            mongo_state = f"error: {exc.__class__.__name__}"
            
        settings = get_settings()
        role = getattr(settings, "PDP_ROLE", "all")
        
        all_ok = db_state == "ok" and redis_state == "ok" and mongo_state == "ok"
        if role == "api" and engine_state not in ("ready", "warming"):
            all_ok = False

        return JSONResponse(
            status_code=200 if all_ok else 503,
            content={
                "status": "ready" if all_ok else "degraded",
                "role": role,
                "db": db_state,
                "redis": redis_state,
                "mongo": mongo_state,
                "engine": engine_state,
            },
        )

    return app


app = create_app()
