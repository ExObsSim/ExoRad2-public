"""The four execution tools through the real stdio server (real tool modules, no stubs)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from run_fixtures import make_project, work_dir_of
from stdio_helper import result_text, run_stdio_session

if TYPE_CHECKING:
    from pathlib import Path

pytest.importorskip("mcp")

RUN_TOOLS = {"run_pipeline", "get_job_status", "cancel_job", "list_jobs"}


def _session(tmp_path: Path, calls: list[tuple[str, dict]], **kwargs):
    return run_stdio_session(calls, work_dir=work_dir_of(tmp_path), stubs="", **kwargs)


def test_the_four_run_tools_are_registered(tmp_path: Path) -> None:
    _lines, results, _ = _session(tmp_path, [("capabilities", {})])
    data = json.loads(result_text(results[0]))
    unavailable = {item["tool"] for item in data["tools"]["unavailable"]}
    assert not (RUN_TOOLS & unavailable)
    assert set(data["tools"]["execution_only"]) >= RUN_TOOLS


def test_error_text_reaches_the_client(tmp_path: Path) -> None:
    payload, targets = make_project(tmp_path)
    existing = work_dir_of(tmp_path) / "results" / "out.h5"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"old")
    calls = [
        ("run_pipeline", {"payload": "proj/missing.xml", "target_list": targets}),
        (
            "run_pipeline",
            {"payload": payload, "target_list": targets, "output": "results/out.h5"},
        ),
        ("get_job_status", {"job_id": "nope"}),
        ("list_jobs", {}),
    ]
    lines, results, _ = _session(tmp_path, calls)
    assert all(json.loads(line) for line in lines), "stdout carries only JSON-RPC"
    missing = result_text(results[0])
    assert "Error executing tool run_pipeline" in missing
    assert "missing.xml" in missing
    refused = result_text(results[1])
    assert "Error executing tool run_pipeline" in refused
    assert "overwrite=True" in refused
    assert existing.read_bytes() == b"old"
    unknown = json.loads(result_text(results[2]))
    assert unknown["status"] == "unknown"
    assert unknown["error"] == "Unknown job id: nope"
    assert json.loads(result_text(results[3]))["count"] == 0


def test_sed_refusal_text_reaches_the_client(tmp_path: Path) -> None:
    from payload_fixtures import find

    def edit(root) -> None:
        find(root, "common/sourceSpectrum").text = "sed"

    payload, targets = make_project(tmp_path, edit=edit)
    _, results, _ = _session(
        tmp_path,
        [
            (
                "run_pipeline",
                {"payload": payload, "target_list": targets, "n_threads": 2},
            )
        ],
    )
    text = result_text(results[0])
    assert "Error executing tool run_pipeline" in text
    assert "SOURCE_SED_BLOCKED" in text
