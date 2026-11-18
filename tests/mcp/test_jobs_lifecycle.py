"""Lifecycle tests for the MCP job manager: watchdog, cap, process groups, shutdown.

Timeouts are generous on purpose: a spawned child imports numpy, h5py, astropy and
matplotlib before it runs a line of its own code, and the suite is run under load.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING

import pytest

from exorad.mcp import jobs
from exorad.mcp.jobs import (
    DEFAULT_MAX_JOBS,
    JobLimitError,
    JobManager,
    max_jobs_from_env,
)

if TYPE_CHECKING:
    from pathlib import Path

ENTRY = "exorad.mcp.jobs:_SelfTestEntry"
START_TIMEOUT = 180.0


@pytest.fixture(autouse=True)
def _process_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXORAD_MCP_EXEC_BACKEND", "process")


def _spec(tmp_path: Path, **selftest: object) -> dict[str, object]:
    return {
        "entry": ENTRY,
        "pipeline": "selftest",
        "output": str(tmp_path / "out.h5"),
        "selftest": selftest,
    }


def _wait_until_terminal(manager: JobManager, job_id: str, timeout: float = 120.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = manager.status(job_id)
        if status["status"] != "running":
            return status
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} never finished")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # a zombie still answers kill(0); treat it as dead
    state = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return bool(state) and not state.startswith("Z")


def _wait_dead(pid: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while _pid_alive(pid) and time.time() < deadline:
        time.sleep(0.2)
    return not _pid_alive(pid)


def _wait_file(path: Path, timeout: float = START_TIMEOUT) -> None:
    deadline = time.time() + timeout
    while not path.exists() and time.time() < deadline:
        time.sleep(0.2)
    assert path.exists(), f"{path} never appeared"


def _kill_all(pids: list[int]) -> None:
    for pid in pids:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)


# --- deadline, cap, reaping -------------------------------------------------------
def test_deadline_enforced_without_polling(tmp_path: Path) -> None:
    manager = JobManager()
    try:
        job_id = manager.submit(
            _spec(tmp_path, sleep=60), log_dir=tmp_path / "logs", max_runtime=1.0
        )
        job = manager._jobs[job_id]
        pid = job._process.pid

        # Never call status()/list_jobs(): the watchdog alone must end the job.
        deadline = time.time() + 60
        while job.status == "running" and time.time() < deadline:
            time.sleep(0.2)

        assert job.status == "timeout"
        assert _wait_dead(pid)
        status = manager.status(job_id)
        assert status["status"] == "timeout"
        assert "max_runtime" in status["reason"]
        assert manager.list_jobs()[0]["reason"] == status["reason"]
    finally:
        manager.shutdown()


def test_concurrency_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXORAD_MCP_MAX_JOBS", "1")
    manager = JobManager()
    first = manager.submit(
        _spec(tmp_path, sleep=60), log_dir=tmp_path / "logs", max_runtime=None
    )
    try:
        with pytest.raises(JobLimitError) as excinfo:
            manager.submit(
                _spec(tmp_path / "other"), log_dir=tmp_path / "logs", max_runtime=None
            )
        message = str(excinfo.value)
        assert "EXORAD_MCP_MAX_JOBS" in message
        assert first in message
        assert jobs.refusal_result(excinfo.value, "standard")["running_jobs"] == [first]
        manager.cancel(first)
        second = manager.submit(
            _spec(tmp_path), log_dir=tmp_path / "logs", max_runtime=None
        )
        _wait_until_terminal(manager, second)
    finally:
        manager.shutdown()


@pytest.mark.parametrize("value", ["", "0", "-3", "abc"])
def test_max_jobs_invalid_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("EXORAD_MCP_MAX_JOBS", value)
    assert max_jobs_from_env() == DEFAULT_MAX_JOBS
    monkeypatch.setenv("EXORAD_MCP_MAX_JOBS", "5")
    assert max_jobs_from_env() == 5


def test_finished_jobs_stay_readable_and_are_reaped(tmp_path: Path) -> None:
    manager = JobManager()
    try:
        job_id = manager.submit(
            _spec(tmp_path, fail=True), log_dir=tmp_path / "logs", max_runtime=None
        )
        _wait_until_terminal(manager, job_id)
        job = manager._jobs[job_id]
        assert job._process is None  # handle released: no zombie
        again = manager.status(job_id)
        assert again["status"] == "failed"
        assert again["reason"] == "exit code 1"
        assert "self-test failure" in again["log_tail"]
        assert job.returncode == 1
    finally:
        manager.shutdown()


# --- process groups -----------------------------------------------------------------
def _start_pool_job(
    manager: JobManager, tmp_path: Path, **extra: object
) -> tuple[str, list[int]]:
    marker = tmp_path / "marker"
    job_id = manager.submit(
        _spec(tmp_path, pool=2, sleep=300, marker=str(marker), **extra),
        log_dir=tmp_path / "logs",
        max_runtime=None,
    )
    _wait_file(marker)
    pool = [int(p) for p in (tmp_path / "marker.pids").read_text().split()]
    assert len(pool) == 2
    return job_id, pool


def test_cancel_kills_pool_workers(tmp_path: Path) -> None:
    manager = JobManager()
    pool: list[int] = []
    try:
        job_id, pool = _start_pool_job(manager, tmp_path)
        child = manager._jobs[job_id]._process.pid
        assert all(_pid_alive(p) for p in pool)

        assert manager.cancel(job_id)["status"] == "cancelled"

        assert _wait_dead(child)
        assert all(_wait_dead(p) for p in pool), "pool workers outlived the job"
    finally:
        _kill_all(pool)
        manager.shutdown()


def test_timeout_kills_pool_workers(tmp_path: Path) -> None:
    manager = JobManager()
    pool: list[int] = []
    try:
        marker = tmp_path / "marker"
        job_id = manager.submit(
            _spec(tmp_path, pool=2, sleep=300, marker=str(marker)),
            log_dir=tmp_path / "logs",
            max_runtime=60,
        )
        _wait_file(marker)
        pool = [int(p) for p in (tmp_path / "marker.pids").read_text().split()]
        manager._jobs[job_id].deadline = time.time() - 1  # expire it now
        assert _wait_until_terminal(manager, job_id)["status"] == "timeout"
        assert all(_wait_dead(p) for p in pool), "pool workers outlived the timeout"
    finally:
        _kill_all(pool)
        manager.shutdown()


def test_output_size_watchdog_kills_job(tmp_path: Path) -> None:
    manager = JobManager()
    pool: list[int] = []
    try:
        marker = tmp_path / "marker"
        spec = _spec(
            tmp_path, pool=2, sleep=300, marker=str(marker), write_bytes=200_000
        )
        spec["max_output_bytes"] = 100_000
        job_id = manager.submit(spec, log_dir=tmp_path / "logs", max_runtime=None)

        status = _wait_until_terminal(
            manager, job_id
        )  # the watchdog, no polling needed

        assert status["status"] == "failed"
        assert status["reason"] == "output exceeded the size limit"
        pool = (
            [int(p) for p in (tmp_path / "marker.pids").read_text().split()]
            if (tmp_path / "marker.pids").exists()
            else []
        )
        assert all(_wait_dead(p) for p in pool)
    finally:
        _kill_all(pool)
        manager.shutdown()


def test_output_limit_comes_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXORAD_MCP_MAX_OUTPUT_MB", "1")
    assert jobs._output_limit_bytes({}) == 1_048_576
    assert jobs._output_limit_bytes({"max_output_bytes": 5}) == 5
    manager = JobManager()
    try:
        job_id = manager.submit(
            _spec(tmp_path, sleep=300, write_bytes=2_000_000),
            log_dir=tmp_path / "logs",
            max_runtime=None,
        )
        status = _wait_until_terminal(manager, job_id)
        assert status["reason"] == "output exceeded the size limit"
    finally:
        manager.shutdown()


def test_an_output_under_the_limit_is_left_alone(tmp_path: Path) -> None:
    manager = JobManager()
    try:
        spec = _spec(tmp_path, write_bytes=1000)
        spec["max_output_bytes"] = 100_000
        job_id = manager.submit(spec, log_dir=tmp_path / "logs", max_runtime=None)
        assert _wait_until_terminal(manager, job_id)["status"] == "succeeded"
    finally:
        manager.shutdown()


# --- hooks --------------------------------------------------------------------------
def test_install_hooks_flags_are_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Off the main thread only atexit registers; the signals wait for the main thread."""
    registered: list[object] = []
    handlers: dict[int, object] = {}
    monkeypatch.setattr(jobs.atexit, "register", lambda f: registered.append(f))
    monkeypatch.setattr(jobs.signal, "getsignal", lambda sig: signal.SIG_DFL)
    monkeypatch.setattr(
        jobs.signal, "signal", lambda sig, handler: handlers.__setitem__(sig, handler)
    )
    manager = JobManager()

    worker = threading.Thread(target=manager.install_hooks)
    worker.start()
    worker.join()
    assert len(registered) == 1
    assert handlers == {}

    manager.install_hooks()  # main thread
    assert len(registered) == 1  # atexit is not registered twice
    assert set(handlers) == {signal.SIGTERM, signal.SIGINT}

    manager.install_hooks()  # idempotent
    assert len(registered) == 1
    assert len(handlers) == 2


def test_signal_handler_shuts_down_then_chains(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = JobManager()
    calls: list[str] = []
    monkeypatch.setattr(manager, "shutdown", lambda: calls.append("shutdown"))

    def previous(signum: int, frame: object) -> None:
        calls.append("previous")

    manager._make_handler(previous)(signal.SIGTERM, None)
    assert calls == ["shutdown", "previous"]
    with pytest.raises(KeyboardInterrupt):
        manager._make_handler(signal.SIG_DFL)(signal.SIGINT, None)


def test_shutdown_is_idempotent_and_marks_jobs(tmp_path: Path) -> None:
    manager = JobManager()
    job_id = manager.submit(
        _spec(tmp_path, sleep=300), log_dir=tmp_path / "logs", max_runtime=None
    )
    pid = manager._jobs[job_id].pid
    manager.shutdown()
    manager.shutdown()
    assert manager.status(job_id)["status"] == "cancelled"
    assert manager.status(job_id)["reason"] == "server shut down"
    assert _wait_dead(pid)


def test_shutdown_kills_a_run_sync_child(tmp_path: Path) -> None:
    manager = JobManager()
    errors: list[BaseException] = []

    def call() -> None:
        try:
            manager.run_sync(
                "exorad.mcp.jobs:_selftest_sync", {"sleep": 300}, timeout=600
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=call)
    thread.start()
    deadline = time.time() + START_TIMEOUT
    while not manager._sync and time.time() < deadline:
        time.sleep(0.1)
    (pid,) = [p.pid for p in manager._sync.values()]
    manager.shutdown()
    thread.join(timeout=60)
    assert not thread.is_alive()
    assert errors  # the call fails once its child is killed
    assert _wait_dead(pid)


# --- helper process: the manager lives in its own process -----------------------------
_HELPER = """
import sys, threading, time
from pathlib import Path
from exorad.mcp.jobs import JobManager

if __name__ == "__main__":
    work = Path(sys.argv[1]); mode = sys.argv[2]
    manager = JobManager()
    spec = {"entry": "exorad.mcp.jobs:_SelfTestEntry", "pipeline": "selftest",
            "output": str(work / "o.h5"),
            "selftest": {"sleep": 300, "pool": 2, "marker": str(work / "marker")}}
    # mcp 2.x runs sync tools in worker threads: the first submit is off-thread,
    # so only the main-thread install (server.main()) can register the handlers.
    worker = threading.Thread(
        target=lambda: manager.submit(spec, log_dir=work / "logs", max_runtime=None)
    )
    worker.start(); worker.join()
    if mode == "sigterm":
        manager.install_hooks()
    job = next(iter(manager._jobs.values()))
    (work / "pid").write_text(str(job._process.pid))
    while not (work / "marker").exists():
        time.sleep(0.1)
    (work / "ready").write_text("1")
    if mode in ("sigterm", "sigkill"):
        time.sleep(300)
"""


def _run_helper(tmp_path: Path, mode: str) -> tuple[subprocess.Popen, int, list[int]]:
    script = tmp_path / "helper.py"
    script.write_text(_HELPER, encoding="utf-8")
    env = os.environ.copy()
    env["EXORAD_MCP_EXEC_BACKEND"] = "process"
    proc = subprocess.Popen([sys.executable, str(script), str(tmp_path), mode], env=env)
    _wait_file(tmp_path / "ready")
    pool = [int(p) for p in (tmp_path / "marker.pids").read_text().split()]
    assert len(pool) == 2
    return proc, int((tmp_path / "pid").read_text()), pool


def test_children_terminated_on_normal_exit(tmp_path: Path) -> None:
    proc, child, pool = _run_helper(tmp_path, "exit")
    try:
        started = time.time()
        proc.wait(timeout=60)
        # interpreter exit must not block until the 300 s job ends
        assert time.time() - started < 40
        assert _wait_dead(child)
        assert all(_wait_dead(p) for p in pool)
    finally:
        _kill_all([child, *pool])


def test_children_terminated_on_sigterm(tmp_path: Path) -> None:
    proc, child, pool = _run_helper(tmp_path, "sigterm")
    try:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=60)
        assert _wait_dead(child)
        assert all(_wait_dead(p) for p in pool)
    finally:
        _kill_all([child, *pool])


def test_parent_sigkill_child_exits(tmp_path: Path) -> None:
    """SIGKILL of the server: the child kills its GROUP, so the pool workers die too.

    Measured on the first port: with ``os._exit(1)`` in ``_watch_parent`` the child
    exited but both ``ProcessPoolExecutor`` workers stayed alive for minutes.
    """
    proc, child, pool = _run_helper(tmp_path, "sigkill")
    try:
        assert all(_pid_alive(p) for p in (child, *pool))
        proc.kill()
        proc.wait(timeout=30)
        assert _wait_dead(child, timeout=60), "job child outlived a SIGKILLed server"
        assert all(_wait_dead(p, timeout=60) for p in pool), (
            "pool workers outlived a SIGKILLed server (orphan leak)"
        )
    finally:
        _kill_all([child, *pool])


def test_watch_parent_never_kills_a_group_it_does_not_lead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If setsid failed the group belongs to the server: only exit, never killpg it."""
    killed: list[tuple[int, int]] = []
    exits: list[int] = []
    monkeypatch.setattr(jobs.os, "getpgid", lambda pid: os.getpid() + 1)
    monkeypatch.setattr(jobs.os, "killpg", lambda pg, sig: killed.append((pg, sig)))
    monkeypatch.setattr(jobs.os, "_exit", lambda code: exits.append(code))
    jobs._kill_own_group_then_exit()
    assert killed == []
    assert exits == [1]
    monkeypatch.setattr(jobs.os, "getpgid", lambda pid: os.getpid())
    jobs._kill_own_group_then_exit()
    assert killed == [(os.getpid(), signal.SIGKILL)]
