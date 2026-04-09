"""Abstract base classes for database backend abstraction.

Defines the interfaces that all database backends (PostgreSQL, Oracle, etc.)
must implement. Business logic depends only on these interfaces.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from .result import ResultRow


class DatabaseConnection(ABC):
    """Wraps a single connection from the pool.

    Provides a uniform interface over asyncpg.Connection, oracledb cursor, etc.
    Methods mirror asyncpg's connection API for minimal migration friction.
    """

    @abstractmethod
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["DatabaseConnection"]:
        """Start a transaction (or savepoint if already in a transaction).

        Yields:
            Self — the same connection, now inside a transaction scope.
            On clean exit the transaction is committed; on exception it is rolled back.
        """
        ...  # pragma: no cover
        yield  # type: ignore[misc]

    @abstractmethod
    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str:
        """Execute a query and return a status string (e.g. 'INSERT 0 1').

        Args:
            query: SQL query with dialect-appropriate placeholders.
            *args: Positional bind parameters.
            timeout: Optional statement timeout in seconds.

        Returns:
            Command status string.
        """
        ...

    @abstractmethod
    async def executemany(self, query: str, args: list[tuple[Any, ...]], *, timeout: float | None = None) -> None:
        """Execute a query for each set of arguments.

        Args:
            query: SQL query with dialect-appropriate placeholders.
            args: List of argument tuples, one per execution.
            timeout: Optional statement timeout in seconds.
        """
        ...

    @abstractmethod
    async def fetch(self, query: str, *args: Any, timeout: float | None = None) -> list[ResultRow]:
        """Execute a query and return all rows.

        Args:
            query: SQL query with dialect-appropriate placeholders.
            *args: Positional bind parameters.
            timeout: Optional statement timeout in seconds.

        Returns:
            List of ResultRow objects.
        """
        ...

    @abstractmethod
    async def fetchrow(self, query: str, *args: Any, timeout: float | None = None) -> ResultRow | None:
        """Execute a query and return a single row (or None).

        Args:
            query: SQL query with dialect-appropriate placeholders.
            *args: Positional bind parameters.
            timeout: Optional statement timeout in seconds.

        Returns:
            A single ResultRow, or None if no rows match.
        """
        ...

    @abstractmethod
    async def fetchval(self, query: str, *args: Any, column: int = 0, timeout: float | None = None) -> Any:
        """Execute a query and return a single value from the first row.

        Args:
            query: SQL query with dialect-appropriate placeholders.
            *args: Positional bind parameters.
            column: Column index to return (default 0).
            timeout: Optional statement timeout in seconds.

        Returns:
            The value from the specified column of the first row, or None.
        """
        ...

    async def copy_records_to_table(
        self,
        table_name: str,
        *,
        records: list[tuple[Any, ...]],
        columns: list[str],
        timeout: float | None = None,
    ) -> None:
        """Bulk-load records into a table.

        Default implementation uses executemany INSERT. Backends with native
        bulk-load support (e.g. asyncpg COPY) should override for performance.
        """
        cols = ", ".join(columns)
        placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))
        query = f"INSERT INTO {table_name} ({cols}) VALUES ({placeholders})"
        await self.executemany(query, list(records))


class DatabaseBackend(ABC):
    """Database pool lifecycle and connection acquisition.

    Manages the connection pool and provides context managers for
    acquiring connections and running transactions.
    """

    @abstractmethod
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
        """Create the connection pool.

        Args:
            dsn: Database connection string.
            min_size: Minimum number of connections in the pool.
            max_size: Maximum number of connections in the pool.
            command_timeout: Default command timeout in seconds.
            acquire_timeout: Timeout for acquiring a connection from the pool.
            statement_cache_size: Size of the prepared-statement cache (0 to disable).
            init_callback: Optional async callback invoked on each new connection.
        """
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Close the connection pool and release all resources."""
        ...

    @abstractmethod
    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[DatabaseConnection]:
        """Acquire a connection from the pool.

        Yields:
            A DatabaseConnection wrapper.
        """
        ...  # pragma: no cover
        yield  # type: ignore[misc]

    @abstractmethod
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[DatabaseConnection]:
        """Acquire a connection and start a transaction.

        The transaction is committed on clean exit, rolled back on exception.

        Yields:
            A DatabaseConnection wrapper inside a transaction.
        """
        ...  # pragma: no cover
        yield  # type: ignore[misc]

    @abstractmethod
    def get_pool(self) -> Any:
        """Return the underlying raw pool object.

        Escape hatch for gradual migration — callers that still need direct
        pool access (e.g. asyncpg-specific features) can use this during
        the transition period.
        """
        ...
