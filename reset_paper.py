import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def reset():
    engine = create_async_engine('postgresql+asyncpg://pdp:pdp@localhost:5432/pdp')
    async with engine.begin() as conn:
        r1 = await conn.execute(text('DELETE FROM trades'))
        r2 = await conn.execute(text('DELETE FROM orders'))
        r3 = await conn.execute(text('DELETE FROM positions'))
        await conn.execute(text('ALTER SEQUENCE trades_id_seq RESTART WITH 1'))
        await conn.execute(text('ALTER SEQUENCE orders_id_seq RESTART WITH 1'))
        await conn.execute(text('ALTER SEQUENCE positions_id_seq RESTART WITH 1'))
        print(f'Cleared: trades={r1.rowcount}, orders={r2.rowcount}, positions={r3.rowcount}')
        print('ID sequences reset to 1.')
    await engine.dispose()

asyncio.run(reset())
