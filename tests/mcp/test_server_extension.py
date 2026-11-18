"""Extension points of the server for other packages (X2, X3).

A throw-away package under ``tmp_path`` plays the extension: its own tool module,
an extra prompt and resource, and a ``main(...)`` call with its own wording.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest
from stdio_helper import REPO_ROOT, result_text, run_stdio_requests

from exorad.mcp import assets, server, tools
from exorad.mcp.sandbox import Sandbox

if TYPE_CHECKING:
    from pathlib import Path

PKG = "extkitx3"

_PKG_SOURCE = textwrap.dedent(
    '''
    from exorad.mcp import tools

    REGISTRY = (
        *(e for e in tools.REGISTRY),
        tools.ToolEntry("ext_hello", "extkitx3.mcp.tools_ext", "ext_hello", False),
        tools.ToolEntry("ext_broken", "extkitx3.mcp.tools_ext", "ext_broken", False),
        tools.ToolEntry("ext_gone", "extkitx3.mcp.not_there", "ext_gone", False),
        tools.ToolEntry("ext_exec", "extkitx3.mcp.tools_ext", "ext_exec", True),
    )
    HIDE = ("diagnose_error",)


    def ext_prompt() -> str:
        """An extension prompt."""
        return "extension prompt text"


    def ext_resource() -> str:
        """An extension resource."""
        return "extension resource text"
    '''
)

_TOOLS_SOURCE = textwrap.dedent(
    '''
    def ext_hello(who: str = "world") -> dict:
        """Say hello."""
        return {"hello": who}


    def ext_broken() -> dict:
        """Fail with an expected error."""
        raise ValueError("extension says: bad input 42")


    def ext_exec() -> dict:
        """Execution only."""
        return {}
    '''
)


@pytest.fixture
def ext_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "extsrc"
    pkg = root / PKG / "mcp"
    pkg.mkdir(parents=True)
    (root / PKG / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text(_PKG_SOURCE)
    (pkg / "tools_ext.py").write_text(_TOOLS_SOURCE)
    monkeypatch.syspath_prepend(str(root))
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join([str(root), os.environ.get("PYTHONPATH", "")])
    )
    yield root
    for name in [m for m in sys.modules if m == PKG or m.startswith(PKG + ".")]:
        del sys.modules[name]


def _tool_names(srv: object) -> set[str]:
    return {tool.name for tool in asyncio.run(srv.list_tools())}


def test_registry_parameter_adds_and_hides_tools(ext_root: Path) -> None:
    import extkitx3.mcp as ext

    srv = server.build_server(registry=ext.REGISTRY, hide=ext.HIDE, name="extkit")
    names = _tool_names(srv)
    assert {"ext_hello", "ext_broken", "ext_exec"} <= names
    assert "diagnose_error" not in names
    assert "ext_gone" not in names
    assert {"validate_config", "capabilities"} <= names
    assert [u["tool"] for u in srv._exorad_unavailable] == ["ext_gone"]
    assert "not present" in srv._exorad_unavailable[0]["reason"]
    assert srv.name == "extkit"


def test_default_server_keeps_exorads_21_tools(ext_root: Path) -> None:
    import extkitx3.mcp  # noqa: F401  (importing the extension changes nothing)

    names = _tool_names(server.build_server(allow_exec=True))
    assert names == {entry.name for entry in tools.REGISTRY}
    assert len(names) == 21
    assert len(tools.REGISTRY) == 21


def test_extension_tools_are_not_registered_without_exec(ext_root: Path) -> None:
    import extkitx3.mcp as ext

    srv = server.build_server(registry=ext.REGISTRY, allow_exec=False)
    assert "ext_exec" not in _tool_names(srv)
    assert "ext_hello" in _tool_names(srv)


def test_extension_error_text_reaches_the_client_in_process(ext_root: Path) -> None:
    import extkitx3.mcp as ext
    from mcp.server.mcpserver.exceptions import ToolError

    srv = server.build_server(registry=ext.REGISTRY)
    with pytest.raises(ToolError, match="extension says: bad input 42"):
        asyncio.run(srv.call_tool("ext_broken", {}))


def test_capabilities_reports_the_registry_that_is_served(ext_root: Path) -> None:
    import extkitx3.mcp as ext

    srv = server.build_server(registry=ext.REGISTRY, hide=ext.HIDE, allow_exec=True)
    result = asyncio.run(srv.call_tool("capabilities", {}))
    caps = (
        result.structured_content if hasattr(result, "structured_content") else result
    )
    caps = caps.get("result", caps) if isinstance(caps, dict) else caps
    listed = caps["tools"]
    assert "ext_hello" in listed["always_available"]
    assert "ext_exec" in listed["execution_only"]
    assert "diagnose_error" not in listed["always_available"]
    assert "ext_gone" not in listed["always_available"]
    assert [u["tool"] for u in listed["unavailable"]] == ["ext_gone"]


def test_capabilities_without_exec_lists_extension_tools_as_disabled(
    ext_root: Path,
) -> None:
    import extkitx3.mcp as ext

    entries = tools.effective_registry(ext.REGISTRY, ext.HIDE)
    os.environ["EXORAD_MCP_NO_EXEC"] = "1"
    caps = tools.capabilities_for(ext.REGISTRY, ext.HIDE)()
    assert "ext_exec" in caps["tools"]["disabled"]
    assert "ext_exec" not in caps["tools"]["execution_only"]
    assert len(entries) == 24


def test_default_capabilities_still_use_the_exorad_constants() -> None:
    from exorad.mcp import tools_info

    caps = tools.capabilities()["tools"]
    assert caps["always_available"] == list(tools_info.ALWAYS_AVAILABLE)
    assert caps["execution_only"] == list(tools_info.EXECUTION_ONLY)
    assert caps["disabled"] == []


def test_registry_misuse_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown tools: nope"):
        tools.load_tools(allow_exec=True, hide=("nope",))
    doubled = (*tools.REGISTRY, tools.REGISTRY[0])
    with pytest.raises(ValueError, match="duplicate"):
        tools.load_tools(allow_exec=True, registry=doubled)


def test_extension_tools_over_stdio(ext_root: Path, tmp_path: Path) -> None:
    launcher = textwrap.dedent(
        """
        import sys
        import extkitx3.mcp as ext
        from exorad.mcp.server import main

        main(sys.argv[1:], name="extkit", registry=ext.REGISTRY, hide=ext.HIDE,
             prompts=[ext.ext_prompt],
             resources=[("extkit://thing", ext.ext_resource)])
        """
    )
    _, (broken, hello, caps, prompts, init), _ = run_stdio_requests(
        [
            ("tools/call", {"name": "ext_broken", "arguments": {}}),
            ("tools/call", {"name": "ext_hello", "arguments": {"who": "ada"}}),
            ("tools/call", {"name": "capabilities", "arguments": {}}),
            ("prompts/list", {}),
            ("tools/list", {}),
        ],
        work_dir=tmp_path / "work",
        stubs="",
        launcher=launcher,
    )
    assert broken["result"]["isError"] is True
    assert "extension says: bad input 42" in result_text(broken)
    assert "ada" in result_text(hello)
    listed = json.loads(result_text(caps))["tools"]
    assert "ext_hello" in listed["always_available"]
    assert "diagnose_error" not in listed["always_available"]
    assert "ext_gone" in [u["tool"] for u in listed["unavailable"]]
    assert "ext_prompt" in {p["name"] for p in prompts["result"]["prompts"]}
    names = {t["name"] for t in init["result"]["tools"]}
    assert "ext_hello" in names
    assert "diagnose_error" not in names


# --- main(): X3 ---------------------------------------------------------------------
@pytest.fixture
def fake_run(monkeypatch: pytest.MonkeyPatch):
    from exorad.mcp import jobs, netguard

    calls: list[str] = []

    class Fake:
        def run(self, transport: str = "stdio", **kwargs: object) -> None:
            calls.append("run")

    built: dict[str, object] = {}

    def fake_build(**kwargs: object) -> Fake:
        built.update(kwargs)
        return Fake()

    monkeypatch.setattr(server, "build_server", fake_build)
    monkeypatch.setattr(netguard, "block_network", lambda: None)
    monkeypatch.setattr(jobs.JOBS, "install_hooks", lambda: calls.append("hooks"))
    monkeypatch.setattr(server, "_route_logging_to_stderr", lambda: None)
    return built, calls


def test_main_passes_the_extension_parameters_to_build_server(
    fake_run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, calls = fake_run

    def prompt() -> str:
        """P."""
        return "p"

    server.main(
        [],
        name="arielrad",
        prompts=[prompt],
        resources=[("x://y", prompt)],
        hide=("diagnose_error",),
        registry=tools.REGISTRY,
    )
    assert built["name"] == "arielrad"
    assert built["prompts"] == (prompt,)
    assert built["resources"] == (("x://y", prompt),)
    assert built["hide"] == ("diagnose_error",)
    assert built["registry"] is tools.REGISTRY
    assert calls == ["hooks", "run"]


def test_setup_runs_before_the_sandbox_is_created(
    fake_run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[object] = []
    work = tmp_path / "ext-work"
    real_from_env = Sandbox.from_env.__func__  # type: ignore[attr-defined]

    def spy(cls, **kwargs):
        seen.append(os.environ.get("EXORAD_MCP_WORK_DIR"))
        return real_from_env(cls, **kwargs)

    monkeypatch.setattr(Sandbox, "from_env", classmethod(spy))

    def setup(args) -> None:
        seen.append(("setup", args.transport, args.work_dir))
        os.environ["EXORAD_MCP_WORK_DIR"] = str(work)

    server.main(["--work-dir", str(tmp_path / "flag")], setup=setup)
    assert seen[0] == ("setup", "stdio", str(tmp_path / "flag"))
    assert seen[1] == str(work)  # the env var set in setup is what from_env saw
    assert work.is_dir()


def test_help_shows_the_extension_text_and_no_exorad_wording(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        server.main(
            ["--help"],
            name="arielrad",
            prog="arielrad-mcp",
            description="Run the ArielRad server.",
            epilog="Set ARIELRAD_MCP_* variables.",
            help_overrides={
                "repo_root": "ArielRad content root (ARIELRAD_MCP_REPO_ROOT).",
                "work_dir": "Writable directory (ARIELRAD_MCP_WORK_DIR).",
                "allow_dir": "Extra directory (ARIELRAD_MCP_ALLOW_DIRS).",
                "no_exec": "Disable the execution tools.",
            },
            version_text="arielrad-mcp 1",
        )
    text = capsys.readouterr().out
    assert "arielrad-mcp" in text
    assert "Run the ArielRad server." in text
    assert "ARIELRAD_MCP_*" in text
    assert "ARIELRAD_MCP_REPO_ROOT" in text
    for forbidden in ("EXORAD_MCP", "ExoRad", "exorad-mcp", "run_pipeline"):
        assert forbidden not in text


def test_default_help_text_is_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        server._parse_args(["--help"])
    text = capsys.readouterr().out
    assert "usage: exorad-mcp" in text
    assert "Run the ExoRad Model Context Protocol server." in text
    assert "EXORAD_MCP_REPO_ROOT" in text
    assert "ExoRad checkout" in text


def test_extra_prompts_and_resources_are_listed(ext_root: Path) -> None:
    import extkitx3.mcp as ext

    srv = server.build_server(
        prompts=[ext.ext_prompt], resources=[("extkit://thing", ext.ext_resource)]
    )
    names = {p.name for p in asyncio.run(srv.list_prompts())}
    assert "ext_prompt" in names
    assert "new_simulation" in names  # ExoRad's own are kept
    uris = {str(r.uri) for r in asyncio.run(srv.list_resources())}
    assert "extkit://thing" in uris


# --- content source -----------------------------------------------------------------
def test_an_extension_can_report_its_pinned_root_as_packaged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXORAD_MCP_REPO_ROOT", str(tmp_path))
    assert Sandbox.from_env().content_source == "override"  # unchanged default
    monkeypatch.setenv(assets.ENV_CONTENT_SOURCE, "packaged")
    box = Sandbox.from_env()
    assert box.content_source == "packaged"
    assert box.to_dict()["content"]["source"] == "packaged"
    monkeypatch.setenv(assets.ENV_CONTENT_SOURCE, "bogus")
    assert Sandbox.from_env().content_source == "override"
    monkeypatch.delenv("EXORAD_MCP_REPO_ROOT")
    monkeypatch.setenv(assets.ENV_CONTENT_SOURCE, "packaged")
    # only meaningful together with an explicit root
    assert assets.resolve_content_root(cwd=REPO_ROOT).source != "packaged"
