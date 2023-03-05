from typing import (
    Any,
    Callable,
    Coroutine,
    Optional,
    Protocol,
    Sequence,
    TypeVar,
)

import asyncmy
from asyncmy.connection import Connection
from asyncmy.pool import Pool
from asyncmy.cursors import Cursor


from gyver.attrs import define, info
from gyver.context import AsyncContext, AtomicAsyncAdapter
from gyver.utils import lazyfield

from .config import DatabaseConfig, db_config_factory

CursorT = TypeVar("CursorT", bound=Cursor, covariant=True)

DEFAULT_PORT = 3306


class CursorContext(Protocol[CursorT]):
    def __await__(self) -> CursorT:
        ...

    async def __aenter__(self) -> CursorT:
        ...

    async def __aexit__(self, exc_type, exc, tb) -> ...:
        ...


@define
class AsyncmyTransaction:
    conn: Connection
    nested: bool

    async def rollback(self):
        pass

    async def commit(self):
        pass


class RootTransaction(AsyncmyTransaction):
    def __init__(self, conn: Connection):
        super().__init__(conn, False)

    async def begin(self):
        async with self.conn.cursor() as cur:
            await cur.execute("BEGIN")

    async def commit(self):
        async with self.conn.cursor() as cur:
            await cur.execute("COMMIT")

    async def rollback(self):
        async with self.conn.cursor() as cur:
            await cur.execute("ROLLBACK")


@define
class NestedTransaction(AsyncmyTransaction):
    count: int

    def __init__(self, conn: Connection, count: int):
        self.__gattrs_init__(conn, True, count)  # type: ignore

    @lazyfield
    def name(self):
        return f"aiomysql_sa_savepoint_{self.count}"

    async def begin(self):
        async with self.conn.cursor() as cur:
            await cur.execute(f"SAVEPOINT {self.name}")

    async def commit(self):
        async with self.conn.cursor() as cur:
            await cur.execute(f"RELEASE SAVEPOINT {self.name}")

    async def rollback(self):
        async with self.conn.cursor() as cur:
            await cur.execute(f"ROLLBACK TO SAVEPOINT {self.name}")


@define
class ConnectionProxy:
    """
    A proxy class that provides a simple interface for managing transactions and
    executing SQL queries on a database connection.

    :param conn: the underlying `aiomysql.Connection` object to proxy.

    :ivar conn: the underlying `aiomysql.Connection` object that is being proxied.
    :ivar transaction_stack: a list of `Transaction` that have been
    started on the underlying `aiomysql.Connection`.
    """

    conn: Connection
    releaser: Callable[[Connection], Coroutine[None, None, None]]
    transaction_stack: list[AsyncmyTransaction]

    def __init__(
        self,
        conn: Connection,
        releaser: Callable[[Connection], Coroutine[None, None, None]],
    ) -> None:
        self.__gattrs_init__(conn, releaser, [])  # type: ignore

    @lazyfield
    def _is_closed(self):
        return False

    def closed(self):
        """
        Determines whether the underlying `Connection` is closed.

        :return: `True` if the underlying `Connection` is closed; otherwise, `False`.
        """
        return self._is_closed

    async def close(self):
        """
        Closes the underlying `Connection` and rolls back any outstanding transactions.
        """
        if self.transaction_stack:
            for trx in reversed(self.transaction_stack):
                await trx.rollback()
            self.transaction_stack.clear()
        await self.releaser(self.conn)
        ConnectionProxy._is_closed.manual_set(self, True)

    async def transaction(self):
        """
        Starts a new transaction on the underlying `Connection`.
        """
        trx = (
            NestedTransaction(self.conn, len(self.transaction_stack) + 1)
            if self.transaction_stack
            else RootTransaction(self.conn)
        )
        await trx.begin()
        self.transaction_stack.append(trx)

    async def commit(self):
        """
        Commits the topmost transaction on the `transaction_stack`.
        """
        if not self.transaction_stack:
            raise RuntimeError("No transaction found in stack")
        trx = self.transaction_stack.pop()
        await trx.commit()

    async def rollback(self):
        """
        Rolls back the topmost transaction on the `transaction_stack`.
        """
        if not self.transaction_stack:
            raise RuntimeError("No transaction found in stack")
        trx = self.transaction_stack.pop()
        await trx.rollback()

    def in_atomic(self):
        """
        Determines whether the `ConnectionProxy` is currently inside a transaction.

        :return: `True` if the `ConnectionProxy` is currently inside a transaction;
        otherwise, `False`.
        """
        return bool(self.transaction_stack)

    def cursor(
        self,
        cursor_class: type[CursorT] = Cursor,
    ) -> CursorContext[CursorT]:
        """
        Creates a cursor object that can be used to execute sqlqueries.

        :param query: the SQL query to execute.
        :param args: the parameters to pass to the SQL query.
        :param prefetch: the number of rows to prefetch from the database.
        :param timeout: the number of seconds to wait before timing out the SQL query.
        :param record_class: the record class to use for the results of the SQL query.
        :return: a new cursor object that can be used to execute sqlqueries.
        """

        return self.conn.cursor(cursor_class)

    async def execute(
        self,
        query: str,
        args: Optional[Sequence] = None,
    ):
        """
        Executes an SQL query and returns the result status.

        :param query: the SQL query to execute.
        :param args: the parameters to pass to the SQL query.
        :param timeout: the number of seconds to wait before timing out the SQL query.
        :return: the rowcount of the SQL query.
        """
        async with self.cursor() as cursor:
            return await cursor.execute(
                query, args  # type:ignore
            )

    async def executemany(
        self,
        query: str,
        args: Sequence[Sequence],
    ):
        """
        Executes an SQL query and returns the result status.

        :param query: the SQL query to execute.
        :param args: the parameters to pass to the SQL query.
        :param timeout: the number of seconds to wait before timing out the SQL query.
        :return: the result status of the SQL query.
        """
        async with self.cursor() as cursor:
            return await cursor.executemany(
                query, args  # type:ignore
            )

    async def fetch(
        self,
        query: str,
        *args,
        cursor_class: type[Cursor] = Cursor,
    ) -> list[Any]:
        """
        Executes an SQL query and returns the rows fetched as a list of records.

        :param query: the SQL query to execute.
        :param args: the parameters to pass to the SQL query.
        :param timeout: the number of seconds to wait before timing out the SQL query.
        :param cursor_class: the class to be used on the cursor to make the records.
        :return: a list of instances of `cursor_class` type.
        """
        async with self.cursor(cursor_class) as cursor:
            await cursor.execute(query, args)
            return await cursor.fetchall()

    async def fetchrow(
        self,
        query: str,
        *args,
        cursor_class: type[Cursor] = Cursor,
    ) -> Optional[Any]:
        """
        Executes an SQL query and returns the first row fetched as a record or None.

        :param query: the SQL query to execute.
        :param args: the parameters to pass to the SQL query.
        :param timeout: the number of seconds to wait before timing out the SQL query.
        :param record_class: the class to be used on the record.
        :return: an instance `record_class`.
        """
        async with self.cursor(cursor_class) as cursor:
            await cursor.execute(query, args)
            return await cursor.fetchone()


AsyncmyContext = AsyncContext[ConnectionProxy]


@define
class AsyncmyAdapter(AtomicAsyncAdapter[ConnectionProxy]):
    """An adapter for connecting to a PostgreSQL database using aiomysql."""

    config: DatabaseConfig = info(default=db_config_factory)

    async def init(self):
        """Initialize the adapter by creating a connection pool."""
        pool = await asyncmy.create_pool(
            maxsize=self.config.pool_size + self.config.max_overflow,
            pool_recycle=self.config.pool_recycle,
            host=self.config.host,
            port=self.config.port if self.config.port != -1 else DEFAULT_PORT,
            user=self.config.user,
            password=self.config.password,
            db=self.config.name,
            autocommit=False,
        )
        AsyncmyAdapter.pool.manual_set(self, pool)
        AsyncmyAdapter.initialized.manual_set(self, True)

    @lazyfield
    def pool(self) -> Pool:
        """The connection pool used by the adapter."""
        raise RuntimeError("Pool is not initialized yet")

    @lazyfield
    def initialized(self):
        """Whether the adapter has been initialized."""
        return False

    async def is_closed(self, client: ConnectionProxy) -> bool:
        """Check if a database connection is closed."""
        return client.closed()

    async def new(self) -> ConnectionProxy:
        """Create a new database connection."""
        if not self.initialized:
            await self.init()
        return ConnectionProxy(await self.pool.acquire(), self.pool.release)

    async def release(self, client: ConnectionProxy) -> None:
        """Release a database connection."""
        await client.close()

    async def begin(self, client: ConnectionProxy) -> None:
        """Begin a new transaction."""
        await client.transaction()

    async def commit(self, client: ConnectionProxy) -> None:
        """Commit the current transaction."""
        await client.commit()

    async def rollback(self, client: ConnectionProxy) -> None:
        """Rollback the current transaction."""
        await client.rollback()

    async def in_atomic(self, client: ConnectionProxy) -> bool:
        """Check if a transaction is currently active."""
        return client.in_atomic()

    def context(self):
        """Create a new context for using the adapter."""
        return AsyncmyContext(self)

    async def dispose(self):
        """
        Shuts down the connection pool and resets the adapter state.

        This method should be called when the application is shutting down or
        when the adapter is no longer needed.

        Raises:
            RuntimeError: If the adapter is not initialized yet.
        """
        if not self.initialized:
            raise RuntimeError("Adapter is not initialized")

        pool = self.pool
        pool.close()
        await pool.wait_closed()
        AsyncmyAdapter.pool.cleanup(self)
        AsyncmyAdapter.initialized.manual_set(self, False)
