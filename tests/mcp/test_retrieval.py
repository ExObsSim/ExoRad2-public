"""Tests for the ExoRad MCP lexical retrieval."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from exorad.mcp import retrieval
from exorad.mcp.retrieval import (
    knowledge_base_manifest,
    search_knowledge_sources,
    tokenize,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_tokenize_splits_identifiers() -> None:
    tokens = tokenize("LoadOptions and wl_grid drive PSF sampling")
    assert {"loadoptions", "load", "options", "wl", "grid", "psf"} <= set(tokens)
    assert "and" not in tokens  # stopword


def test_tokenize_drops_single_characters_and_stopwords() -> None:
    assert tokenize("a of x the") == []


def test_tokenize_keeps_exorad_xml_tags_whole_and_split() -> None:
    tokens = set(tokenize("ConfigPath working_R NoiseX ForceChannelWlEdge"))
    assert {"configpath", "working", "noisex", "forcechannelwledge"} <= tokens
    assert {"config", "path", "force", "channel", "wl", "edge"} <= tokens


@pytest.fixture
def kb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tiny knowledge base with a single retrievable file."""
    root = tmp_path / "repo"
    (root / "docs" / "source").mkdir(parents=True)
    (root / "AGENTS.md").write_text("Grounding rules.\n", encoding="utf-8")
    (root / "docs" / "source" / "faqs.rst").write_text(
        "Quickstart\n==========\n\n"
        "Run the standard pipeline first.\n\n"
        "Radiometric model\n-----------------\n\n"
        "The radiometric model computes photon noise and the signal.\n",
        encoding="utf-8",
    )
    retrieval._CACHE.clear()
    monkeypatch.setenv("EXORAD_MCP_REPO_ROOT", str(root))
    return root


def test_ranks_the_relevant_section_first(kb: Path) -> None:
    sources = search_knowledge_sources("radiometric photon noise", max_results=3)

    assert sources
    assert sources[0].path == "docs/source/faqs.rst"
    assert "radiometric model computes photon noise" in sources[0].text.lower()
    assert sources[0].score == pytest.approx(1.0)


def test_rst_chunking_follows_sections(kb: Path) -> None:
    sources = search_knowledge_sources("radiometric model", max_results=5)
    hit = next(s for s in sources if "photon noise" in s.text.lower())
    # the chunk starts at the "Radiometric model" heading, not the top of file
    assert hit.text.lower().startswith("radiometric model")


def test_unmatched_query_returns_nothing(kb: Path) -> None:
    assert search_knowledge_sources("quxzzy frobnicated blorptastic") == []


def test_index_cache_invalidates_on_change(kb: Path) -> None:
    assert search_knowledge_sources("telescope aperture diameter") == []

    (kb / "docs" / "source" / "telescope.rst").write_text(
        "Telescope\n=========\n\nThe telescope aperture diameter sets the collecting area.\n",
        encoding="utf-8",
    )
    sources = search_knowledge_sources("telescope aperture diameter")

    assert sources
    assert sources[0].path == "docs/source/telescope.rst"


# --- the real knowledge base --------------------------------------------------
INTERNAL_NOTES = (
    "docs/ai-agents/mcp-plan.md",
    "docs/ai-agents/mcp-spec.md",
)


def test_internal_notes_are_never_indexed() -> None:
    """Audit #11: the planning notes must not reach the KB (red-first regression)."""
    matched = set(knowledge_base_manifest()["matched_files"])
    for note in INTERNAL_NOTES:
        assert note not in matched
    # the user-facing agent guides stay in
    assert "docs/ai-agents/parameter-setup-guide.md" in matched


def test_internal_notes_never_appear_in_search_hits() -> None:
    # words that only the internal spec uses heavily
    for query in (
        "audit lesson Opus review disposition",
        "normalised copy H17 netguard",
    ):
        paths = {s.path for s in search_knowledge_sources(query, max_results=20)}
        assert not paths & set(INTERNAL_NOTES)


def test_internal_notes_excluded_even_when_present_in_a_synthetic_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    (root / "docs" / "ai-agents").mkdir(parents=True)
    for note in INTERNAL_NOTES:
        (root / note).write_text("zorblax internal plan\n", encoding="utf-8")
    (root / "docs" / "ai-agents" / "guide.md").write_text("# Guide\n\nzorblax public\n")
    retrieval._CACHE.clear()
    monkeypatch.setenv("EXORAD_MCP_REPO_ROOT", str(root))
    paths = {s.path for s in search_knowledge_sources("zorblax")}
    assert paths == {"docs/ai-agents/guide.md"}


def test_network_sources_are_not_indexed() -> None:
    matched = set(knowledge_base_manifest()["matched_files"])
    assert "exorad/tasks/downloadSed.py" not in matched
    assert "exorad/utils/version_control.py" not in matched


def test_manifest_lists_the_exorad_patterns() -> None:
    manifest = knowledge_base_manifest()
    patterns = {p["pattern"] for p in manifest["source_patterns"]}
    assert {
        "AGENTS.md",
        "docs/source/user/**/*.rst",
        "examples/*.xml",
        "examples/test_target.csv",
        "exorad/exorad.py",
    } <= patterns
    assert manifest["matched_file_count"] > 40
    assert manifest["retrieval_backend"] == "bm25"
    # numeric data tables are shipped for runs but not indexed
    matched = set(manifest["matched_files"])
    assert "examples/QE.csv" not in matched
    assert "examples/test_target.csv" in matched
    assert "examples/payload_example.xml" in matched


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("ConfigPath", "docs/source/user/inputs.rst"),
        ("ForceChannelWlEdge", "examples/payload_example.xml"),
        ("working_R", "docs/source/user/troubleshooting.rst"),
    ],
)
def test_xml_tags_are_retrievable_by_their_exact_name(
    query: str, expected: str
) -> None:
    paths = [s.path for s in search_knowledge_sources(query, max_results=8)]
    assert expected in paths, paths
