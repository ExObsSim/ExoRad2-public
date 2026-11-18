"""Server-level tests through the real stdio server (raw JSON-RPC).

The tool groups of other tasks are replaced by stubs raising the expected
exception types (see ``stdio_helper``), so these tests check the SERVER wiring:
error text reaches the client, stdout carries only JSON-RPC while stderr gets the
log lines, nested knowledge-base files are readable, and ``capabilities`` is
honest about tool modules it could not load.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from stdio_helper import (
    REPO_ROOT,
    result_text,
    run_stdio_requests,
    run_stdio_session,
)

from exorad.mcp import server, tools

if TYPE_CHECKING:
    from pathlib import Path

pytest.importorskip("mcp.server.mcpserver", reason="requires the 'mcp' extra")


def test_sandbox_violation_text_reaches_the_client(tmp_path: Path) -> None:
    outside = tmp_path / "outside" / "secret.h5"
    _, (response,), _ = run_stdio_session(
        [("inspect_output", {"path": str(outside)})], work_dir=tmp_path / "work"
    )
    assert response["result"]["isError"] is True
    text = result_text(response).lower()
    assert "outside the directories this mcp server may read" in text


def test_overwrite_refusal_text_reaches_the_client(tmp_path: Path) -> None:
    _, (response,), _ = run_stdio_session(
        [("run_pipeline", {"output": "out.h5"})], work_dir=tmp_path / "work"
    )
    assert response["result"]["isError"] is True
    assert "overwrite=True" in result_text(response)


def test_invalid_payload_text_reaches_the_client(tmp_path: Path) -> None:
    _, (response,), _ = run_stdio_session(
        [("validate_config", {"configuration": "p.xml"})], work_dir=tmp_path / "work"
    )
    assert response["result"]["isError"] is True
    assert "ForceChannelWlEdge" in result_text(response)


def test_keyerror_text_is_not_quoted_and_unknown_job_names_the_id(
    tmp_path: Path,
) -> None:
    _, (job, target), _ = run_stdio_session(
        [("get_job_status", {"job_id": "nope"}), ("explain_output", {"target": "T1"})],
        work_dir=tmp_path / "work",
    )
    assert (
        result_text(job) == "Error executing tool get_job_status: Unknown job id: nope"
    )
    assert result_text(target).endswith("unknown target T1")
    assert "'" not in result_text(target)


def test_a_bare_runtime_error_keeps_the_sdk_generic_error(tmp_path: Path) -> None:
    """A genuine bug must not be dressed up as an expected failure."""
    _, (response,), _ = run_stdio_session(
        [("plot_output", {})], work_dir=tmp_path / "work"
    )
    assert response["result"]["isError"] is True
    assert "kaboom" not in result_text(response)


def test_stdout_carries_only_json_rpc_and_stderr_gets_the_logs(tmp_path: Path) -> None:
    """Logs go to stderr, leaving stdout to the protocol.

    Mutation check (no red-first possible: the library handler already writes to
    stderr): pointing the handlers at ``sys.stdout`` in ``_route_logging_to_stderr``
    makes this test fail on the non-JSON lines.
    """
    lines, (response,), stderr = run_stdio_session(
        [("validate_config", {"configuration": "p.xml"})], work_dir=tmp_path / "work"
    )
    assert response["result"]["isError"] is True
    assert lines
    for line in lines:
        assert json.loads(line)["jsonrpc"] == "2.0", line
    assert "ExoRad MCP server" in stderr
    assert "stub-library-log-line" in stderr
    assert "stub-library-log-line" not in "\n".join(lines)


def test_mcp_log_level_debug_reaches_stderr(tmp_path: Path) -> None:
    """DEBUG needs the exorad.mcp logger's own handler (the shared one sits at INFO)."""
    lines, (_,), stderr = run_stdio_session(
        [("validate_config", {"configuration": "p.xml"})],
        work_dir=tmp_path / "work",
        env={"EXORAD_MCP_LOG_LEVEL": "DEBUG"},
    )
    assert "stub-mcp-debug-line" in stderr
    assert all("stub-mcp-debug-line" not in line for line in lines)
    _, (_,), quiet = run_stdio_session(
        [("validate_config", {"configuration": "p.xml"})], work_dir=tmp_path / "work"
    )
    assert "stub-mcp-debug-line" not in quiet


def test_nested_kb_file_is_readable_through_the_real_server(tmp_path: Path) -> None:
    """``exorad://kb/{path}`` matches one segment only; the template needs ``{+path}``."""
    uri = "exorad://kb/docs/source/user/inputs.rst"
    _, (index, nested, top), _ = run_stdio_requests(
        [
            ("resources/read", {"uri": "exorad://kb"}),
            ("resources/read", {"uri": uri}),
            ("resources/read", {"uri": "exorad://kb/AGENTS.md"}),
        ],
        work_dir=tmp_path / "work",
    )
    assert uri in index["result"]["contents"][0]["text"]
    assert "ConfigPath" in nested["result"]["contents"][0]["text"]
    assert top["result"]["contents"][0]["text"]


def test_tools_list_matches_the_registry(tmp_path: Path) -> None:
    _, (listed,), _ = run_stdio_requests(
        [("tools/list", {})], work_dir=tmp_path / "work"
    )
    names = {t["name"] for t in listed["result"]["tools"]}
    assert names == set(tools.TOOL_NAMES)
    assert len(names) == 21
    assert all(t["description"].strip() for t in listed["result"]["tools"])


def test_no_exec_leaves_out_the_execution_tools(tmp_path: Path) -> None:
    _, (listed,), _ = run_stdio_requests(
        [("tools/list", {})], work_dir=tmp_path / "work", extra_args=("--no-exec",)
    )
    names = {t["name"] for t in listed["result"]["tools"]}
    exec_only = {e.name for e in tools.REGISTRY if e.execution_only}
    assert exec_only == {
        "run_pipeline",
        "get_job_status",
        "cancel_job",
        "list_jobs",
        "plot_output",
    }
    assert names == set(tools.TOOL_NAMES) - exec_only


def test_capabilities_lists_a_missing_tool_module_honestly(tmp_path: Path) -> None:
    """Hiding a module makes the server skip its tools and say so, not crash."""
    _, (listed, caps), stderr = run_stdio_requests(
        [("tools/list", {}), ("tools/call", {"name": "capabilities", "arguments": {}})],
        work_dir=tmp_path / "work",
        stubs="hide:exorad.mcp.tools_run",
    )
    names = {t["name"] for t in listed["result"]["tools"]}
    assert {"run_pipeline", "get_job_status", "cancel_job", "list_jobs"}.isdisjoint(
        names
    )
    assert "capabilities" in names
    body = json.loads(result_text(caps))
    unavailable = {u["tool"]: u for u in body["tools"]["unavailable"]}
    assert set(unavailable) >= {"run_pipeline", "get_job_status", "cancel_job"}
    assert unavailable["run_pipeline"]["module"] == "exorad.mcp.tools_run"
    assert "not present" in unavailable["run_pipeline"]["reason"]
    assert "run_pipeline" not in body["tools"]["execution_only"]
    assert "run_pipeline (" in stderr  # the startup log says it too


def test_user_facing_runtime_errors_reach_the_client(tmp_path: Path) -> None:
    """ContentMissingError (a RuntimeError) is a clean message, not a crash."""
    _, (response,), _ = run_stdio_session(
        [("draft_config", {})], work_dir=tmp_path / "work"
    )
    assert response["result"]["isError"] is True
    text = result_text(response)
    assert text != "Error executing tool draft_config"
    assert "Reference configuration" in text


def test_expose_errors_converts_package_runtime_errors_only() -> None:
    from exorad.mcp.assets import ContentMissingError
    from exorad.mcp.embeddings import EmbeddingsUnavailableError
    from exorad.mcp.sandbox import PathNotAllowedError

    tool_error = server._tool_error_class()

    def raiser(exc: Exception):
        def tool() -> None:
            raise exc

        return server._expose_errors(tool)

    for exc in (
        ContentMissingError("no kb"),
        EmbeddingsUnavailableError("no extra"),
        PathNotAllowedError("outside"),
        FileNotFoundError("gone"),
        ImportError("no dep"),
        LookupError("missing"),
    ):
        with pytest.raises(tool_error, match=str(exc)):
            raiser(exc)()

    with pytest.raises(tool_error) as info:
        raiser(KeyError("Unknown job id: x"))()
    assert str(info.value) == "Unknown job id: x"

    # A bare RuntimeError is a likely bug: it must not be relabelled as expected.
    with pytest.raises(RuntimeError) as info:
        raiser(RuntimeError("boom"))()
    assert not isinstance(info.value, tool_error)


def test_repo_root_constant_is_the_worktree() -> None:
    assert (REPO_ROOT / "exorad" / "mcp" / "server.py").is_file()
