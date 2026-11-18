"""Minimal raw JSON-RPC client for the stdio MCP server (used by server-level tests).

The server is started through a small launcher (``python -c``) so that tests can
(a) replace the tool groups that other tasks provide by stubs raising the expected
exception types, which makes these wiring tests independent of the tools'
implementations, and (b) hide a tool module to see how the server reports it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

# Runs in the server process. ``EXORAD_TEST_STUBS`` is "stub", "hide:<module>,..."
# or empty (real tools). Stubs are installed unconditionally (also once the real
# modules exist) because these tests check the server's wiring, not the tools.
_LAUNCHER = r'''
import logging
import os
import sys
import types

mode = os.environ.get("EXORAD_TEST_STUBS", "")


def _module(name, **funcs):
    mod = types.ModuleType(name)
    for key, func in funcs.items():
        func.__module__ = name
        setattr(mod, key, func)
    sys.modules[name] = mod


if mode == "stub":
    from exorad.mcp import jobs
    from exorad.mcp.sandbox import Sandbox

    def inspect_output(path: str, max_items: int = 80) -> dict:
        """Stub: a sandbox refusal (PathNotAllowedError, a ValueError)."""
        Sandbox.from_env().resolve_read(path)
        return {"path": path}

    def explain_output(path: str = "o.h5", target: str = "") -> dict:
        """Stub: an unknown name (KeyError)."""
        raise KeyError(f"unknown target {target}")

    def plot_output(path: str = "o.h5") -> dict:
        """Stub: a genuine bug (bare RuntimeError)."""
        raise RuntimeError("stub bug: kaboom")

    _module(
        "exorad.mcp.tools_output",
        inspect_output=inspect_output,
        explain_output=explain_output,
        plot_output=plot_output,
    )

    def run_pipeline(payload: str = "p.xml", output: str = "o.h5") -> dict:
        """Stub: refuses to overwrite (FileExistsError, an OSError)."""
        raise FileExistsError(f"{output} exists; pass overwrite=True to replace it")

    def get_job_status(job_id: str) -> dict:
        """Stub: the real job manager's unknown-id KeyError."""
        return jobs.JOBS.status(job_id)

    def cancel_job(job_id: str) -> dict:
        """Stub."""
        return {"job_id": job_id}

    def list_jobs() -> dict:
        """Stub."""
        return {"jobs": jobs.JOBS.list_jobs()}

    _module(
        "exorad.mcp.tools_run",
        run_pipeline=run_pipeline,
        get_job_status=get_job_status,
        cancel_job=cancel_job,
        list_jobs=list_jobs,
    )

    def validate_config(configuration: str = "p.xml") -> dict:
        """Stub: logs through ExoRad's loggers, then reports an invalid payload."""
        logging.getLogger("exorad.StubTask").info("stub-library-log-line")
        logging.getLogger("exorad.mcp.stub").debug("stub-mcp-debug-line")
        raise ValueError("invalid payload: missing element ForceChannelWlEdge")

    def config_requirements(kind: str = "payload") -> dict:
        """Stub."""
        return {}

    def draft_config(name: str = "payload") -> dict:
        """Stub: missing content (ContentMissingError, a RuntimeError subclass)."""
        from exorad.mcp.assets import ContentMissingError

        raise ContentMissingError("Reference configuration examples/payload_example.xml")

    def draft_target_list(name: str = "targets") -> dict:
        """Stub."""
        return {}

    def compare_configs(config1: str = "a", config2: str = "b") -> dict:
        """Stub."""
        return {}

    _module(
        "exorad.mcp.tools_config",
        validate_config=validate_config,
        config_requirements=config_requirements,
        draft_config=draft_config,
        draft_target_list=draft_target_list,
        compare_configs=compare_configs,
    )
elif mode.startswith("hide:"):
    for name in mode[5:].split(","):
        sys.modules[name] = None  # import raises ModuleNotFoundError

from exorad.mcp.server import main

main(sys.argv[1:])
'''


def run_stdio_requests(
    requests: list[tuple[str, dict[str, Any]]],
    *,
    work_dir: Path,
    repo_root: Path = REPO_ROOT,
    timeout: float = 240.0,
    stubs: str = "stub",
    env: dict[str, str] | None = None,
    extra_args: tuple[str, ...] = (),
    launcher: str | None = None,
) -> tuple[list[str], list[dict[str, Any]], str]:
    """Start the real server over stdio and issue JSON-RPC requests.

    ``launcher`` replaces the default launcher source (``python -c``): an
    extension test starts its own ``main(...)`` call that way.

    Parameters
    ----------
    requests : list of (method, params)
        e.g. ``("tools/call", {"name": ..., "arguments": {...}})``.
    stubs : str
        ``"stub"`` (default), ``"hide:<module>[,<module>]"`` or ``""`` (real tools).

    Returns
    -------
    tuple
        Raw stdout lines, the response of each request (in order), and stderr.
    """
    child_env = dict(os.environ)
    child_env["EXORAD_MCP_EXEC_BACKEND"] = "inline"
    child_env["EXORAD_TEST_STUBS"] = stubs
    child_env.update(env or {})
    messages: list[dict[str, Any]] = [
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]
    for index, (method, params) in enumerate(requests, start=1):
        messages.append(
            {"jsonrpc": "2.0", "id": index, "method": method, "params": params}
        )
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            launcher or _LAUNCHER,
            "--repo-root",
            str(repo_root),
            "--work-dir",
            str(work_dir),
            *extra_args,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=child_env,
        cwd=str(work_dir.parent),
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None
    stderr_chunks: list[str] = []
    stderr_thread = threading.Thread(
        target=lambda: stderr_chunks.append(proc.stderr.read()), daemon=True
    )
    stderr_thread.start()
    # Close the pipe only after every answer arrived: EOF cancels in-flight calls.
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    lines: list[str] = []
    results: dict[int, dict[str, Any]] = {}
    try:
        for message in messages:
            proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()
        wanted = set(range(1, len(requests) + 1))
        while wanted:
            line = proc.stdout.readline()
            if not line:
                break
            if not line.strip():
                continue
            lines.append(line.rstrip("\n"))
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("id") in wanted:
                results[message["id"]] = message
                wanted.discard(message["id"])
        proc.stdin.close()
        # Anything still written before exit also counts as stdout output.
        lines.extend(
            row.rstrip("\n") for row in proc.stdout.read().splitlines() if row.strip()
        )
        proc.wait(timeout=30)
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
        stderr_thread.join(timeout=5)
    ordered = [results.get(i, {}) for i in range(1, len(requests) + 1)]
    return lines, ordered, "".join(stderr_chunks)


def run_stdio_session(
    calls: list[tuple[str, dict[str, Any]]], **kwargs: Any
) -> tuple[list[str], list[dict[str, Any]], str]:
    """Like :func:`run_stdio_requests` for ``tools/call`` requests only."""
    return run_stdio_requests(
        [("tools/call", {"name": n, "arguments": a}) for n, a in calls], **kwargs
    )


def result_text(message: dict[str, Any]) -> str:
    """Concatenate the text content of a ``tools/call`` response."""
    result = message.get("result") or {}
    parts = [c.get("text", "") for c in result.get("content", [])]
    if "error" in message:
        parts.append(json.dumps(message["error"]))
    return "\n".join(parts)
