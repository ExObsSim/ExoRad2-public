"""Shared fixtures for the ExoRad MCP tests.

The MCP tool functions read their sandbox from the environment (the server sets
it once at startup); tests point it at the real checkout with a throwaway
working directory, and individual tests override ``EXORAD_MCP_REPO_ROOT`` when
they need a synthetic repository.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_MCP_ENV = (
    "EXORAD_MCP_ALLOW_DIRS",
    "EXORAD_MCP_NO_EXEC",
    "EXORAD_MCP_MAX_THREADS",
    "EXORAD_MCP_MAX_RUNTIME",
    "EXORAD_MCP_MAX_JOBS",
    "EXORAD_MCP_RETRIEVAL",
    "EXORAD_MCP_MAX_TARGETS",
    "EXORAD_MCP_MAX_OUTPUT_MB",
    "EXORAD_MCP_MAX_BINS",
    "EXORAD_MCP_MAX_DATA_MB",
    "EXORAD_MCP_MAX_FILE_MB",
    "EXORAD_MCP_VALIDATE_TIMEOUT",
    "EXORAD_MCP_LOG_LEVEL",
)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The ExoRad checkout the tests run from."""
    return REPO_ROOT


@pytest.fixture(autouse=True)
def _isolate_environ():
    """Restore ``os.environ`` after every test.

    ``server.main`` assigns to ``os.environ`` on purpose (spawned job children inherit it) and
    ``monkeypatch.delenv(..., raising=False)`` on an absent variable records nothing to undo,
    so without this the child environment (``EXORAD_NO_VERSION_CHECK=1`` in particular) leaked
    into every later test of the session and silently disabled ``VersionControl``.
    """
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture(autouse=True)
def _mcp_sandbox_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EXORAD_MCP_REPO_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("EXORAD_MCP_WORK_DIR", str(tmp_path / "mcp-work"))
    # Pipeline runs execute in-process by default in tests (no subprocess spawn);
    # job tests opt back into the real process backend where it matters.
    monkeypatch.setenv("EXORAD_MCP_EXEC_BACKEND", "inline")
    for name in _MCP_ENV:
        monkeypatch.delenv(name, raising=False)
