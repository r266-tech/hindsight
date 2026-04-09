"""Database backend abstraction layer.

Provides a uniform interface over different database drivers (asyncpg, oracledb, etc.)
so that business logic is decoupled from any specific database platform.

Usage:
    from hindsight_api.engine.db import create_database_backend, DatabaseBackend

    backend = create_database_backend("postgresql")
    await backend.initialize(dsn="postgresql://...")
    async with backend.acquire() as conn:
        rows = await conn.fetch("SELECT ...")
"""

from .base import DatabaseBackend, DatabaseConnection
from .result import ResultRow

__all__ = [
    "DatabaseBackend",
    "DatabaseConnection",
    "ResultRow",
    "create_database_backend",
]


def create_database_backend(backend_type: str) -> DatabaseBackend:
    """Factory: create a DatabaseBackend by name.

    Args:
        backend_type: One of "postgresql" or "oracle".

    Returns:
        An uninitialized DatabaseBackend instance.

    Raises:
        ValueError: If backend_type is not recognized.
    """
    if backend_type == "postgresql":
        from .postgresql import PostgreSQLBackend

        return PostgreSQLBackend()
    elif backend_type == "oracle":
        from .oracle import OracleBackend

        return OracleBackend()
    raise ValueError(f"Unknown database backend: {backend_type!r}. Supported backends: 'postgresql', 'oracle'.")
