"""Regression tests of the second independent review (H1-H3, F1-F6, N1-N10).

Each test failed before its fix. Nothing here writes into the checkout: work
directories live under ``tmp_path``.
"""

from __future__ import annotations

import json
import lzma
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from run_fixtures import FakeJobs, make_project, work_dir_of
from test_plotting import FIXTURE_XZ

from exorad.mcp import (
    authoring,
    configuration,
    jobs,
    outputs,
    pipelines,
    plotting,
    prompts,
    sandbox,
    server,
    tools_output,
    tools_run,
)
from exorad.mcp.jobs import JobManager, OutputInUseError
from exorad.mcp.sandbox import PathNotAllowedError, Sandbox

REPO = Path(__file__).resolve().parents[2]
ENTRY = "exorad.mcp.jobs:_SelfTestEntry"


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeJobs:
    recorder = FakeJobs()
    monkeypatch.setattr(jobs, "JOBS", recorder)
    return recorder


@pytest.fixture
def real_jobs(monkeypatch: pytest.MonkeyPatch):
    """A real manager (spawned children) as ``jobs.JOBS``."""
    monkeypatch.setenv("EXORAD_MCP_EXEC_BACKEND", "process")
    manager = JobManager()
    monkeypatch.setattr(jobs, "JOBS", manager)
    yield manager
    manager.shutdown()


def _sleeping(output: Path, seconds: float = 60.0) -> dict:
    return {
        "entry": ENTRY,
        "pipeline": "selftest",
        "output": str(output),
        "selftest": {"sleep": seconds},
    }


# -- H1: two jobs never share an output ---------------------------------------------
def test_manager_refuses_the_same_output_of_a_running_job(
    real_jobs: JobManager, tmp_path: Path
) -> None:
    out = tmp_path / "res" / "a.h5"
    first = real_jobs.submit(_sleeping(out), log_dir=tmp_path / "l", max_runtime=None)
    with pytest.raises(OutputInUseError) as info:
        real_jobs.submit(_sleeping(out), log_dir=tmp_path / "l", max_runtime=None)
    assert info.value.job_id == first
    assert info.value.what == "output"


def test_manager_refuses_the_output_directory_of_a_running_job(
    real_jobs: JobManager, tmp_path: Path
) -> None:
    first = real_jobs.submit(
        _sleeping(tmp_path / "res" / "a.h5"), log_dir=tmp_path / "l", max_runtime=None
    )
    with pytest.raises(OutputInUseError) as info:
        real_jobs.submit(
            _sleeping(tmp_path / "res" / "b.h5"),
            log_dir=tmp_path / "l",
            max_runtime=None,
        )
    assert info.value.job_id == first
    assert info.value.what == "directory"
    # another directory is fine
    real_jobs.submit(
        _sleeping(tmp_path / "other" / "b.h5"), log_dir=tmp_path / "l", max_runtime=None
    )


def test_run_pipeline_refuses_overwrite_on_a_running_output(
    real_jobs: JobManager, tmp_path: Path
) -> None:
    payload, targets = make_project(tmp_path)
    out = work_dir_of(tmp_path) / "results" / "same.h5"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"being written")
    real_jobs.submit(_sleeping(out), log_dir=tmp_path / "l", max_runtime=None)
    for name in ("same.h5", "neighbour.h5"):
        result = tools_run.run_pipeline(
            payload, targets, output=f"results/{name}", overwrite=True
        )
        assert result["status"] == "refused", result
        assert result["reason"] == "output_in_use"
        assert result["conflicting_job"] in result["running_jobs"]
    assert out.read_bytes() == b"being written"
    assert not list(work_dir_of(tmp_path).glob("runs/*")), "plan directory removed"


# -- H2: a file in the path of the output --------------------------------------------
def test_output_below_a_regular_file_is_refused_and_the_file_kept(
    tmp_path: Path, fake: FakeJobs
) -> None:
    payload, targets = make_project(tmp_path)
    blocker = work_dir_of(tmp_path) / "bad" / "text.h5"
    blocker.parent.mkdir(parents=True)
    blocker.write_text("precious")
    with pytest.raises(ValueError, match="is a file, not a directory"):
        tools_run.run_pipeline(payload, targets, output="bad/text.h5/x.h5")
    assert blocker.read_text() == "precious"
    assert fake.specs == []


# -- F1: overwrite=True re-runs into the directory of an earlier run ------------------
def _fake_previous_run(tmp_path: Path) -> Path:
    """Leave what a finished run leaves: the output, run.json and the input copies."""
    out_dir = work_dir_of(tmp_path) / "results"
    out_dir.mkdir(parents=True)
    out = out_dir / "out.h5"
    out.write_bytes(b"old")
    (out_dir / "payload.xml").write_text("<old-normalised-copy/>")
    (out_dir / "targets.csv").write_text("old")
    (out_dir / "out.run.json").write_text(
        json.dumps({"input_copies": ["payload.xml", "targets.csv"]})
    )
    return out


def test_overwrite_replaces_the_input_copies_of_the_same_output(
    tmp_path: Path, fake: FakeJobs
) -> None:
    payload, targets = make_project(tmp_path)
    _fake_previous_run(tmp_path)
    tools_run.run_pipeline(payload, targets, output="results/out.h5", overwrite=True)
    assert len(fake.specs) == 1


def test_overwrite_still_refuses_an_unrelated_file_of_that_name(
    tmp_path: Path, fake: FakeJobs
) -> None:
    payload, targets = make_project(tmp_path)
    out = _fake_previous_run(tmp_path)
    (out.parent / "out.run.json").unlink()  # not a run of THIS output
    with pytest.raises(FileExistsError, match=r"payload\.xml"):
        tools_run.run_pipeline(
            payload, targets, output="results/out.h5", overwrite=True
        )
    # a record does not license a file it does not name
    (out.parent / "out.run.json").write_text(json.dumps({"input_copies": []}))
    with pytest.raises(FileExistsError, match=r"payload\.xml"):
        tools_run.run_pipeline(
            payload, targets, output="results/out.h5", overwrite=True
        )


@pytest.mark.slow
def test_a_real_second_run_with_overwrite_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXORAD_MCP_EXEC_BACKEND", "process")
    payload, targets = make_project(tmp_path, n_targets=1)
    try:
        for overwrite in (False, True):
            result = tools_run.run_pipeline(
                payload,
                targets,
                output="results/out.h5",
                overwrite=overwrite,
                wait_seconds=50,
            )
            deadline = time.time() + 300
            while result["status"] == "running" and time.time() < deadline:
                time.sleep(1)
                result = tools_run.get_job_status(result["job_id"])
            assert result["status"] == "succeeded", result
    finally:
        jobs.JOBS.shutdown()


# -- F2 / F3: the sync pool waits, then says busy ------------------------------------
def _busy(*args: object, **kwargs: object):
    raise jobs.SyncLimitError(2)


def test_deep_validation_over_the_cap_is_busy_not_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jobs.JOBS, "run_sync", _busy)
    result = configuration.validate_configuration_file(
        "examples/payload_example.xml", deep=True
    )
    assert result["valid"] is None
    assert result["status"] == "busy"
    assert "DEEP_BUILD_FAILED" not in json.dumps(result["findings"])
    assert "NOT" in result["message"]


def test_plot_over_the_cap_is_busy_not_plottable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    work = work_dir_of(tmp_path)
    work.mkdir(parents=True)
    (work / "out.h5").write_bytes(lzma.decompress(FIXTURE_XZ.read_bytes()))
    monkeypatch.setattr(jobs.JOBS, "run_sync", _busy)
    result = tools_output.plot_output("out.h5")
    assert result["status"] == "busy"
    assert result["plottable"] is None
    assert result["figures"] == []
    assert "error" not in result


def test_run_sync_waits_for_a_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXORAD_MCP_EXEC_BACKEND", "process")
    monkeypatch.setenv("EXORAD_MCP_MAX_JOBS", "1")
    manager = JobManager()
    box: dict[str, dict] = {}
    thread = threading.Thread(
        target=lambda: box.update(
            first=manager.run_sync(
                "exorad.mcp.jobs:_selftest_sync", {"sleep": 4}, timeout=60
            )
        )
    )
    thread.start()
    try:
        deadline = time.time() + 60
        while not manager._sync and time.time() < deadline:
            time.sleep(0.05)
        second = manager.run_sync(
            "exorad.mcp.jobs:_selftest_sync", {}, timeout=60, slot_wait=60
        )
        assert second["answer"] == 1
    finally:
        thread.join(90)
        manager.shutdown()
    assert box["first"]["answer"] == 1


# -- F4: finite durations ---------------------------------------------------------------
@pytest.mark.parametrize("raw", ["inf", "-inf", "nan", "1e400", "0", "-3", "abc"])
def test_float_env_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("EXORAD_MCP_MAX_RUNTIME", raw)
    assert sandbox._float_env("EXORAD_MCP_MAX_RUNTIME", 3600.0) == 3600.0


def test_float_env_clamps_a_huge_finite_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXORAD_MCP_VALIDATE_TIMEOUT", "1e9")
    value = sandbox._float_env("EXORAD_MCP_VALIDATE_TIMEOUT", 120.0)
    assert value == sandbox.MAX_SECONDS


def test_capabilities_are_strict_json_with_an_infinite_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXORAD_MCP_MAX_RUNTIME", "inf")
    monkeypatch.setenv("EXORAD_MCP_VALIDATE_TIMEOUT", "1e400")
    text = json.dumps(Sandbox.from_env().to_dict(), allow_nan=False)
    assert "Infinity" not in text


def test_run_sync_survives_an_enormous_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXORAD_MCP_EXEC_BACKEND", "process")
    manager = JobManager()
    try:
        for value in (float("inf"), 1e9):
            result = manager.run_sync(
                "exorad.mcp.jobs:_selftest_sync", {"value": 1}, timeout=value
            )
            assert result["answer"] == 2
    finally:
        manager.shutdown()


# -- F5: the SDK import error ------------------------------------------------------------
def test_import_error_with_a_good_version_does_not_blame_the_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "_pkg_version", lambda name: "2.1.0")
    monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", None)
    with pytest.raises(ImportError) as info:
        server._load_server_class()
    text = str(info.value)
    assert "is required" not in text
    assert "2.1.0" in text
    assert "ModuleNotFoundError" in text  # the original exception is kept


def test_out_of_range_version_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_pkg_version", lambda name: "1.9.0")
    monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", None)
    with pytest.raises(ImportError, match=r"mcp 1\.9\.0 is installed but mcp>=2,<3"):
        server._load_server_class()


def test_main_prints_one_clean_line_when_the_sdk_cannot_be_imported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(server, "_pkg_version", lambda name: "2.1.0")
    monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", None)
    with pytest.raises(SystemExit) as info:
        server.main(["--no-exec"])
    assert info.value.code == 1
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1
    assert err[0].startswith("exorad-mcp: error:")


def test_documented_check_command_works(tmp_path: Path) -> None:
    command = "from exorad.mcp.server import build_server; build_server()"
    done = subprocess.run(
        [sys.executable, "-c", command],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={**os.environ, "EXORAD_MCP_WORK_DIR": str(tmp_path / "w")},
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == ""
    assert command in (REPO / "docs/source/user/mcp.rst").read_text()


# -- F6: the channel prompt ----------------------------------------------------------------
def test_set_up_channel_does_not_promise_adding_a_channel() -> None:
    text = prompts.set_up_channel("photometer")
    assert "cannot add a channel" in text
    assert "by hand" in text
    assert "Help me add a" not in text


# -- H3: the work directory ------------------------------------------------------------------
def test_default_work_dir_falls_back_to_the_user_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("EXORAD_MCP_WORK_DIR")
    monkeypatch.setattr(sandbox, "can_create_dir", lambda path: False)
    monkeypatch.setenv("HOME", str(tmp_path))
    box = Sandbox.from_env()
    assert box.work_dir == (tmp_path / ".exorad" / "mcp-runs").resolve()


def test_an_explicit_work_dir_is_never_replaced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sandbox, "can_create_dir", lambda path: False)
    box = Sandbox.from_env()
    assert box.work_dir == (tmp_path / "mcp-work").resolve()


def test_can_create_dir(tmp_path: Path) -> None:
    assert sandbox.can_create_dir(tmp_path / "a" / "b")
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert not sandbox.can_create_dir(blocker / "sub")


def test_unusable_explicit_work_dir_is_one_error_line(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    done = subprocess.run(
        [sys.executable, "-m", "exorad.mcp.server", "--work-dir", str(blocker / "w")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        timeout=120,
    )
    assert done.returncode != 0
    assert "Traceback" not in done.stderr
    lines = [line for line in done.stderr.splitlines() if line.strip()]
    assert len(lines) == 1, done.stderr
    assert "cannot use" in lines[0]


def test_no_exec_does_not_create_the_work_dir_at_startup() -> None:
    box = Sandbox.from_env(allow_exec=False)
    server._prepare_work_dir(box, explicit=True, prog="exorad-mcp")
    assert not box.work_dir.exists()
    exec_box = Sandbox.from_env(allow_exec=True)
    server._prepare_work_dir(exec_box, explicit=True, prog="exorad-mcp")
    assert exec_box.work_dir.is_dir()


# -- N1: redirect first --------------------------------------------------------------------------
def test_worker_redirects_before_anything_else(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    order: list[str] = []

    def redirect(path: str):
        order.append("redirect")
        raise RuntimeError("stop here")

    monkeypatch.setattr(jobs, "_redirect_output", redirect)
    monkeypatch.setattr(jobs, "_become_group_leader", lambda: order.append("setsid"))
    with pytest.raises(RuntimeError, match="stop here"):
        jobs._worker({"entry": ENTRY}, str(tmp_path / "x.log"), os.getpid())
    assert order == ["redirect"]


# -- N2: table errors name the file -------------------------------------------------------------
def test_broken_ecsv_header_is_reported_not_read_as_csv(tmp_path: Path) -> None:
    path = tmp_path / "mcp-work" / "t.ecsv"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# %ECSV 1.0\n# ---\n# datatype: [{name: a, datatype: nonsense\na\n1\n"
    )
    with pytest.raises(ValueError, match=r"cannot read t\.ecsv"):
        outputs._inspect_table(path, Sandbox.from_env())


# -- N3: plot folders ---------------------------------------------------------------------------
def test_plot_folders_do_not_collide() -> None:
    box = Sandbox.from_env()
    names = {
        plotting.output_stem(box.work_dir / rel, box)
        for rel in ("results/a-b.h5", "results/a/b.h5", "x.h5", "x.hdf5")
    }
    assert len(names) == 4


def test_target_with_the_efficiency_plot_is_refused(tmp_path: Path) -> None:
    work = work_dir_of(tmp_path)
    work.mkdir(parents=True)
    (work / "o.h5").write_bytes(b"x")
    with pytest.raises(ValueError, match="kind='table' only"):
        plotting.prepare(
            (work / "o.h5").resolve(), "efficiency", "t0", Sandbox.from_env()
        )


# -- N5: path-like keys ----------------------------------------------------------------------------
def test_data_override_is_path_like() -> None:
    box = Sandbox.from_env()
    base = box.repo_root
    with pytest.raises(PathNotAllowedError):
        authoring.check_override("data", "/etc/passwd", sandbox=box, base=base)
    with pytest.raises(ValueError, match="URL"):
        authoring.check_override("data", "https://x.org/t.csv", sandbox=box, base=base)
    with pytest.raises(ValueError, match="pickle"):
        authoring.check_override("data", "t.pkl", sandbox=box, base=base)


# -- N7: the wait ------------------------------------------------------------------------------------
def test_wait_seconds_is_clamped_to_fifty(tmp_path: Path, fake: FakeJobs) -> None:
    assert pipelines.MAX_WAIT_SECONDS == 50.0
    seen: list[float | None] = []
    original = fake.wait

    def wait(job_id: str, timeout: float | None) -> dict:
        seen.append(timeout)
        return original(job_id, timeout)

    fake.wait = wait  # type: ignore[method-assign]
    payload, targets = make_project(tmp_path)
    tools_run.run_pipeline(payload, targets, wait_seconds=600)
    assert seen == [50.0]


# -- docs ---------------------------------------------------------------------------------------------
PUBLISHED = (
    "docs/source/user/mcp.rst",
    "docs/source/agentic_support.rst",
    "AGENTS.md",
    "docs/ai-agents/codebase-map.md",
)
INTERNAL = ("mcp-plan", "mcp-spec", "noxfile", "changelog.d", "scripts/")


@pytest.mark.parametrize("name", PUBLISHED)
def test_published_text_does_not_name_internal_files(name: str) -> None:
    text = (REPO / name).read_text(encoding="utf-8")
    found = [word for word in INTERNAL if word in text]
    assert not found, f"{name} names {found}"


def test_docs_describe_the_new_behaviour() -> None:
    text = (REPO / "docs/source/user/mcp.rst").read_text(encoding="utf-8")
    for needle in (
        "Response conventions",
        "PHOENIX_PATH",
        "~/.exorad/mcp-runs",
        "output_in_use",
        'status="busy"',
        "stays alive but stops answering",
    ):
        assert needle in text, needle
    assert "(0 to 600)" not in text
    assert re.search(r"^mcp-runs/$", (REPO / ".gitignore").read_text(), re.MULTILINE)
