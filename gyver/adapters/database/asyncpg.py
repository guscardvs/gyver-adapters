from typing import Optional, Sequence, TypeVar

import asyncpg
from asyncpg.connection import Connection
from asyncpg.pool import Pool
from asyncpg.protocol import Record
from asyncpg.transaction import Transaction

from gyver.attrs import define, info
from gyver.context import AsyncContext, AtomicAsyncAdapter
from gyver.utils import lazyfield

from .config import DatabaseConfig, db_config_factory, make_uri

RecordT = TypeVar("RecordT", bound=Record)

DEFAULT_PORT = 5432


@define
class ConnectionProxy:
    conn: Connection
    transaction_stack: list[Transaction]

    def __init__(self, conn: Connection) -> None:
        self.__gattrs_init__(conn, [])  # type: ignore

    def closed(self):
        return self.conn.is_closed()

    async def close(self):
        if self.transaction_stack:
            for trx in reversed(self.transaction_stack):
                await trx.rollback()
            self.transaction_stack.clear()
        await self.conn.close()

    async def transaction(self):
        trx = self.conn.transaction()
        self.transaction_stack.append(trx)

    async def commit(self):
        if not self.transaction_stack:
            raise RuntimeError("No transaction found in stack")
        trx = self.transaction_stack.pop()
        await trx.commit()

    async def rollback(self):
        if not self.transaction_stack:
            raise RuntimeError("No transaction found in stack")
        trx = self.transaction_stack.pop()
        await trx.rollback()

    def in_atomic(self):
        return bool(self.transaction_stack)

    def cursor(
        self,
        query: str,
        *args,
        prefetch: Optional[int] = None,
        timeout: Optional[float] = None,
        record_class: Optional[type[Record]] = None,
    ):
        return self.conn.cursor(
            query,
            *args,
            prefetch=prefetch,
            timeout=timeout,
            record_class=record_class,
        )

    async def execute(
        self,
        query: str,
        *args,
        timeout: Optional[float] = None,
    ):
        return await self.conn.execute(
            query, *args, timeout=timeout  # type:ignore
        )

    async def executemany(
        self,
        command: str,
        args: Sequence[Sequence],
        *,
        timeout: Optional[float] = None,
    ):
        return await self.conn.executemany(
            command, args, timeout=timeout  # type:ignore
        )

    async def fetch(
        self,
        query: str,
        *args,
        timeout: Optional[float] = None,
        record_class: type[RecordT] = None,
    ) -> list[RecordT]:
        return await self.conn.fetch(
            query, *args, timeout=timeout, record_class=record_class
        )

    async def fetchrow(
        self,
        query: str,
        *args,
        timeout: Optional[float] = None,
        record_class: type[RecordT] = None,
    ) -> Optional[RecordT]:
        return await self.conn.fetchrow(
            query, *args, timeout=timeout, record_class=record_class
        )


AsyncpgContext = AsyncContext[ConnectionProxy]


@define
class AsyncpgAdapter(AtomicAsyncAdapter[ConnectionProxy]):
    config: DatabaseConfig = info(default=db_config_factory)

    @lazyfield
    def uri(self):
        return make_uri(
            self.config,
            self.config.port if self.config.port != -1 else DEFAULT_PORT,
            "postgres",
        )

    async def init(self):
        pool = asyncpg.create_pool(
            self.uri,
            max_size=self.config.pool_size + self.config.max_overflow,
            max_inactive_connection_lifetime=self.config.pool_recycle,
        )
        await pool  # pool._async_init can return none
        AsyncpgAdapter.pool.manual_set(self, pool)
        AsyncpgAdapter.initialized.manual_set(self, True)

    @lazyfield
    def pool(self) -> Pool:
        raise RuntimeError("Pool is not initialized yet")

    @lazyfield
    def initialized(self):
        return False

    async def is_closed(self, client: ConnectionProxy) -> bool:
        return client.closed()

    async def new(self) -> ConnectionProxy:
        if not self.initialized:
            await self.init()
        return ConnectionProxy(await self.pool.acquire())

    async def release(self, client: ConnectionProxy) -> None:
        await client.close()

    async def begin(self, client: ConnectionProxy) -> None:
        await client.transaction()

    async def commit(self, client: ConnectionProxy) -> None:
        await client.commit()

    async def rollback(self, client: ConnectionProxy) -> None:
        await client.rollback()

    async def in_atomic(self, client: ConnectionProxy) -> bool:
        return client.in_atomic()

    def context(self):
        return AsyncpgContext(self)
