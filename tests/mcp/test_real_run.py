"""Real pipeline runs through the spawned-child backend (no stubs).

The example payload with the demo SED and a small ``working_R`` (see
``run_fixtures.make_project``). One run lives in the default path; the others are
``slow``. Work dirs live under ``tmp_path``; nothing is written into the checkout.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from run_fixtures import HEADER, make_project, target_rows, work_dir_of

from exorad.mcp import jobs, pipelines, targets, tools_output, tools_run

WAIT = 300.0


@pytest.fixture(autouse=True)
def _spawned_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXORAD_MCP_EXEC_BACKEND", "process")
    monkeypatch.setenv("EXORAD_MCP_MAX_THREADS", "2")
    yield
    jobs.JOBS.shutdown()


def _finish(job_id: str, timeout: float = WAIT) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = tools_run.get_job_status(job_id)
        if status["status"] != "running":
            return status
        time.sleep(0.5)
    raise AssertionError(f"job {job_id} did not finish")


def _finish_raw(job_id: str, timeout: float = WAIT) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = jobs.JOBS.status(job_id)
        if status["status"] != "running":
            return status
        time.sleep(0.5)
    raise AssertionError(f"job {job_id} did not finish")


def test_real_run_succeeds_and_the_output_is_readable(tmp_path: Path) -> None:
    payload, targets_csv = make_project(tmp_path, n_targets=1)
    started = time.time()
    first = tools_run.run_pipeline(
        payload, targets_csv, output="results/out.h5", wait_seconds=WAIT
    )
    elapsed = time.time() - started
    print(f"real run took {elapsed:.1f} s")
    assert first["status"] == "succeeded", first
    assert first["outcome"] == "complete"
    assert first["targets_done"] == 1, "one `observed` line per finished target"
    assert first["targets_started"] == 1
    assert first["summary"]["targets_written"] == 1
    assert first["summary"]["target_names"] == ["t0"]
    assert {c["name"] for c in first["summary"]["channels"]} == {"Phot", "Spec"}
    names = [f["name"] for f in first["files"]]
    assert "out.h5" in names
    assert "out.run.json" in names
    out = work_dir_of(tmp_path) / "results" / "out.h5"
    assert out.is_file()
    # the estimate must cover the real size
    assert first["estimated_output_mb"] >= out.stat().st_size / 1_048_576
    # the log shows no absolute path and no double count
    status = tools_run.get_job_status(first["job_id"])
    assert status["status"] == "succeeded"
    assert str(tmp_path) not in json.dumps(status)

    # the output tools read it
    inspected = tools_output.inspect_output("results/out.h5")
    assert inspected["exorad"]["targets"] == ["t0"]
    # round trip: the display form returned by run_pipeline is accepted back
    for shown in (
        first["output"],
        *(f["path"] for f in first["files"] if f["name"] == "out.h5"),
    ):
        assert shown.startswith("work:"), shown
        assert tools_output.inspect_output(shown)["exorad"]["targets"] == ["t0"]
        assert tools_output.explain_output(shown)["unexplained"] == []
    explained = tools_output.explain_output("results/out.h5")
    assert explained["unexplained"] == []

    # a second run onto the same output is refused, and with overwrite it works
    with pytest.raises(FileExistsError, match="overwrite=True"):
        tools_run.run_pipeline(payload, targets_csv, output="results/out.h5")
    listing = tools_run.list_jobs()
    assert [j["job_id"] for j in listing["jobs"]] == [first["job_id"]]


@pytest.mark.slow
def test_real_run_with_two_worker_processes_and_plots(tmp_path: Path) -> None:
    payload, targets_csv = make_project(tmp_path, n_targets=3)
    result = tools_run.run_pipeline(
        payload, targets_csv, n_threads=2, plot=True, wait_seconds=WAIT
    )
    assert result["status"] == "succeeded", result
    assert result["n_threads"] == 2
    assert result["summary"]["targets_written"] == 3
    assert result["targets_done"] == 3
    names = {f["name"] for f in result["files"]}
    assert {"efficiency.png", "t0.png", "t1.png", "t2.png"} <= names
    for entry in result["files"]:
        assert entry["size_bytes"] > 0


@pytest.mark.slow
def test_a_bad_target_in_the_middle_gives_a_partial_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The library keeps the good targets (E0.1); the wrapper names the missing one.

    Static validation (rightly) rejects a target without a distance, so it is
    bypassed here to drive the child with the defect that makes the library skip.
    """
    rows = ["good1,1,5000,1,20", "bad,1,5000,1,", "good2,1.5,6000,1,10"]
    payload, targets_csv = make_project(tmp_path, rows=rows)
    real = targets.validate_target_list

    def lenient(path, *, sandbox):
        report = real(path, sandbox=sandbox)
        report.findings = []
        report.names = ["good1", "bad", "good2"]
        report.rows = 3
        return report

    monkeypatch.setattr(pipelines.targets, "validate_target_list", lenient)
    # the child re-validates the target list (and would refuse this one): the
    # backstop test switches that off in the spec the server builds
    real_spec = pipelines.RunPlan.spec
    monkeypatch.setattr(
        pipelines.RunPlan, "spec", lambda self: {**real_spec(self), "revalidate": False}
    )
    result = tools_run.run_pipeline(payload, targets_csv, wait_seconds=WAIT)
    assert result["status"] == "failed", result
    assert result["outcome"] == "partial"
    assert result["skipped_targets"] == ["bad"]
    assert result["summary"]["target_names"] == ["good1", "good2"]
    assert (
        "targets skipped: bad" in result["reason"]
        or "targets skipped: bad" in result["log_tail"]
    )
    assert any("skipped: bad" in w for w in result["warnings"])
    # the value the server returned must be usable as is (no manual prefix stripping)
    inspected = tools_output.inspect_output(result["output"])
    assert inspected["exorad"]["targets"] == ["good1", "good2"]


@pytest.mark.slow
def test_cancel_a_long_run(tmp_path: Path) -> None:
    payload, targets_csv = make_project(tmp_path, n_targets=80, rows=target_rows(80))
    started = tools_run.run_pipeline(payload, targets_csv, wait_seconds=0)
    assert started["status"] == "running"
    log = Path(started["log_file"].replace("work:", str(work_dir_of(tmp_path)) + "/"))
    deadline = time.time() + WAIT
    while time.time() < deadline:
        if log.exists() and "observing" in log.read_text(errors="replace"):
            break
        time.sleep(0.5)
    cancelled = tools_run.cancel_job(started["job_id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["outcome"] == "cancelled"
    assert tools_run.get_job_status(started["job_id"])["status"] == "cancelled"
    assert (
        any("incomplete" in w for w in cancelled.get("warnings", []))
        or not (cancelled["files"])
    )


@pytest.mark.slow
def test_a_sed_payload_forced_past_the_static_rule_makes_no_connection(
    tmp_path: Path,
) -> None:
    """Backstop only (n_threads=1): the guard in the child blocks the downloader.

    The static refusal is the real control (see test_pipelines, n_threads=1 and 2).
    """
    import xml.etree.ElementTree as ET

    from payload_fixtures import find

    payload, targets_csv = make_project(tmp_path, n_targets=1)
    work = work_dir_of(tmp_path)
    root = ET.parse(work / payload).getroot()
    find(root, "common/sourceSpectrum").text = "sed"
    find(root, "ConfigPath").text = str(work / "proj")
    forced = work / "forced.xml"
    ET.ElementTree(root).write(forced)
    spec = {
        "entry": pipelines.ENTRY,
        "pipeline": "standard",
        "payload": str(forced),
        "target_list": str(work / targets_csv),
        "output": str(work / "forced" / "o.h5"),
        "n_thread": 1,
        "plot": False,
        "full_contrib": False,
        "replace": False,
        "expected_targets": ["t0"],
        "revalidate": False,  # the static rules would refuse this payload again
    }
    job_id = jobs.JOBS.submit(spec, log_dir=work / "logs", max_runtime=WAIT)
    final = _finish_raw(job_id)
    assert final["status"] == "succeeded", final
    log = (work / "logs" / f"{job_id}.log").read_text(errors="replace")
    # the downloader's failure is swallowed by ExoRad: the run falls back to a
    # black body, which is what the output records (nothing was downloaded)
    assert "target t0 saved" in log
    import h5py

    with h5py.File(work / "forced" / "o.h5", "r") as handle:
        model = handle["targets/t0/star/model"][()]
    text = model.decode() if isinstance(model, bytes) else str(model)
    assert "lanck" in text, text


def test_header_constant_is_the_example_header() -> None:
    assert HEADER.startswith("star name")


def test_a_table_swapped_for_a_link_after_planning_fails_the_real_child(
    tmp_path: Path,
) -> None:
    """The child re-checks its inputs: a link swapped in after planning is refused."""
    import xml.etree.ElementTree as ET

    payload, targets_csv = make_project(tmp_path, n_targets=1)
    plan = pipelines.plan_run(payload, targets_csv)
    root = ET.parse(plan.payload).getroot()
    table = Path(next(e.text.strip() for e in root.iter("datafile") if "QE" in e.text))
    decoy = table.parent / "decoy.csv"
    decoy.write_bytes(table.read_bytes())
    table.unlink()
    table.symlink_to(decoy)
    work = work_dir_of(tmp_path)
    job_id = jobs.JOBS.submit(plan.spec(), log_dir=work / "logs", max_runtime=WAIT)
    final = _finish_raw(job_id)
    assert final["status"] == "failed", final
    assert "NOT_REGULAR_FILE" in final["log_tail"]
    assert "ConfigRuleError" in final["log_tail"]
    assert str(tmp_path) not in final["log_tail"]
    assert not plan.output.exists(), "the library must not have started"
