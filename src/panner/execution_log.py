"""SQLite-backed execution log for CodeAgent SQL executions.

Captures every SQL execution for citation grounding (P1.2 CitationChecker
consumes this). Schema fields follow DIRECTIONS.md §Phase 1:

    execution_id / query_id / sql / stdout_truncated / stdout_path /
    started_at / finished_at / exit_code / derived_from_query_ids (JSON)

Phase 1 starts with SQLite directly (not in-memory list) per the redirect
in DIRECTIONS.md §Phase 1 — avoids a Phase 2 schema migration. Phase 2 only
changes the default db_path from in-memory style to filesystem.

Atomic write is SQLite WAL + transaction-level; the "tempfile + os.rename"
pattern from DIRECTIONS.md §Phase 2 applies to large-result parquet files
(P2.2), not SQLite rows.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


_DEFAULT_DB_PATH = "~/.panner/execution_log.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_db_path() -> str:
    return os.path.expanduser(_DEFAULT_DB_PATH)


@dataclass
class ExecutionRecord:
    """A single SQL execution record.

    execution_id scopes one CodeAgent run; query_id scopes one SQL within
    that run. derived_from_query_ids is the DAG edges used by
    find_derivation_chain (D2 design).
    """

    execution_id: str
    query_id: str
    sql: str
    started_at: str
    finished_at: Optional[str] = None
    stdout_truncated: Optional[str] = None
    stdout_path: Optional[str] = None
    exit_code: Optional[int] = None
    derived_from_query_ids: list[str] = field(default_factory=list)

    def contains_value(self, value: str) -> bool:
        """Substring match on stdout_truncated (literal). Phase 1 only."""
        if self.stdout_truncated is None:
            return False
        return value in self.stdout_truncated


class ExecutionLog:
    """SQLite-backed execution log for CodeAgent SQL executions.

    Construction:
        ExecutionLog()                            -> ~/.panner/execution_log.db
        ExecutionLog(db_path="/tmp/foo.db")       -> file-backed
        ExecutionLog(db_path=":memory:")          -> in-memory, ephemeral

    Primary APIs:
        record(execution_id, query_id, sql, ...)  -> insert / upsert one row
        query_by_query_id(query_id) -> list       -> fetch by query_id
        find_derivation_chain(target_value)       -> BFS walk the derived DAG

    Atomic write semantics rely on SQLite WAL + explicit transactions.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS sql_executions (
        execution_id TEXT NOT NULL,
        query_id TEXT NOT NULL,
        sql TEXT NOT NULL,
        stdout_truncated TEXT,
        stdout_path TEXT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        exit_code INTEGER,
        derived_from_query_ids TEXT,
        PRIMARY KEY (execution_id, query_id)
    )
    """

    _INDEXES = (
        "CREATE INDEX IF NOT EXISTS idx_query_id ON sql_executions(query_id)",
        "CREATE INDEX IF NOT EXISTS idx_started_at ON sql_executions(started_at)",
    )

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            db_path = _default_db_path()
        elif db_path == ":memory:":
            pass
        else:
            expanded = os.path.expanduser(db_path)
            parent = os.path.dirname(expanded)
            if parent:
                os.makedirs(parent, exist_ok=True)
            db_path = expanded

        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        if db_path != ":memory:":
            # WAL allows concurrent readers + 1 writer without row corruption
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(self._SCHEMA)
        for idx in self._INDEXES:
            self._conn.execute(idx)

    def __del__(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def record(
        self,
        execution_id: str,
        query_id: str,
        sql: str,
        *,
        stdout_truncated: Optional[str] = None,
        stdout_path: Optional[str] = None,
        started_at: Optional[str] = None,
        finished_at: Optional[str] = None,
        exit_code: Optional[int] = None,
        derived_from_query_ids: Optional[list[str]] = None,
    ) -> None:
        """Insert / upsert an execution record. Idempotent on (execution_id, query_id)."""
        if started_at is None:
            started_at = _now_iso()
        derived_json = json.dumps(derived_from_query_ids or [])

        # BEGIN IMMEDIATE acquires RESERVED lock for safe upsert under WAL
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                """
                INSERT INTO sql_executions (
                    execution_id, query_id, sql, stdout_truncated, stdout_path,
                    started_at, finished_at, exit_code, derived_from_query_ids
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(execution_id, query_id) DO UPDATE SET
                    sql = excluded.sql,
                    stdout_truncated = excluded.stdout_truncated,
                    stdout_path = excluded.stdout_path,
                    finished_at = excluded.finished_at,
                    exit_code = excluded.exit_code,
                    derived_from_query_ids = excluded.derived_from_query_ids
                """,
                (
                    execution_id,
                    query_id,
                    sql,
                    stdout_truncated,
                    stdout_path,
                    started_at,
                    finished_at,
                    exit_code,
                    derived_json,
                ),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def query_by_query_id(self, query_id: str) -> list[ExecutionRecord]:
        """Return all execution records matching query_id, newest first."""
        cursor = self._conn.execute(
            "SELECT * FROM sql_executions WHERE query_id = ? ORDER BY started_at DESC",
            (query_id,),
        )
        return [self._row_to_record(row) for row in cursor.fetchall()]

    def query_all(self) -> list[ExecutionRecord]:
        """All records, newest first. Prefer query_by_query_id where possible."""
        cursor = self._conn.execute("SELECT * FROM sql_executions ORDER BY started_at DESC")
        return [self._row_to_record(row) for row in cursor.fetchall()]

    def find_derivation_chain(self, target_value: str) -> list[ExecutionRecord]:
        """BFS walk over the derived_from_query_ids DAG.

        Returns records whose stdout contains target_value (direct) and
        records transitively connected via derived_from_query_ids. Walks
        BOTH downstream (who derives from this record) AND upstream (who
        does this record derive from) for robustness.

        Per D2 (DIRECTIONS.md §隐藏决策落地 D2):
            - direct: target_value in stdout_truncated
            - transitive: derived_from_query_ids edges connect direct match
              to other records
            - empty result: CitationChecker interprets as "no source — refuse".

        Phase 1 = literal string match. Fuzzy ±0.01 numeric match is the
        CitationChecker's responsibility (P1.2), which may either pre-process
        target_value or wrap this method.
        """
        all_records = self.query_all()
        if not all_records:
            return []

        direct = [r for r in all_records if r.contains_value(target_value)]
        if not direct:
            return []

        by_query_id: dict[str, ExecutionRecord] = {r.query_id: r for r in all_records}
        visited_query_ids: set[str] = set()
        chain: list[ExecutionRecord] = []
        queue: list[ExecutionRecord] = list(direct)

        while queue:
            rec = queue.pop(0)
            if rec.query_id in visited_query_ids:
                continue
            visited_query_ids.add(rec.query_id)
            chain.append(rec)

            # Downstream: records that derive from this one
            for other in all_records:
                if other.query_id not in visited_query_ids and rec.query_id in other.derived_from_query_ids:
                    queue.append(other)

            # Upstream: records this one derives from
            for upstream_qid in rec.derived_from_query_ids:
                upstream = by_query_id.get(upstream_qid)
                if upstream is not None and upstream.query_id not in visited_query_ids:
                    queue.append(upstream)

        return chain

    @staticmethod
    def _row_to_record(row: tuple) -> ExecutionRecord:
        (
            execution_id,
            query_id,
            sql,
            stdout_truncated,
            stdout_path,
            started_at,
            finished_at,
            exit_code,
            derived_json,
        ) = row
        return ExecutionRecord(
            execution_id=execution_id,
            query_id=query_id,
            sql=sql,
            stdout_truncated=stdout_truncated,
            stdout_path=stdout_path,
            started_at=started_at,
            finished_at=finished_at,
            exit_code=exit_code,
            derived_from_query_ids=json.loads(derived_json or "[]"),
        )
