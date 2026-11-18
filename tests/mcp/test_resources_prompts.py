"""Tests for MCP resources and prompts."""

from __future__ import annotations

import asyncio

import pytest

from exorad.mcp import prompts, resources

TOOL_NAMES = {
    "capabilities",
    "exorad_project_context",
    "knowledge_base_manifest",
    "search_knowledge_base",
    "customisation_guide",
    "list_pipelines",
    "describe_pipeline",
    "list_examples",
    "config_requirements",
    "draft_config",
    "draft_target_list",
    "validate_config",
    "compare_configs",
    "run_pipeline",
    "get_job_status",
    "cancel_job",
    "list_jobs",
    "inspect_output",
    "explain_output",
    "plot_output",
    "diagnose_error",
}


def test_knowledge_base_index_lists_uris() -> None:
    index = resources.knowledge_base_index()
    assert index["count"] > 0
    uris = {entry["uri"] for entry in index["resources"]}
    assert "exorad://kb/AGENTS.md" in uris
    assert "exorad://kb/docs/source/user/inputs.rst" in uris


def test_internal_notes_are_not_resources() -> None:
    uris = {entry["uri"] for entry in resources.knowledge_base_index()["resources"]}
    assert "exorad://kb/docs/ai-agents/mcp-plan.md" not in uris
    assert "exorad://kb/docs/ai-agents/mcp-spec.md" not in uris


def test_read_knowledge_file_returns_text() -> None:
    text = resources.read_knowledge_file("AGENTS.md")
    assert isinstance(text, str)
    assert "ExoRad" in text


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "../../../etc/passwd",
        "../pyproject.toml",
        "docs/../pyproject.toml",
        "/etc/passwd",
        "docs/ai-agents/mcp-plan.md",
        "docs/ai-agents/mcp-spec.md",
        "examples/customsed.csv",
        "",
    ],
)
def test_read_knowledge_file_rejects_paths_outside_the_manifest(path: str) -> None:
    with pytest.raises(FileNotFoundError):
        resources.read_knowledge_file(path)


def test_read_knowledge_file_truncates_large_files(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from exorad.mcp import retrieval

    root = tmp_path / "repo"
    root.mkdir()
    (root / "AGENTS.md").write_text("x" * (resources._MAX_RESOURCE_BYTES + 500))
    retrieval._CACHE.clear()
    monkeypatch.setenv("EXORAD_MCP_REPO_ROOT", str(root))
    text = resources.read_knowledge_file("AGENTS.md")
    assert text.endswith("... [truncated]\n")
    assert len(text.encode()) < resources._MAX_RESOURCE_BYTES + 100


@pytest.mark.parametrize("prompt", prompts.ALL_PROMPTS, ids=lambda p: p.__name__)
def test_prompts_mention_the_tools_and_grounding(prompt) -> None:
    text = prompt()
    assert "search_knowledge_base" in text
    assert "insufficient_evidence" in text
    assert "ExoRad" in text
    assert "ExoSim" not in text


def test_prompt_set_matches_the_spec() -> None:
    assert {p.__name__ for p in prompts.ALL_PROMPTS} == {
        "new_simulation",
        "set_up_channel",
        "diagnose_failed_run",
        "explain_output",
    }


def test_new_simulation_names_the_tools_in_order() -> None:
    text = prompts.new_simulation()
    order = [
        "config_requirements",
        "list_examples",
        "draft_config",
        "draft_target_list",
        "validate_config",
        "run_pipeline",
        "get_job_status",
        "explain_output",
        "plot_output",
    ]
    positions = [text.index(name) for name in order]
    assert positions == sorted(positions)


def test_diagnose_failed_run_names_the_tools_in_order() -> None:
    text = prompts.diagnose_failed_run()
    positions = [
        text.index(n) for n in ("get_job_status", "diagnose_error", "validate_config")
    ]
    assert positions == sorted(positions)


def test_every_tool_named_in_a_prompt_exists() -> None:
    import re

    for prompt in prompts.ALL_PROMPTS:
        for word in re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", prompt()):
            if word in {"insufficient_evidence", "applied", "not_applied"}:
                continue
            assert word in TOOL_NAMES, f"{prompt.__name__} mentions unknown tool {word}"


# --- through the real SDK (mcp 2.x API only) ---------------------------------
def _server():
    pytest.importorskip("mcp.server.mcpserver", reason="requires the 'mcp' extra")
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("exorad")
    server.resource(resources.KB_INDEX_URI)(resources.knowledge_base_index)
    server.resource(resources.KB_URI_TEMPLATE)(resources.read_knowledge_file)
    for prompt in prompts.ALL_PROMPTS:
        server.prompt()(prompt)
    return server


def _text(item) -> str:
    return str(getattr(item, "content", item))


def test_sdk_lists_the_resource_template_and_prompts() -> None:
    server = _server()
    templates = asyncio.run(server.list_resource_templates())
    names = {p.name for p in asyncio.run(server.list_prompts())}
    assert any(t.uri_template == "exorad://kb/{+path}" for t in templates)
    assert names == {p.__name__ for p in prompts.ALL_PROMPTS}


def test_sdk_reads_the_index_and_agents_md() -> None:
    server = _server()
    uris = {str(r.uri) for r in asyncio.run(server.list_resources())}
    assert "exorad://kb" in uris
    index = list(asyncio.run(server.read_resource("exorad://kb")))
    assert "exorad://kb/AGENTS.md" in _text(index[0])
    contents = list(asyncio.run(server.read_resource("exorad://kb/AGENTS.md")))
    assert contents
    assert "ExoRad" in _text(contents[0])


def test_sdk_reads_a_nested_knowledge_file() -> None:
    """A plain ``{path}`` template cannot reach ``docs/source/user/inputs.rst``."""
    server = _server()
    contents = list(
        asyncio.run(server.read_resource("exorad://kb/docs/source/user/inputs.rst"))
    )
    assert contents
    assert "ConfigPath" in _text(contents[0])


@pytest.mark.parametrize(
    "uri",
    [
        "exorad://kb/../pyproject.toml",
        "exorad://kb/..%2Fpyproject.toml",
        "exorad://kb/docs/../../pyproject.toml",
        "exorad://kb//etc/passwd",
        "exorad://kb/pyproject.toml",
        "exorad://kb/docs/ai-agents/mcp-spec.md",
        "exorad://kb/docs/ai-agents/mcp-plan.md",
    ],
)
def test_sdk_refuses_traversal_and_unlisted_files(uri: str) -> None:
    server = _server()
    with pytest.raises(Exception) as excinfo:
        list(asyncio.run(server.read_resource(uri)))
    assert "[extension]" not in str(excinfo.value)
    assert "root:" not in str(excinfo.value)


@pytest.mark.parametrize("prompt", prompts.ALL_PROMPTS, ids=lambda p: p.__name__)
def test_sdk_prompts_render_through_get_prompt(prompt) -> None:
    server = _server()
    result = asyncio.run(server.get_prompt(prompt.__name__, {}))
    text = "".join(m.content.text for m in result.messages)
    assert "insufficient_evidence" in text


def test_sdk_prompt_arguments_are_passed() -> None:
    server = _server()
    result = asyncio.run(
        server.get_prompt("set_up_channel", {"instrument": "photometer"})
    )
    assert "photometer" in "".join(m.content.text for m in result.messages)
    result = asyncio.run(server.get_prompt("explain_output", {"path": "run/out.h5"}))
    assert "run/out.h5" in "".join(m.content.text for m in result.messages)


# --- through the real server (task B); skipped until exorad.mcp.server exists ---
def test_real_server_registers_resources_and_prompts() -> None:
    server_module = pytest.importorskip("exorad.mcp.server")
    server = server_module.build_server()
    templates = asyncio.run(server.list_resource_templates())
    prompt_names = {p.name for p in asyncio.run(server.list_prompts())}
    assert any(t.uri_template == resources.KB_URI_TEMPLATE for t in templates)
    assert prompt_names == {p.__name__ for p in prompts.ALL_PROMPTS}
    contents = list(
        asyncio.run(server.read_resource("exorad://kb/docs/source/user/inputs.rst"))
    )
    assert "ConfigPath" in _text(contents[0])
