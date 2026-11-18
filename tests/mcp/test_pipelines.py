"""Unit tests of the pipeline wrapper (preflight, job spec, reports); no process is spawned.

``jobs.JOBS`` is replaced by a recorder, so every test looks at what WOULD reach the
job child. The real spawned runs are in ``test_real_run.py``.
"""

from __future__ import annotations

import inspect
import json
import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import h5py
import numpy as np
import pytest
from payload_fixtures import REPO_ROOT, find
from run_fixtures import FakeJobs, make_project, work_dir_of

from exorad.mcp import jobs, pipelines, rules, tools_run
from exorad.mcp.sandbox import PathNotAllowedError, Sandbox


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeJobs:
    recorder = FakeJobs()
    monkeypatch.setattr(jobs, "JOBS", recorder)
    return recorder


def _runs(tmp_path: Path) -> list[Path]:
    runs = work_dir_of(tmp_path) / "runs"
    return sorted(runs.iterdir()) if runs.is_dir() else []


# -- argument whitelist ----------------------------------------------------------------
def test_run_pipeline_signature_is_the_whitelist() -> None:
    params = list(inspect.signature(tools_run.run_pipeline).parameters)
    assert params == [
        "payload",
        "target_list",
        "output",
        "n_threads",
        "plot",
        "full_contrib",
        "overwrite",
        "wait_seconds",
        "max_runtime_seconds",
        "pipeline",
    ]


def test_job_spec_carries_only_the_whitelisted_keys(
    tmp_path: Path, fake: FakeJobs
) -> None:
    payload, targets = make_project(tmp_path)
    tools_run.run_pipeline(
        payload, targets, plot=True, full_contrib=True, overwrite=True
    )
    spec = fake.specs[0]
    assert set(spec) == {
        "entry",
        "pipeline",
        "payload",
        "target_list",
        "output",
        "n_thread",
        "plot",
        "full_contrib",
        "replace",
        "expected_targets",
        "max_output_bytes",
        "sandbox",
    }
    assert spec["entry"] == "exorad.mcp.pipelines:run_standard"
    assert spec["plot"] is True
    assert spec["full_contrib"] is True
    # `debug` and `log` are not exposed: the child fixes them (H12)
    assert "debug" not in spec
    assert "log" not in spec


def test_overwrite_maps_to_replace(tmp_path: Path, fake: FakeJobs) -> None:
    payload, targets = make_project(tmp_path)
    tools_run.run_pipeline(payload, targets)
    tools_run.run_pipeline(payload, targets, overwrite=True)
    assert [spec["replace"] for spec in fake.specs] == [False, True]


def test_unknown_pipeline_is_refused(tmp_path: Path, fake: FakeJobs) -> None:
    payload, targets = make_project(tmp_path)
    with pytest.raises(ValueError, match="unknown pipeline 'bogus'"):
        tools_run.run_pipeline(payload, targets, pipeline="bogus")
    assert fake.specs == []


# -- the normalised copy -------------------------------------------------------------------
def test_job_receives_the_normalised_copy_validation_opened(
    tmp_path: Path, fake: FakeJobs
) -> None:
    payload, targets = make_project(tmp_path)
    before = Path.cwd()
    tools_run.run_pipeline(payload, targets)
    assert Path.cwd() == before, "the wrapper must not chdir"
    spec = fake.specs[0]
    copy = Path(spec["payload"])
    original = work_dir_of(tmp_path) / payload
    assert copy != original
    assert copy.is_absolute()
    assert copy.is_relative_to(work_dir_of(tmp_path) / "runs")
    # exactly what validation writes for the same payload: same bytes
    box = Sandbox.from_env()
    again = rules.normalise_payload(original, sandbox=box, dest_dir=tmp_path / "again")
    assert again.path is not None
    assert copy.read_bytes() == again.path.read_bytes()
    # and every path in the copy is absolute and exists (no cwd-dependent file left)
    root = ET.parse(copy).getroot()
    assert Path(root.findtext("ConfigPath", "").strip()).is_absolute()
    tables = list(root.iter("datafile"))
    assert tables
    for element in tables:
        path = Path((element.text or "").strip())
        assert path.is_absolute()
        assert path.is_file()


def test_relative_datafile_without_keyword_is_absolute_in_the_copy(
    tmp_path: Path, fake: FakeJobs
) -> None:
    """The ablation of spec 2.1: a value without `__ConfigPath__` is cwd-dependent."""

    def edit(root: ET.Element) -> None:
        find(root, "channel[Spec]/detector/qe/datafile").text = "examples/QE.csv"

    payload, targets = make_project(tmp_path, edit=edit)
    tools_run.run_pipeline(payload, targets)
    root = ET.parse(fake.specs[0]["payload"]).getroot()
    qe = find(root, "channel[Spec]/detector/qe/datafile")
    assert Path(qe.text or "") == work_dir_of(tmp_path) / "proj" / "examples" / "QE.csv"


# -- network and code execution refusals (decision D3) --------------------------------------
def _sed_edit(root: ET.Element) -> None:
    find(root, "common/sourceSpectrum").text = "sed"


@pytest.mark.parametrize("n_threads", [1, 2])
def test_sed_source_is_refused_before_any_job(
    tmp_path: Path, fake: FakeJobs, n_threads: int
) -> None:
    """With n_threads=2 the pool workers are not covered by netguard: this is the control."""
    payload, targets = make_project(tmp_path, edit=_sed_edit)
    with pytest.raises(rules.ConfigRuleError, match="SOURCE_SED_BLOCKED"):
        tools_run.run_pipeline(payload, targets, n_threads=n_threads)
    assert fake.specs == []
    assert _runs(tmp_path) == [], "a refused run must leave no run directory"


def test_url_in_a_data_path_is_refused(tmp_path: Path, fake: FakeJobs) -> None:
    def edit(root: ET.Element) -> None:
        find(
            root, "channel[Spec]/detector/qe/datafile"
        ).text = "http://example.org/qe.csv"

    payload, targets = make_project(tmp_path, edit=edit)
    with pytest.raises(rules.ConfigRuleError, match="URL"):
        tools_run.run_pipeline(payload, targets, n_threads=2)
    assert fake.specs == []


def test_error_findings_are_listed_one_per_line(tmp_path: Path, fake: FakeJobs) -> None:
    def edit(root: ET.Element) -> None:
        find(root, "common/sourceSpectrum").text = "sed"
        find(root, "common").remove(find(root, "common/wl_min"))

    payload, targets = make_project(tmp_path, edit=edit)
    with pytest.raises(rules.ConfigRuleError) as raised:
        tools_run.run_pipeline(payload, targets)
    lines = str(raised.value).splitlines()
    assert len(lines) >= 2
    assert any("SOURCE_SED_BLOCKED" in line for line in lines)
    assert any("MISSING_ELEMENT" in line for line in lines)
    assert str(tmp_path) not in str(raised.value), "no absolute server path in the text"


def test_bad_target_list_is_refused(tmp_path: Path, fake: FakeJobs) -> None:
    payload, targets = make_project(tmp_path, rows=["a,1,5000,1,20", "a,1,5000,1,20"])
    with pytest.raises(rules.ConfigRuleError, match="TARGET_DUPLICATE"):
        tools_run.run_pipeline(payload, targets)
    assert fake.specs == []


def test_target_count_limit(
    tmp_path: Path, fake: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXORAD_MCP_MAX_TARGETS", "2")
    payload, targets = make_project(tmp_path, n_targets=3)
    with pytest.raises(ValueError, match=r"TARGET_COUNT|above the limit"):
        tools_run.run_pipeline(payload, targets)
    assert fake.specs == []
    assert _runs(tmp_path) == []


def test_working_R_above_the_cap_is_refused(tmp_path: Path, fake: FakeJobs) -> None:
    payload, targets = make_project(tmp_path, working_R=rules.MAX_WORKING_R + 1)
    with pytest.raises(ValueError, match="working_R"):
        tools_run.run_pipeline(payload, targets)
    assert fake.specs == []


def test_execution_disabled_is_a_permission_error(
    tmp_path: Path, fake: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXORAD_MCP_NO_EXEC", "1")
    payload, targets = make_project(tmp_path)
    with pytest.raises(PermissionError, match="disabled"):
        tools_run.run_pipeline(payload, targets)
    assert fake.specs == []


# -- threads, runtime, wait ----------------------------------------------------------------
def test_n_threads_is_clamped_to_the_server_limit(
    tmp_path: Path, fake: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXORAD_MCP_MAX_THREADS", "2")
    payload, targets = make_project(tmp_path, n_targets=5)
    result = tools_run.run_pipeline(payload, targets, n_threads=64)
    assert fake.specs[0]["n_thread"] == 2
    assert result["n_threads"] == 2
    assert any("n_threads reduced from 64 to 2" in w for w in result["warnings"])


def test_n_threads_never_exceeds_the_number_of_targets(
    tmp_path: Path, fake: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXORAD_MCP_MAX_THREADS", "8")
    payload, targets = make_project(tmp_path, n_targets=2)
    tools_run.run_pipeline(payload, targets, n_threads=6)
    assert fake.specs[0]["n_thread"] == 2


@pytest.mark.parametrize("bad", [0, -1, True, 1.5])
def test_n_threads_below_one_or_not_an_integer_is_refused(
    tmp_path: Path, fake: FakeJobs, bad: object
) -> None:
    payload, targets = make_project(tmp_path)
    with pytest.raises(ValueError, match="n_threads"):
        tools_run.run_pipeline(payload, targets, n_threads=bad)  # type: ignore[arg-type]
    assert fake.specs == []


def test_negative_wait_is_refused(tmp_path: Path, fake: FakeJobs) -> None:
    payload, targets = make_project(tmp_path)
    with pytest.raises(ValueError, match="wait_seconds"):
        tools_run.run_pipeline(payload, targets, wait_seconds=-1)


def test_job_cap_is_a_returned_refusal_and_leaves_nothing(
    tmp_path: Path, fake: FakeJobs
) -> None:
    fake.raises = jobs.JobLimitError(2, ["aaa", "bbb"])
    payload, targets = make_project(tmp_path)
    result = tools_run.run_pipeline(payload, targets)
    assert result["status"] == "refused"
    assert result["limit"] == 2
    assert result["running_jobs"] == ["aaa", "bbb"]
    assert _runs(tmp_path) == []


# -- the output ---------------------------------------------------------------------------
def test_default_output_is_a_fresh_run_directory(
    tmp_path: Path, fake: FakeJobs
) -> None:
    payload, targets = make_project(tmp_path)
    result = tools_run.run_pipeline(payload, targets, plot=True)
    out = Path(fake.specs[0]["output"])
    assert out.name == "output.h5"
    assert out.parent.parent == work_dir_of(tmp_path) / "runs"
    assert result["output"].startswith("work:runs/")
    assert str(tmp_path) not in json.dumps(result), "no absolute path in the result"


def test_output_exists_without_overwrite_is_refused(
    tmp_path: Path, fake: FakeJobs
) -> None:
    payload, targets = make_project(tmp_path)
    existing = work_dir_of(tmp_path) / "results" / "out.h5"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"old")
    with pytest.raises(FileExistsError, match="overwrite=True"):
        tools_run.run_pipeline(payload, targets, output="results/out.h5")
    assert fake.specs == []
    assert existing.read_bytes() == b"old"
    tools_run.run_pipeline(payload, targets, output="results/out.h5", overwrite=True)
    assert fake.specs[0]["replace"] is True


@pytest.mark.parametrize(
    ("output", "error"),
    [
        ("../escape/out.h5", PathNotAllowedError),
        ("/etc/out.h5", PathNotAllowedError),
        ("results/out.txt", ValueError),
        ("out.h5", ValueError),  # directly in the work dir root
        ("results", ValueError),  # no suffix
        ("http://example.org/o.h5", ValueError),
    ],
)
def test_bad_output_paths_are_refused(
    tmp_path: Path, fake: FakeJobs, output: str, error: type[Exception]
) -> None:
    payload, targets = make_project(tmp_path)
    with pytest.raises(error):
        tools_run.run_pipeline(payload, targets, output=output)
    assert fake.specs == []
    assert _runs(tmp_path) == []


def test_output_dir_clash_with_another_input_is_refused(
    tmp_path: Path, fake: FakeJobs
) -> None:
    """The library copies the payload next to the output and would overwrite this file."""
    payload, targets = make_project(tmp_path)
    clash = work_dir_of(tmp_path) / "results" / "payload.xml"
    clash.parent.mkdir(parents=True)
    clash.write_text("<root>precious</root>")
    with pytest.raises(FileExistsError, match=r"payload.xml"):
        tools_run.run_pipeline(payload, targets, output="results/out.h5")
    assert clash.read_text() == "<root>precious</root>"


def test_output_in_the_payload_directory_is_refused_because_of_the_copy(
    tmp_path: Path, fake: FakeJobs
) -> None:
    """Everything in one directory is the natural layout, and the unsafe one."""
    payload, targets = make_project(tmp_path)
    original = (work_dir_of(tmp_path) / payload).read_bytes()
    with pytest.raises(FileExistsError, match=r"payload.xml"):
        tools_run.run_pipeline(payload, targets, output="proj/out.h5")
    assert (work_dir_of(tmp_path) / payload).read_bytes() == original


def test_output_next_to_the_target_list_itself_is_allowed(
    tmp_path: Path, fake: FakeJobs
) -> None:
    """The target list is copied onto itself (a no-op), not onto another file."""
    payload, _ = make_project(tmp_path, name="a")
    _, targets = make_project(tmp_path, name="b")
    (work_dir_of(tmp_path) / "b" / "payload.xml").unlink()
    tools_run.run_pipeline(payload, targets, output="b/out.h5")
    assert Path(fake.specs[0]["output"]) == work_dir_of(tmp_path) / "b" / "out.h5"


def test_files_listed_are_those_the_run_produces(
    tmp_path: Path, fake: FakeJobs
) -> None:
    payload, targets = make_project(tmp_path, rows=["a b(1),1,5000,1,20"])
    result = tools_run.run_pipeline(payload, targets, plot=True)
    plan = pipelines.registered_run(result["job_id"])
    assert plan is not None
    out_dir = plan.output.parent
    for name in ("output.h5", "efficiency.png", "a b(1).png", "unrelated.txt"):
        (out_dir / name).write_bytes(b"x")
    names = [f["name"] for f in pipelines.list_files(plan, Sandbox.from_env())]
    assert names == ["output.h5", "efficiency.png", "a b(1).png"]


# -- the size estimate (H11) ---------------------------------------------------------------
#: (working_R, n_targets, n_channels, result rows, full_contrib, measured bytes):
#: real runs of examples/payload_example.xml with the demo SED (the Spec channel
#: has 13 rows at targetR=20, the Phot channel 1), standard_pipeline, 2026-11-11.
MEASURED_RUNS = [
    (1000, 1, 2, 14, False, 2461588),
    (1000, 3, 2, 14, False, 2856300),
    (3000, 1, 2, 14, False, 3821588),
    (3000, 3, 2, 14, False, 4504300),
    (6000, 1, 2, 14, False, 5861588),
    (6000, 3, 2, 14, False, 6976300),
    (6000, 3, 2, 14, True, 7075020),
    (6000, 1, 1, 1, False, 3554576),  # photometer only
    (6000, 3, 1, 1, False, 4642704),
    (6000, 1, 1, 13, False, 3226384),  # spectrometer only
    (6000, 3, 1, 13, False, 4336480),
]


@pytest.mark.parametrize(
    ("working_R", "n_targets", "n_channels", "bins", "full", "measured"), MEASURED_RUNS
)
def test_estimate_matches_measurements(
    working_R: int,
    n_targets: int,
    n_channels: int,
    bins: int,
    full: bool,
    measured: int,
) -> None:
    estimate = pipelines.estimate_output_mb(
        n_targets, working_R, n_channels, spectral_bins=bins, full_contrib=full
    )
    actual = measured / 1_048_576
    assert estimate >= actual, "the estimate must not be below the real size"
    assert estimate <= 1.6 * actual, "and must not be wildly above it"


def test_estimate_scales_with_working_R() -> None:
    sizes = [
        pipelines.estimate_output_mb(100, working_R, 2)
        for working_R in (1000, 6000, 30000)
    ]
    assert sizes[0] < sizes[1] < sizes[2]
    assert sizes[2] > 3.5 * sizes[1], "x5 the grid is nearly x5 the file (H11)"
    # linear in the number of targets
    one = pipelines.estimate_output_mb(1, 6000, 2)
    hundred = pipelines.estimate_output_mb(101, 6000, 2)
    assert hundred - one == pytest.approx(
        100 * (pipelines.estimate_output_mb(2, 6000, 2) - one)
    )


def test_estimate_grows_with_channels_and_bins() -> None:
    assert pipelines.estimate_output_mb(10, 6000, 4) > pipelines.estimate_output_mb(
        10, 6000, 2
    )
    assert pipelines.estimate_output_mb(
        10, 6000, 2, spectral_bins=5000
    ) > 2 * pipelines.estimate_output_mb(10, 6000, 2, spectral_bins=14)


def test_count_spectral_bins(tmp_path: Path) -> None:
    payload, _ = make_project(tmp_path)
    path = work_dir_of(tmp_path) / payload
    assert pipelines.count_spectral_bins(path) == 1 + 13  # photometer + targetR=20
    root = ET.parse(path).getroot()
    find(root, "channel[Spec]/targetR").text = "200"
    ET.ElementTree(root).write(tmp_path / "r200.xml")
    expected = math.ceil(math.log(1.95 / 1.1) / math.log1p(1 / 200)) + 1
    assert pipelines.count_spectral_bins(tmp_path / "r200.xml") == 1 + expected
    find(root, "channel[Spec]/targetR").text = "native"
    ET.ElementTree(root).write(tmp_path / "native.xml")
    assert pipelines.count_spectral_bins(tmp_path / "native.xml") == (
        1 + pipelines.ASSUMED_NATIVE_BINS
    )


def test_preflight_refuses_estimated_oversize(
    tmp_path: Path, fake: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXORAD_MCP_MAX_OUTPUT_MB", "4")
    small, targets = make_project(tmp_path, name="small", n_targets=1, working_R=1000)
    big, _ = make_project(tmp_path, name="big", n_targets=1, working_R=6000)
    tools_run.run_pipeline(small, targets)  # about 3.6 MB padded: fits
    assert len(fake.specs) == 1
    with pytest.raises(ValueError, match=r"estimated output is .* MB"):
        tools_run.run_pipeline(big, "big/targets.csv")
    assert len(fake.specs) == 1
    assert fake.specs[0]["max_output_bytes"] == 4 * 1_048_576


def test_many_targets_are_refused_by_the_size_estimate(
    tmp_path: Path, fake: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXORAD_MCP_MAX_OUTPUT_MB", "50")
    payload, targets = make_project(tmp_path, n_targets=150, working_R=6000)
    with pytest.raises(ValueError, match="estimated output"):
        tools_run.run_pipeline(payload, targets)
    payload, targets = make_project(tmp_path, name="few", n_targets=20, working_R=6000)
    tools_run.run_pipeline(payload, targets)


# -- runtime ----------------------------------------------------------------------------
def test_runtime_is_clamped_to_the_server_cap(
    tmp_path: Path, fake: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXORAD_MCP_MAX_RUNTIME", "100")
    payload, targets = make_project(tmp_path)
    tools_run.run_pipeline(payload, targets, max_runtime_seconds=10_000)
    tools_run.run_pipeline(payload, targets, max_runtime_seconds=30)
    tools_run.run_pipeline(payload, targets)
    assert [kw["max_runtime"] for kw in fake.kwargs] == [100.0, 30.0, 100.0]


def test_a_clamped_runtime_is_reported(
    tmp_path: Path, fake: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXORAD_MCP_MAX_RUNTIME", "100")
    payload, targets = make_project(tmp_path)
    clamped = tools_run.run_pipeline(payload, targets, max_runtime_seconds=10_000)
    assert any(
        "max_runtime_seconds" in w and "100" in w and "EXORAD_MCP_MAX_RUNTIME" in w
        for w in clamped["warnings"]
    ), clamped["warnings"]
    fine = tools_run.run_pipeline(payload, targets, max_runtime_seconds=30)
    assert not any("max_runtime_seconds" in w for w in fine["warnings"])


@pytest.mark.parametrize("bad", [0, -5])
def test_non_positive_runtime_is_refused(
    tmp_path: Path, fake: FakeJobs, bad: float
) -> None:
    payload, targets = make_project(tmp_path)
    with pytest.raises(ValueError, match="positive"):
        tools_run.run_pipeline(payload, targets, max_runtime_seconds=bad)
    assert fake.specs == []


# -- run_standard, the job entry (the library is replaced; no process) ----------------------
def _fake_pipeline(
    monkeypatch: pytest.MonkeyPatch, written: list[str], boom: bool = False
):
    calls: list[dict] = []

    def standard_pipeline(**kwargs: object) -> None:
        calls.append(kwargs)
        out = Path(str(kwargs["output"]))
        out.parent.mkdir(parents=True, exist_ok=True)
        with h5py.File(out, "w") as handle:
            chans = handle.create_group("payload/channels/Phot")
            chans.create_dataset("Phot", data=np.zeros(1))
            for name in written:
                handle.create_group(f"targets/{name}")
        if boom:
            raise RuntimeError("no target could be observed")

    import exorad

    monkeypatch.setattr(exorad, "standard_pipeline", standard_pipeline)
    # these unit specs name files that do not exist; the re-check has its own tests
    monkeypatch.setattr(pipelines, "revalidate_inputs", lambda spec: None)
    return calls


def _spec(tmp_path: Path, expected: list[str]) -> dict:
    return {
        "pipeline": "standard",
        "payload": str(tmp_path / "payload.xml"),
        "target_list": str(tmp_path / "t.csv"),
        "output": str(tmp_path / "out" / "o.h5"),
        "n_thread": 3,
        "plot": True,
        "full_contrib": True,
        "replace": False,
        "expected_targets": expected,
    }


def test_run_standard_passes_the_whitelist_to_the_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_pipeline(monkeypatch, ["a", "b"])
    summary = pipelines.run_standard(_spec(tmp_path, ["a", "b"]))
    assert calls == [
        {
            "options": str(tmp_path / "payload.xml"),
            "target_list": str(tmp_path / "t.csv"),
            "output": str(tmp_path / "out" / "o.h5"),
            "plot": True,
            "full_contrib": True,
            "n_thread": 3,
            "debug": False,
            "log": False,
            "replace": False,
        }
    ]
    assert summary["skipped"] == []
    assert summary["targets_written"] == ["a", "b"]


def test_run_standard_reports_skipped_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E0.1 keeps the good targets; the wrapper must still say which are missing."""
    _fake_pipeline(monkeypatch, ["a", "c"])
    spec = _spec(tmp_path, ["a", "b", "c"])
    with pytest.raises(RuntimeError, match=r"targets skipped: b \(2 of 3 written\)"):
        pipelines.run_standard(spec)
    info = json.loads((tmp_path / "out" / "o.run.json").read_text())
    assert info["skipped"] == ["b"]
    assert info["targets_written"] == ["a", "c"]
    assert info["targets_requested"] == ["a", "b", "c"]
    assert str(tmp_path) not in json.dumps(info), "run.json carries no absolute path"


def test_run_standard_writes_run_json_when_the_library_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_pipeline(monkeypatch, [], boom=True)
    with pytest.raises(RuntimeError, match="no target could be observed"):
        pipelines.run_standard(_spec(tmp_path, ["a"]))
    info = json.loads((tmp_path / "out" / "o.run.json").read_text())
    assert info["skipped"] == ["a"]
    assert "no target could be observed" in info["error"]


# -- job reports ---------------------------------------------------------------------------
def _plan_with_run_json(tmp_path: Path, requested: list[str], written: list[str]):
    payload, targets = make_project(tmp_path, n_targets=len(requested))
    box = Sandbox.from_env()
    plan = pipelines.plan_run(payload, targets, sandbox=box)
    plan.output.parent.mkdir(parents=True, exist_ok=True)
    plan.output.write_bytes(b"hdf5")
    pipelines.run_json_path(plan.output).write_text(
        json.dumps(
            {
                "targets_requested": requested,
                "targets_written": written,
                "skipped": [n for n in requested if n not in written],
                "channels": [{"name": "Phot", "n_bins": 1}],
                "runtime_s": 1.0,
            }
        )
    )
    pipelines.register_run("jobx", plan)
    return plan


def test_a_failed_job_with_good_targets_is_a_partial_outcome(tmp_path: Path) -> None:
    _plan_with_run_json(tmp_path, ["t0", "t1", "t2"], ["t0", "t2"])
    status = {
        "job_id": "jobx",
        "status": "failed",
        "output": "x",
        "reason": "exit code 1",
    }
    result = pipelines.describe_job(status)
    assert result["status"] == "failed"
    assert result["outcome"] == "partial"
    assert result["skipped_targets"] == ["t1"]
    assert result["summary"]["targets_written"] == 2
    assert result["summary"]["targets_requested"] == 3
    assert any("skipped: t1" in w for w in result["warnings"])
    names = [f["name"] for f in result["files"]]
    assert "output.h5" in names
    assert "output.run.json" in names
    assert all(f["path"].startswith("work:") for f in result["files"])


def test_a_failed_job_without_any_target_is_failed_not_partial(tmp_path: Path) -> None:
    _plan_with_run_json(tmp_path, ["t0"], [])
    result = pipelines.describe_job(
        {"job_id": "jobx", "status": "failed", "output": "x"}
    )
    assert result["outcome"] == "failed"
    assert result["skipped_targets"] == ["t0"]


def test_a_succeeded_job_is_complete_with_a_summary(tmp_path: Path) -> None:
    _plan_with_run_json(tmp_path, ["t0", "t1"], ["t0", "t1"])
    result = pipelines.describe_job(
        {"job_id": "jobx", "status": "succeeded", "output": "x"}
    )
    assert result["outcome"] == "complete"
    assert "skipped_targets" not in result
    assert result["summary"]["target_names"] == ["t0", "t1"]
    assert result["summary"]["channels"] == [{"name": "Phot", "n_bins": 1}]


def test_a_cancelled_job_warns_that_the_output_is_incomplete(tmp_path: Path) -> None:
    _plan_with_run_json(tmp_path, ["t0"], [])
    plan = pipelines.registered_run("jobx")
    assert plan is not None
    pipelines.run_json_path(plan.output).unlink()
    result = pipelines.describe_job(
        {"job_id": "jobx", "status": "cancelled", "output": "x"}
    )
    assert result["outcome"] == "cancelled"
    assert any("incomplete" in w for w in result["warnings"])


def test_get_job_status_unknown_id_has_no_doubled_quotes() -> None:
    result = tools_run.get_job_status("nope")
    assert result["status"] == "unknown"
    assert result["job_id"] == "nope"
    assert result["error"] == "Unknown job id: nope"
    assert tools_run.cancel_job("nope")["status"] == "unknown"


def test_list_jobs_has_an_outcome_per_job(tmp_path: Path, fake: FakeJobs) -> None:
    payload, targets = make_project(tmp_path)
    tools_run.run_pipeline(payload, targets)
    tools_run.run_pipeline(payload, targets)
    listing = tools_run.list_jobs()
    assert listing["count"] == 2
    assert [item["outcome"] for item in listing["jobs"]] == ["running", "running"]


def test_cancel_job_returns_the_cancelled_status(
    tmp_path: Path, fake: FakeJobs
) -> None:
    payload, targets = make_project(tmp_path)
    started = tools_run.run_pipeline(payload, targets)
    result = tools_run.cancel_job(started["job_id"])
    assert result["status"] == "cancelled"
    assert result["outcome"] == "cancelled"


def test_example_from_the_content_root_plans_with_absolute_paths(
    tmp_path: Path, fake: FakeJobs
) -> None:
    tools_run.run_pipeline("examples/payload_example.xml", "examples/test_target.csv")
    spec = fake.specs[0]
    assert Path(spec["target_list"]) == REPO_ROOT / "examples" / "test_target.csv"
    assert spec["expected_targets"] == ["myTest", "myTest2"]
    root = ET.parse(spec["payload"]).getroot()
    assert os.path.isabs(root.findtext("ConfigPath", "").strip())
    sed = find(root, "common/sourceSpectrum/CustomSed").text or ""
    assert Path(sed) == REPO_ROOT / "examples" / "customsed.csv"
