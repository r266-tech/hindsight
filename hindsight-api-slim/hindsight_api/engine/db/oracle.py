"""Oracle 23ai backend implementation using python-oracledb.

Wraps oracledb's async pool and cursor objects behind the DatabaseBackend
and DatabaseConnection interfaces.

Requires: python-oracledb (thin mode — pure Python, no Oracle client needed).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from .base import DatabaseBackend, DatabaseConnection
from .result import ResultRow

logger = logging.getLogger(__name__)


def _import_oracledb():
    """Lazy import oracledb to avoid hard dependency."""
    try:
        import oracledb  # type: ignore[import-not-found]

        # Use thin mode (pure Python, no Oracle client needed)
        oracledb.defaults.fetch_lobs = False
        return oracledb
    except ImportError:
        raise ImportError(
            "python-oracledb is required for Oracle backend. Install it with: pip install oracledb"
        ) from None


class OracleConnection(DatabaseConnection):
    """DatabaseConnection wrapper around an oracledb async connection."""

    __slots__ = ("_conn",)

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str:
        cursor = self._conn.cursor()
        try:
            await cursor.execute(query, args or None)
            return f"OK {cursor.rowcount}"
        finally:
            await cursor.close()

    async def executemany(self, query: str, args: list[tuple[Any, ...]], *, timeout: float | None = None) -> None:
        cursor = self._conn.cursor()
        try:
            await cursor.executemany(query, args)
        finally:
            await cursor.close()

    async def fetch(self, query: str, *args: Any, timeout: float | None = None) -> list[ResultRow]:
        cursor = self._conn.cursor()
        try:
            await cursor.execute(query, args or None)
            columns = [col[0].lower() for col in cursor.description or []]
            rows = await cursor.fetchall()
            return [ResultRow(dict(zip(columns, row))) for row in rows]
        finally:
            await cursor.close()

    async def fetchrow(self, query: str, *args: Any, timeout: float | None = None) -> ResultRow | None:
        cursor = self._conn.cursor()
        try:
            await cursor.execute(query, args or None)
            columns = [col[0].lower() for col in cursor.description or []]
            row = await cursor.fetchone()
            if row is None:
                return None
            return ResultRow(dict(zip(columns, row)))
        finally:
            await cursor.close()

    async def fetchval(self, query: str, *args: Any, column: int = 0, timeout: float | None = None) -> Any:
        cursor = self._conn.cursor()
        try:
            await cursor.execute(query, args or None)
            row = await cursor.fetchone()
            if row is None:
                return None
            return row[column]
        finally:
            await cursor.close()


class OracleBackend(DatabaseBackend):
    """DatabaseBackend implementation wrapping an oracledb async connection pool."""

    def __init__(self) -> None:
        self._pool: Any = None
        self._oracledb: Any = None

    async def initialize(
        self,
        dsn: str,
        *,
        min_size: int = 5,
        max_size: int = 20,
        command_timeout: float = 300,
        acquire_timeout: float = 30,
        statement_cache_size: int = 0,
        init_callback: Any | None = None,
    ) -> None:
        oracledb = _import_oracledb()
        self._oracledb = oracledb

        self._pool = oracledb.create_pool_async(
            dsn=dsn,
            min=min_size,
            max=max_size,
            stmtcachesize=statement_cache_size,
        )
        # Await pool creation
        self._pool = await self._pool

        logger.info(f"Oracle pool created (min={min_size}, max={max_size})")

    async def shutdown(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("Oracle pool closed")

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[OracleConnection]:
        pool = self._ensure_pool()
        conn = await pool.acquire()
        try:
            yield OracleConnection(conn)
        finally:
            await pool.release(conn)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[OracleConnection]:
        pool = self._ensure_pool()
        conn = await pool.acquire()
        try:
            yield OracleConnection(conn)
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
        finally:
            await pool.release(conn)

    def get_pool(self) -> Any:
        return self._ensure_pool()

    def _ensure_pool(self) -> Any:
        if self._pool is None:
            raise RuntimeError("OracleBackend is not initialized. Call initialize() first.")
        return self._pool
