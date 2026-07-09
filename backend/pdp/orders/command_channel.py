import asyncio
from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from redis.asyncio import Redis

from pdp.orders.models import OrderRequest

class OrderCommand(BaseModel):
    cmd_id: str
    kind: Literal["place", "cancel", "kill"]
    order: OrderRequest | None = None
    cancel_order_id: int | None = None
    requester: str
    ts: datetime

class OrderResult(BaseModel):
    cmd_id: str
    status: Literal["placed", "cancelled", "rejected", "killed"]
    order_id: int | None = None
    detail: str | None = None

class CommandProducer:
    """API-side: enqueues commands and waits for results."""
    def __init__(self, redis: Redis, timeout: float = 5.0):
        self.redis = redis
        self.timeout = timeout
        
    async def execute(self, cmd: OrderCommand) -> OrderResult:
        # Check if engine is ready
        status = await self.redis.get("engine:status")
        if status != b"ready" and cmd.kind == "place":
            # Engine not ready, return rejected
            return OrderResult(
                cmd_id=cmd.cmd_id, 
                status="rejected", 
                detail="engine unavailable (status != ready)"
            )
            
        await self.redis.xadd("orders.commands", {"data": cmd.model_dump_json()})
        
        # Poll for result (Wait for ack in orders.results)
        # Using pub/sub or scanning orders.results. For simplicity, we can XREAD.
        # But we need a specific cmd_id. It's easier if engine also publishes result to pub/sub
        # or we just poll the stream. We'll poll `orders.results` from the end.
        end_time = asyncio.get_event_loop().time() + self.timeout
        last_id = "$"
        while asyncio.get_event_loop().time() < end_time:
            resp = await self.redis.xread({"orders.results": last_id}, count=100, block=500)
            if resp:
                for stream, msgs in resp:
                    for msg_id, data in msgs:
                        last_id = msg_id
                        result_json = data.get(b"data") or data.get("data")
                        if result_json:
                            res = OrderResult.model_validate_json(result_json)
                            if res.cmd_id == cmd.cmd_id:
                                return res
        
        return OrderResult(
            cmd_id=cmd.cmd_id,
            status="rejected",
            detail="timeout waiting for engine"
        )

class CommandConsumer:
    """Engine-side: consumes commands, executes them idempotently, and publishes results."""
    def __init__(self, redis: Redis, router, group_name="engine", consumer_name="engine-1"):
        self.redis = redis
        self.router = router
        self.group_name = group_name
        self.consumer_name = consumer_name
        self._running = False

    async def start(self):
        self._running = True
        try:
            await self.redis.xgroup_create("orders.commands", self.group_name, id="0", mkstream=True)
        except Exception:
            pass  # Group already exists
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._running = False
        if hasattr(self, "_task"):
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self):
        import structlog
        log = structlog.get_logger()
        while self._running:
            try:
                resp = await self.redis.xreadgroup(
                    self.group_name, self.consumer_name, {"orders.commands": ">"}, count=10, block=1000
                )
                if not resp:
                    continue
                    
                for stream, msgs in resp:
                    for msg_id, data in msgs:
                        try:
                            cmd_json = data.get(b"data") or data.get("data")
                            if not cmd_json:
                                await self.redis.xack("orders.commands", self.group_name, msg_id)
                                continue
                                
                            cmd = OrderCommand.model_validate_json(cmd_json)
                            # Idempotency check
                            is_new = await self.redis.set(f"cmd:done:{cmd.cmd_id}", "1", nx=True, ex=86400)
                            if not is_new:
                                await self.redis.xack("orders.commands", self.group_name, msg_id)
                                continue
                                
                            try:
                                result = await self._execute(cmd)
                            except Exception as exc:
                                # allow retry if execution failed unexpectedly
                                await self.redis.delete(f"cmd:done:{cmd.cmd_id}")
                                log.error("command_execution_failed", cmd_id=cmd.cmd_id, exc=str(exc))
                                result = OrderResult(cmd_id=cmd.cmd_id, status="rejected", detail=str(exc))
                            
                            # Publish result
                            await self.redis.xadd("orders.results", {"data": result.model_dump_json()})
                            await self.redis.xack("orders.commands", self.group_name, msg_id)
                        except Exception as e:
                            log.error("command_processing_error", msg_id=msg_id, exc=str(e))
                            await asyncio.sleep(0.5)
            except Exception as e:
                if self._running:
                    log.error("command_consumer_error", exc=str(e))
                    await asyncio.sleep(1.0)

    async def _execute(self, cmd: OrderCommand) -> OrderResult:
        from pdp.db.session import get_session_maker
        # Execute logic against the actual order_router
        if cmd.kind == "place" and cmd.order:
            # Assuming router.place_order returns an order_id or raises
            try:
                session_maker = get_session_maker()
                async with session_maker() as session:
                    order_id = await self.router.place_order(cmd.order, session)
                return OrderResult(cmd_id=cmd.cmd_id, status="placed", order_id=order_id)
            except Exception as e:
                return OrderResult(cmd_id=cmd.cmd_id, status="rejected", detail=str(e))
        elif cmd.kind == "cancel" and cmd.cancel_order_id:
            try:
                session_maker = get_session_maker()
                async with session_maker() as session:
                    await self.router.cancel_order(cmd.cancel_order_id, session)
                return OrderResult(cmd_id=cmd.cmd_id, status="cancelled", order_id=cmd.cancel_order_id)
            except Exception as e:
                return OrderResult(cmd_id=cmd.cmd_id, status="rejected", detail=str(e))
        elif cmd.kind == "kill":
            try:
                session_maker = get_session_maker()
                await self.router._ks.execute(session_maker, self.router, {"trigger": "manual_kill_command"})
                return OrderResult(cmd_id=cmd.cmd_id, status="killed")
            except Exception as e:
                return OrderResult(cmd_id=cmd.cmd_id, status="rejected", detail=str(e))
                
        return OrderResult(cmd_id=cmd.cmd_id, status="rejected", detail="invalid command payload")
