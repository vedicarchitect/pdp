import asyncio
import structlog
from typing import Any, Protocol
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
import redis.asyncio as redis_asyncio

from pdp.db.session import dispose_engine, get_engine, get_session_maker
from pdp.mongo.client import connect as mongo_connect
from pdp.mongo.client import disconnect as mongo_disconnect
from pdp.mongo.collections import init_collections
from pdp.settings import Settings, get_settings
from pdp.logging import configure_logging, truncate_errors_jsonl

log = structlog.get_logger()

class StartupGroup(Protocol):
    name: str
    # A group carrying live-trading responsibility. If it cannot start, the process must not
    # serve traffic: a healthy-looking API with a dead broker sync or strategy host is how
    # subsystem failures go unnoticed for weeks.
    required: bool
    async def start(self, app: FastAPI) -> None: ...
    async def stop(self, app: FastAPI) -> None: ...

class InfraGroup:
    name = "infra"
    required = True

    async def start(self, app: FastAPI) -> None:
        settings: Settings = get_settings()
        configure_logging(
            settings.LOG_LEVEL,
            redaction_enabled=settings.LOG_REDACTION_ENABLED,
            errors_jsonl_path=settings.ERRORS_JSONL_PATH,
            errors_jsonl_max_lines=settings.ERRORS_JSONL_MAX_LINES,
        )
        truncate_errors_jsonl()
        app.state.started_at = datetime.now(UTC)
        app.state.settings = settings
        app.state.redis = redis_asyncio.from_url(settings.REDIS_URL, decode_responses=True)
        mongo_client, mongo_db = mongo_connect(settings)
        app.state.mongo_client = mongo_client
        app.state.mongo_db = mongo_db
        await init_collections(mongo_db, settings)

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
            "infra_started",
            app=settings.APP_NAME,
            env=settings.ENV,
            live=settings.LIVE,
            broker=settings.BROKER,
            git_sha=settings.GIT_SHA,
            role=getattr(settings, "PDP_ROLE", "api")
        )

    async def stop(self, app: FastAPI) -> None:
        if getattr(app.state, "opensearch_indexer", None) is not None:
            from pdp.observability import close_opensearch, set_active_indexer
            await app.state.opensearch_indexer.stop()
            set_active_indexer(None)
            await close_opensearch()
        if getattr(app.state, "redis", None) is not None:
            await app.state.redis.aclose()
        if getattr(app.state, "mongo_client", None) is not None:
            mongo_disconnect(app.state.mongo_client)
        await dispose_engine()

class WebGroup:
    name = "web"
    required = True

    async def start(self, app: FastAPI) -> None:
        from pdp.alerts.ws import AlertsHub
        from pdp.market.ws import WSHub
        from pdp.options.hub import OptionsHub
        from pdp.orders.ws import OrdersHub
        from pdp.portfolio.hub import PortfolioHub

        app.state.ws_hub = WSHub()
        app.state.orders_hub = OrdersHub(redis=app.state.redis)
        app.state.options_hub = OptionsHub()
        app.state.portfolio_hub = PortfolioHub()
        app.state.alerts_hub = AlertsHub()

        settings = app.state.settings
        if settings.EVENTS_ENABLED:
            from pdp.events.hub import EventsHub
            from pdp.events.store import EventStore
            from pdp.events.push import WebPushSender
            
            app.state.event_store = EventStore(app.state.mongo_db)
            app.state.events_hub = EventsHub(store=app.state.event_store)
            app.state.web_push_sender = WebPushSender(settings, get_session_maker())

        from pdp.runtime.bridge import MarketBridge, GenericPubSubBridge
        app.state.market_bridge = MarketBridge(app.state.redis, app.state.ws_hub)
        await app.state.market_bridge.start()

        from pdp.orders.command_channel import CommandProducer
        app.state.command_producer = CommandProducer(app.state.redis)

        app.state.pubsub_bridge = GenericPubSubBridge(app.state.redis, {
            "orders.*": (app.state.orders_hub, "publish_raw"),
            "portfolio.*": (app.state.portfolio_hub, "publish_raw")
        })
        await app.state.pubsub_bridge.start()

    async def stop(self, app: FastAPI) -> None:
        if getattr(app.state, "market_bridge", None):
            await app.state.market_bridge.stop()
        if getattr(app.state, "pubsub_bridge", None):
            await app.state.pubsub_bridge.stop()

class JobRunnerGroup:
    name = "job_runner"
    required = False

    async def start(self, app: FastAPI) -> None:
        settings = app.state.settings
        from pdp.jobs.runner import JobRunner
        from pdp.housekeeping.tasks import (
            backfill_levels,
            backfill_options,
            backfill_spot,
            backfill_vix,
            reset_paper,
            snapshot_instruments,
            validate_warehouse,
        )
        from pdp.ml.routes import train_handler
        from pdp.backtest.job_handlers import (
            backtest_single_handler,
            backtest_sweep_handler,
            backtest_walkforward_handler,
        )

        job_runner = JobRunner(get_session_maker(), app.state.redis)
        job_runner.register_handler("housekeeping:backfill-spot", backfill_spot)
        job_runner.register_handler("housekeeping:backfill-options", backfill_options)
        job_runner.register_handler("housekeeping:backfill-levels", backfill_levels)
        job_runner.register_handler("housekeeping:backfill-vix", backfill_vix)
        job_runner.register_handler("housekeeping:reset-paper", reset_paper)
        job_runner.register_handler("housekeeping:validate-warehouse", validate_warehouse)
        job_runner.register_handler("housekeeping:snapshot-instruments", snapshot_instruments)
        job_runner.register_handler("ml_train", train_handler)
        job_runner.register_handler("backtest:single", backtest_single_handler)
        job_runner.register_handler("backtest:sweep", backtest_sweep_handler)
        job_runner.register_handler("backtest:walkforward", backtest_walkforward_handler)
        app.state.job_runner = job_runner

    async def stop(self, app: FastAPI) -> None:
        pass

class FeedEngineGroup:
    name = "feed_engine"
    required = True

    async def start(self, app: FastAPI) -> None:
        settings = app.state.settings
        mongo_db = app.state.mongo_db
        redis = app.state.redis
        
        await redis.set("engine:status", b"warming")
        
        # Hubs are retrieved gracefully if available (in 'all' mode)
        ws_hub = getattr(app.state, "ws_hub", None)
        
        from pdp.orders.ws import OrdersHub
        orders_hub = getattr(app.state, "orders_hub", None)
        if not orders_hub:
            orders_hub = OrdersHub(redis=redis)
            
        from pdp.portfolio.hub import PortfolioHub
        portfolio_hub = getattr(app.state, "portfolio_hub", None)
        if not portfolio_hub:
            portfolio_hub = PortfolioHub(redis=redis)
            
        options_hub = getattr(app.state, "options_hub", None)
        alerts_hub = getattr(app.state, "alerts_hub", None)
        events_hub = getattr(app.state, "events_hub", None)
        event_store = getattr(app.state, "event_store", None)
        web_push_sender = getattr(app.state, "web_push_sender", None)

        from pdp.orders.paper import PaperBroker
        from pdp.orders.router import OrderRouter

        paper_broker = PaperBroker(get_session_maker(), settings.PAPER_SLIPPAGE_BPS)
        if orders_hub: paper_broker.set_hub(orders_hub)
        await paper_broker.start(redis)
        app.state.paper_broker = paper_broker

        dhan_broker = None
        if settings.LIVE and settings.BROKER == "dhan" and settings.DHAN_CLIENT_ID:
            from pdp.orders.dhan_broker import DhanBroker
            dhan_broker = DhanBroker(get_session_maker(), settings)
            if orders_hub: dhan_broker.set_hub(orders_hub)
            await dhan_broker.start(redis)
            log.info("dhan_broker_enabled", client_id=settings.DHAN_CLIENT_ID)
        app.state.dhan_broker = dhan_broker

        from pdp.orders.margin import MarginService
        margin_service = MarginService.from_settings(settings) if settings.MARGIN_CHECK_ENABLED else None
        
        order_router = OrderRouter(settings, paper_broker, dhan_broker, margin_service)
        app.state.order_router = order_router

        from pdp.strategy.host import StrategyHost
        strategy_host = StrategyHost(
            strategies_dir=Path("strategies"),
            order_router=order_router,
            session_maker=get_session_maker(),
        )
        strategy_host.load_registry()
        strategy_host.set_redis(redis)
        strategy_host.set_paper_broker(paper_broker)
        if options_hub: strategy_host.set_options_hub(options_hub)
        app.state.strategy_host = strategy_host

        from pdp.indicators.engine import IndicatorEngine
        indicator_engine = IndicatorEngine(
            st_period=settings.SUPERTREND_PERIOD,
            st_multiplier=settings.SUPERTREND_MULTIPLIER,
        )
        app.state.indicator_engine = indicator_engine
        strategy_host.set_indicator_engine(indicator_engine)

        from pdp.indicators.warmup import warm_up_indicator_engine
        from pdp.strategy.registry import load_all
        _all_configs = load_all(Path("strategies"))
        _watchlist_dicts = [
            {"security_id": w.security_id, "exchange_segment": w.exchange_segment, "timeframes": w.timeframes}
            for cfg in _all_configs
            for w in cfg.watchlist
        ]

        for _cfg in _all_configs:
            for _w in _cfg.watchlist:
                if _w.indicators:
                    for _tf in _w.timeframes:
                        indicator_engine.configure_suite(_w.security_id, _tf, _w.indicators)

        try:
            from pdp.indicators.warmup import configure_matrix_suites
            _matrix_entries = await configure_matrix_suites(indicator_engine, get_session_maker())
            _watchlist_dicts.extend(_matrix_entries)
            # Publish the static index→futures-contract map so pdp-api (no in-process engine)
            # can resolve the VWAP/VWMA source sid for the indicator matrix.
            import json as _json
            await redis.set(
                "matrix:futures_sids", _json.dumps(indicator_engine.matrix_futures_sids), ex=86400
            )
        except Exception as exc:
            log.warning("matrix_suites_configure_failed", exc=str(exc))

        if _watchlist_dicts:
            try:
                await warm_up_indicator_engine(indicator_engine, mongo_db, settings, _watchlist_dicts)
            except Exception as exc:
                log.warning("indicator_warmup_failed", exc=str(exc))

        try:
            from pdp.indicators.levels_store import compute_session_levels
            await compute_session_levels(
                mongo_db,
                security_ids=["13", "25", "51"],
                holiday_json=settings.NSE_HOLIDAYS_JSON,
            )
            log.info("session_levels_computed")
        except Exception as exc:
            log.warning("session_levels_compute_failed", exc=str(exc))

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

        if settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN:
            from pdp.alerts.evaluator import AlertEvaluator
            from pdp.market.bar_writer import BarWriter
            from pdp.market.bars import BarAggregator
            from pdp.market.dhan_ws import DhanTickerAdapter
            from pdp.market.router import TickRouter

            alert_evaluator = AlertEvaluator(get_session_maker())
            app.state.alert_evaluator = alert_evaluator

            def on_alert_notification(notification):
                if alerts_hub:
                    pass
                log.debug("alert_notification", alert_id=notification.alert_id, status=notification.status)

            alert_evaluator.register_notification_callback(on_alert_notification)
            await alert_evaluator.load_alerts()

            bar_aggregator = BarAggregator()
            bar_writer = BarWriter(mongo_db["market_bars"])
            await bar_writer.start()
            app.state.bar_writer = bar_writer

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
                if settings.VIX_SECURITY_ID:
                    await adapter.subscribe(settings.VIX_SECURITY_ID, "IDX_I", session)
                if settings.INTEL_ENABLED:
                    for _sid in (
                        settings.MCX_GOLD_SECURITY_ID,
                        settings.MCX_SILVER_SECURITY_ID,
                        settings.MCX_CRUDE_SECURITY_ID,
                        settings.MCX_NATGAS_SECURITY_ID,
                    ):
                        if _sid:
                            await adapter.subscribe(_sid, "MCX_COMM", session)

            tick_router = TickRouter(
                bar_aggregator=bar_aggregator,
                bar_writer=bar_writer,
                strategy_host=strategy_host,
                alert_evaluator=alert_evaluator,
                indicator_engine=indicator_engine,
            )
            app.state.tick_router = tick_router
            app.state.tick_router_task = asyncio.create_task(
                tick_router.run(adapter.queue, redis),
                name="tick-router",
            )

            from pdp.market.watchdog import FeedWatchdog
            from pdp.risk.feed_halt import FeedStaleHalt

            feed_halt = FeedStaleHalt(halt_after_seconds=settings.FEED_STALE_HALT_SECONDS)
            app.state.feed_halt = feed_halt
            order_router._feed_halt = feed_halt

            feed_watchdog = FeedWatchdog(tick_router, adapter, settings.FEED_STALE_SECONDS, feed_halt=feed_halt)
            await feed_watchdog.start()
            app.state.feed_watchdog = feed_watchdog
            log.info("market_feed_started")
        else:
            app.state.dhan_adapter = None

        from pdp.portfolio.service import PortfolioService
        portfolio_service = PortfolioService(
            redis=redis,
            engine=get_engine(),
            hub=portfolio_hub,
            settings=settings,
            mongo_db=mongo_db,
        )
        await portfolio_service.start()
        app.state.portfolio_service = portfolio_service
        if orders_hub:
            portfolio_service.subscribe_fill_events(orders_hub)
            strategy_host.subscribe_fill_events(orders_hub)

        from pdp.journal.service import JournalService
        journal_service = JournalService(mongo_db=mongo_db)
        await journal_service.start()
        if orders_hub:
            journal_service.subscribe_fill_events(orders_hub)
        app.state.journal_service = journal_service

        from pdp.risk.service import KillSwitchService
        _ks = KillSwitchService()

        async def _auto_kill() -> None:
            await _ks.execute(get_session_maker(), order_router, {"trigger": "hard_cap_auto"})
            _es = getattr(app.state, "event_service", None)
            if _es is not None:
                _es.emit_kill_switch("hard_cap_auto")

        portfolio_service.set_hard_cap_callback(_auto_kill, settings.RISK_DAILY_LOSS_CAP_INR)

        if settings.EVENTS_ENABLED and events_hub and event_store and web_push_sender:
            from pdp.events.service import EventService
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
            if options_hub:
                options_hub.register_listener(event_service.on_chain)
            if getattr(app.state, "tick_router", None):
                app.state.tick_router.event_service = event_service
            if getattr(app.state, "feed_watchdog", None):
                app.state.feed_watchdog.event_service = event_service
            if orders_hub:
                orders_hub.register_fill_callback(event_service.on_order_fill)
            strategy_host.set_event_service(event_service)
            
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
                    _margin_warning_fired = False

            portfolio_service.set_margin_warning_callback(_check_margin_warning)

        for _auto_sid in list(strategy_host._configs):
            try:
                await strategy_host.start(_auto_sid)
            except Exception as _exc:
                log.error("strategy_autostart_failed", strategy_id=_auto_sid, exc=str(_exc))

        from pdp.orders.command_channel import CommandConsumer
        app.state.command_consumer = CommandConsumer(redis, order_router)
        await app.state.command_consumer.start()

        await redis.set("engine:status", b"ready")
        log.info("engine_ready")

    async def stop(self, app: FastAPI) -> None:
        redis = getattr(app.state, "redis", None)
        if redis:
            await redis.delete("engine:status")
            
        if getattr(app.state, "command_consumer", None):
            await app.state.command_consumer.stop()
        if getattr(app.state, "strategy_host", None):
            for _auto_sid in list(app.state.strategy_host._running):
                try:
                    await app.state.strategy_host.stop(_auto_sid)
                except Exception:
                    pass
        if getattr(app.state, "event_service", None):
            await app.state.event_service.stop()
        if getattr(app.state, "journal_service", None):
            await app.state.journal_service.stop()
        if getattr(app.state, "portfolio_service", None):
            await app.state.portfolio_service.stop()
        
        tick_router_task = getattr(app.state, "tick_router_task", None)
        if tick_router_task is not None:
            if getattr(app.state, "feed_watchdog", None):
                await app.state.feed_watchdog.stop()
            if getattr(app.state, "dhan_adapter", None):
                await app.state.dhan_adapter.stop()
            if getattr(app.state, "tick_router", None):
                await app.state.tick_router.stop()
            tick_router_task.cancel()
            try:
                await tick_router_task
            except asyncio.CancelledError:
                pass
                
        if getattr(app.state, "bar_writer", None):
            await app.state.bar_writer.stop()
        if getattr(app.state, "dhan_broker", None):
            await app.state.dhan_broker.stop()
        if getattr(app.state, "paper_broker", None):
            await app.state.paper_broker.stop()


class OpsGroup:
    name = "ops"
    required = True  # carries broker sync; the intel poller inside is fault-isolated separately

    async def start(self, app: FastAPI) -> None:
        settings = app.state.settings
        
        from pdp.options.fii_dii import StubFIIDIISource
        app.state.fii_dii_source = StubFIIDIISource()

        intel_poller = None
        if settings.INTEL_ENABLED:
            try:
                intel_poller = self._build_intel_poller(app, settings)
                intel_poller.start()
            except Exception as exc:
                # Dashboard intel is not live-trading critical; never let it block startup.
                log.error("intel_poller_start_failed", exc=str(exc))
                intel_poller = None
        app.state.intel_poller = intel_poller

        options_poller = None
        if settings.OPTIONS_POLLER_ENABLED and settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN:
            from pdp.options.poller import OptionsChainPoller
            options_hub = getattr(app.state, "options_hub", None)
            options_poller = OptionsChainPoller(
                collection=app.state.mongo_db["option_chains"],
                hub=options_hub,
                settings=settings,
            )
            app.state.options_poller = options_poller
            await options_poller.start()

        broker_sync_scheduler = None
        if settings.BROKER_SYNC_ENABLED:
            from pdp.broker_sync.client import BrokerAccountClient
            from pdp.broker_sync.scheduler import BrokerSyncScheduler
            from pdp.broker_sync.service import BrokerSyncService

            broker_sync_service = BrokerSyncService(
                session_maker=get_session_maker(),
                snapshots_col=app.state.mongo_db["broker_snapshots"],
                client=BrokerAccountClient(settings),
                event_service=getattr(app.state, "event_service", None),
                live_mode=settings.LIVE and settings.BROKER == "dhan",
            )
            if getattr(app.state, "dhan_adapter", None) is not None:
                broker_sync_service.set_market_adapter(app.state.dhan_adapter)
                await broker_sync_service.subscribe_current_positions()

            app.state.broker_sync_service = broker_sync_service
            broker_sync_scheduler = BrokerSyncScheduler(
                broker_sync_service, eod_time=settings.BROKER_SYNC_EOD_TIME
            )
            await broker_sync_scheduler.start()

            from pdp.broker_sync.intraday_poller import BrokerIntradayPoller
            intraday_poller = BrokerIntradayPoller(broker_sync_service, settings)
            await intraday_poller.start()
            app.state.broker_intraday_poller = intraday_poller

        app.state.broker_sync_scheduler = broker_sync_scheduler

        scrip_refresh_scheduler = None
        if settings.SCRIP_REFRESH_ENABLED:
            from pdp.instruments.scheduler import ScripRefreshScheduler
            scrip_refresh_scheduler = ScripRefreshScheduler(get_session_maker(), settings)
            await scrip_refresh_scheduler.start()
        app.state.scrip_refresh_scheduler = scrip_refresh_scheduler

    def _build_intel_poller(self, app: FastAPI, settings: Settings) -> Any:
        import json as _json
        from pdp.intel.poller import IntelPoller
        from pdp.intel.sources.global_market import StubGlobalMarketSource, YfinanceGlobalMarketSource
        from pdp.intel.sources.news import FeedparserNewsSource, StubNewsSource
        from pdp.intel.sources.sentiment import BlendedSentimentSource, StubSentimentSource
        from pdp.options.fii_dii import NseFIIDIISource

        try:
            import yfinance as _yf
            global_market_source = YfinanceGlobalMarketSource()
        except ImportError:
            global_market_source = StubGlobalMarketSource()

        try:
            import feedparser as _fp
            news_source = FeedparserNewsSource()
        except ImportError:
            news_source = StubNewsSource()

        try:
            import vaderSentiment as _vs
            sentiment_source = BlendedSentimentSource()
        except ImportError:
            sentiment_source = StubSentimentSource()

        try:
            import nsepython as _nse
            app.state.fii_dii_source = NseFIIDIISource()
        except ImportError:
            pass

        return IntelPoller(
            redis=app.state.redis,
            global_market_source=global_market_source,
            news_source=news_source,
            sentiment_source=sentiment_source,
            fii_dii_source=app.state.fii_dii_source,
            news_feed_urls=_json.loads(settings.INTEL_NEWS_FEED_URLS),
            vix_security_id=settings.VIX_SECURITY_ID,
            global_indices_interval=settings.INTEL_GLOBAL_INDICES_POLL_SECONDS,
            news_interval=settings.INTEL_NEWS_POLL_SECONDS,
            fii_dii_interval=settings.INTEL_FII_DII_POLL_SECONDS,
            mongo_db=app.state.mongo_db,
        )

    async def stop(self, app: FastAPI) -> None:
        if getattr(app.state, "intel_poller", None):
            await app.state.intel_poller.stop()
        if getattr(app.state, "options_poller", None):
            await app.state.options_poller.stop()
        if getattr(app.state, "broker_sync_scheduler", None):
            await app.state.broker_sync_scheduler.stop()
        if getattr(app.state, "broker_intraday_poller", None):
            await app.state.broker_intraday_poller.stop()
        if getattr(app.state, "scrip_refresh_scheduler", None):
            await app.state.scrip_refresh_scheduler.stop()

GROUPS_BY_ROLE = {
    "all": [InfraGroup, WebGroup, JobRunnerGroup, FeedEngineGroup, OpsGroup],
    "api": [InfraGroup, WebGroup, JobRunnerGroup],
    "engine": [InfraGroup, FeedEngineGroup],
    "ops": [InfraGroup, OpsGroup, JobRunnerGroup],
}
