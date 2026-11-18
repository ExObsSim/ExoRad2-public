"""A test must not leave the server's child environment behind for the rest of the session.

``exorad.mcp.server.main`` sets ``EXORAD_NO_VERSION_CHECK`` (and ``MPLBACKEND``, thread caps,
``EXORAD_MCP_*``) in ``os.environ`` on purpose, so that spawned job children inherit them.
``monkeypatch.delenv(name, raising=False)`` on a variable that is ABSENT records nothing, so
a later assignment by ``main`` was never undone, and ``VersionControl`` (which returns early
when ``EXORAD_NO_VERSION_CHECK`` is set) silently stopped checking for every test that ran
afterwards: ``tests/test_git.py`` failed only in a full run (found 2026-11-12). The autouse
fixture in ``conftest.py`` restores ``os.environ`` after every test.

The two tests below depend on running in this order within the file: the first one
pollutes the environment, the second asserts it is clean again.
"""

from __future__ import annotations

import os

_LEAKED = ("EXORAD_NO_VERSION_CHECK", "MPLBACKEND", "EXORAD_MCP_NO_EXEC")


def test_a_test_may_set_the_environment_directly() -> None:
    for name in _LEAKED:
        os.environ.pop(name, None)
    # what server.main() does: plain assignment, not monkeypatch
    os.environ["EXORAD_NO_VERSION_CHECK"] = "1"
    os.environ["MPLBACKEND"] = "Agg"
    os.environ["EXORAD_MCP_NO_EXEC"] = "1"


def test_the_next_test_starts_from_a_clean_environment() -> None:
    assert "EXORAD_NO_VERSION_CHECK" not in os.environ
    assert "EXORAD_MCP_NO_EXEC" not in os.environ
