"""Filesystem sandbox for the ExoRad MCP server.

An MCP client is an autonomous program driven by a language model: it can ask
the server to read or write *any* path it likes. Every filesystem access made by
a tool must therefore be confined to an explicit allowlist of directories.

The sandbox has two kinds of root:

``repo_root``
    The *content root*: the ExoRad checkout, or the documentation/examples
    packaged inside the wheel (see :mod:`exorad.mcp.assets` for the precedence).
    Tools may **read** payloads, examples and source here, but never write.
``work_dir``
    A dedicated directory (default ``<repo_root>/mcp-runs``, or
    ``./mcp-runs`` when the content is packaged) where pipeline outputs and
    logs are written and may be read back.

Extra read/write roots can be added with ``EXORAD_MCP_ALLOW_DIRS`` for users who
keep their payloads outside the checkout.

Environment variables (all optional, overridden by explicit arguments):

============================== ===============================================
``EXORAD_MCP_REPO_ROOT``        content root override (default: checkout, else packaged)
``EXORAD_MCP_WORK_DIR``         writable output directory (default: ``<repo>/mcp-runs``)
``EXORAD_MCP_ALLOW_DIRS``       extra allowed roots, ``os.pathsep``-separated
``EXORAD_MCP_NO_EXEC``          if truthy, the execution tools are disabled
``EXORAD_MCP_MAX_THREADS``      cap on ``n_threads`` (worker processes), default ``min(4, cpus)``
``EXORAD_MCP_MAX_RUNTIME``      hard wall-clock limit per run, seconds (default 3600)
``EXORAD_MCP_MAX_JOBS``         concurrent runs allowed (default 2; invalid or 0 -> default)
``EXORAD_MCP_EXEC_BACKEND``     ``process`` (default) or ``inline`` (tests only)
``EXORAD_MCP_MAX_TARGETS``      rows in a target list (default 200)
``EXORAD_MCP_MAX_OUTPUT_MB``    hard limit on one job's HDF5 output (default 512)
``EXORAD_MCP_MAX_BINS``         spectral bins per channel (default 20000)
``EXORAD_MCP_MAX_DATA_MB``      size of any data table a payload references (default 64)
``EXORAD_MCP_MAX_FILE_MB``      size of a target list or payload XML (default 2)
``EXORAD_MCP_VALIDATE_TIMEOUT`` seconds for ``validate_config(deep=True)`` / plots (120)
============================== ===============================================

``EXORAD_MCP_RETRIEVAL`` and ``EXORAD_MCP_LOG_LEVEL`` are read by the retrieval and
server modules. There is deliberately no switch that enables network access.
"""

from __future__ import annotations

import logging
import math
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from exorad.mcp.assets import (
    ENV_REPO_ROOT,  # noqa: F401  (re-exported for the server CLI)
    content_report,
    resolve_content_root,
    warn_if_content_missing,
)

ENV_WORK_DIR = "EXORAD_MCP_WORK_DIR"
ENV_ALLOW_DIRS = "EXORAD_MCP_ALLOW_DIRS"
ENV_NO_EXEC = "EXORAD_MCP_NO_EXEC"
ENV_MAX_THREADS = "EXORAD_MCP_MAX_THREADS"
ENV_MAX_RUNTIME = "EXORAD_MCP_MAX_RUNTIME"
ENV_MAX_JOBS = "EXORAD_MCP_MAX_JOBS"
ENV_EXEC_BACKEND = "EXORAD_MCP_EXEC_BACKEND"
ENV_MAX_TARGETS = "EXORAD_MCP_MAX_TARGETS"
ENV_MAX_OUTPUT_MB = "EXORAD_MCP_MAX_OUTPUT_MB"
ENV_MAX_BINS = "EXORAD_MCP_MAX_BINS"
ENV_MAX_DATA_MB = "EXORAD_MCP_MAX_DATA_MB"
ENV_MAX_FILE_MB = "EXORAD_MCP_MAX_FILE_MB"
ENV_VALIDATE_TIMEOUT = "EXORAD_MCP_VALIDATE_TIMEOUT"

_LOGGER = logging.getLogger("exorad.mcp.sandbox")

DEFAULT_WORK_DIRNAME = "mcp-runs"
#: Per-user fallback for the DEFAULT work directory when it cannot be created
#: (for example the server starts in ``/``): ``~/.exorad/mcp-runs``.
FALLBACK_WORK_PARTS = (".exorad", DEFAULT_WORK_DIRNAME)
#: Upper bound of every duration read from the environment or a tool argument
#: (about 11.6 days): larger or non-finite values are refused or clamped.
MAX_SECONDS = 1.0e6
DEFAULT_MAX_RUNTIME = 3600.0
DEFAULT_MAX_JOBS = 2
DEFAULT_MAX_TARGETS = 200
DEFAULT_MAX_OUTPUT_MB = 512
DEFAULT_MAX_BINS = 20000
DEFAULT_MAX_DATA_MB = 64
DEFAULT_MAX_FILE_MB = 2
DEFAULT_VALIDATE_TIMEOUT = 120.0
_TRUTHY = {"1", "true", "yes", "on"}


class PathNotAllowedError(ValueError):
    """Raised when a tool is asked to touch a path outside the sandbox."""


def _resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _within(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


_WARNED: set[tuple[str, str]] = set()


def _warn_once(name: str, raw: str, message: str) -> None:
    """One log line per variable and value (the sandbox is rebuilt on every call)."""
    if (name, raw) not in _WARNED:
        _WARNED.add((name, raw))
        _LOGGER.warning("%s=%r: %s", name, raw, message)


def _float_env(name: str, default: float) -> float:
    """A finite positive float from the environment, at most :data:`MAX_SECONDS`.

    Invalid, non-positive, ``inf`` and ``nan`` values (``1e400`` parses to
    ``inf``) fall back to ``default``; a finite value above :data:`MAX_SECONDS`
    is clamped to it. Each case logs one warning.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        _warn_once(name, raw, f"not a number; using the default {default:g}")
        return default
    if not math.isfinite(value) or value <= 0:
        _warn_once(
            name, raw, f"must be a finite number above 0; using the default {default:g}"
        )
        return default
    if value > MAX_SECONDS:
        _warn_once(name, raw, f"above the limit; using {MAX_SECONDS:g} seconds")
        return MAX_SECONDS
    return value


def _int_env(name: str, default: int) -> int:
    """A positive int from the environment; invalid or non-positive -> default."""
    raw = os.environ.get(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return value if value > 0 else default


def can_create_dir(path: Path) -> bool:
    """Whether ``path`` exists as a directory or could be created (nothing is created).

    True when ``path`` is a writable directory, or its nearest existing ancestor
    is a writable, searchable directory.
    """
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate.is_dir() and os.access(
                candidate, os.W_OK | os.X_OK if candidate != path else os.W_OK
            )
    return False


def fallback_work_dir() -> Path:
    """``~/.exorad/mcp-runs``, the per-user work directory of last resort."""
    return _resolve(Path.home().joinpath(*FALLBACK_WORK_PARTS))


def _default_work_dir(default: Path) -> Path:
    """The default work directory, or the per-user fallback if it is unusable.

    Starting in ``/`` (or any read-only place) would make ``<cwd>/mcp-runs``
    impossible: serve from ``~/.exorad/mcp-runs`` instead and say so once. An
    EXPLICIT work directory never reaches here: it is never replaced.
    """
    if can_create_dir(default):
        return _resolve(default)
    fallback = fallback_work_dir()
    _warn_once(
        "work-dir",
        str(default),
        f"the default work directory {default} cannot be created; using {fallback}",
    )
    return fallback


def _default_threads() -> int:
    return max(1, min(4, os.cpu_count() or 1))


def ensure_regular_file(path: Path, *, max_bytes: int | None = None) -> Path:
    """Require an existing regular file of at most ``max_bytes`` bytes.

    A FIFO, device or directory is refused: a FIFO reports size 0 (so it would
    slip past a size limit) and blocks the reader that opens it. ``path`` should
    already be resolved by :meth:`Sandbox.resolve_read`.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    PathNotAllowedError
        If it is not a regular file, or is larger than ``max_bytes``.
    """
    try:
        info = path.stat()
    except FileNotFoundError:
        raise FileNotFoundError(f"file not found: {path.name}") from None
    if not stat.S_ISREG(info.st_mode):
        raise PathNotAllowedError(
            f"'{path.name}' is not a regular file (directories, pipes and devices "
            "are not accepted)"
        )
    if max_bytes is not None and info.st_size > max_bytes:
        raise PathNotAllowedError(
            f"'{path.name}' is {info.st_size / 1_048_576:.1f} MB, above the "
            f"{max_bytes / 1_048_576:g} MB limit"
        )
    return path


def _runtime_prefixes() -> list[tuple[str, str]]:
    """``(path, label)`` pairs hiding the interpreter and the user's home.

    Longest first, so ``<site-packages>`` wins over ``<python>`` and both over
    ``~``. One-component paths (``/usr``, ``/root``) and ``/`` are skipped: they
    would mangle ordinary text.
    """
    import site
    import sys
    import sysconfig

    found: dict[str, str] = {}

    def add(raw: object, label: str) -> None:
        if not raw:
            return
        text = str(raw).rstrip("/\\")
        if len([part for part in re.split(r"[/\\]", text) if part]) < 2:
            return
        found.setdefault(text, label)
        if text.startswith("/private/"):  # macOS /tmp and /var aliases
            found.setdefault(text[len("/private") :], label)

    paths = sysconfig.get_paths()
    for key in ("purelib", "platlib"):
        add(paths.get(key), "<site-packages>")
    try:
        for entry in site.getsitepackages():
            add(entry, "<site-packages>")
        add(site.getusersitepackages(), "<site-packages>")
    except Exception:
        pass
    add(sys.prefix, "<python>")
    add(sys.base_prefix, "<python>")
    add(sys.exec_prefix, "<python>")
    try:
        home = Path.home()
    except Exception:
        home = None
    if home is not None:
        add(home, "~")
        with_resolved = _resolve(home)
        add(with_resolved, "~")
    return sorted(found.items(), key=lambda item: len(item[0]), reverse=True)


def redact_runtime(text: str, *, interpreter: bool = True, home: bool = True) -> str:
    """Hide the interpreter prefixes and the home directory in free text.

    ``site-packages`` becomes ``<site-packages>``, ``sys.prefix`` /
    ``sys.base_prefix`` become ``<python>`` and the user's home directory
    becomes ``~``, so tracebacks do not reveal the server's layout.
    :meth:`Sandbox.redact` calls it in two steps around the sandbox roots (the
    interpreter first, the home last): a virtual environment inside the
    checkout, the usual layout on Linux and in CI, is under the content root
    and must still read ``<site-packages>``; a root under the home must read
    ``work:`` / ``content:`` and not ``~/...``.
    """
    for path, label in _runtime_prefixes():
        if label == "~" and not home:
            continue
        if label != "~" and not interpreter:
            continue
        pattern = re.escape(path) + r"(?=[/\\]|(?![\w.\-]))"
        text = re.sub(pattern, label, text)
    return text


@dataclass(frozen=True)
class Sandbox:
    """The directories an MCP tool is allowed to touch, plus run limits."""

    repo_root: Path
    work_dir: Path
    extra_roots: tuple[Path, ...] = field(default_factory=tuple)
    allow_exec: bool = True
    max_threads: int = field(default_factory=_default_threads)
    max_runtime: float = DEFAULT_MAX_RUNTIME
    max_jobs: int = DEFAULT_MAX_JOBS
    max_targets: int = DEFAULT_MAX_TARGETS
    max_output_mb: int = DEFAULT_MAX_OUTPUT_MB
    max_bins: int = DEFAULT_MAX_BINS
    max_data_mb: int = DEFAULT_MAX_DATA_MB
    max_file_mb: int = DEFAULT_MAX_FILE_MB
    validate_timeout: float = DEFAULT_VALIDATE_TIMEOUT
    exec_backend: str = "process"
    content_source: str = "override"

    @classmethod
    def from_env(
        cls,
        *,
        repo_root: str | Path | None = None,
        work_dir: str | Path | None = None,
        allow_exec: bool | None = None,
    ) -> Sandbox:
        """Build a sandbox from explicit arguments, then the environment."""
        content = resolve_content_root(repo_root)
        root, source = _resolve(content.path), content.source
        # Never write runs into site-packages: packaged content uses ./mcp-runs.
        work_base = Path.cwd() if source == "packaged" else root
        explicit = work_dir or os.environ.get(ENV_WORK_DIR)
        if explicit:
            work = _resolve(explicit)
        else:
            work = _default_work_dir(work_base / DEFAULT_WORK_DIRNAME)
        warn_if_content_missing(root, source)
        extra = tuple(
            _resolve(item)
            for item in os.environ.get(ENV_ALLOW_DIRS, "").split(os.pathsep)
            if item.strip()
        )
        if allow_exec is None:
            allow_exec = os.environ.get(ENV_NO_EXEC, "").strip().lower() not in _TRUTHY
        backend = os.environ.get(ENV_EXEC_BACKEND, "process").strip().lower()
        return cls(
            repo_root=root,
            work_dir=work,
            extra_roots=extra,
            allow_exec=allow_exec,
            max_threads=_int_env(ENV_MAX_THREADS, _default_threads()),
            max_runtime=_float_env(ENV_MAX_RUNTIME, DEFAULT_MAX_RUNTIME),
            max_jobs=_int_env(ENV_MAX_JOBS, DEFAULT_MAX_JOBS),
            max_targets=_int_env(ENV_MAX_TARGETS, DEFAULT_MAX_TARGETS),
            max_output_mb=_int_env(ENV_MAX_OUTPUT_MB, DEFAULT_MAX_OUTPUT_MB),
            max_bins=_int_env(ENV_MAX_BINS, DEFAULT_MAX_BINS),
            max_data_mb=_int_env(ENV_MAX_DATA_MB, DEFAULT_MAX_DATA_MB),
            max_file_mb=_int_env(ENV_MAX_FILE_MB, DEFAULT_MAX_FILE_MB),
            validate_timeout=_float_env(ENV_VALIDATE_TIMEOUT, DEFAULT_VALIDATE_TIMEOUT),
            exec_backend=backend if backend in {"process", "inline"} else "process",
            content_source=source,
        )

    def to_spec(self) -> dict[str, object]:
        """The roots and limits a job child needs to re-check its inputs.

        JSON-serialisable; :meth:`from_spec` is the inverse. The child must not
        guess these from its environment: the plan may have been made with an
        explicit sandbox.
        """
        return {
            "repo_root": str(self.repo_root),
            "work_dir": str(self.work_dir),
            "extra_roots": [str(root) for root in self.extra_roots],
            "max_data_mb": self.max_data_mb,
            "max_file_mb": self.max_file_mb,
            "max_bins": self.max_bins,
            "max_targets": self.max_targets,
            "content_source": self.content_source,
        }

    @classmethod
    def from_spec(cls, spec: dict[str, object]) -> Sandbox:
        """Rebuild the sandbox written by :meth:`to_spec` (execution limits default)."""
        return cls(
            repo_root=Path(str(spec["repo_root"])),
            work_dir=Path(str(spec["work_dir"])),
            extra_roots=tuple(Path(str(r)) for r in spec.get("extra_roots", [])),  # type: ignore[attr-defined]
            max_data_mb=int(spec["max_data_mb"]),  # type: ignore[call-overload]
            max_file_mb=int(spec["max_file_mb"]),  # type: ignore[call-overload]
            max_bins=int(spec["max_bins"]),  # type: ignore[call-overload]
            max_targets=int(spec["max_targets"]),  # type: ignore[call-overload]
            content_source=str(spec.get("content_source", "override")),
        )

    def log_dir(self) -> Path:
        """Directory for per-job log files."""
        return self.work_dir / "logs"

    def clamp_threads(self, requested: int | None) -> int:
        """Clamp a requested worker count to ``1..max_threads`` (``None`` -> 1)."""
        if requested is None:
            return 1
        return max(1, min(int(requested), self.max_threads))

    # -- roots ----------------------------------------------------------------
    @property
    def readable_roots(self) -> tuple[Path, ...]:
        """Directories a tool may read from."""
        return (self.repo_root, self.work_dir, *self.extra_roots)

    @property
    def writable_roots(self) -> tuple[Path, ...]:
        """Directories a tool may write to (never the checkout itself)."""
        return (self.work_dir, *self.extra_roots)

    def _labelled_roots(self) -> list[tuple[str, Path]]:
        """``(label, root)`` pairs, most specific first (the work dir may sit in the repo)."""
        pairs = [("work:", self.work_dir)]
        pairs += [(f"allow[{i}]:", root) for i, root in enumerate(self.extra_roots)]
        pairs.append(("content:", self.repo_root))
        return sorted(pairs, key=lambda item: len(item[1].parts), reverse=True)

    def _readable_labels(self) -> str:
        return ", ".join(
            label.rstrip(":") for label, _ in reversed(self._labelled_roots())
        )

    def _writable_labels(self) -> str:
        return ", ".join(
            ["work", *(f"allow[{i}]" for i in range(len(self.extra_roots)))]
        )

    # -- display ------------------------------------------------------------
    def display_path(self, path: str | Path) -> str:
        """Show ``path`` without leaking the server's absolute directory layout.

        A path under a sandbox root becomes ``work:<relative>``,
        ``content:<relative>`` or ``allow[i]:<relative>``; anything else shows
        only its file name (``<outside>/name``).
        """
        raw = Path(path).expanduser()
        candidates = [Path(os.path.normpath(raw))]
        if raw.is_absolute():
            candidates.append(_resolve(raw))
        for candidate in candidates:
            for label, root in self._labelled_roots():
                if _within(candidate, root):
                    rel = candidate.relative_to(root).as_posix()
                    return f"{label}{rel}"
        return f"<outside>/{raw.name}" if raw.name else "<outside>"

    def redact(self, text: str) -> str:
        """Replace the sandbox root prefixes inside free text (logs, attributes)."""
        text = redact_runtime(text, home=False)
        for label, root in self._labelled_roots():
            spellings = {str(root)}
            if str(root).startswith("/private/"):  # macOS /tmp and /var aliases
                spellings.add(str(root)[len("/private") :])
            for spelling in sorted(spellings, key=len, reverse=True):
                pattern = re.escape(spelling) + r"(?:(?P<sep>[/\\])|(?![\w.\-]))"

                def _sub(match: re.Match[str], label: str = label) -> str:
                    return label if match.group("sep") else f"{label}."

                text = re.sub(pattern, _sub, text)
        return redact_runtime(text, interpreter=False)

    # -- resolution ---------------------------------------------------------
    def _to_abs(self, raw: str | Path, base: Path) -> Path:
        candidate = Path(raw).expanduser()
        return _resolve(candidate if candidate.is_absolute() else base / candidate)

    def _readable(self, target: Path) -> bool:
        return any(_within(target, root) for root in self.readable_roots)

    def _expand_label(self, raw: str | Path) -> str | Path:
        """Turn a DISPLAY path back into a real one.

        :meth:`display_path` shows ``work:runs/x/out.h5``, ``content:examples/a.xml``
        or ``allow[i]:file`` so that no absolute server path leaks. A client passes
        that string back to another tool, so the label is expanded to its root here.
        The expanded path then goes through exactly the same containment checks as
        any other path (``..``, symlinks, ``~`` and the readable/writable roots), so
        a label never widens the sandbox. Anything else is returned unchanged.
        """
        text = str(raw)
        for label, root in self._labelled_roots():
            if text.startswith(label):
                rest = text[len(label) :]
                # Not normalised on purpose: the display form never has a slash after
                # the label, and ``root / "/etc/passwd"`` is ``/etc/passwd``, which the
                # containment check then refuses.
                return root / rest if rest else root
        if re.match(r"allow\[\d+\]:", text):
            raise PathNotAllowedError(
                f"'{text}' refers to an allowed directory that is not configured "
                f"({self._readable_labels()})"
            )
        return raw

    @staticmethod
    def _refuse_urls(raw: str | Path) -> None:
        text = str(raw)
        if "://" in text:
            raise PathNotAllowedError(
                f"'{text}' looks like a URL: URLs are not allowed, only files "
                "inside the sandbox"
            )
        if "\0" in text:
            raise PathNotAllowedError("a path must not contain a NUL character")

    def resolve_read(self, raw: str | Path, *, prefer_work_dir: bool = False) -> Path:
        """Resolve a path a tool wants to read; confine it to a readable root.

        Relative paths are taken against the content root (``repo_root``). With
        ``prefer_work_dir`` they are tried against the working directory first
        (so ``out.h5`` produced by a run is found) and fall back to the content
        root (so ``examples/...`` still works). Whichever candidate is used must
        lie in a readable root after symlinks, ``..`` and ``~`` are resolved. A
        value containing ``://`` (a URL) is refused outright.
        """
        self._refuse_urls(raw)
        raw = self._expand_label(raw)
        escaped = False
        if prefer_work_dir and not Path(raw).expanduser().is_absolute():
            candidate = self._to_abs(raw, self.work_dir)
            if self._readable(candidate):
                if candidate.exists():
                    return candidate
            else:
                # e.g. a symlink in the work dir pointing out of the sandbox
                escaped = os.path.lexists(self.work_dir / Path(raw).expanduser())
        target = self._to_abs(raw, self.repo_root)
        if escaped and self._readable(target) and not target.exists():
            raise PathNotAllowedError(
                f"'{raw}' exists in the working directory but resolves outside the "
                f"directories this MCP server may read ({self._readable_labels()})"
            )
        if not self._readable(target):
            raise PathNotAllowedError(
                f"'{raw}' is outside the directories this MCP server may read "
                f"({self._readable_labels()})"
            )
        return target

    def resolve_input_file(
        self,
        raw: str | Path,
        *,
        prefer_work_dir: bool = False,
        max_mb: float | None = None,
    ) -> Path:
        """:meth:`resolve_read` plus the checks for a file that will be OPENED.

        The result must exist, be a regular file (no FIFO, device, directory)
        and, when ``max_mb`` is given, not exceed it.
        """
        path = self.resolve_read(raw, prefer_work_dir=prefer_work_dir)
        limit = None if max_mb is None else int(max_mb * 1_048_576)
        return ensure_regular_file(path, max_bytes=limit)

    def resolve_write(self, raw: str | Path) -> Path:
        """Resolve a path a tool wants to write; confine it to the work dir."""
        self._refuse_urls(raw)
        raw = self._expand_label(raw)
        target = self._to_abs(raw, self.work_dir)
        if not any(_within(target, root) for root in self.writable_roots):
            raise PathNotAllowedError(
                f"'{raw}' is outside the writable working directory "
                f"({self._writable_labels()}); "
                "pass an output path under the working directory"
            )
        return target

    def ensure_work_dir(self) -> Path:
        """Create the working directory if needed and return it.

        Called lazily by the tools that write (a draft, a run), and at start-up
        only when execution is enabled.
        """
        self.work_dir.mkdir(parents=True, exist_ok=True)
        return self.work_dir

    def to_dict(self) -> dict[str, object]:
        """Serialisable description, for the ``capabilities`` tool.

        This is the one place where the roots are shown in full.
        """
        return {
            "repo_root": str(self.repo_root),
            "content": content_report(self.repo_root, self.content_source),
            "work_dir": str(self.work_dir),
            "extra_roots": [str(r) for r in self.extra_roots],
            "execution_enabled": self.allow_exec,
            "max_threads": self.max_threads,
            "max_runtime_seconds": self.max_runtime,
            "max_jobs": self.max_jobs,
            "max_targets": self.max_targets,
            "max_output_mb": self.max_output_mb,
            "max_bins": self.max_bins,
            "max_data_mb": self.max_data_mb,
            "max_file_mb": self.max_file_mb,
            "validate_timeout_seconds": self.validate_timeout,
        }
