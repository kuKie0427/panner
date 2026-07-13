"""Tests for CitationChecker (P1.2).

30 cases: token extraction / numeric grounding / date grounding / D2 derived
chain / mixed answers / RefusalAnswer / hallucination refusal / edge cases.
Per feature_list.json P1.2 exit gate.
"""

from __future__ import annotations

import pytest

from panner.citation import CitationChecker, RefusalAnswer
from panner.execution_log import ExecutionLog


@pytest.fixture
def checker() -> CitationChecker:
    return CitationChecker()


@pytest.fixture
def log() -> ExecutionLog:
    return ExecutionLog(db_path=":memory:")


def test_extract_numeric_integer(checker):
    tokens = checker.extract_claim_tokens("Top store did 1234 in revenue")
    assert any(t.type == "numeric" and t.value == 1234.0 for t in tokens)


def test_extract_numeric_decimal(checker):
    tokens = checker.extract_claim_tokens("Total is 1234.56")
    assert any(t.type == "numeric" and abs(t.value - 1234.56) < 1e-9 for t in tokens)


def test_extract_numeric_percentage(checker):
    tokens = checker.extract_claim_tokens("Growth is 15%")
    assert any(t.type == "numeric" and abs(t.value - 0.15) < 1e-9 for t in tokens)


def test_extract_numeric_decimal_percentage(checker):
    tokens = checker.extract_claim_tokens("Growth is 15.5%")
    assert any(t.type == "numeric" and abs(t.value - 0.155) < 1e-9 for t in tokens)


def test_extract_numeric_thousands(checker):
    tokens = checker.extract_claim_tokens("Population is 1,234,567")
    assert any(t.type == "numeric" and t.value == 1234567 for t in tokens)


def test_extract_numeric_negative(checker):
    tokens = checker.extract_claim_tokens("Loss of -0.001")
    assert any(t.type == "numeric" and abs(t.value - (-0.001)) < 1e-9 for t in tokens)


def test_extract_date_iso(checker):
    tokens = checker.extract_claim_tokens("Date: 2026-07-13")
    assert any(t.type == "date" and t.literal == "2026-07-13" for t in tokens)


def test_extract_no_claims(checker):
    assert checker.extract_claim_tokens("Sales increased last quarter") == []


def test_grounding_direct_match(checker, log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT 1234.56;", stdout_truncated="1234.56")
    assert checker.check("Revenue is 1234.56", log).passed


def test_grounding_precision_tolerance(checker, log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT 1234.560001;", stdout_truncated="1234.560001")
    assert checker.check("Revenue is 1234.56", log).passed


def test_grounding_fails_when_outside_tolerance(checker, log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT 1234.58;", stdout_truncated="1234.58")
    result = checker.check("Revenue is 1234.56", log)
    assert not result.passed
    assert any(t.value == 1234.56 for t in result.missing_sources)


def test_grounding_percentage_matches_fraction(checker, log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT 0.15;", stdout_truncated="0.15")
    assert checker.check("Growth is 15%", log).passed


def test_grounding_thousands_separator(checker, log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT 1234567;", stdout_truncated="1234567")
    assert checker.check("Total: 1,234,567", log).passed


def test_grounding_negative_within_tolerance(checker, log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT -0.005;", stdout_truncated="-0.005")
    assert checker.check("Value: -0.001", log).passed


def test_grounding_no_source_hallucination(checker, log):
    result = checker.check("Revenue is 99999.99", log)
    assert not result.passed
    assert result.refusal_reason is not None


def test_grounding_partial_match_fails(checker, log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT 100.0;", stdout_truncated="100.0")
    result = checker.check("100.01 and 200", log)
    assert not result.passed


def test_derived_chain_grounding(checker, log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT 100;", stdout_truncated="100")
    log.record(execution_id="e2", query_id="q2", sql="SELECT 115;", stdout_truncated="115")
    log.record(
        execution_id="e3",
        query_id="q3",
        sql="SELECT q2/q1;",
        stdout_truncated="0.15",
        derived_from_query_ids=["q1", "q2"],
    )
    assert checker.check("YoY growth is 15%", log).passed


def test_derived_chain_walked_includes_upstream(checker, log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT 100;", stdout_truncated="100")
    log.record(
        execution_id="e2", query_id="q2", sql="SELECT 0.15;", stdout_truncated="0.15", derived_from_query_ids=["q1"]
    )
    chain = checker._find_numeric_chain(0.15, log)
    assert {r.query_id for r in chain} == {"q1", "q2"}


def test_hallucinated_no_chain(checker, log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT 0.15;", stdout_truncated="0.15")
    result = checker.check("Growth is 0.30", log)
    assert not result.passed


def test_grounding_date_match(checker, log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT MAX(date) FROM sales;", stdout_truncated="2026-07-13")
    assert checker.check("Last sale: 2026-07-13", log).passed


def test_grounding_date_no_match(checker, log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT MAX(date) FROM sales;", stdout_truncated="2026-07-13")
    assert not checker.check("Last sale: 2025-01-01", log).passed


def test_grounding_date_with_numeric(checker, log):
    log.record(
        execution_id="e1",
        query_id="q1",
        sql="SELECT date, revenue FROM sales LIMIT 1;",
        stdout_truncated="2026-07-13, 1234.56",
    )
    assert checker.check("Sale on 2026-07-13 was 1234.56", log).passed


def test_mixed_grounded_and_missing(checker, log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT 100.0;", stdout_truncated="100.0")
    result = checker.check("Value is 100.0, but growth is 0.5", log)
    assert not result.passed
    assert len(result.missing_sources) >= 1
    assert len(result.grounded_chains) >= 1


def test_all_numeric_in_one_sql(checker, log):
    log.record(
        execution_id="e1", query_id="q1", sql="SELECT SUM(rev), SUM(cost) FROM t;", stdout_truncated="1234.56, 789.10"
    )
    assert checker.check("Revenue 1234.56, cost 789.10", log).passed


def test_multi_line_sql_output(checker, log):
    log.record(
        execution_id="e1", query_id="q1", sql="SELECT * FROM t;", stdout_truncated="---\n1 | 1234.56\n2 | 99.5\n---"
    )
    assert checker.check("Revenue is 1234.56 and 99.5", log).passed


def test_refusal_render_simple():
    r = RefusalAnswer(reason="x", missing_claims=["1234.56"])
    rendered = r.render()
    assert "1234.56" in rendered


def test_refusal_render_truncates_long_list():
    claims = [f"claim_{i}" for i in range(10)]
    r = RefusalAnswer(reason="x", missing_claims=claims)
    assert "5 more" in r.render()


def test_refusal_render_default_reason_when_empty():
    r = RefusalAnswer(reason="ignored", missing_claims=[])
    assert r.render() == RefusalAnswer.DEFAULT_REASON


def test_check_empty_answer(checker, log):
    assert checker.check("", log).passed


def test_check_empty_log(checker, log):
    assert not checker.check("Revenue 100", log).passed


def test_check_chain_dict_present_in_pass(checker, log):
    log.record(execution_id="e1", query_id="q1", sql="SELECT 100.0;", stdout_truncated="100.0")
    result = checker.check("Value is 100.0", log)
    assert result.passed
    assert len(result.grounded_chains) == 1
