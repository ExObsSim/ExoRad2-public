"""Tests for the ExoRad MCP server entry point and the tool registry."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

from exorad.mcp import jobs, netguard, server, tools, tools_info

if TYPE_CHECKING:
    from pathlib import Path

try:
    server._load_server_class()
    _HAS_MCP = True
except ImportError:
    _HAS_MCP = False

requires_mcp = pytest.mark.skipif(
    not _HAS_MCP, reason="requires the 'mcp' optional dependency"
)

_CHILD_ENV = (
    "EXORAD_NO_VERSION_CHECK",
    "MPLBACKEND",
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


@pytest.fixture(autouse=True)
def _restore_logging_and_env(monkeypatch: pytest.MonkeyPatch):
    """``main`` rebinds log handlers and edits ``os.environ``: undo it per test."""
    from exorad.log import logger as exorad_logger

    for name in (*_CHILD_ENV, "EXORAD_MCP_LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)  # recorded, restored on teardown
    stream = exorad_logger.ch.stream
    level = server._LOGGER.level
    yield
    exorad_logger.ch.stream = stream
    for handler in list(server._LOGGER.handlers):
        if getattr(handler, server._HANDLER_TAG, False):
            server._LOGGER.removeHandler(handler)
    server._LOGGER.setLevel(level)
    server._LOGGER.propagate = True


def _tool_names(srv: object) -> set[str]:
    return {tool.name for tool in asyncio.run(srv.list_tools())}


class _FakeServer:
    def __init__(self, calls: list[str] | None = None) -> None:
        self.calls = calls if calls is not None else []
        self.transport = None
        self.kwargs: dict[str, object] = {}

    def run(self, transport: str = "stdio", **kwargs: object) -> None:
        self.calls.append("run")
        self.transport = transport
        self.kwargs = kwargs


@pytest.fixture
def fake_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Run ``server.main`` against a fake server, with the process-wide hooks stubbed."""
    fake = _FakeServer()
    blocked: list[bool] = []
    monkeypatch.setattr(server, "build_server", lambda **_: fake)
    monkeypatch.setattr(netguard, "block_network", lambda: blocked.append(True))
    monkeypatch.setattr(jobs.JOBS, "install_hooks", lambda: fake.calls.append("hooks"))
    monkeypatch.setenv("EXORAD_MCP_WORK_DIR", str(tmp_path / "w"))
    fake.blocked = blocked  # type: ignore[attr-defined]
    return fake


# --- CLI ----------------------------------------------------------------------
def test_parse_args_defaults() -> None:
    args = server._parse_args([])
    assert args.transport == "stdio"
    assert args.host == "127.0.0.1"
    assert args.port == 8000
    assert args.no_exec is False
    assert args.allow_dir == []


def test_parse_args_rejects_unknown_transport() -> None:
    with pytest.raises(SystemExit):
        server._parse_args(["--transport", "websocket"])


def test_allow_dir_is_repeatable() -> None:
    args = server._parse_args(["--allow-dir", "/a", "--allow-dir", "/b"])
    assert args.allow_dir == ["/a", "/b"]


def test_help_text_is_truthful(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        server._parse_args(["--help"])
    text = " ".join(capsys.readouterr().out.split())
    # content root precedence: override > checkout > packaged
    assert text.index("EXORAD_MCP_REPO_ROOT") < text.index("checkout")
    assert text.index("checkout") < text.index("packaged in the wheel")
    assert "./mcp-runs" in text
    assert "NO authentication" in text
    assert "127.0.0.1" in text
    assert "EXORAD_MCP_ALLOW_DIRS" in text
    assert "--no-exec" in text


def test_module_help_runs() -> None:
    """``python -m exorad.mcp.server --help`` is what the ``exorad-mcp`` script runs."""
    proc = subprocess.run(
        [sys.executable, "-m", "exorad.mcp.server", "--help"],
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "usage: exorad-mcp" in proc.stdout


def test_import_server_touches_no_network_and_writes_no_stdout() -> None:
    code = textwrap.dedent(
        """
        import socket

        def refuse(*a, **k):
            raise AssertionError("network used at import")

        socket.socket.connect = refuse
        socket.create_connection = refuse
        socket.getaddrinfo = refuse
        import exorad.mcp.server
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


# --- SDK loading ----------------------------------------------------------------
def test_missing_sdk_error_points_at_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", None)
    with pytest.raises(ImportError) as info:
        server._load_server_class()
    assert 'pip install "exorad[mcp]"' in str(info.value)
    assert "mcp>=2,<3" in str(info.value)


def test_there_is_no_mcp_1x_fallback() -> None:
    import inspect

    source = inspect.getsource(server)
    assert "FastMCP" not in source
    assert "from mcp.server import" not in source


# --- build_server ---------------------------------------------------------------
@requires_mcp
def test_build_server_records_bind_address() -> None:
    srv = server.build_server(host="0.0.0.0", port=9001)
    assert srv._exorad_bind == ("0.0.0.0", 9001)


@requires_mcp
def test_build_server_registers_read_only_tools_without_exec() -> None:
    srv = server.build_server(allow_exec=False)
    names = _tool_names(srv)
    assert "search_knowledge_base" in names
    assert {
        "run_pipeline",
        "get_job_status",
        "cancel_job",
        "list_jobs",
        "plot_output",
    }.isdisjoint(names)


@requires_mcp
def test_build_server_registers_every_loadable_registry_tool() -> None:
    srv = server.build_server(allow_exec=True)
    loaded = tools.load_tools(allow_exec=True)
    assert _tool_names(srv) == {name for name, _ in loaded.registered}
    assert srv._exorad_unavailable == loaded.unavailable
    # the info tools of task C exist in this tree
    assert set(tools_info.ALWAYS_AVAILABLE) & _tool_names(srv)


@requires_mcp
def test_every_registered_tool_has_a_description() -> None:
    srv = server.build_server()
    registered = asyncio.run(srv.list_tools())
    assert registered
    missing = [t.name for t in registered if not (t.description or "").strip()]
    assert missing == []


@requires_mcp
def test_resources_and_prompts_are_registered() -> None:
    from exorad.mcp import prompts, resources

    srv = server.build_server()
    templates = {t.uri_template for t in asyncio.run(srv.list_resource_templates())}
    assert resources.KB_URI_TEMPLATE in templates
    assert resources.KB_URI_TEMPLATE == "exorad://kb/{+path}"
    uris = {str(r.uri) for r in asyncio.run(srv.list_resources())}
    assert resources.KB_INDEX_URI in uris
    assert {p.name for p in asyncio.run(srv.list_prompts())} == {
        p.__name__ for p in prompts.ALL_PROMPTS
    }


# --- registry ---------------------------------------------------------------------
def test_registry_has_21_unique_tools_in_step_with_the_info_lists() -> None:
    names = [entry.name for entry in tools.REGISTRY]
    assert len(names) == 21
    assert len(set(names)) == 21
    always = {e.name for e in tools.REGISTRY if not e.execution_only}
    exec_only = {e.name for e in tools.REGISTRY if e.execution_only}
    assert always == set(tools_info.ALWAYS_AVAILABLE)
    assert exec_only == set(tools_info.EXECUTION_ONLY)
    assert {e.module for e in tools.REGISTRY} <= {
        "exorad.mcp.tools",
        "exorad.mcp.tools_info",
        "exorad.mcp.tools_config",
        "exorad.mcp.tools_run",
        "exorad.mcp.tools_output",
    }


def test_registry_skips_a_missing_module_and_says_so() -> None:
    loaded = tools.load_tools(allow_exec=True)
    by_tool = {u["tool"]: u for u in loaded.unavailable}
    present = {name for name, _ in loaded.registered}
    # every tool is either registered or reported, never silently dropped
    assert present | set(by_tool) == set(tools.TOOL_NAMES)
    for item in by_tool.values():
        assert item["reason"]
        assert item["module"].startswith("exorad.mcp.tools_")


def test_registry_reports_a_broken_module_without_crashing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from exorad.mcp import discovery

    (tmp_path / "broken_tools_mod.py").write_text(
        "raise ImportError('no libfoo')\n", encoding="utf-8"
    )
    (tmp_path / "nofunc_tools_mod.py").write_text("X = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(
        tools,
        "REGISTRY",
        (
            tools.ToolEntry("a", "broken_tools_mod", "a", False),
            tools.ToolEntry("b", "nofunc_tools_mod", "b", False),
            tools.ToolEntry("c", "exorad.mcp.tools_info", "list_examples", False),
        ),
    )
    discovery.clear_discovery_errors()
    try:
        loaded = tools.load_tools(allow_exec=True)
        assert [name for name, _ in loaded.registered] == ["c"]
        reasons = {u["tool"]: u["reason"] for u in loaded.unavailable}
        assert "no libfoo" in reasons["a"]
        assert "no function b" in reasons["b"]
        assert any("no libfoo" in str(e) for e in discovery.discovery_errors())
    finally:
        discovery.clear_discovery_errors()


def test_exec_only_tools_are_disabled_not_unavailable() -> None:
    loaded = tools.load_tools(allow_exec=False)
    assert set(loaded.disabled) == set(tools_info.EXECUTION_ONLY)
    assert not {u["tool"] for u in loaded.unavailable} & set(loaded.disabled)


def test_capabilities_wrapper_lists_unavailable_and_trims_the_lists() -> None:
    caps = tools.capabilities()
    unavailable = {u["tool"] for u in caps["tools"]["unavailable"]}
    for key in ("always_available", "execution_only"):
        assert not unavailable & set(caps["tools"][key])
    assert "capabilities" in caps["tools"]["always_available"]
    assert "discovery_errors" in caps


# --- main -------------------------------------------------------------------------
@pytest.mark.parametrize("transport", ["stdio", "sse", "http"])
def test_main_runs_the_selected_transport(
    transport: str, fake_main: _FakeServer
) -> None:
    server.main(["--transport", transport])

    assert fake_main.transport == server._TRANSPORTS[transport]
    # The bind address is a run() keyword on the network transports only.
    expected = {} if transport == "stdio" else {"host": "127.0.0.1", "port": 8000}
    assert fake_main.kwargs == expected
    # The network guard is for stdio only: binding resolves 127.0.0.1.
    assert fake_main.blocked == ([True] if transport == "stdio" else [])  # type: ignore[attr-defined]


def test_main_installs_signal_hooks_on_main_thread_before_run(
    fake_main: _FakeServer,
) -> None:
    """Tools run in worker threads, so main() must register the handlers first."""
    server.main([])
    assert fake_main.calls == ["hooks", "run"]


def test_http_transport_defaults_to_loopback_and_warns(
    fake_main: _FakeServer, capfd: pytest.CaptureFixture[str]
) -> None:
    server.main(["--transport", "http"])
    assert fake_main.kwargs["host"] == "127.0.0.1"
    err = capfd.readouterr().err
    assert "NO authentication" in err


def test_main_flags_become_environment(
    fake_main: _FakeServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import os

    monkeypatch.setenv("EXORAD_MCP_ALLOW_DIRS", "/pre")
    monkeypatch.delenv("EXORAD_MCP_NO_EXEC", raising=False)
    server.main(
        [
            "--repo-root",
            str(tmp_path),
            "--work-dir",
            str(tmp_path / "wd"),
            "--allow-dir",
            "/x",
            "--allow-dir",
            "/y",
            "--no-exec",
        ]
    )
    assert os.environ["EXORAD_MCP_REPO_ROOT"] == str(tmp_path)
    assert os.environ["EXORAD_MCP_WORK_DIR"] == str(tmp_path / "wd")
    assert os.environ["EXORAD_MCP_ALLOW_DIRS"].split(os.pathsep) == ["/pre", "/x", "/y"]
    assert os.environ["EXORAD_MCP_NO_EXEC"] == "1"


def test_main_sets_the_child_environment_in_the_server_process(
    fake_main: _FakeServer,
) -> None:
    import os

    server.main([])
    assert os.environ["EXORAD_NO_VERSION_CHECK"] == "1"
    assert os.environ["MPLBACKEND"] == "Agg"
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        assert os.environ[name] == "1"


def test_main_keeps_a_user_chosen_matplotlib_backend(
    fake_main: _FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    monkeypatch.setenv("MPLBACKEND", "svg")
    server.main([])
    assert os.environ["MPLBACKEND"] == "svg"


# --- logging ----------------------------------------------------------------------
def test_route_logging_to_stderr(capfd: pytest.CaptureFixture[str]) -> None:
    from exorad.log import logger as exorad_logger

    server._route_logging_to_stderr()
    logging.getLogger("exorad.Probe").info("hello-from-exorad")
    out, err = capfd.readouterr()
    assert "hello-from-exorad" not in out
    assert "hello-from-exorad" in err
    assert exorad_logger.ch.stream is sys.stderr


def test_mcp_logger_serves_debug_while_the_shared_handler_stays_at_info(
    capfd: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from exorad.log import logger as exorad_logger

    monkeypatch.setenv("EXORAD_MCP_LOG_LEVEL", "DEBUG")
    server._route_logging_to_stderr()
    logging.getLogger("exorad.mcp.probe").debug("mcp-debug-probe")
    logging.getLogger("exorad.Other").debug("library-debug-probe")
    _, err = capfd.readouterr()
    assert err.count("mcp-debug-probe") == 1  # no duplicate through propagation
    assert "library-debug-probe" not in err
    assert exorad_logger.ch.level == logging.INFO


def test_route_logging_twice_adds_one_handler() -> None:
    server._route_logging_to_stderr()
    server._route_logging_to_stderr()
    ours = [
        h for h in server._LOGGER.handlers if getattr(h, server._HANDLER_TAG, False)
    ]
    assert len(ours) == 1


def test_invalid_log_level_falls_back_to_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXORAD_MCP_LOG_LEVEL", "LOUD")
    server._route_logging_to_stderr()
    assert server._LOGGER.level == logging.INFO
