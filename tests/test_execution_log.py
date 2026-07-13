"""Tests for execution_log (P1.1).

Covers: insertion, JSON roundtrip, query_by_query_id, find_derivation_chain
direct + transitive + no-match, ordering, concurrent writes no-collision
(P1.1 exit gate), schema persistence, parent dir creation, in-memory
isolation.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from panner.execution_log import ExecutionLog, ExecutionRecord


@pytest.fixture
def log():
    return ExecutionLog(db_path=":memory:")


def test_record_insert_and_query(log):
    log.record(
        execution_id="exec-001",
        query_id="q-001",
        sql="SELECT 1;",
        stdout_truncated="1",
        exit_code=0,
    )
    records = log.query_by_query_id("q-001")
    assert len(records) == 1
    assert records[0].execution_id == "exec-001"
    assert records[0].sql == "SELECT 1;"
    assert records[0].stdout_truncated == "1"
    assert records[0].exit_code == 0


def test_record_upsert_idempotent(log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT 1;", stdout_truncated="1")
    log.record(execution_id="e1", query_id="q1", sql="SELECT 2;", stdout_truncated="2")
    records = log.query_all()
    assert len(records) == 1
    assert records[0].sql == "SELECT 2;"
    assert records[0].stdout_truncated == "2"


def test_derived_from_query_ids_roundtrip(log):
    log.record(
        execution_id="e2",
        query_id="q2",
        sql="SELECT 2;",
        derived_from_query_ids=["q1", "q-prev"],
    )
    records = log.query_by_query_id("q2")
    assert records[0].derived_from_query_ids == ["q1", "q-prev"]


def test_stdout_path_field(log):
    log.record(
        execution_id="e3",
        query_id="q3",
        sql="SELECT big;",
        stdout_truncated="(truncated; see parquet)",
        stdout_path="/tmp/panner/results/e3_q3.parquet",
    )
    rec = log.query_by_query_id("q3")[0]
    assert rec.stdout_path == "/tmp/panner/results/e3_q3.parquet"


def test_find_derivation_chain_direct(log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT 100;", stdout_truncated="100")
    chain = log.find_derivation_chain("100")
    assert len(chain) == 1
    assert chain[0].query_id == "q1"


def test_find_derivation_chain_transitive(log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT 100;", stdout_truncated="100")
    log.record(
        execution_id="e2",
        query_id="q2",
        sql="SELECT 2.0;",
        stdout_truncated="115",
        derived_from_query_ids=["q1"],
    )
    log.record(
        execution_id="e3",
        query_id="q3",
        sql="SELECT 15;",
        stdout_truncated="15%",
        derived_from_query_ids=["q1", "q2"],
    )
    chain = log.find_derivation_chain("15%")
    chain_qids = {r.query_id for r in chain}
    assert chain_qids == {"q3", "q1", "q2"}


def test_find_derivation_chain_no_match(log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT 100;", stdout_truncated="100")
    chain = log.find_derivation_chain("999999")
    assert chain == []


def test_find_derivation_chain_empty_log(log):
    chain = log.find_derivation_chain("anything")
    assert chain == []


def test_query_by_query_id_returns_newest_first(log):
    log.record(
        execution_id="e1",
        query_id="q1",
        sql="SELECT 1;",
        stdout_truncated="1",
        started_at="2026-07-13T10:00:00+00:00",
    )
    log.record(
        execution_id="e2",
        query_id="q1",
        sql="SELECT 2;",
        stdout_truncated="2",
        started_at="2026-07-13T11:00:00+00:00",
    )
    records = log.query_by_query_id("q1")
    assert records[0].execution_id == "e2"
    assert records[1].execution_id == "e1"


@pytest.mark.timeout(30)
def test_concurrent_writes_no_collision(tmp_path):
    """P1.1 exit gate: 4 threads x 25 records = 100 records, all persisted."""
    db_path = str(tmp_path / "exec.db")
    n_threads = 4
    n_per_thread = 25
    barrier = threading.Barrier(n_threads)

    def writer(tid: int) -> None:
        log = ExecutionLog(db_path=db_path)
        barrier.wait()
        for i in range(n_per_thread):
            log.record(
                execution_id=f"exec-t{tid}-i{i:03d}",
                query_id=f"q-t{tid}",
                sql=f"SELECT {tid * 100 + i};",
                stdout_truncated=str(tid * 100 + i),
            )

    with ThreadPoolExecutor(max_workers=n_threads) as ex:
        list(ex.map(writer, range(n_threads)))

    log = ExecutionLog(db_path=db_path)
    records = log.query_all()
    assert len(records) == n_threads * n_per_thread
    unique_ids = {r.execution_id for r in records}
    assert len(unique_ids) == n_threads * n_per_thread


def test_schema_persistence_across_reopen(tmp_path):
    db_path = str(tmp_path / "exec.db")
    log1 = ExecutionLog(db_path=db_path)
    log1.record(execution_id="e1", query_id="q1", sql="SELECT 1;", stdout_truncated="1")

    log2 = ExecutionLog(db_path=db_path)
    records = log2.query_all()
    assert len(records) == 1
    assert records[0].execution_id == "e1"


def test_in_memory_db_creates_no_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    log = ExecutionLog(db_path=":memory:")
    log.record(execution_id="e1", query_id="q1", sql="SELECT 1;", stdout_truncated="1")
    assert list(tmp_path.iterdir()) == []


def test_explicit_path_creates_parent_dir(tmp_path):
    db_path = str(tmp_path / "subdir" / "exec.db")
    log = ExecutionLog(db_path=db_path)
    log.record(execution_id="e1", query_id="q1", sql="SELECT 1;", stdout_truncated="1")
    assert os.path.exists(db_path)


def test_execution_record_dataclass():
    rec = ExecutionRecord(
        execution_id="e1",
        query_id="q1",
        sql="SELECT 1;",
        started_at="2026-07-13T10:00:00+00:00",
    )
    assert rec.derived_from_query_ids == []
    assert rec.contains_value("1") is False
    assert rec.finished_at is None
