from __future__ import annotations

import asyncio
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
    settings: Settings = get_settings()
    configure_logging(
        settings.LOG_LEVEL,
        redaction_enabled=settings.LOG_REDACTION_ENABLED,
        errors_jsonl_path=settings.ERRORS_JSONL_PATH,
        errors_jsonl_max_lines=settings.ERRORS_JSONL_MAX_LINES,
    )
    truncate_errors_jsonl()
    started_at = datetime.now(UTC)
    app.state.started_at = started_at
    app.state.settings = settings
    app.state.redis = redis_asyncio.from_url(settings.REDIS_URL, decode_responses=True)
    mongo_client, mongo_db = mongo_connect(settings)
    app.state.mongo_client = mongo_client
    app.state.mongo_db = mongo_db
    await init_collections(mongo_db, settings)

    # Unified OpenSearch log pipeline — bootstrap templates + start the single non-blocking
    # indexer early so subsequent service logs auto-ship. No-op when OPENSEARCH_ENABLED=false.
    app.state.opensearch_indexer = None
    if settings.OPENSEARCH_ENABLED:
        from pdp.observability import OpenSearchIndexer, get_opensearch, set_active_indexer
        from pdp.observability.mappings import ensure_templates
        from pdp.observability.processor import set_level_floor

        os_client = get_opensearch()
        if os_client is not None:
            await ensure_templates(os_client, settings.OPENSEARCH_INDEX_PREFIX)
            set_level_floor(settings.OPENSEARCH_LOG_LEVEL)
            os_indexer = OpenSearchIndexer(
                os_client,
                prefix=settings.OPENSEARCH_INDEX_PREFIX,
                bulk_interval=settings.OPENSEARCH_BULK_INTERVAL,
                bulk_max=settings.OPENSEARCH_BULK_MAX,
                queue_max=settings.OPENSEARCH_QUEUE_MAX,
            )
            await os_indexer.start()
            set_active_indexer(os_indexer)
            app.state.opensearch_indexer = os_indexer

    log.info(
        "app_starting",
        app=settings.APP_NAME,
        env=settings.ENV,
        live=settings.LIVE,
        broker=settings.BROKER,
        git_sha=settings.GIT_SHA,
    )

    # Job Runner — stored on app.state (no class-level singleton)
    from pdp.housekeeping.tasks import (
        backfill_options,
        backfill_spot,
        reset_paper,
        snapshot_instruments,
        validate_warehouse,
    )
    from pdp.jobs.runner import JobRunner
    from pdp.ml.routes import train_handler

    job_runner = JobRunner(get_session_maker(), app.state.redis)
    job_runner.register_handler("housekeeping:backfill-spot", backfill_spot)
    job_runner.register_handler("housekeeping:backfill-options", backfill_options)
    job_runner.register_handler("housekeeping:reset-paper", reset_paper)
    job_runner.register_handler("housekeeping:validate-warehouse", validate_warehouse)
    job_runner.register_handler("housekeeping:snapshot-instruments", snapshot_instruments)
    job_runner.register_handler("ml_train", train_handler)
    from pdp.backtest.job_handlers import (
        backtest_single_handler,
        backtest_sweep_handler,
        backtest_walkforward_handler,
    )
    job_runner.register_handler("backtest:single", backtest_single_handler)
    job_runner.register_handler("backtest:sweep", backtest_sweep_handler)
    job_runner.register_handler("backtest:walkforward", backtest_walkforward_handler)
    app.state.job_runner = job_runner

    # WebSocket hubs — always available
    from pdp.alerts.ws import AlertsHub
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
    alerts_hub = AlertsHub()
    app.state.alerts_hub = alerts_hub

    # FII/DII data source — stub by default; swap for a concrete source when one is configured
    from pdp.options.fii_dii import StubFIIDIISource
    app.state.fii_dii_source = StubFIIDIISource()

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

    from pdp.orders.margin import MarginService

    margin_service = MarginService.from_settings(settings) if settings.MARGIN_CHECK_ENABLED else None
    if settings.MARGIN_CHECK_ENABLED and margin_service is None:
        log.warning("margin_service_disabled", reason="no Dhan credentials")

    order_router = OrderRouter(settings, paper_broker, dhan_broker, margin_service)
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
    strategy_host.set_redis(app.state.redis)
    strategy_host.set_paper_broker(paper_broker)
    app.state.strategy_host = strategy_host

    # Universal indicator engine — computes SuperTrend once per (security, timeframe)
    # on each closed bar; strategies consume it via ctx.indicators (rule #4). Period and
    # multiplier are settings-driven (default ST(10,2), the backtest-promoted config).
    from pdp.indicators.engine import IndicatorEngine

    indicator_engine = IndicatorEngine(
        st_period=settings.SUPERTREND_PERIOD,
        st_multiplier=settings.SUPERTREND_MULTIPLIER,
    )
    app.state.indicator_engine = indicator_engine
    strategy_host.set_indicator_engine(indicator_engine)

    # Seed IndicatorEngine from MongoDB / Dhan API so ST is valid immediately on first bar.
    from pdp.indicators.warmup import warm_up_indicator_engine
    from pdp.strategy.registry import load_all

    _all_configs = load_all(Path("strategies"))
    _watchlist_dicts = [
        {"security_id": w.security_id, "exchange_segment": w.exchange_segment, "timeframes": w.timeframes}
        for cfg in _all_configs
        for w in cfg.watchlist
    ]

    # Build indicator suite from the union of each strategy's watchlist indicator requests.
    for _cfg in _all_configs:
        for _w in _cfg.watchlist:
            if _w.indicators:
                for _tf in _w.timeframes:
                    indicator_engine.configure_suite(_w.security_id, _tf, _w.indicators)

    if _watchlist_dicts:
        try:
            await warm_up_indicator_engine(indicator_engine, mongo_db, settings, _watchlist_dicts)
        except Exception as exc:
            log.warning("indicator_warmup_failed", exc=str(exc))

    # ML loaders — load requested artifacts per watchlist entry (opt-in, non-blocking)
    if settings.ML_ENABLED and settings.ML_ACTIVE_VERSION:
        from pdp.ml.infer import ModelLoader, register_loader
        for _cfg in _all_configs:
            for _w in _cfg.watchlist:
                if _w.ml_signal.enabled:
                    _ml_version = _w.ml_signal.version or settings.ML_ACTIVE_VERSION
                    _ml_head = _w.ml_signal.head
                    for _tf in _w.timeframes:
                        _loader = ModelLoader(settings.ML_MODEL_DIR, _ml_version, _ml_head)
                        _loader.load()
                        if _loader.ready:
                            register_loader(_w.security_id, _tf, _loader, _ml_head)
                            log.info("ml_loader_registered", sid=_w.security_id, tf=_tf,
                                     version=_ml_version, head=_ml_head)

    # Market feed — only starts when Dhan credentials are configured
    tick_router_task = None
    bar_writer = None
    alert_evaluator = None
    if settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN:
        from pdp.alerts.evaluator import AlertEvaluator
        from pdp.market.bar_writer import BarWriter
        from pdp.market.bars import BarAggregator
        from pdp.market.dhan_ws import DhanTickerAdapter
        from pdp.market.router import TickRouter

        # Initialize alerts evaluator (pass the sessionmaker instance, per
        # Callable[[], AsyncSession] — sessionmaker() yields an AsyncSession)
        alert_evaluator = AlertEvaluator(get_session_maker())
        app.state.alert_evaluator = alert_evaluator

        # Register callback to push alerts to WebSocket hub
        def on_alert_notification(notification):
            # Push alert to AlertsHub (which routes to user's connected clients)
            # We'll look up the user_id from the alert record
            # For v1, we use a deferred approach: UI polls or subscribes to WebSocket
            # and receives backfill on connect
            _alerts_hub = app.state.alerts_hub
            # TODO: Query alert from DB to get user_id and publish to hub
            log.debug("alert_notification", alert_id=notification.alert_id, status=notification.status)

        alert_evaluator.register_notification_callback(on_alert_notification)

        # Load alerts from database
        await alert_evaluator.load_alerts()

        bar_aggregator = BarAggregator()
        bar_writer = BarWriter(app.state.mongo_db["market_bars"])
        await bar_writer.start()

        adapter = DhanTickerAdapter(
            settings.DHAN_CLIENT_ID,
            settings.DHAN_ACCESS_TOKEN,
            reconnect_base_delay=settings.FEED_RECONNECT_BASE_DELAY,
            reconnect_max_delay=settings.FEED_RECONNECT_MAX_DELAY,
        )
        app.state.dhan_adapter = adapter
        strategy_host.set_market_adapter(adapter)
        async with get_session_maker()() as session:
            await adapter.start(session)
        tick_router = TickRouter(
            bar_aggregator=bar_aggregator,
            bar_writer=bar_writer,
            ws_hub=ws_hub,
            strategy_host=strategy_host,
            alert_evaluator=alert_evaluator,
            indicator_engine=indicator_engine,
        )
        app.state.tick_router = tick_router
        tick_router_task = asyncio.create_task(
            tick_router.run(adapter.queue, app.state.redis),
            name="tick-router",
        )

        from pdp.market.watchdog import FeedWatchdog
        from pdp.risk.feed_halt import FeedStaleHalt

        feed_halt = FeedStaleHalt(halt_after_seconds=settings.FEED_STALE_HALT_SECONDS)
        app.state.feed_halt = feed_halt
        # Inject into order router so live orders can be blocked during sustained stall
        order_router._feed_halt = feed_halt

        feed_watchdog = FeedWatchdog(
            tick_router, adapter, settings.FEED_STALE_SECONDS, feed_halt=feed_halt
        )
        await feed_watchdog.start()
        app.state.feed_watchdog = feed_watchdog

        log.info("market_feed_started", client_id=settings.DHAN_CLIENT_ID, alerts_engine="enabled")
    else:
        app.state.dhan_adapter = None
        app.state.feed_watchdog = None
        app.state.feed_halt = None
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

    # Paper-trade journal — records fills, computes daily P&L / progress stats.
    from pdp.journal.service import JournalService

    journal_service = JournalService(mongo_db=mongo_db)
    await journal_service.start()
    journal_service.subscribe_fill_events(orders_hub)
    app.state.journal_service = journal_service

    # Wire hard-cap auto-kill: when daily loss > RISK_DAILY_LOSS_CAP_INR the
    # kill-switch fires automatically (paper-safe — no real money at risk).
    from pdp.risk.service import KillSwitchService as _KSS  # noqa: N814

    _ks = _KSS()

    async def _auto_kill() -> None:
        await _ks.execute(get_session_maker(), order_router, {"trigger": "hard_cap_auto"})
        _es = getattr(app.state, "event_service", None)
        if _es is not None:
            _es.emit_kill_switch("hard_cap_auto")

    portfolio_service.set_hard_cap_callback(_auto_kill, settings.RISK_DAILY_LOSS_CAP_INR)

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

    # Live event publisher — monitors manual positions + market, emits realtime events.
    event_service = None
    if settings.EVENTS_ENABLED:
        from pdp.events.hub import EventsHub
        from pdp.events.push import WebPushSender
        from pdp.events.service import EventService
        from pdp.events.store import EventStore

        event_store = EventStore(mongo_db)
        events_hub = EventsHub(store=event_store)
        web_push_sender = WebPushSender(settings, get_session_maker())
        app.state.events_hub = events_hub
        app.state.event_store = event_store
        app.state.web_push_sender = web_push_sender

        event_service = EventService(
            settings=settings,
            engine=indicator_engine,
            hub=events_hub,
            store=event_store,
            push_sender=web_push_sender,
            session_maker=get_session_maker(),
            adapter=app.state.dhan_adapter,
            portfolio_service=portfolio_service,
            journal_service=journal_service,
            mongo_db=mongo_db,
        )
        app.state.event_service = event_service
        await event_service.start()
        options_hub.register_listener(event_service.on_chain)
        _tr = getattr(app.state, "tick_router", None)
        if _tr is not None:
            _tr.event_service = event_service
        # Wire ORDER_FILL events (task 11.1) and STRATEGY_SIGNAL (task 11.5)
        orders_hub.register_fill_callback(event_service.on_order_fill)
        strategy_host.set_event_service(event_service)
        # Wire MARGIN_WARNING: emit when soft-cap % of daily loss cap is breached (task 11.4)
        _soft_cap_pct = settings.RISK_SOFT_CAP_PCT / 100.0
        _soft_cap_inr = settings.RISK_DAILY_LOSS_CAP_INR * _soft_cap_pct
        _margin_warning_fired = False

        def _check_margin_warning(daily_loss: float) -> None:
            nonlocal _margin_warning_fired
            if daily_loss >= _soft_cap_inr:
                if not _margin_warning_fired:
                    _margin_warning_fired = True
                    event_service.emit_margin_warning(daily_loss, settings.RISK_DAILY_LOSS_CAP_INR)
            else:
                _margin_warning_fired = False  # re-arm if recovered

        portfolio_service.set_margin_warning_callback(_check_margin_warning)
        log.info("event_publisher_enabled")
    else:
        app.state.event_service = None

    # Broker account sync (chunk 2) — daily archival of Dhan-reported account state.
    broker_sync_scheduler = None
    if settings.BROKER_SYNC_ENABLED:
        from pdp.broker_sync.client import BrokerAccountClient
        from pdp.broker_sync.scheduler import BrokerSyncScheduler
        from pdp.broker_sync.service import BrokerSyncService

        broker_sync_service = BrokerSyncService(
            session_maker=get_session_maker(),
            snapshots_col=mongo_db["broker_snapshots"],
            client=BrokerAccountClient(settings),
        )
        app.state.broker_sync_service = broker_sync_service
        broker_sync_scheduler = BrokerSyncScheduler(
            broker_sync_service, eod_time=settings.BROKER_SYNC_EOD_TIME
        )
        await broker_sync_scheduler.start()
        log.info("broker_sync_enabled", eod_time=settings.BROKER_SYNC_EOD_TIME)
    else:
        app.state.broker_sync_service = None
        log.info("broker_sync_disabled")

    # Scrip-master refresh — daily pre-open refresh of instrument master (gated).
    scrip_refresh_scheduler = None
    if settings.SCRIP_REFRESH_ENABLED:
        from pdp.instruments.scheduler import ScripRefreshScheduler

        scrip_refresh_scheduler = ScripRefreshScheduler(get_session_maker(), settings)
        await scrip_refresh_scheduler.start()
        log.info("scrip_refresh_enabled", refresh_time=settings.SCRIP_REFRESH_TIME)
    else:
        log.info("scrip_refresh_disabled")

    try:
        yield
    finally:
        log.info("app_shutting_down")
        if scrip_refresh_scheduler is not None:
            await scrip_refresh_scheduler.stop()
        if broker_sync_scheduler is not None:
            await broker_sync_scheduler.stop()
        if event_service is not None:
            await event_service.stop()
        await journal_service.stop()
        await portfolio_service.stop()
        if tick_router_task is not None:
            watchdog = getattr(app.state, "feed_watchdog", None)
            if watchdog:
                await watchdog.stop()
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
        if app.state.opensearch_indexer is not None:
            from pdp.observability import close_opensearch, set_active_indexer

            await app.state.opensearch_indexer.stop()
            set_active_indexer(None)
            await close_opensearch()
        await app.state.redis.aclose()
        mongo_disconnect(app.state.mongo_client)
        await dispose_engine()


def create_app() -> FastAPI:
    import structlog as _sl
    from fastapi import Request
    from fastapi.responses import JSONResponse

    _exc_log = _sl.get_logger()

    app = FastAPI(title="PDP", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(Exception)
    async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        import structlog as _sl2
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
    from pdp.events.routes import events_ws_router
    from pdp.events.routes import router as events_router
    from pdp.instruments.routes import router as instruments_router
    from pdp.journal.routes import router as journal_router
    from pdp.market.routes import router as market_router
    from pdp.market.ws import ws_router
    from pdp.options.routes import router as options_router
    from pdp.options.ws import options_ws_router
    from pdp.orders.routes import router as orders_router
    from pdp.orders.ws import orders_ws_router
    from pdp.portfolio.routes import router as portfolio_router
    from pdp.portfolio.ws import portfolio_ws_router
    from pdp.positional.routes import router as positional_router
    from pdp.risk.routes import risk_router, settings_router
    from pdp.strategy.routes import router as strategy_router
    from pdp.strategy.routes import strangle_router
    from pdp.backtest.routes import router as backtest_router
    from pdp.backtest.warehouse_routes import router as strangle_bt_router
    from pdp.jobs.routes import router as jobs_router
    from pdp.jobs.ws import router as jobs_ws_router
    from pdp.ml.routes import router as ml_router
    from pdp.housekeeping.routes import router as housekeeping_router
    from pdp.broker_sync.routes import router as broker_sync_router
    from pdp.observability.ingest import router as logs_ingest_router
    from pdp.observability.routes import router as observability_router

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
    app.include_router(backtest_router)
    app.include_router(strangle_bt_router)
    app.include_router(jobs_router, prefix="/api/v1/jobs", tags=["Jobs"])
    app.include_router(jobs_ws_router, prefix="/ws/jobs", tags=["Jobs WS"])
    app.include_router(ml_router, prefix="/api/v1/ml", tags=["ML"])
    app.include_router(housekeeping_router, prefix="/api/v1/housekeeping", tags=["Housekeeping"])
    app.include_router(broker_sync_router)
    app.include_router(logs_ingest_router)
    app.include_router(observability_router)

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
