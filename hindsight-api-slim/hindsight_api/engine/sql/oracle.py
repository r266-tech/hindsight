"""Oracle 23ai SQL dialect implementation.

Provides Oracle-specific SQL fragments for parameter binding, JSON operators,
vector distance (VECTOR_DISTANCE), full-text search (Oracle Text), and
other non-portable patterns.
"""

from .base import SQLDialect


class OracleDialect(SQLDialect):
    """SQL dialect for Oracle 23ai (python-oracledb)."""

    # -- Parameter binding -----------------------------------------------

    def param(self, n: int) -> str:
        return f":{n}"

    # -- Type casting ----------------------------------------------------

    def cast(self, param: str, type_name: str) -> str:
        # Oracle uses standard CAST syntax
        oracle_type = self._map_type(type_name)
        return f"CAST({param} AS {oracle_type})"

    @staticmethod
    def _map_type(pg_type: str) -> str:
        """Map PostgreSQL type names to Oracle equivalents."""
        mapping = {
            "jsonb": "CLOB",  # Oracle stores JSON in CLOB
            "json": "CLOB",
            "text": "VARCHAR2(4000)",
            "text[]": "CLOB",  # JSON array
            "uuid": "RAW(16)",
            "uuid[]": "CLOB",  # JSON array
            "varchar[]": "CLOB",  # JSON array
            "float8": "BINARY_DOUBLE",
            "float8[]": "CLOB",
            "timestamptz": "TIMESTAMP WITH TIME ZONE",
            "timestamptz[]": "CLOB",
            "vector": "VECTOR",
            "vector[]": "CLOB",
            "integer": "NUMBER",
            "bigint": "NUMBER",
            "boolean": "NUMBER(1)",
        }
        return mapping.get(pg_type, pg_type.upper())

    # -- Vector operations -----------------------------------------------

    def vector_distance(self, col: str, param: str) -> str:
        return f"VECTOR_DISTANCE({col}, {param}, COSINE)"

    def vector_similarity(self, col: str, param: str) -> str:
        return f"(1 - VECTOR_DISTANCE({col}, {param}, COSINE))"

    # -- JSON operations -------------------------------------------------

    def json_extract_text(self, col: str, key: str) -> str:
        return f"JSON_VALUE({col}, '$.{key}')"

    def json_contains(self, col: str, param: str) -> str:
        return f"JSON_EXISTS({col}, '$?(@  == {param})')"

    def json_merge(self, col: str, param: str) -> str:
        return f"JSON_MERGEPATCH({col}, {param})"

    # -- Text search -----------------------------------------------------

    def text_search_score(self, col: str, query_param: str, *, index_name: str | None = None) -> str:
        # Oracle Text: CONTAINS with SCORE
        return "SCORE(1)"

    def text_search_order(self, col: str, query_param: str, *, index_name: str | None = None) -> str:
        return "SCORE(1) DESC"

    # -- Fuzzy string matching -------------------------------------------

    def similarity(self, col: str, param: str) -> str:
        return f"UTL_MATCH.EDIT_DISTANCE_SIMILARITY({col}, {param}) / 100.0"

    # -- Upsert ----------------------------------------------------------

    def upsert(
        self,
        table: str,
        columns: list[str],
        conflict_columns: list[str],
        update_columns: list[str],
    ) -> str:
        col_list = ", ".join(columns)
        src_cols = ", ".join(f":{i + 1} AS {c}" for i, c in enumerate(columns))
        on_clause = " AND ".join(f"t.{c} = s.{c}" for c in conflict_columns)

        if not update_columns:
            return (
                f"MERGE INTO {table} t "
                f"USING (SELECT {src_cols} FROM DUAL) s "
                f"ON ({on_clause}) "
                f"WHEN NOT MATCHED THEN INSERT ({col_list}) "
                f"VALUES ({', '.join(f's.{c}' for c in columns)})"
            )

        updates = ", ".join(f"t.{c} = s.{c}" for c in update_columns)
        return (
            f"MERGE INTO {table} t "
            f"USING (SELECT {src_cols} FROM DUAL) s "
            f"ON ({on_clause}) "
            f"WHEN MATCHED THEN UPDATE SET {updates} "
            f"WHEN NOT MATCHED THEN INSERT ({col_list}) "
            f"VALUES ({', '.join(f's.{c}' for c in columns)})"
        )

    # -- Bulk operations -------------------------------------------------

    def bulk_unnest(self, param_types: list[tuple[str, str]]) -> str:
        # Oracle: use JSON_TABLE to expand a JSON array into rows
        # Caller passes a JSON array as the parameter
        columns = []
        for i, (param, sql_type) in enumerate(param_types):
            oracle_type = self._map_type(sql_type.rstrip("[]"))
            columns.append(f"c{i} {oracle_type} PATH '$[{i}]'")
        cols_spec = ", ".join(columns)
        # Using first param as the JSON array source
        first_param = param_types[0][0]
        return f"JSON_TABLE({first_param}, '$[*]' COLUMNS ({cols_spec}))"

    # -- Pagination ------------------------------------------------------

    def limit_offset(self, limit_param: str, offset_param: str) -> str:
        return f"OFFSET {offset_param} ROWS FETCH FIRST {limit_param} ROWS ONLY"

    # -- RETURNING clause ------------------------------------------------

    def returning(self, columns: list[str]) -> str:
        # Oracle RETURNING requires INTO clause with output bind variables.
        # The backend layer handles the output variable binding.
        return f"RETURNING {', '.join(columns)} INTO {', '.join(f':out_{c}' for c in columns)}"

    # -- Pattern matching ------------------------------------------------

    def ilike(self, col: str, param: str) -> str:
        return f"UPPER({col}) LIKE UPPER({param})"

    # -- Array operations ------------------------------------------------

    def array_any(self, param: str) -> str:
        # Oracle: expand JSON array to rows for IN clause
        return f"IN (SELECT value FROM JSON_TABLE({param}, '$[*]' COLUMNS (value PATH '$')))"

    def array_all(self, param: str) -> str:
        return f"NOT IN (SELECT value FROM JSON_TABLE({param}, '$[*]' COLUMNS (value PATH '$')))"

    def array_contains(self, col: str, param: str) -> str:
        # Oracle: check all elements of param array exist in col JSON array
        return (
            f"(SELECT COUNT(*) FROM JSON_TABLE({param}, '$[*]' COLUMNS (v PATH '$')) "
            f"WHERE JSON_EXISTS({col}, '$[*]?(@ == v)')) = "
            f"(SELECT COUNT(*) FROM JSON_TABLE({param}, '$[*]' COLUMNS (v PATH '$')))"
        )

    # -- Locking ---------------------------------------------------------

    def for_update_skip_locked(self) -> str:
        return "FOR UPDATE SKIP LOCKED"

    def advisory_lock(self, id_param: str) -> str:
        # Oracle doesn't have advisory locks. Use SELECT FOR UPDATE NOWAIT on a lock row.
        return "SELECT 1 FROM dual FOR UPDATE NOWAIT"

    # -- UUID generation -------------------------------------------------

    def generate_uuid(self) -> str:
        return "SYS_GUID()"

    # -- Misc ------------------------------------------------------------

    def greatest(self, *args: str) -> str:
        return f"GREATEST({', '.join(args)})"

    def current_timestamp(self) -> str:
        return "SYSTIMESTAMP"

    def array_agg(self, expr: str) -> str:
        return f"JSON_ARRAYAGG({expr})"
