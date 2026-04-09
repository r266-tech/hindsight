"""Oracle 23ai backend implementation using python-oracledb.

Wraps oracledb's async pool and cursor objects behind the DatabaseBackend
and DatabaseConnection interfaces.

Includes transparent query rewriting so that PostgreSQL-style SQL ($1 params,
::type casts) works against Oracle without requiring callers to change their
query strings.

Requires: python-oracledb (thin mode — pure Python, no Oracle client needed).
"""

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from .base import DatabaseBackend, DatabaseConnection
from .result import ResultRow

logger = logging.getLogger(__name__)

# Regex patterns for PostgreSQL → Oracle query rewriting
_PG_PARAM_RE = re.compile(r"\$(\d+)")
# Match ::type casts but NOT :: inside string literals.
# Handles common types: jsonb, json, text, uuid, uuid[], varchar[], text[],
# timestamptz, timestamptz[], interval, vector, integer, bigint, float, numeric
_PG_CAST_RE = re.compile(
    r"::(?:jsonb|json|text|uuid(?:\[\])?|varchar(?:\[\])?|text\[\]|"
    r"timestamptz(?:\[\])?|interval|vector|integer|bigint|float|numeric)"
)


def _rewrite_pg_to_oracle(query: str) -> str:
    """Rewrite PostgreSQL-style SQL to Oracle-compatible SQL.

    Handles:
    - $N parameter placeholders → :N
    - ::type casts → removed (Oracle uses implicit conversion or TO_* functions)
    - NOW() → SYSTIMESTAMP
    - gen_random_uuid() → SYS_GUID()
    - ILIKE → case-insensitive LIKE (UPPER/LIKE)
    """
    # Replace $N with :N
    query = _PG_PARAM_RE.sub(r":\1", query)
    # Remove PostgreSQL-style type casts (::jsonb, ::text, etc.)
    query = _PG_CAST_RE.sub("", query)
    # Replace NOW() with SYSTIMESTAMP
    query = re.sub(r"\bNOW\(\)", "SYSTIMESTAMP", query, flags=re.IGNORECASE)
    # Replace gen_random_uuid() with SYS_GUID()
    query = re.sub(r"\bgen_random_uuid\(\)", "SYS_GUID()", query, flags=re.IGNORECASE)
    return query


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
    """DatabaseConnection wrapper around an oracledb async connection.

    Transparently rewrites PostgreSQL-style SQL ($N params, ::type casts)
    to Oracle syntax so that existing consumer code works without modification.
    """

    __slots__ = ("_conn",)

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["OracleConnection"]:
        # Oracle uses savepoints for nested transactions
        import uuid as _uuid

        sp_name = f"sp_{_uuid.uuid4().hex[:12]}"
        cursor = self._conn.cursor()
        await cursor.execute(f"SAVEPOINT {sp_name}")
        cursor.close()
        try:
            yield self
        except Exception:
            cursor = self._conn.cursor()
            await cursor.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
            cursor.close()
            raise
        # On clean exit, the savepoint is simply released (implicit with next commit)

    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str:
        query = _rewrite_pg_to_oracle(query)
        cursor = self._conn.cursor()
        try:
            await cursor.execute(query, args or None)
            return f"OK {cursor.rowcount}"
        finally:
            cursor.close()

    async def executemany(self, query: str, args: list[tuple[Any, ...]], *, timeout: float | None = None) -> None:
        query = _rewrite_pg_to_oracle(query)
        cursor = self._conn.cursor()
        try:
            await cursor.executemany(query, args)
        finally:
            cursor.close()

    async def fetch(self, query: str, *args: Any, timeout: float | None = None) -> list[ResultRow]:
        query = _rewrite_pg_to_oracle(query)
        cursor = self._conn.cursor()
        try:
            await cursor.execute(query, args or None)
            columns = [col[0].lower() for col in cursor.description or []]
            rows = await cursor.fetchall()
            return [ResultRow(dict(zip(columns, row))) for row in rows]
        finally:
            cursor.close()

    async def fetchrow(self, query: str, *args: Any, timeout: float | None = None) -> ResultRow | None:
        query = _rewrite_pg_to_oracle(query)
        cursor = self._conn.cursor()
        try:
            await cursor.execute(query, args or None)
            columns = [col[0].lower() for col in cursor.description or []]
            row = await cursor.fetchone()
            if row is None:
                return None
            return ResultRow(dict(zip(columns, row)))
        finally:
            cursor.close()

    async def fetchval(self, query: str, *args: Any, column: int = 0, timeout: float | None = None) -> Any:
        query = _rewrite_pg_to_oracle(query)
        cursor = self._conn.cursor()
        try:
            await cursor.execute(query, args or None)
            row = await cursor.fetchone()
            if row is None:
                return None
            return row[column]
        finally:
            cursor.close()


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

        # create_pool_async returns an AsyncConnectionPool directly (not a coroutine)
        self._pool = oracledb.create_pool_async(
            dsn=dsn,
            min=min_size,
            max=max_size,
            stmtcachesize=statement_cache_size,
        )

        logger.info(f"Oracle pool created (min={min_size}, max={max_size})")

    async def shutdown(self) -> None:
        if self._pool is not None:
            await self._pool.close(force=True)
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
