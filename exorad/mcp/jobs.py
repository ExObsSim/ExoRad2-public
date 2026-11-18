"""Background job manager for MCP pipeline runs.

An ExoRad run can take minutes to hours. Running it in-process would block the
MCP event loop, could not be cancelled, and would leak process-global state
(``PassVal``, root-logger levels, ``pyplot``) into the server. Instead each run
happens in a separate *spawned* process that this module supervises: it can be
waited on with a timeout, cancelled, and its log inspected.

The manager is a process-local singleton (:data:`JOBS`); jobs do not survive a
server restart.

A job is described by a ``spec`` dict: ``{"entry": "pkg.mod:func", "pipeline":
str, "output": str, ...entry-specific keys}``. The child imports ``pkg.mod`` and
calls ``func(spec)``. Only entries whose module starts with an allowed prefix
(``exorad.mcp.``; an extension package registers its own with
:func:`register_entry_prefix`) are accepted, so a bug elsewhere cannot turn the
job runner into an import-anything tool.

Lifecycle guarantees
--------------------
* Each child is its own session and process-group leader (``os.setsid``) and is
  deliberately *not* daemonic: ``ObserveTargetlist`` starts a
  ``ProcessPoolExecutor`` for ``n_thread > 1`` and a daemonic process may not have
  children. Every signal the manager sends goes to the whole GROUP
  (``os.killpg``), so the pool workers die with the child (cancel, timeout,
  shutdown). A plain ``terminate`` of the child alone would orphan them.
* Children never outlive the server. (a) An ``atexit`` hook terminates every
  running child before :mod:`multiprocessing`'s own exit hook would block joining
  it, (b) SIGTERM / SIGINT handlers do the same, escalating from SIGTERM to
  SIGKILL after a short grace period, then chain to the previous handler, and
  (c) each child watches its parent pid and, if the server is killed without any
  chance to clean up (SIGKILL), kills its own process GROUP. (A bare ``os._exit``
  there would leave the pool workers running: measured.) Both hooks are installed
  by :meth:`JobManager.install_hooks`, which ``server.main()`` calls on the main
  thread before serving.
* ``max_runtime`` is enforced by a watchdog thread, so a client need not poll; it
  is clamped to ``EXORAD_MCP_MAX_RUNTIME`` and must be positive.
* At most ``EXORAD_MCP_MAX_JOBS`` (default 2) jobs run at once. The one-shot
  children of :meth:`JobManager.run_sync` (deep validation, plots) have their own
  pool of the same size: more are refused with :class:`SyncLimitError`, and they
  never take a background-job slot, so they cannot starve ``run_pipeline``.
* The output file is watched: a job whose HDF5 exceeds ``EXORAD_MCP_MAX_OUTPUT_MB``
  (or ``spec["max_output_bytes"]``) is killed and recorded as ``failed``.
* Process-group kill is POSIX only. On Windows a child is stopped with
  ``terminate`` and its pool workers are not covered: execution is documented as
  unsupported there.
"""

from __future__ import annotations

import atexit
import contextlib
import importlib
import json
import multiprocessing as mp
import multiprocessing.util
import os
import re
import shutil
import signal
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from exorad.mcp.sandbox import (
    DEFAULT_MAX_JOBS,
    DEFAULT_MAX_OUTPUT_MB,
    DEFAULT_MAX_RUNTIME,
    ENV_EXEC_BACKEND,
    ENV_MAX_JOBS,
    ENV_MAX_OUTPUT_MB,
    ENV_MAX_RUNTIME,
    MAX_SECONDS,
    Sandbox,
    _float_env,
    _int_env,
    redact_runtime,
)

# multiprocessing registers its own atexit hook (it JOINS every live child, which
# would block until the job ends) when ``multiprocessing.util`` is first imported.
# atexit runs last-in first-out, so that module must be imported BEFORE our hook is
# registered (``install_hooks``) for ours to run first. Importing it here, at module
# import, guarantees the order whatever else the process imported.
_ = multiprocessing.util

# ExoRad imports h5py/matplotlib/astropy at import time and macOS has no
# fork-safe default; only "spawn" is safe here.
_MP = mp.get_context("spawn")

LOG_TAIL_CHARS = 4000
_LOG_SCAN_BYTES = 2_000_000

#: How long a validation or plot call waits for a free one-shot child before it
#: reports ``busy`` (bounded: a client's tool call must return in reasonable time).
SYNC_SLOT_WAIT_SECONDS = 20.0
_SLOT_POLL_SECONDS = 0.1

_KILL_GRACE_SECONDS = 3.0
_WATCHDOG_INTERVAL = 0.25
_PARENT_POLL_SECONDS = 1.0

_STATUS_RUNNING = "running"
_STATUS_SUCCEEDED = "succeeded"
_STATUS_FAILED = "failed"
_STATUS_CANCELLED = "cancelled"
_STATUS_TIMEOUT = "timeout"

_TERMINAL = {_STATUS_SUCCEEDED, _STATUS_FAILED, _STATUS_CANCELLED, _STATUS_TIMEOUT}

_SIGKILL = getattr(signal, "SIGKILL", signal.SIGTERM)

#: Environment every child must see BEFORE it imports numpy/matplotlib/exorad.
#: ``server.main()`` puts it into the server's ``os.environ`` (a spawned child
#: inherits it at process start); ``_worker`` re-asserts it for the in-process
#: paths. ``MPLBACKEND`` is only a default, the rest are forced.
CHILD_ENV_FORCED = {
    "EXORAD_NO_VERSION_CHECK": "1",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}
CHILD_ENV_DEFAULTS = {"MPLBACKEND": "Agg"}

# What the environment looked like when this module was imported. In a spawned
# child that is what the process inherited, before ``_worker`` re-asserts it.
_ENV_AT_IMPORT = {
    name: os.environ.get(name) for name in (*CHILD_ENV_FORCED, *CHILD_ENV_DEFAULTS)
}

_ALLOWED_ENTRY_PREFIXES: list[str] = ["exorad.mcp."]


def apply_child_env(environ: Any = None) -> None:
    """Set the environment a job child needs (see :data:`CHILD_ENV_FORCED`)."""
    environ = os.environ if environ is None else environ
    for name, value in CHILD_ENV_FORCED.items():
        environ[name] = value
    for name, value in CHILD_ENV_DEFAULTS.items():
        environ.setdefault(name, value)


def register_entry_prefix(prefix: str) -> None:
    """Allow job entries whose module starts with ``prefix`` (e.g. ``arielrad.mcp.``).

    A prefix must end with ``.``, be made of at least two dotted identifiers (a
    package and a sub-package, like ``arielrad.mcp.``), and its top-level package
    must not be a standard-library module (``os.``, ``subprocess.``, ``sys.`` ...).

    This is server-side Python state: it is set by the extension package's own
    code at import time, never from a client request, and a job spec only ever
    names a constant ``module:function`` entry that the parent checks against the
    list BEFORE spawning. It is NOT an entry-point injection hole: a client
    cannot add a prefix or choose a module. The spawned child re-registers the
    parent's tuple (:func:`registered_entry_prefixes`) because it re-imports this
    module with only the default list.
    """
    if not isinstance(prefix, str) or not prefix.endswith("."):
        raise ValueError("an entry prefix must end with '.'")
    parts = prefix[:-1].split(".")
    if len(parts) < 2 or not all(part.isidentifier() for part in parts):
        raise ValueError(
            f"an entry prefix must name a package and a sub-package such as "
            f"'arielrad.mcp.', got {prefix!r}"
        )
    if parts[0] in sys.stdlib_module_names:
        raise ValueError(
            f"an entry prefix may not be a standard-library module: {prefix!r}"
        )
    if prefix not in _ALLOWED_ENTRY_PREFIXES:
        _ALLOWED_ENTRY_PREFIXES.append(prefix)


def registered_entry_prefixes() -> tuple[str, ...]:
    """Return the allowed entry prefixes (what a job child must be given)."""
    return tuple(_ALLOWED_ENTRY_PREFIXES)


def _check_entry(entry: object) -> str:
    """Return ``entry`` if it is ``module:function`` under an allowed prefix."""
    if not isinstance(entry, str) or entry.count(":") != 1:
        raise ValueError(
            f"A job entry must be a 'module:function' string, got {entry!r}."
        )
    module, func = entry.split(":")
    if not module or not func or not func.isidentifier():
        raise ValueError(
            f"A job entry must be a 'module:function' string, got {entry!r}."
        )
    if not module.startswith(tuple(_ALLOWED_ENTRY_PREFIXES)):
        raise ValueError(
            f"Job entry {entry!r} is refused: its module must start with one of "
            f"{', '.join(_ALLOWED_ENTRY_PREFIXES)}"
        )
    return entry


def _resolve_entry(entry: str) -> Any:
    module, func = _check_entry(entry).split(":")
    return getattr(importlib.import_module(module), func)


class JobLimitError(RuntimeError):
    """Raised by :meth:`JobManager.submit` when too many jobs are running."""

    def __init__(self, limit: int, running: list[str]) -> None:
        self.limit = limit
        self.running = running
        super().__init__(
            f"Too many concurrent jobs: {len(running)} running "
            f"(limit {limit}, set by {ENV_MAX_JOBS}). Running job ids: "
            f"{', '.join(running)}. Wait for one to finish with get_job_status, "
            f"cancel one with cancel_job, or raise the limit via {ENV_MAX_JOBS} "
            "when starting the server."
        )


class SyncLimitError(RuntimeError):
    """Raised by :meth:`JobManager.run_sync` when too many one-shot children run."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(
            f"Too many concurrent validation / plot children: {limit} already "
            f"running (limit {limit}, set by {ENV_MAX_JOBS}). Wait a moment and "
            f"retry, or raise the limit via {ENV_MAX_JOBS} when starting the "
            "server. Background pipeline jobs are counted separately and are not "
            "affected."
        )


class OutputInUseError(RuntimeError):
    """Raised by :meth:`JobManager.submit` when a running job owns the output.

    Two jobs must never write the same output file, nor share an output
    directory: the library copies the payload and the target list next to the
    output and, with ``replace``, DELETES an existing output first, which would
    destroy the file another job is writing. ``overwrite`` therefore never
    applies to a running job's files.
    """

    def __init__(self, job_id: str, what: str) -> None:
        self.job_id = job_id
        self.what = what  # "output" or "directory"
        shared = (
            "is the output file of"
            if what == "output"
            else "is in the output directory of"
        )
        super().__init__(
            f"The requested output {shared} running job {job_id}; two runs must "
            "not share an output file or directory, whatever `overwrite` says. "
            f"Wait for job {job_id} (get_job_status), cancel it (cancel_job), or "
            "choose another output path in another directory."
        )


def refusal_result(
    exc: JobLimitError | OutputInUseError, pipeline: str
) -> dict[str, Any]:
    """The tool result for a refused submission (a return value, not an error).

    ``status`` is ``"refused"`` and nothing was started. A full job table adds
    ``limit`` and ``running_jobs``; an output that a running job owns adds
    ``reason="output_in_use"`` and ``conflicting_job``.
    """
    if isinstance(exc, OutputInUseError):
        return {
            "status": "refused",
            "reason": "output_in_use",
            "error": str(exc),
            "conflicting_job": exc.job_id,
            "running_jobs": [exc.job_id],
            "pipeline": pipeline,
        }
    return {
        "status": "refused",
        "error": str(exc),
        "limit": exc.limit,
        "running_jobs": list(exc.running),
        "pipeline": pipeline,
    }


def max_jobs_from_env() -> int:
    """Concurrent-job cap from ``EXORAD_MCP_MAX_JOBS`` (0 / invalid -> default)."""
    return _int_env(ENV_MAX_JOBS, DEFAULT_MAX_JOBS)


def effective_runtime(requested: float | None) -> float:
    """Clamp a requested runtime to the server cap ``EXORAD_MCP_MAX_RUNTIME``.

    ``None`` means "the cap". A request that is not strictly positive is refused.
    """
    cap = _float_env(ENV_MAX_RUNTIME, DEFAULT_MAX_RUNTIME)
    if requested is None:
        return cap
    if not requested > 0:
        raise ValueError(f"max_runtime must be positive, got {requested!r}.")
    return min(float(requested), cap)


# -- process-group helpers -------------------------------------------------
def _signal_group(process: Any, sig: int) -> None:
    """Send ``sig`` to the child's whole process group (or to the child alone).

    The child becomes a group leader only once ``_worker`` has run ``setsid``; a
    signal sent earlier (while it is still importing) goes to the child alone,
    which has no pool workers yet.
    """
    try:
        pid = process.pid
    except ValueError:  # closed
        return
    if pid is None:
        return
    try:
        if hasattr(os, "killpg") and os.getpgid(pid) == pid:
            os.killpg(pid, sig)
            return
    except OSError:
        pass
    with contextlib.suppress(OSError):
        os.kill(pid, sig)


def _sweep_group(pid: int | None) -> None:
    """SIGKILL whatever is still alive in the group led by ``pid`` (if any)."""
    if pid is None or not hasattr(os, "killpg"):
        return
    try:
        os.killpg(pid, 0)
    except OSError:
        return
    with contextlib.suppress(OSError):
        os.killpg(pid, _SIGKILL)


def _terminate(process: Any) -> None:
    """Ask the child's group to stop, kill it after a grace period, sweep it."""
    try:
        pid = process.pid
        alive = process.is_alive()
    except ValueError:
        return
    if alive:
        _signal_group(process, signal.SIGTERM)
        process.join(_KILL_GRACE_SECONDS)
        if process.is_alive():
            _signal_group(process, _SIGKILL)
            process.join(5)
    _sweep_group(pid)


def _watch_parent(parent_pid: int) -> None:
    """Kill this child's whole process group if the server dies (e.g. SIGKILL).

    The child is its own group leader after ``setsid``, so the group is exactly
    the child and its pool workers. ``os._exit`` alone would leave the workers
    running (measured), so the group is killed first. If the child is NOT a group
    leader (``setsid`` failed) the group is somebody else's and is never touched.
    """
    while True:
        time.sleep(_PARENT_POLL_SECONDS)
        if os.getppid() != parent_pid:
            _kill_own_group_then_exit()


def _kill_own_group_then_exit() -> None:
    if hasattr(os, "killpg"):
        with contextlib.suppress(OSError):
            if os.getpgid(0) == os.getpid():
                os.killpg(os.getpid(), _SIGKILL)
    os._exit(1)


def _become_group_leader() -> None:
    if hasattr(os, "setsid"):
        with contextlib.suppress(OSError):
            os.setsid()


def _redirect_output(log_path: str) -> Any:
    """Point fds 1 and 2 (and ``sys.stdout/stderr``) at the job log.

    ``dup2`` on the descriptors, not ``contextlib.redirect_*``: pool workers and
    anything else the child starts inherit the log, and nothing they print can
    reach the server's stdout (the JSON-RPC channel).
    """
    import sys

    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.flush()
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)
    handle = open(1, "w", encoding="utf-8", buffering=1, closefd=False)  # noqa: SIM115
    sys.stdout = handle
    sys.stderr = handle
    return handle


def _route_exorad_logging(handle: Any) -> None:
    """Rebind the ExoRad console handler to the log (it bound stderr at import)."""
    try:
        from exorad.log import logger as exorad_logger
    except ImportError:
        return
    exorad_logger.ch.setStream(handle)


def _worker(
    spec: dict[str, Any],
    log_path: str,
    parent_pid: int | None = None,
    result_path: str | None = None,
    prefixes: tuple[str, ...] = (),
) -> None:
    """Subprocess entry point: run one entry, logging stdout/stderr to a file.

    ``prefixes`` is the parent's registered entry-prefix tuple: the spawned child
    re-imports this module with the default list only, so it re-registers them
    (each one is validated again by :func:`register_entry_prefix`).
    """
    # Nothing before the redirect: from here on every line this process (and the
    # pool workers it starts) prints belongs to the job log, never to the server's
    # stdout, which is the JSON-RPC channel. (What the interpreter imported while
    # unpickling this call, the ExoRad package included, precedes it and cannot be
    # redirected from Python.)
    handle = _redirect_output(log_path)
    import traceback

    _become_group_leader()
    if parent_pid is not None:
        threading.Thread(target=_watch_parent, args=(parent_pid,), daemon=True).start()
    try:
        apply_child_env()
        from exorad.mcp import netguard

        netguard.block_network()
        _route_exorad_logging(handle)
        for prefix in prefixes:
            register_entry_prefix(prefix)
        result = _resolve_entry(spec["entry"])(spec)
        if result_path is not None:
            Path(result_path).write_text(json.dumps(result), encoding="utf-8")
    except BaseException:
        traceback.print_exc(file=handle)
        handle.flush()
        sys.exit(1)


@dataclass
class Job:
    """State of a single background run."""

    id: str
    pipeline: str
    output: str
    log_path: str
    status: str = _STATUS_RUNNING
    submitted_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    deadline: float | None = None
    max_output_bytes: int | None = None
    returncode: int | None = None
    reason: str | None = None
    pid: int | None = None
    _process: Any = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Serialisable status; paths shown through the sandbox, log tail redacted."""
        sandbox = _sandbox_or_none()

        def show(path: str) -> str:
            return sandbox.display_path(path) if (sandbox and path) else path

        data: dict[str, Any] = {
            "job_id": self.id,
            "pipeline": self.pipeline,
            "status": self.status,
            "output": show(self.output),
            "log_file": show(self.log_path),
            "submitted_at": min(
                self.submitted_at, self.started_at or self.submitted_at
            ),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "runtime_seconds": round(
                (self.finished_at or time.time())
                - (self.started_at or self.submitted_at),
                2,
            ),
        }
        data.update(_count_progress(self.log_path))
        if self.reason:
            data["reason"] = self.reason
        if self.status in _TERMINAL and self.status != _STATUS_SUCCEEDED:
            tail = _read_tail(self.log_path)
            data["log_tail"] = sandbox.redact(tail) if sandbox else redact_runtime(tail)
        return data


def _sandbox_or_none() -> Sandbox | None:
    try:
        return Sandbox.from_env()
    except Exception:  # a broken environment must not break job status
        return None


def _read_tail(path: str, chars: int = LOG_TAIL_CHARS) -> str:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 4 * chars))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return text[-chars:]


# The library logs ``observing <name>`` when a target starts and
# ``target <name> observed`` when it finishes (``target <name> saved`` is written
# only at the very end, so it cannot show progress).
_STARTED_RE = re.compile(r"^\S+ - INFO - observing (\S.*?)\s*$", re.MULTILINE)
_DONE_RE = re.compile(r"^\S+ - INFO - target (\S.*?) observed\s*$", re.MULTILINE)


def _count_progress(path: str) -> dict[str, int]:
    """Targets started and finished observing, counted from the job log."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - _LOG_SCAN_BYTES))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return {"targets_started": 0, "targets_done": 0}
    return {
        "targets_started": len(_STARTED_RE.findall(text)),
        "targets_done": len(_DONE_RE.findall(text)),
    }


def _output_limit_bytes(spec: dict[str, Any]) -> int:
    explicit = spec.get("max_output_bytes")
    if isinstance(explicit, int | float) and explicit > 0:
        return int(explicit)
    return _int_env(ENV_MAX_OUTPUT_MB, DEFAULT_MAX_OUTPUT_MB) * 1_048_576


class JobManager:
    """Supervises job subprocesses for one MCP server."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._sync: dict[int, Any] = {}
        self._lock = threading.RLock()
        self._watchdog: threading.Thread | None = None
        self._atexit_registered = False
        self._signals_installed = False

    # -- lifecycle --------------------------------------------------------
    def submit(
        self,
        spec: dict[str, Any],
        *,
        log_dir: str | Path,
        max_runtime: float | None,
        max_jobs: int | None = None,
    ) -> str:
        """Start a job subprocess and return its job id.

        Parameters
        ----------
        spec : dict
            ``{"entry": "module:function", "pipeline": str, "output": str, ...}``.
        log_dir : path
            Directory for the per-job log ``<id>.log``.
        max_runtime : float or None
            Deadline in seconds, clamped to ``EXORAD_MCP_MAX_RUNTIME``; ``None``
            means the cap; zero or negative is refused.
        max_jobs : int, optional
            Concurrent-job cap (default: ``EXORAD_MCP_MAX_JOBS``).

        Raises
        ------
        ValueError
            Non-positive ``max_runtime`` or an entry that is not allowed.
        JobLimitError
            If ``max_jobs`` jobs already run.
        OutputInUseError
            A running job has the same output file or output directory
            (checked under the manager lock, so two submissions cannot race).
        """
        _check_entry(spec.get("entry"))
        runtime = effective_runtime(max_runtime)
        limit = max_jobs or max_jobs_from_env()
        with self._lock:
            running = self._running_ids()
            clash = self._output_clash(str(spec.get("output") or ""))
            if clash is not None:
                raise OutputInUseError(*clash)
            if len(running) >= limit:
                raise JobLimitError(limit, running)

            job_id = uuid.uuid4().hex[:12]
            log_path = str(Path(log_dir) / f"{job_id}.log")
            Path(log_dir).mkdir(parents=True, exist_ok=True)

            self.install_hooks()
            submitted = time.time()
            process = _MP.Process(
                target=_worker,
                args=(spec, log_path, os.getpid(), None, registered_entry_prefixes()),
                name=f"exorad-mcp-{job_id}",
            )
            process.start()
            now = time.time()
            self._jobs[job_id] = Job(
                id=job_id,
                submitted_at=submitted,
                pipeline=spec.get("pipeline", ""),
                output=spec.get("output", ""),
                log_path=log_path,
                started_at=now,
                deadline=now + runtime,
                max_output_bytes=_output_limit_bytes(spec),
                pid=process.pid,
                _process=process,
            )
            self._ensure_watchdog()
            return job_id

    def run_sync(
        self,
        entry: str,
        spec: dict[str, Any],
        *,
        timeout: float,
        slot_wait: float = 0.0,
    ) -> dict[str, Any]:
        """Run a one-shot entry in a child under the same guards; return its result.

        The entry is called as ``func(spec)`` and must return a JSON-serialisable
        dict. With ``EXORAD_MCP_EXEC_BACKEND=inline`` (tests only) it runs in this
        process instead.

        ``timeout`` is clamped to :data:`~exorad.mcp.sandbox.MAX_SECONDS`.
        ``slot_wait`` is how long to wait for a free one-shot child when all are
        taken (0: do not wait, raise :class:`SyncLimitError` at once).

        Raises
        ------
        ValueError
            Entry not allowed, or ``timeout`` not positive (or not a number).
        SyncLimitError
            All one-shot children are busy and none became free within ``slot_wait``.
        TimeoutError
            The child did not finish within ``timeout`` seconds (it is killed).
        RuntimeError
            The child failed; the message carries the redacted log tail.
        """
        _check_entry(entry)
        if not timeout > 0:
            raise ValueError(f"timeout must be positive, got {timeout!r}.")
        timeout = min(float(timeout), MAX_SECONDS)  # join() overflows on huge values
        full = {"pipeline": "sync", "output": "", **spec, "entry": entry}
        if os.environ.get(ENV_EXEC_BACKEND, "process").strip().lower() == "inline":
            return json.loads(json.dumps(_resolve_entry(entry)(full)))

        scratch = Path(tempfile.mkdtemp(prefix="exorad-mcp-sync-"))
        result_path = scratch / "result.json"
        log_path = scratch / "run.log"
        process = _MP.Process(
            target=_worker,
            args=(
                full,
                str(log_path),
                os.getpid(),
                str(result_path),
                registered_entry_prefixes(),
            ),
            name="exorad-mcp-sync",
        )
        pid: int | None = None
        slot_deadline = time.monotonic() + max(0.0, float(slot_wait))
        try:
            while pid is None:
                with self._lock:
                    limit = max_jobs_from_env()
                    if len(self._sync) < limit:
                        self.install_hooks()
                        process.start()
                        pid = process.pid
                        assert pid is not None  # set once started
                        self._sync[pid] = process
                        break
                    if time.monotonic() >= slot_deadline:
                        raise SyncLimitError(limit)
                time.sleep(_SLOT_POLL_SECONDS)
            process.join(timeout)
            if process.is_alive():
                _terminate(process)
                raise TimeoutError(f"{entry} did not finish within {timeout:g} s.")
            if process.exitcode != 0:
                tail = _read_tail(str(log_path))
                sandbox = _sandbox_or_none()
                tail = sandbox.redact(tail) if sandbox else redact_runtime(tail)
                raise RuntimeError(
                    f"{entry} failed (exit code {process.exitcode}):\n{tail}"
                )
            _sweep_group(process.pid)
            return json.loads(result_path.read_text(encoding="utf-8"))
        finally:
            with self._lock:
                if pid is not None:
                    self._sync.pop(pid, None)
            with contextlib.suppress(ValueError, OSError):
                process.close()
            shutil.rmtree(scratch, ignore_errors=True)

    def wait(self, job_id: str, timeout: float | None) -> dict[str, Any]:
        """Block up to ``timeout`` seconds for the job, then report its status."""
        job = self._get(job_id)
        process = job._process
        if process is not None and job.status == _STATUS_RUNNING:
            # the watchdog may reap (close) the process while we wait
            with contextlib.suppress(ValueError, AttributeError, OverflowError):
                process.join(None if timeout is None else min(timeout, MAX_SECONDS))
        return self.status(job_id)

    def status(self, job_id: str) -> dict[str, Any]:
        """Return the current status, reaping the process if it has exited."""
        with self._lock:
            job = self._get(job_id)
            self._refresh(job)
            return job.to_dict()

    def cancel(self, job_id: str) -> dict[str, Any]:
        """Terminate a running job and its whole process group."""
        with self._lock:
            job = self._get(job_id)
            self._refresh(job)
            if job.status == _STATUS_RUNNING and job._process is not None:
                _terminate(job._process)
                self._finish(job, _STATUS_CANCELLED, reason="cancelled by request")
            return job.to_dict()

    def list_jobs(self) -> list[dict[str, Any]]:
        """Return every known job, oldest first."""
        with self._lock:
            for job in self._jobs.values():
                self._refresh(job)
            return [
                job.to_dict()
                for job in sorted(self._jobs.values(), key=lambda j: j.submitted_at)
            ]

    def output_clash(self, output: str) -> tuple[str, str] | None:
        """``(job_id, "output" | "directory")`` of a running job that owns ``output``."""
        with self._lock:
            self._running_ids()  # reaps finished jobs first
            return self._output_clash(output)

    def running_ids(self) -> list[str]:
        """Ids of the jobs currently running."""
        with self._lock:
            return self._running_ids()

    def shutdown(self) -> None:
        """Terminate every running child and its group (idempotent)."""
        with self._lock:
            procs: list[tuple[Job | None, Any]] = [
                (job, job._process)
                for job in self._jobs.values()
                if job.status == _STATUS_RUNNING and job._process is not None
            ]
            procs += [(None, p) for p in self._sync.values()]
            for _, process in procs:
                try:
                    if process.is_alive():
                        _signal_group(process, signal.SIGTERM)
                except (ValueError, AttributeError, OSError):
                    pass
            end = time.time() + _KILL_GRACE_SECONDS
            for _, process in procs:
                try:
                    process.join(max(0.0, end - time.time()))
                    if process.is_alive():
                        _signal_group(process, _SIGKILL)
                        process.join(2)
                    _sweep_group(process.pid)
                except (ValueError, AttributeError, OSError):
                    pass
            for job, _ in procs:
                if job is not None:
                    self._finish(job, _STATUS_CANCELLED, reason="server shut down")

    # -- internals ------------------------------------------------------
    def _get(self, job_id: str) -> Job:
        try:
            return self._jobs[job_id]
        except KeyError:
            raise KeyError(f"Unknown job id: {job_id}") from None

    def _output_clash(self, output: str) -> tuple[str, str] | None:
        """Running job with the same output file, or in the same output directory."""
        if not output:
            return None
        mine = Path(os.path.normpath(output))
        for job in self._jobs.values():
            if job.status != _STATUS_RUNNING or not job.output:
                continue
            theirs = Path(os.path.normpath(job.output))
            if theirs == mine:
                return job.id, "output"
            if theirs.parent == mine.parent:
                return job.id, "directory"
        return None

    def _running_ids(self) -> list[str]:
        for job in self._jobs.values():
            self._refresh(job)
        return [j.id for j in self._jobs.values() if j.status == _STATUS_RUNNING]

    def _finish(self, job: Job, status: str, *, reason: str | None = None) -> None:
        """Record a terminal state, reap the process and release its handle."""
        process = job._process
        job.status = status
        job.finished_at = time.time()
        if reason:
            job.reason = reason
        if process is not None:
            try:
                process.join(0.1)
                job.returncode = process.exitcode
                if not process.is_alive():
                    process.close()
            except (ValueError, AttributeError, OSError):
                pass
            job._process = None

    def _output_too_big(self, job: Job) -> bool:
        if not job.max_output_bytes or not job.output:
            return False
        try:
            return os.path.getsize(job.output) > job.max_output_bytes
        except OSError:
            return False

    def _refresh(self, job: Job) -> None:
        if job.status != _STATUS_RUNNING or job._process is None:
            return
        process = job._process
        try:
            alive = process.is_alive()
        except ValueError:  # already closed
            return
        if alive:
            if job.deadline is not None and time.time() > job.deadline:
                _terminate(process)
                self._finish(
                    job,
                    _STATUS_TIMEOUT,
                    reason="exceeded max_runtime and was terminated by the watchdog",
                )
            elif self._output_too_big(job):
                _terminate(process)
                self._finish(
                    job, _STATUS_FAILED, reason="output exceeded the size limit"
                )
            return
        code = process.exitcode
        # a crashed child may have left pool workers behind
        _sweep_group(job.pid)
        self._finish(
            job,
            _STATUS_SUCCEEDED if code == 0 else _STATUS_FAILED,
            reason=None if code == 0 else f"exit code {code}",
        )

    def _ensure_watchdog(self) -> None:
        if self._watchdog is not None and self._watchdog.is_alive():
            return
        self._watchdog = threading.Thread(
            target=self._watch, name="exorad-mcp-watchdog", daemon=True
        )
        self._watchdog.start()

    def _watch(self) -> None:
        """Enforce deadlines and the output limit and reap finished children."""
        while True:
            time.sleep(_WATCHDOG_INTERVAL)
            with self._lock:
                running = [
                    j for j in self._jobs.values() if j.status == _STATUS_RUNNING
                ]
                for job in running:
                    self._refresh(job)
                if not any(j.status == _STATUS_RUNNING for j in running):
                    self._watchdog = None
                    return

    def install_hooks(self) -> None:
        """Register the atexit and SIGTERM/SIGINT hooks (idempotent).

        Signal handlers can only be set from the main thread, and mcp 2.x runs
        sync tools in worker threads, so ``server.main()`` calls this on the main
        thread before serving. A call from another thread registers only atexit
        and leaves the signal handlers for a later main-thread call.
        """
        if not self._atexit_registered:
            self._atexit_registered = True
            atexit.register(self.shutdown)
        if self._signals_installed:
            return
        if threading.current_thread() is not threading.main_thread():
            return
        self._signals_installed = True
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                previous = signal.getsignal(sig)
                signal.signal(sig, self._make_handler(previous))
            except (ValueError, OSError):
                continue

    def _make_handler(self, previous: Any) -> Any:
        def handler(signum: int, frame: Any) -> None:
            self.shutdown()
            if callable(previous):
                previous(signum, frame)
            elif signum == signal.SIGINT:
                raise KeyboardInterrupt
            else:  # SIG_DFL / SIG_IGN: re-deliver with the default action
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)

        return handler


class _SelfTestEntry:
    """Trivial job entry used only by the job-manager tests.

    Referenced as ``exorad.mcp.jobs:_SelfTestEntry`` in a spec so the real
    subprocess path can be exercised without a heavy ExoRad run. Options come
    from ``spec["selftest"]``: ``sleep`` (seconds), ``fail``, ``marker`` (file
    written when the entry starts), ``pool`` (start that many pool workers; their
    pids go to ``<marker>.pids``), ``pool_print`` (workers print a line),
    ``write_bytes`` (grow ``spec["output"]`` to that size), ``report_env`` (file
    receiving the environment seen at import and at run time) and ``connect``
    (try to open an internet connection and log the outcome).
    """

    def __init__(self, spec: dict[str, Any]) -> None:
        opts = dict(spec.get("selftest", {}))
        marker = opts.get("marker")
        if opts.get("report_env"):
            Path(opts["report_env"]).write_text(
                json.dumps(
                    {
                        "at_import": _ENV_AT_IMPORT,
                        "now": {k: os.environ.get(k) for k in _ENV_AT_IMPORT},
                    }
                ),
                encoding="utf-8",
            )
        if opts.get("connect"):
            import socket

            try:
                socket.create_connection(("192.0.2.1", 9), timeout=1)
            except OSError as exc:
                print(f"connect failed: {type(exc).__name__}: {exc}", flush=True)
        if opts.get("write_bytes"):
            with open(spec["output"], "wb") as handle:
                handle.write(b"\0" * int(opts["write_bytes"]))
        print("self-test entry running", flush=True)
        pool = None
        if opts.get("pool"):
            from concurrent.futures import ProcessPoolExecutor

            n = int(opts["pool"])
            pool = ProcessPoolExecutor(max_workers=n)
            futures = [
                pool.submit(_selftest_pool_task, bool(opts.get("pool_print")))
                for _ in range(n)
            ]
            pids = sorted({f.result(timeout=120) for f in futures})
            if marker:
                Path(f"{marker}.pids").write_text(
                    " ".join(map(str, pids)), encoding="utf-8"
                )
        if marker:
            Path(marker).write_text("started", encoding="utf-8")
        time.sleep(float(opts.get("sleep", 0.0)))
        if opts.get("fail"):
            raise RuntimeError("self-test failure")
        print("self-test entry done", flush=True)
        if pool is not None:
            pool.shutdown()


def _selftest_pool_task(say: bool) -> int:
    time.sleep(1.0)  # keep both workers busy so the pool really starts n of them
    if say:
        print("pool worker says hello", flush=True)
    return os.getpid()


def _selftest_sync(spec: dict[str, Any]) -> dict[str, Any]:
    """One-shot entry used only by the ``run_sync`` tests.

    Options: ``value`` (returned plus one as ``answer``), ``sleep``, ``fail``.
    Reports whether it runs in its own process group with the network guard and
    the child environment in place.
    """
    from exorad.mcp import netguard

    time.sleep(float(spec.get("sleep", 0.0)))
    if spec.get("fail"):
        raise RuntimeError("sync self-test failure")
    return {
        "answer": int(spec.get("value", 0)) + 1,
        "pid": os.getpid(),
        "group_leader": hasattr(os, "getpgid") and os.getpgid(0) == os.getpid(),
        "blocked": netguard.is_blocked(),
        "env": {k: os.environ.get(k) for k in (*CHILD_ENV_FORCED, *CHILD_ENV_DEFAULTS)},
    }


JOBS = JobManager()
