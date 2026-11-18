"""Tests for the ExoRad MCP background job manager (real spawn path)."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import TYPE_CHECKING

import pytest

from exorad.mcp import jobs
from exorad.mcp.jobs import JobLimitError, JobManager

if TYPE_CHECKING:
    from pathlib import Path

ENTRY = "exorad.mcp.jobs:_SelfTestEntry"


def _spec(tmp_path: Path, **selftest: object) -> dict[str, object]:
    return {
        "entry": ENTRY,
        "pipeline": "selftest",
        "output": str(tmp_path / "out.h5"),
        "selftest": selftest,
    }


def _wait_until_terminal(
    manager: JobManager, job_id: str, timeout: float = 120.0
) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = manager.status(job_id)
        if status["status"] != "running":
            return status
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} never finished: {manager.status(job_id)}")


def _wait_for(path: Path, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    while not path.exists() and time.time() < deadline:
        time.sleep(0.1)
    assert path.exists(), f"{path} never appeared"


@pytest.fixture(autouse=True)
def _process_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """conftest defaults to ``inline``; these tests exercise the real spawn path."""
    monkeypatch.setenv("EXORAD_MCP_EXEC_BACKEND", "process")


@pytest.fixture
def manager():
    mgr = JobManager()
    yield mgr
    mgr.shutdown()


def test_job_succeeds_and_reports_runtime(manager: JobManager, tmp_path: Path) -> None:
    job_id = manager.submit(
        _spec(tmp_path), log_dir=tmp_path / "logs", max_runtime=None
    )

    status = _wait_until_terminal(manager, job_id)

    assert status["status"] == "succeeded"
    assert status["job_id"] == job_id
    assert status["runtime_seconds"] >= 0
    assert "log_tail" not in status  # only attached on failure
    assert "reason" not in status


def test_job_failure_captures_log_tail_and_reason(
    manager: JobManager, tmp_path: Path
) -> None:
    job_id = manager.submit(
        _spec(tmp_path, fail=True), log_dir=tmp_path / "logs", max_runtime=None
    )

    status = _wait_until_terminal(manager, job_id)

    assert status["status"] == "failed"
    assert "self-test failure" in status["log_tail"]
    assert status["reason"] == "exit code 1"


def test_job_times_out(manager: JobManager, tmp_path: Path) -> None:
    job_id = manager.submit(
        _spec(tmp_path, sleep=60), log_dir=tmp_path / "logs", max_runtime=1.0
    )

    status = _wait_until_terminal(manager, job_id)

    assert status["status"] == "timeout"
    assert status["finished_at"] is not None


def test_job_can_be_cancelled(manager: JobManager, tmp_path: Path) -> None:
    marker = tmp_path / "marker"
    job_id = manager.submit(
        _spec(tmp_path, sleep=60, marker=str(marker)),
        log_dir=tmp_path / "logs",
        max_runtime=None,
    )
    _wait_for(marker)

    status = manager.cancel(job_id)

    assert status["status"] == "cancelled"
    assert status["reason"] == "cancelled by request"
    assert manager.status(job_id)["status"] == "cancelled"


def test_cancel_after_the_job_finished_keeps_its_result(
    manager: JobManager, tmp_path: Path
) -> None:
    job_id = manager.submit(
        _spec(tmp_path), log_dir=tmp_path / "logs", max_runtime=None
    )
    _wait_until_terminal(manager, job_id)
    assert manager.cancel(job_id)["status"] == "succeeded"


def test_list_jobs_orders_by_submission(manager: JobManager, tmp_path: Path) -> None:
    first = manager.submit(_spec(tmp_path), log_dir=tmp_path / "logs", max_runtime=None)
    second = manager.submit(
        _spec(tmp_path / "second"), log_dir=tmp_path / "logs", max_runtime=None
    )
    _wait_until_terminal(manager, first)
    _wait_until_terminal(manager, second)

    assert [job["job_id"] for job in manager.list_jobs()] == [first, second]


def test_unknown_job_id_raises_without_doubled_quotes() -> None:
    manager = JobManager()
    with pytest.raises(KeyError) as info:
        manager.status("does-not-exist")
    assert info.value.args[0] == "Unknown job id: does-not-exist"
    with pytest.raises(KeyError):
        manager.cancel("does-not-exist")


# --- admission rules ------------------------------------------------------------
def test_unknown_entry_prefix_is_refused(manager: JobManager, tmp_path: Path) -> None:
    for entry in (
        "os:system",
        "subprocess:run",
        "exorad.tasks:LoadOptions",
        "exorad.mcp",
    ):
        spec = _spec(tmp_path)
        spec["entry"] = entry
        with pytest.raises(ValueError, match="entry"):
            manager.submit(spec, log_dir=tmp_path / "logs", max_runtime=None)
        with pytest.raises(ValueError, match="entry"):
            manager.run_sync(entry, {}, timeout=5)
    assert manager.list_jobs() == []


def test_an_extension_package_can_register_its_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jobs, "_ALLOWED_ENTRY_PREFIXES", ["exorad.mcp."])
    with pytest.raises(ValueError):
        jobs._check_entry("arielrad.mcp.pipelines:run")
    jobs.register_entry_prefix("arielrad.mcp.")
    assert jobs._check_entry("arielrad.mcp.pipelines:run")
    with pytest.raises(ValueError):
        jobs.register_entry_prefix("arielrad")


@pytest.mark.parametrize("bad", [0, -1, -0.5, float("nan")])
def test_non_positive_runtime_is_rejected(
    manager: JobManager, tmp_path: Path, bad: float
) -> None:
    with pytest.raises(ValueError, match="positive"):
        manager.submit(_spec(tmp_path), log_dir=tmp_path / "logs", max_runtime=bad)
    assert manager.list_jobs() == []


def test_runtime_is_clamped_to_the_server_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXORAD_MCP_MAX_RUNTIME", "120")
    assert jobs.effective_runtime(None) == 120
    assert jobs.effective_runtime(30) == 30
    assert jobs.effective_runtime(99999) == 120


def test_deadline_uses_the_clamped_runtime(
    manager: JobManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXORAD_MCP_MAX_RUNTIME", "2")
    job_id = manager.submit(
        _spec(tmp_path, sleep=60), log_dir=tmp_path / "logs", max_runtime=3600
    )
    status = _wait_until_terminal(manager, job_id)
    assert status["status"] == "timeout"
    assert status["runtime_seconds"] < 60


def test_cap_result_for_the_tool_layer(manager: JobManager, tmp_path: Path) -> None:
    exc = JobLimitError(1, ["abc"])
    result = jobs.refusal_result(exc, "standard")
    assert result["status"] == "refused"
    assert result["running_jobs"] == ["abc"]
    assert result["limit"] == 1
    assert result["pipeline"] == "standard"
    assert "EXORAD_MCP_MAX_JOBS" in result["error"]


# --- the child ---------------------------------------------------------------------
def test_job_child_is_its_own_group_leader_and_not_daemonic(
    manager: JobManager, tmp_path: Path
) -> None:
    marker = tmp_path / "marker"
    job_id = manager.submit(
        _spec(tmp_path, sleep=60, marker=str(marker)),
        log_dir=tmp_path / "logs",
        max_runtime=None,
    )
    _wait_for(marker)
    process = manager._jobs[job_id]._process
    assert process.daemon is False
    assert os.getpgid(process.pid) == process.pid != os.getpgid(0)


def test_job_log_captures_child_and_pool_output(
    manager: JobManager, tmp_path: Path
) -> None:
    """dup2 on fds 1/2: pool workers write into the same log as their parent."""
    job_id = manager.submit(
        _spec(tmp_path, pool=2, pool_print=True),
        log_dir=tmp_path / "logs",
        max_runtime=None,
    )
    status = _wait_until_terminal(manager, job_id)
    assert status["status"] == "succeeded", status
    log = (tmp_path / "logs" / f"{job_id}.log").read_text(encoding="utf-8")
    assert "self-test entry running" in log
    assert log.count("pool worker says hello") == 2


def test_job_child_stdout_never_reaches_parent_stdout(tmp_path: Path) -> None:
    """The job's prints go to its log; a parent's stdout (JSON-RPC) stays clean."""
    import subprocess

    code = (
        "import sys\n"
        "from exorad.mcp.jobs import JobManager\n"
        "if __name__ == '__main__':\n"
        "    m = JobManager()\n"
        f"    jid = m.submit({_spec(tmp_path)!r}, "
        f"log_dir={str(tmp_path / 'logs')!r}, max_runtime=None)\n"
        "    m.wait(jid, 120)\n"
        "    sys.stderr.write(m.status(jid)['status'])\n"
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
    assert proc.stderr.endswith("succeeded")


def test_job_status_redacts_the_log_tail_and_shows_display_paths(
    manager: JobManager, tmp_path: Path
) -> None:
    job_id = manager.submit(
        _spec(tmp_path, fail=True),
        log_dir=tmp_path / "mcp-work" / "logs",
        max_runtime=None,
    )
    status = _wait_until_terminal(manager, job_id)
    work = str(tmp_path / "mcp-work")
    assert work not in status["log_file"]
    assert work not in status["log_tail"]
    assert "work:" in status["log_file"]


def test_progress_counts_started_and_finished_observations(
    manager: JobManager, tmp_path: Path
) -> None:
    """``targets_done`` is finished observing, not the end-only ``saved`` lines."""
    job_id = manager.submit(
        _spec(tmp_path), log_dir=tmp_path / "logs", max_runtime=None
    )
    _wait_until_terminal(manager, job_id)
    log = tmp_path / "logs" / f"{job_id}.log"
    with log.open("a", encoding="utf-8") as handle:
        handle.write(
            "exorad - INFO - observing A\nexorad - INFO - observing B\n"
            "exorad - INFO - observing C\nexorad - INFO - target A observed\n"
            "exorad - WARNING - target B skipped. Please check for previous error\n"
            "exorad - INFO - target A saved\n"
        )
    status = manager.status(job_id)
    assert status["targets_started"] == 3
    assert status["targets_done"] == 1  # only A finished successfully


def test_log_tail_redacts_interpreter_and_home_paths(
    manager: JobManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import site
    import sysconfig

    home = tmp_path / "fakehome"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    job_id = manager.submit(
        _spec(tmp_path, fail=True), log_dir=tmp_path / "logs", max_runtime=None
    )
    _wait_until_terminal(manager, job_id)
    site_dir = sysconfig.get_paths()["purelib"]
    log = tmp_path / "logs" / f"{job_id}.log"
    with log.open("a", encoding="utf-8") as handle:
        handle.write(
            f'File "{site_dir}/astropy/table.py", line 3\n'
            f'File "{sys.prefix}/lib/x.py", line 4\n'
            f'File "{home}/proj/mine.py", line 5\n'
        )
    tail = manager.status(job_id)["log_tail"]
    assert site_dir not in tail
    assert sys.prefix not in tail
    assert str(home) not in tail
    assert "<site-packages>/astropy/table.py" in tail
    assert "~/proj/mine.py" in tail
    assert site.getsitepackages()[0] not in tail


def test_submitted_at_never_follows_started_at(
    manager: JobManager, tmp_path: Path
) -> None:
    job_id = manager.submit(
        _spec(tmp_path), log_dir=tmp_path / "logs", max_runtime=None
    )
    status = manager.status(job_id)
    assert status["submitted_at"] <= status["started_at"]
    _wait_until_terminal(manager, job_id)


def test_run_sync_children_are_capped_by_the_job_limit(
    manager: JobManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    monkeypatch.setenv("EXORAD_MCP_MAX_JOBS", "1")
    box: dict[str, object] = {}

    def slow() -> None:
        box["result"] = manager.run_sync(
            "exorad.mcp.jobs:_selftest_sync", {"sleep": 8}, timeout=60
        )

    thread = threading.Thread(target=slow)
    thread.start()
    deadline = time.time() + 60
    while not manager._sync and time.time() < deadline:
        time.sleep(0.05)
    assert manager._sync
    try:
        with pytest.raises(jobs.SyncLimitError, match="EXORAD_MCP_MAX_JOBS"):
            manager.run_sync("exorad.mcp.jobs:_selftest_sync", {}, timeout=60)
        # the sync children do not take a background-job slot: run_pipeline
        # cannot be starved by a user's own validation / plot calls
        job_id = manager.submit(
            _spec(tmp_path), log_dir=tmp_path / "logs", max_runtime=None
        )
        _wait_until_terminal(manager, job_id)
    finally:
        thread.join(90)
    assert box["result"]["answer"] == 1
    # the slot is free again
    assert manager.run_sync("exorad.mcp.jobs:_selftest_sync", {}, timeout=60)


def test_child_inherits_the_environment_set_in_the_server(
    manager: JobManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The variables must be in the child BEFORE it imports numpy and exorad.

    ``at_import`` is the environment as the child inherited it (recorded when
    ``exorad.mcp.jobs`` was imported), before ``_worker`` re-asserts anything.
    """
    for name in jobs.CHILD_ENV_FORCED:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("MPLBACKEND", raising=False)
    jobs.apply_child_env()  # what server.main() does
    report = tmp_path / "env.json"
    job_id = manager.submit(
        _spec(tmp_path, report_env=str(report)),
        log_dir=tmp_path / "logs",
        max_runtime=None,
    )
    assert _wait_until_terminal(manager, job_id)["status"] == "succeeded"
    seen = json.loads(report.read_text(encoding="utf-8"))
    assert seen["at_import"]["EXORAD_NO_VERSION_CHECK"] == "1"
    assert seen["at_import"]["MPLBACKEND"] == "Agg"
    assert seen["at_import"]["OMP_NUM_THREADS"] == "1"
    assert seen["now"] == seen["at_import"]


def test_worker_reasserts_the_environment_for_the_inline_paths(
    manager: JobManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A server not started through main() (library use) still gets a safe child."""
    for name in (*jobs.CHILD_ENV_FORCED, "MPLBACKEND"):
        monkeypatch.delenv(name, raising=False)
    report = tmp_path / "env.json"
    job_id = manager.submit(
        _spec(tmp_path, report_env=str(report)),
        log_dir=tmp_path / "logs",
        max_runtime=None,
    )
    assert _wait_until_terminal(manager, job_id)["status"] == "succeeded"
    seen = json.loads(report.read_text(encoding="utf-8"))
    assert seen["at_import"]["EXORAD_NO_VERSION_CHECK"] is None
    assert seen["now"]["EXORAD_NO_VERSION_CHECK"] == "1"
    assert seen["now"]["MPLBACKEND"] == "Agg"


def test_job_child_blocks_the_network(manager: JobManager, tmp_path: Path) -> None:
    job_id = manager.submit(
        _spec(tmp_path, connect=True), log_dir=tmp_path / "logs", max_runtime=None
    )
    assert _wait_until_terminal(manager, job_id)["status"] == "succeeded"
    log = (tmp_path / "logs" / f"{job_id}.log").read_text(encoding="utf-8")
    assert "connect failed: NetworkBlockedError" in log
    assert "network access is disabled in the ExoRad MCP" in log


def test_job_with_two_workers_runs(manager: JobManager, tmp_path: Path) -> None:
    """A non-daemonic child can start a process pool (n_thread > 1)."""
    marker = tmp_path / "marker"
    job_id = manager.submit(
        _spec(tmp_path, pool=2, marker=str(marker)),
        log_dir=tmp_path / "logs",
        max_runtime=None,
    )
    assert _wait_until_terminal(manager, job_id)["status"] == "succeeded"
    pids = [int(p) for p in (tmp_path / "marker.pids").read_text().split()]
    assert len(pids) == 2


# --- run_sync --------------------------------------------------------------------
def test_run_sync_returns_the_entry_result_from_a_child(
    manager: JobManager, tmp_path: Path
) -> None:
    result = manager.run_sync(
        "exorad.mcp.jobs:_selftest_sync", {"value": 41}, timeout=120
    )
    assert result["answer"] == 42
    assert result["pid"] != os.getpid()
    assert result["group_leader"] is True
    assert result["blocked"] is True
    assert result["env"]["EXORAD_NO_VERSION_CHECK"] == "1"


def test_run_sync_timeout_kills_the_child(manager: JobManager) -> None:
    started = time.time()
    with pytest.raises(TimeoutError, match="did not finish within"):
        manager.run_sync("exorad.mcp.jobs:_selftest_sync", {"sleep": 60}, timeout=15)
    assert time.time() - started < 50
    assert manager._sync == {}


def test_run_sync_failure_carries_the_redacted_log_tail(manager: JobManager) -> None:
    with pytest.raises(RuntimeError, match="sync self-test failure"):
        manager.run_sync("exorad.mcp.jobs:_selftest_sync", {"fail": True}, timeout=120)


def test_run_sync_rejects_a_non_positive_timeout(manager: JobManager) -> None:
    with pytest.raises(ValueError, match="timeout"):
        manager.run_sync("exorad.mcp.jobs:_selftest_sync", {}, timeout=0)


def test_run_sync_inline_backend_runs_in_process(
    manager: JobManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXORAD_MCP_EXEC_BACKEND", "inline")
    result = manager.run_sync("exorad.mcp.jobs:_selftest_sync", {"value": 1}, timeout=5)
    assert result["answer"] == 2
    assert result["pid"] == os.getpid()
