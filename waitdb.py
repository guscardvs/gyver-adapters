import asyncio
import aiomysql
import asyncpg
import time
from gyver.adapters.database.config import DatabaseConfig, make_uri
from gyver.config import AdapterConfigFactory

factory = AdapterConfigFactory()


async def wait_for_postgres(timeout: int):
    # Wait for the database to initialize by attempting to connect every second
    # until a connection is successful or the timeout is reached.dsn = make_uri(
    dsn = make_uri(factory.load(DatabaseConfig, "pg"), 5432, "postgres")
    end_time = time.monotonic() + timeout
    while time.monotonic() < end_time:
        try:
            await asyncpg.connect(dsn=dsn)
            break
        except Exception:
            await asyncio.sleep(1)
    else:
        raise SystemExit(1)


async def wait_for_mysql(timeout: int):
    # Wait for the database to initialize by attempting to connect every second
    # until a connection is successful or the timeout is reached.dsn = make_uri(
    cfg = factory.load(DatabaseConfig, "my")
    end_time = time.monotonic() + timeout
    while time.monotonic() < end_time:
        try:
            await aiomysql.connect(
                host=cfg.host,
                user=cfg.user,
                password=cfg.password,
                db=cfg.name,
            )
            break
        except Exception:
            await asyncio.sleep(1)
    else:
        raise SystemExit(1)


if __name__ == "__main__":
    # Replace the values below with your own DSN and timeout.

    timeout = 20

    async def run():
        await asyncio.gather(
            wait_for_mysql(timeout), wait_for_postgres(timeout)
        )

    asyncio.run(run())
