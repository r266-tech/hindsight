"""Tests for the database abstraction layer (db + sql modules).

Unit tests that verify the abstraction interfaces work correctly
without requiring a live database connection.
"""

import pytest

from hindsight_api.engine.db import DatabaseBackend, DatabaseConnection, ResultRow, create_database_backend
from hindsight_api.engine.db.postgresql import PostgreSQLBackend
from hindsight_api.engine.sql import SQLDialect, create_sql_dialect
from hindsight_api.engine.sql.postgresql import PostgreSQLDialect


# ---------------------------------------------------------------------------
# ResultRow tests
# ---------------------------------------------------------------------------


class TestResultRow:
    def test_dict_access(self):
        row = ResultRow({"id": 1, "name": "test"})
        assert row["id"] == 1
        assert row["name"] == "test"

    def test_attr_access(self):
        row = ResultRow({"id": 1, "name": "test"})
        assert row.id == 1
        assert row.name == "test"

    def test_get_with_default(self):
        row = ResultRow({"id": 1})
        assert row.get("id") == 1
        assert row.get("missing") is None
        assert row.get("missing", "default") == "default"

    def test_keys(self):
        row = ResultRow({"a": 1, "b": 2})
        assert set(row.keys()) == {"a", "b"}

    def test_values(self):
        row = ResultRow({"a": 1, "b": 2})
        assert set(row.values()) == {1, 2}

    def test_items(self):
        row = ResultRow({"a": 1, "b": 2})
        assert set(row.items()) == {("a", 1), ("b", 2)}

    def test_contains(self):
        row = ResultRow({"id": 1})
        assert "id" in row
        assert "missing" not in row

    def test_len(self):
        row = ResultRow({"a": 1, "b": 2, "c": 3})
        assert len(row) == 3

    def test_bool_always_true(self):
        row = ResultRow({})
        assert bool(row)

    def test_repr(self):
        row = ResultRow({"id": 1})
        assert "ResultRow" in repr(row)

    def test_missing_attr_raises(self):
        row = ResultRow({"id": 1})
        with pytest.raises(AttributeError):
            _ = row.missing


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


class TestFactories:
    def test_create_postgresql_backend(self):
        backend = create_database_backend("postgresql")
        assert isinstance(backend, PostgreSQLBackend)
        assert isinstance(backend, DatabaseBackend)

    def test_create_unknown_backend_raises(self):
        with pytest.raises(ValueError, match="Unknown database backend"):
            create_database_backend("mysql")

    def test_create_postgresql_dialect(self):
        dialect = create_sql_dialect("postgresql")
        assert isinstance(dialect, PostgreSQLDialect)
        assert isinstance(dialect, SQLDialect)

    def test_create_unknown_dialect_raises(self):
        with pytest.raises(ValueError, match="Unknown SQL dialect"):
            create_sql_dialect("mysql")


# ---------------------------------------------------------------------------
# PostgreSQLDialect tests
# ---------------------------------------------------------------------------


class TestPostgreSQLDialect:
    @pytest.fixture()
    def d(self):
        return PostgreSQLDialect()

    def test_param(self, d):
        assert d.param(1) == "$1"
        assert d.param(3) == "$3"

    def test_cast(self, d):
        assert d.cast("$1", "jsonb") == "$1::jsonb"
        assert d.cast("$2", "uuid[]") == "$2::uuid[]"

    def test_vector_distance(self, d):
        assert d.vector_distance("embedding", "$1") == "embedding <=> $1::vector"

    def test_vector_similarity(self, d):
        assert d.vector_similarity("embedding", "$1") == "1 - (embedding <=> $1::vector)"

    def test_json_extract_text(self, d):
        assert d.json_extract_text("col", "key") == "col ->> 'key'"

    def test_json_contains(self, d):
        assert d.json_contains("col", "$1") == "col @> $1::jsonb"

    def test_json_merge(self, d):
        assert d.json_merge("col", "$1") == "col || $1::jsonb"

    def test_text_search_score_bm25(self, d):
        result = d.text_search_score("text", "$1", index_name="idx_test")
        assert "to_bm25query" in result

    def test_text_search_score_tsvector(self, d):
        result = d.text_search_score("text", "$1")
        assert "ts_rank_cd" in result

    def test_similarity(self, d):
        assert d.similarity("col", "$1") == "similarity(col, $1)"

    def test_upsert_do_nothing(self, d):
        sql = d.upsert("t", ["a", "b"], ["a"], [])
        assert "ON CONFLICT (a) DO NOTHING" in sql

    def test_upsert_do_update(self, d):
        sql = d.upsert("t", ["a", "b"], ["a"], ["b"])
        assert "ON CONFLICT (a) DO UPDATE SET b = EXCLUDED.b" in sql

    def test_bulk_unnest(self, d):
        result = d.bulk_unnest([("$1", "text[]"), ("$2", "uuid[]")])
        assert result == "unnest($1::text[], $2::uuid[])"

    def test_limit_offset(self, d):
        assert d.limit_offset("$1", "$2") == "LIMIT $1 OFFSET $2"

    def test_returning(self, d):
        assert d.returning(["id", "name"]) == "RETURNING id, name"

    def test_ilike(self, d):
        assert d.ilike("col", "$1") == "col ILIKE $1"

    def test_array_any(self, d):
        assert d.array_any("$1") == "= ANY($1)"

    def test_array_all(self, d):
        assert d.array_all("$1") == "!= ALL($1)"

    def test_array_contains(self, d):
        assert d.array_contains("tags", "$1") == "tags @> $1::varchar[]"

    def test_for_update_skip_locked(self, d):
        assert d.for_update_skip_locked() == "FOR UPDATE SKIP LOCKED"

    def test_advisory_lock(self, d):
        assert d.advisory_lock("$1") == "pg_try_advisory_lock($1)"

    def test_generate_uuid(self, d):
        assert d.generate_uuid() == "gen_random_uuid()"

    def test_greatest(self, d):
        assert d.greatest("a", "b") == "GREATEST(a, b)"

    def test_current_timestamp(self, d):
        assert d.current_timestamp() == "now()"

    def test_array_agg(self, d):
        assert d.array_agg("col") == "array_agg(col)"


# ---------------------------------------------------------------------------
# OracleDialect tests (no oracledb dependency needed)
# ---------------------------------------------------------------------------


class TestOracleDialect:
    @pytest.fixture()
    def d(self):
        from hindsight_api.engine.sql.oracle import OracleDialect

        return OracleDialect()

    def test_param(self, d):
        assert d.param(1) == ":1"
        assert d.param(3) == ":3"

    def test_vector_distance(self, d):
        assert "VECTOR_DISTANCE" in d.vector_distance("embedding", ":1")
        assert "COSINE" in d.vector_distance("embedding", ":1")

    def test_ilike(self, d):
        assert "UPPER" in d.ilike("col", ":1")

    def test_upsert(self, d):
        sql = d.upsert("t", ["a", "b"], ["a"], ["b"])
        assert "MERGE INTO" in sql

    def test_limit_offset(self, d):
        result = d.limit_offset(":1", ":2")
        assert "FETCH FIRST" in result
        assert "OFFSET" in result

    def test_returning(self, d):
        result = d.returning(["id"])
        assert "RETURNING" in result
        assert "INTO" in result

    def test_generate_uuid(self, d):
        assert d.generate_uuid() == "SYS_GUID()"

    def test_current_timestamp(self, d):
        assert d.current_timestamp() == "SYSTIMESTAMP"


# ---------------------------------------------------------------------------
# PostgreSQLBackend unit tests (no live DB)
# ---------------------------------------------------------------------------


class TestPostgreSQLBackendUnit:
    def test_uninitialized_acquire_raises(self):
        backend = PostgreSQLBackend()
        with pytest.raises(RuntimeError, match="not initialized"):
            backend.get_pool()

    def test_uninitialized_get_pool_raises(self):
        backend = PostgreSQLBackend()
        with pytest.raises(RuntimeError, match="not initialized"):
            backend.get_pool()


# ---------------------------------------------------------------------------
# Config integration test
# ---------------------------------------------------------------------------


class TestConfig:
    def test_database_backend_field_exists(self):
        from hindsight_api.config import HindsightConfig

        # Verify the field exists on the dataclass
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(HindsightConfig)}
        assert "database_backend" in field_names

    def test_default_database_backend(self):
        from hindsight_api.config import DEFAULT_DATABASE_BACKEND

        assert DEFAULT_DATABASE_BACKEND == "postgresql"
