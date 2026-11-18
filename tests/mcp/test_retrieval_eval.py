"""Retrieval eval suite: guardrail against ranking regressions.

Runs the tuned set (``retrieval_cases``) and the blind set
(``retrieval_cases_blind``) through the real retrieval stack against the
repository knowledge base and checks recall@5. The gate (>= 0.80) applies to the
union of both sets; each score is also asserted and printed separately, because
the tuned set is optimistic (spec 5.2) and the blind set is the honest figure.

It is deliberately an aggregate check so that a single reworded doc page does not
break CI, while a real regression in the ranker or a lost doc page does.
"""

from __future__ import annotations

import pytest

# tests/mcp has no __init__.py on purpose: a package named ``tests/mcp`` would
# shadow the ``mcp`` SDK (pytest puts ``tests/`` on sys.path for package tests).
from retrieval_cases import CASES
from retrieval_cases_blind import BLIND_CASES

from exorad.mcp.retrieval import knowledge_base_manifest, search_knowledge_sources

TOP_K = 5
MIN_RECALL = 0.80

TUNED = [(case.question, case.expected) for case in CASES]


def _hits_for(question: str) -> list[str]:
    return [hit.path for hit in search_knowledge_sources(question, max_results=TOP_K)]


def _misses(cases: list[tuple[str, str]]) -> list[tuple[str, str, list[str]]]:
    out = []
    for question, expected in cases:
        paths = _hits_for(question)
        if not any(expected in path for path in paths):
            out.append((question, expected, paths))
    return out


def _report(misses: list[tuple[str, str, list[str]]]) -> str:
    return "\n".join(
        f"  - {q!r}\n    want *{exp}*, got:\n" + "\n".join(f"      {p}" for p in got)
        for q, exp, got in misses
    )


def test_case_counts_follow_the_spec() -> None:
    assert len(TUNED) == 24
    assert len(BLIND_CASES) >= 8


@pytest.mark.slow
def test_retrieval_recall_at_k_on_the_union() -> None:
    cases = TUNED + list(BLIND_CASES)
    misses = _misses(cases)
    recall = 1 - len(misses) / len(cases)
    assert recall >= MIN_RECALL, (
        f"retrieval recall@{TOP_K} = {recall:.0%} (< {MIN_RECALL:.0%}) on the union; "
        f"{len(misses)} misses:\n{_report(misses)}"
    )


@pytest.mark.slow
def test_retrieval_recall_on_each_set_is_reported(
    capsys: pytest.CaptureFixture,
) -> None:
    tuned_misses = _misses(TUNED)
    blind_misses = _misses(list(BLIND_CASES))
    tuned = 1 - len(tuned_misses) / len(TUNED)
    blind = 1 - len(blind_misses) / len(BLIND_CASES)
    with capsys.disabled():
        print(
            f"\nretrieval recall@{TOP_K}: tuned {tuned:.2f} "
            f"({len(TUNED) - len(tuned_misses)}/{len(TUNED)}), "
            f"blind {blind:.2f} "
            f"({len(BLIND_CASES) - len(blind_misses)}/{len(BLIND_CASES)})"
        )
        if blind_misses:
            print("blind misses:\n" + _report(blind_misses))
    # The tuned set must stay healthy on its own; the blind figure is reported
    # and gated only through the union (spec 5.2: never reword after a miss).
    assert tuned >= MIN_RECALL, _report(tuned_misses)


@pytest.mark.slow
def test_every_case_expected_path_exists() -> None:
    """A typo in an expected fragment would make a case unfalsifiable."""
    known = set(knowledge_base_manifest()["matched_files"])
    for question, expected in TUNED + list(BLIND_CASES):
        assert any(expected in path for path in known), (
            f"no knowledge-base file matches expected fragment {expected!r} "
            f"for question {question!r}"
        )
