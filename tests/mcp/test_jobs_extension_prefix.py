"""An extension package's job entries must reach the spawned child (X1)."""

from __future__ import annotations

import json
import os
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

from exorad.mcp import jobs
from exorad.mcp.jobs import JobManager

if TYPE_CHECKING:
    from pathlib import Path

PKG = "extkitx1"
PREFIX = f"{PKG}.mcp."


@pytest.fixture
def ext_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A throw-away package OUTSIDE ``exorad.mcp`` with a job entry."""
    root = tmp_path / "extsrc"
    pkg = root / PKG / "mcp"
    pkg.mkdir(parents=True)
    (root / PKG / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "entry.py").write_text(
        textwrap.dedent(
            """
            import os

            def run(spec):
                return {"pid": os.getpid(), "value": spec.get("value", 0) + 1}

            def run_job(spec):
                from pathlib import Path
                Path(spec["output"]).write_text("ran")
            """
        )
    )
    monkeypatch.syspath_prepend(str(root))
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join([str(root), os.environ.get("PYTHONPATH", "")])
    )
    monkeypatch.setenv("EXORAD_MCP_EXEC_BACKEND", "process")
    monkeypatch.setattr(jobs, "_ALLOWED_ENTRY_PREFIXES", ["exorad.mcp."])
    yield PREFIX
    for name in [m for m in sys.modules if m == PKG or m.startswith(PKG + ".")]:
        del sys.modules[name]


@pytest.fixture
def manager():
    mgr = JobManager()
    yield mgr
    mgr.shutdown()


def test_run_sync_reaches_an_extension_entry_in_the_child(
    ext_package: str, manager: JobManager
) -> None:
    jobs.register_entry_prefix(ext_package)
    result = manager.run_sync(f"{PKG}.mcp.entry:run", {"value": 41}, timeout=120)
    assert result["value"] == 42
    assert result["pid"] != os.getpid()


def test_submit_reaches_an_extension_entry_in_the_child(
    ext_package: str, manager: JobManager, tmp_path: Path
) -> None:
    import time

    jobs.register_entry_prefix(ext_package)
    out = tmp_path / "out.txt"
    spec = {"entry": f"{PKG}.mcp.entry:run_job", "pipeline": "x", "output": str(out)}
    job_id = manager.submit(spec, log_dir=tmp_path / "logs", max_runtime=None)
    deadline = time.time() + 120
    while time.time() < deadline and manager.status(job_id)["status"] == "running":
        time.sleep(0.1)
    status = manager.status(job_id)
    assert status["status"] == "succeeded", json.dumps(status)[:800]
    assert out.read_text() == "ran"


def test_an_unregistered_extension_entry_is_refused_by_the_parent(
    ext_package: str, manager: JobManager, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="refused"):
        manager.run_sync(f"{PKG}.mcp.entry:run", {}, timeout=5)
    with pytest.raises(ValueError, match="refused"):
        manager.submit(
            {"entry": f"{PKG}.mcp.entry:run", "pipeline": "x", "output": ""},
            log_dir=tmp_path,
            max_runtime=None,
        )


def test_system_entries_stay_refused_after_a_registration(
    ext_package: str, manager: JobManager
) -> None:
    jobs.register_entry_prefix(ext_package)
    for entry in ("os:system", "subprocess:run", "os.path:join", "sys:exit"):
        with pytest.raises(ValueError, match="refused"):
            manager.run_sync(entry, {}, timeout=5)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        ".",
        "arielrad",
        "arielrad.mcp",
        "os.",
        "subprocess.",
        "sys.",
        "a.",
        "..",
        "x y.z.",
    ],
)
def test_bad_prefixes_are_refused(bad: str, ext_package: str) -> None:
    with pytest.raises(ValueError):
        jobs.register_entry_prefix(bad)
    assert jobs._ALLOWED_ENTRY_PREFIXES == ["exorad.mcp."]


def test_registering_twice_is_idempotent(ext_package: str) -> None:
    jobs.register_entry_prefix(ext_package)
    jobs.register_entry_prefix(ext_package)
    assert ["exorad.mcp.", ext_package] == jobs._ALLOWED_ENTRY_PREFIXES
    assert jobs.registered_entry_prefixes() == ("exorad.mcp.", ext_package)
