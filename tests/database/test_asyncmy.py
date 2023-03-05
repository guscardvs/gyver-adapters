from aiomysql import DictCursor
import pytest

from gyver.adapters.database.asyncmy import ConnectionProxy
from gyver.adapters.database.asyncmy import AsyncmyAdapter
from gyver.adapters.database.config import DatabaseConfig
from gyver.config import AdapterConfigFactory


@pytest.fixture(scope="module")
async def adapter(factory: AdapterConfigFactory):
    config = factory.load(DatabaseConfig, "my")
    adapter = AsyncmyAdapter(config)
    await adapter.init()
    context = adapter.context()
    async with context as connection:
        await connection.execute(
            """CREATE TABLE my_table(
                id INT AUTO_INCREMENT PRIMARY KEY,
                name TEXT
            )"""
        )
    yield adapter
    async with context as connection:
        await connection.execute("DROP TABLE my_table")
    await adapter.dispose()


@pytest.fixture
async def connection(adapter: AsyncmyAdapter):
    context = adapter.context()

    async with context as connection:
        await connection.execute("TRUNCATE TABLE my_table")
        yield connection


async def createmany(connection: ConnectionProxy, n: int):
    await connection.transaction()
    for _ in range(n):
        await connection.execute(
            "INSERT INTO my_table (name) VALUES (%s)", ("John",)
        )
    await connection.commit()


async def test_adapter_initialized(adapter: AsyncmyAdapter):
    assert adapter.initialized is True


async def test_new_connection(connection: ConnectionProxy):
    assert connection is not None


async def test_close_connection(adapter: AsyncmyAdapter):
    connection = await adapter.new()
    await connection.close()
    assert connection.closed() is True


async def test_execute_query(connection: ConnectionProxy):
    result = await connection.execute("SELECT 1")
    assert result == 1


async def test_fetch_query(connection: ConnectionProxy):
    await createmany(connection, 10)
    rows = await connection.fetch("SELECT * FROM my_table")
    assert len(rows) == 10  # Assuming my_table has 10 rows


async def test_fetchrow_query(connection: ConnectionProxy):
    await createmany(connection, 1)
    row = await connection.fetchrow("SELECT * FROM my_table")
    assert row is not None


async def test_transaction(connection: ConnectionProxy):
    await connection.transaction()
    await connection.execute(
        "INSERT INTO my_table (id, name) VALUES (%s, %s)", (11, "John")
    )
    await connection.commit()

    # Verify the data was inserted correctly
    rows = await connection.fetch(
        "SELECT * FROM my_table WHERE id = %s", 11, cursor_class=DictCursor
    )
    assert len(rows) == 1
    assert rows[0]["id"] == 11
    assert rows[0]["name"] == "John"


async def test_rollback(connection: ConnectionProxy):
    await connection.transaction()
    await connection.execute("INSERT INTO my_table (name) VALUES (%s)", "John")
    await connection.rollback()

    # Verify the data was not inserted
    rows = await connection.fetch("SELECT * FROM my_table WHERE id = %s", 11)
    assert len(rows) == 0
