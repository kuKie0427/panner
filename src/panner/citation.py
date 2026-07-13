"""Citation grounding checker — Phase 1 main battlefield.

CitationChecker verifies every numeric / date / string claim in CodeAgent's
final_answer against ExecutionLog SQL executions. Per DIRECTIONS.md §Phase 1:

    "framework post-processor 强制检查; 无 grounding 的答案一律拒绝
    (不是 LLM 自我审查, 是 framework 拦截)"

Public API:
    CitationChecker().check(answer, log) -> CheckResult

Supporting types:
    Token            — a single claim extracted from answer
    CheckResult      — passed flag + missing tokens + refusal reason + grounded chains
    RefusalAnswer    — dataclass for framework to substitute rejected final_answer
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional

from panner.execution_log import ExecutionLog, ExecutionRecord


NumericTol = 0.01


@dataclass(frozen=True)
class Token:
    """A single claim token extracted from final_answer.

    type='numeric' carries .value as float (with % normalized to fraction).
    type='date' / 'string' carry .literal as the verbatim substring.
    """

    type: Literal["numeric", "date", "string"]
    literal: str
    value: Optional[float] = None


@dataclass
class CheckResult:
    """Result of CitationChecker.check()."""

    passed: bool
    missing_sources: list[Token] = field(default_factory=list)
    refusal_reason: Optional[str] = None
    grounded_chains: dict[Token, list[ExecutionRecord]] = field(default_factory=dict)


@dataclass
class RefusalAnswer:
    """Framework-side replacement for final_answer when citation fails.

    Per DIRECTIONS.md §Phase 1 L72: answer is replaced with a deterministic
    refusal string, never a paraphrase. The (1-retry) rule from open issue
    #2 (framework offers LLM one chance to regenerate with full execution_log
    SQL summaries) is enforced by P1.3 (CodeAgent integration), not here.
    """

    reason: str
    missing_claims: list[str] = field(default_factory=list)

    DEFAULT_REASON = "I don't have data to support this answer."

    def render(self) -> str:
        if not self.missing_claims:
            return self.DEFAULT_REASON
        sample = self.missing_claims[:5]
        suffix = f" and {len(self.missing_claims) - 5} more" if len(self.missing_claims) > 5 else ""
        joined = ", ".join(sample)
        return f"{self.DEFAULT_REASON} Missing source for: {joined}{suffix}."


# Numeric tokens: integers (any digit count) / decimals / percentages /
# thousands-separated / signed. Two alternatives: thousands (comma-required)
# vs plain integer run. Year-in-date contexts are filtered at the call site
# (extract_claim_tokens) so a "2026-07-13" date doesn't emit "2026" as a
# numeric claim.
_NUMERIC_PATTERN = re.compile(r"(?<!\d)-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?(?!\d)")

_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


class CitationChecker:
    """Verifies every claim in an LLM answer against ExecutionLog.

    Construction modes: regex-only by default (covers ~80% simple cases per
    DIRECTIONS.md open issue #1). spaCy fallback is intentionally NOT
    included in P1.2 — it's a future extension if regex recall plateaus.
    """

    NUMERIC_TOLERANCE: float = NumericTol

    def extract_claim_tokens(self, answer: str) -> list[Token]:
        """Extract numeric + ISO 8601 date tokens from answer."""
        tokens: list[Token] = []
        date_spans = [(m.start(), m.end()) for m in _DATE_PATTERN.finditer(answer)]
        for m in _DATE_PATTERN.finditer(answer):
            tokens.append(Token(type="date", literal=m.group()))
        for m in _NUMERIC_PATTERN.finditer(answer):
            if any(start <= m.start() < end for start, end in date_spans):
                continue
            literal = m.group()
            value = self._parse_numeric(literal)
            if value is not None:
                tokens.append(Token(type="numeric", literal=literal, value=value))
        return tokens

    def check(self, answer: str, log: ExecutionLog) -> CheckResult:
        tokens = self.extract_claim_tokens(answer)
        if not tokens:
            return CheckResult(passed=True)

        missing: list[Token] = []
        chains: dict[Token, list[ExecutionRecord]] = {}
        for token in tokens:
            chain = self._find_grounding(token, log)
            if chain:
                chains[token] = chain
            else:
                missing.append(token)

        passed = not missing
        refusal_reason: Optional[str] = None
        if not passed:
            refusal_reason = RefusalAnswer(
                reason=RefusalAnswer.DEFAULT_REASON,
                missing_claims=[t.literal for t in missing],
            ).render()

        return CheckResult(
            passed=passed,
            missing_sources=missing,
            refusal_reason=refusal_reason,
            grounded_chains=chains,
        )

    def _find_grounding(self, token: Token, log: ExecutionLog) -> list[ExecutionRecord]:
        """Returns grounding chain. Empty list = no source for this token."""
        if token.type == "numeric":
            return self._find_numeric_chain(token.value, log)
        return log.find_derivation_chain(token.literal)

    def _find_numeric_chain(self, target: float, log: ExecutionLog) -> list[ExecutionRecord]:
        """Find stdout-containing ±tolerance records then BFS DAG (D2)."""
        all_records = log.query_all()
        candidates = [
            r
            for r in all_records
            if r.stdout_truncated is not None
            and _stdout_contains_numeric_near(r.stdout_truncated, target, self.NUMERIC_TOLERANCE)
        ]
        if not candidates:
            return []

        by_query_id: dict[str, ExecutionRecord] = {r.query_id: r for r in all_records}
        visited: set[str] = set()
        chain: list[ExecutionRecord] = []
        queue: list[ExecutionRecord] = list(candidates)

        while queue:
            rec = queue.pop(0)
            if rec.query_id in visited:
                continue
            visited.add(rec.query_id)
            chain.append(rec)

            for other in all_records:
                if other.query_id not in visited and rec.query_id in other.derived_from_query_ids:
                    queue.append(other)

            for upstream_qid in rec.derived_from_query_ids:
                upstream = by_query_id.get(upstream_qid)
                if upstream is not None and upstream.query_id not in visited:
                    queue.append(upstream)

        return chain

    @staticmethod
    def _parse_numeric(literal: str) -> Optional[float]:
        """Parse numeric literal. Percentages normalized to fraction (0.50, not 50.0)."""
        s = literal.replace(",", "")
        if s.endswith("%"):
            try:
                return float(s[:-1]) / 100
            except ValueError:
                return None
        try:
            return float(s)
        except ValueError:
            return None


def _stdout_contains_numeric_near(stdout: str, target: float, tolerance: float) -> bool:
    """Return True if stdout contains any number within ±tolerance of target."""
    for v in _extract_numbers(stdout):
        if abs(v - target) <= tolerance:
            return True
    return False


def _extract_numbers(stdout: str) -> list[float]:
    """Pull all numeric values (including percentages normalized to fraction)
    from a stdout string. Used by numeric chain walker."""
    out: list[float] = []
    for m in _NUMERIC_PATTERN.finditer(stdout):
        literal = m.group()
        s = literal.replace(",", "")
        if s.endswith("%"):
            try:
                out.append(float(s[:-1]) / 100)
            except ValueError:
                pass
            continue
        try:
            out.append(float(s))
        except ValueError:
            pass
    return out
