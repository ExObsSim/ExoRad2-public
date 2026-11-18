"""Tests for the information, grounding and help tools (``tools_info``)."""

from __future__ import annotations

import json

import pytest

from exorad.mcp import tools_info
from exorad.mcp.tools_info import (
    capabilities,
    customisation_guide,
    diagnose_error,
    exorad_project_context,
    knowledge_base_manifest,
    search_knowledge_base,
)


# --- search_knowledge_base ---------------------------------------------------
def test_search_returns_grounded_sources() -> None:
    result = search_knowledge_base(
        "how do I define a photometer channel", max_results=2
    )
    assert result["status"] == "ok"
    assert result["grounded"] is True
    assert 1 <= len(result["sources"]) <= 2
    assert {"path", "start_line", "end_line", "score", "text"} <= set(
        result["sources"][0]
    )
    assert result["minimum_retrieval_score"] > 0
    assert result["truncated"] is False


def test_search_reports_insufficient_evidence() -> None:
    result = search_knowledge_base("quxzzy frobnicated zputanium blorptastic")
    assert result["status"] == "insufficient_evidence"
    assert result["grounded"] is False
    assert result["sources"] == []
    assert "Do not answer from general knowledge" in result["message"]


@pytest.mark.parametrize("query", ["", "   ", "\n"])
def test_search_rejects_an_empty_query(query: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        search_knowledge_base(query)


@pytest.mark.parametrize(("asked", "cap"), [(0, 1), (-5, 1), (500, 20)])
def test_search_clamps_max_results(asked: int, cap: int) -> None:
    result = search_knowledge_base("noise", max_results=asked)
    assert 1 <= len(result["sources"]) <= cap


def test_search_respects_the_char_budget() -> None:
    """max_chars splits evenly across passages (at least 200 each) and flags cuts."""
    query = "radiometric model photon noise"
    full = search_knowledge_base(query, max_results=3)
    assert full["status"] == "ok"
    assert any(len(s["text"]) > 400 for s in full["sources"])

    budgeted = search_knowledge_base(query, max_results=3, max_chars=900)
    assert budgeted["truncated"] is True
    per_source = max(200, 900 // len(budgeted["sources"]))
    for source in budgeted["sources"]:
        assert len(source["text"]) <= per_source + 8  # + the " ..." marker
        if source.get("truncated"):
            assert source["full_text_chars"] > len(source["text"])
            assert source["path"]
            assert source["start_line"] <= source["end_line"]


def test_char_budget_has_a_floor_of_200_characters() -> None:
    result = search_knowledge_base("noise", max_results=5, max_chars=10)
    for source in result["sources"]:
        assert len(source["text"]) <= 208


def test_char_budget_leaves_short_passages_alone() -> None:
    result = search_knowledge_base("noise", max_results=3, max_chars=10_000_000)
    assert result["truncated"] is False
    assert not any("truncated" in s for s in result["sources"])


def test_search_result_is_json_serialisable() -> None:
    json.dumps(search_knowledge_base("target list columns"))


# --- manifest / customisation ------------------------------------------------
def test_manifest_tool_matches_retrieval() -> None:
    from exorad.mcp.retrieval import knowledge_base_manifest as raw

    assert knowledge_base_manifest() == raw()
    assert tools_info.knowledge_base_manifest_tool() == raw()


def test_customisation_guide_returns_grounded_sources() -> None:
    result = customisation_guide("add a custom noise source")
    assert result["status"] == "ok"
    paths = [s["path"] for s in result["sources"]]
    assert any("custom_noise" in p or "payload" in p for p in paths), paths


# --- exorad_project_context ----------------------------------------------------
def test_project_context_reads_the_curated_files() -> None:
    result = exorad_project_context()
    assert set(result["files"]) == set(tools_info.PROJECT_CONTEXT_FILES)
    assert result["missing"] == []
    assert "ExoRad" in result["files"]["AGENTS.md"]
    assert "capabilities" in result
    assert "exosim_project_context" not in json.dumps(result["capabilities"])


def test_project_context_reports_missing_files(tmp_path, monkeypatch) -> None:
    (tmp_path / "AGENTS.md").write_text("only this\n")
    monkeypatch.setenv("EXORAD_MCP_REPO_ROOT", str(tmp_path))
    result = exorad_project_context()
    assert list(result["files"]) == ["AGENTS.md"]
    assert "docs/ai-agents/codebase-map.md" in result["missing"]


# --- capabilities -----------------------------------------------------------------
def test_capabilities_reports_the_environment() -> None:
    result = capabilities()
    assert result["versions"]["exorad"]
    assert result["versions"]["python"]
    assert {"mcp_sdk", "sentence_transformers", "astropy", "h5py"} <= set(
        result["versions"]
    )
    assert result["pipelines"] == ["standard"]
    assert "search_knowledge_base" in result["tools"]["always_available"]
    assert result["execution_enabled"] is True
    assert "run_pipeline" in result["tools"]["execution_only"]
    assert result["retrieval"]["backend"] in {"bm25", "hybrid"}
    assert result["discovery_errors"] == []


def test_capabilities_network_policy() -> None:
    assert capabilities()["network"] == {
        "enabled": False,
        "sed_download": "blocked",
        "version_check": "off",
    }


def test_capabilities_states_that_there_is_no_authentication() -> None:
    assert "no authentication" in capabilities()["transport_authentication"]


def test_capabilities_has_a_content_report_and_limits() -> None:
    result = capabilities()
    content = result["content"]
    assert content["source"] == "override"
    assert content["knowledge_base_files"] > 40
    assert content["example_configs"] >= 1
    assert content["warnings"] == []
    assert content == result["sandbox"]["content"]
    assert set(result["limits"]) == {
        "max_threads",
        "max_runtime_seconds",
        "max_jobs",
        "max_targets",
        "max_output_mb",
        "max_bins",
        "max_data_mb",
    }


def test_capabilities_warns_when_the_content_is_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EXORAD_MCP_REPO_ROOT", str(tmp_path))
    warnings = capabilities()["content"]["warnings"]
    assert warnings
    assert any("Knowledge base is empty" in w for w in warnings)


def test_capabilities_lists_exactly_the_21_tools() -> None:
    tools = capabilities()["tools"]
    names = tools["always_available"] + tools["execution_only"]
    assert len(names) == 21
    assert len(set(names)) == 21
    assert "suggest_next_steps" not in names
    assert "exorad_project_context" in names
    assert "exosim_project_context" not in names


def test_capabilities_hides_execution_tools_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("EXORAD_MCP_NO_EXEC", "1")
    result = capabilities()
    assert result["execution_enabled"] is False
    assert result["tools"]["execution_only"] == []
    assert set(result["tools"]["disabled"]) == set(tools_info.EXECUTION_ONLY)


def test_capabilities_never_raises(monkeypatch) -> None:
    from exorad.mcp import sandbox

    def boom(*_a, **_k):
        raise RuntimeError("no sandbox")

    monkeypatch.setattr(sandbox.Sandbox, "from_env", classmethod(boom))
    result = capabilities()
    assert "error" in result["sandbox"]
    assert result["execution_enabled"] is False
    json.dumps(result)


def test_capabilities_is_json_serialisable() -> None:
    json.dumps(capabilities())


# --- diagnose_error: one test per category ----------------------------------------
CASES = [
    (
        "network_blocked",
        "OSError: network access is disabled in the ExoRad MCP",
        "",
    ),
    (
        "network_blocked",
        "sourceSpectrum 'sed' downloads from the network and is disabled",
        "",
    ),
    ("pickle_refused", "PICKLE_REFUSED: datadict points at a .pickle file", ""),
    ("skipped_target", "AttributeError: target information incomplete", ""),
    (
        "skipped_target",
        "target myStar skipped",
        "AttributeError: 'NoneType' object has no attribute 'write'",
    ),
    (
        "configpath",
        "TypeError: replace() argument 2 must be str, not None",
        "",
    ),
    ("configpath", "OSError: Cannot read input file", ""),
    (
        "missing_file",
        "FileNotFoundError: [Errno 2] No such file or directory: 'QE.csv'",
        "",
    ),
    ("missing_element", "KeyError: 'ForceChannelWlEdge'", ""),
    ("missing_element", "UnboundLocalError: window_size_px", ""),
    ("unit", "ValueError: 'micrn' is not a valid unit", ""),
    (
        "unit",
        "astropy.units.core.UnitConversionError: 'um2' and 'um' are not convertible",
        "",
    ),
    ("phoenix_path", "OSError: No phoenix path specified", ""),
    ("memory", "MemoryError", ""),
    ("memory", "output exceeded the size limit", ""),
    (
        "output_exists",
        "ValueError: Unable to synchronously create dataset (name already exists)",
        "",
    ),
    ("output_exists", "OSError: Unable to open file (file signature not found)", ""),
    ("dependency", "ModuleNotFoundError: No module named 'h5py'", ""),
    ("general", "something odd happened", ""),
]


@pytest.mark.parametrize(("category", "message", "trace"), CASES)
def test_diagnose_error_categories(category: str, message: str, trace: str) -> None:
    result = diagnose_error(message, traceback_text=trace)
    assert result["category"] == category
    assert result["suggestions"]
    assert all(isinstance(s, str) and s for s in result["suggestions"])
    assert isinstance(result["related_docs"], list)


def test_every_category_has_a_test_case() -> None:
    declared = {c[0] for c in tools_info._CATEGORIES} | {"general"}
    assert declared == {c[0] for c in CASES}


def test_diagnose_error_order_prefers_the_network_over_missing_file() -> None:
    result = diagnose_error("network access is disabled; file not found")
    assert result["category"] == "network_blocked"


def test_diagnose_error_attaches_related_docs() -> None:
    result = diagnose_error(
        "OSError: No phoenix path specified", context="phoenix source"
    )
    assert result["related_docs"]
    assert {"path", "score"} == set(result["related_docs"][0])
    assert any(
        "troubleshooting" in d["path"] or "prepare_target" in d["path"]
        for d in result["related_docs"]
    )


def test_diagnose_error_parses_a_traceback() -> None:
    trace = (
        "Traceback (most recent call last):\n"
        '  File "/x/exorad/tasks/loadSource.py", line 80, in __call__\n'
        "    raise AttributeError('target information incomplete')\n"
        "AttributeError: target information incomplete\n"
    )
    result = diagnose_error("run failed", traceback_text=trace)
    assert result["error_type"] == "AttributeError"
    assert result["exception_message"] == "target information incomplete"
    assert result["last_frame"].endswith("in __call__")
    assert result["category"] == "skipped_target"


def test_diagnose_error_without_a_traceback_has_no_error_type() -> None:
    assert diagnose_error("plain text")["error_type"] is None


def test_diagnose_error_mentions_no_exosim_advice() -> None:
    for _, message, trace in CASES:
        text = json.dumps(diagnose_error(message, traceback_text=trace))
        assert "exosim" not in text.lower()
        assert "ExoSim" not in text
