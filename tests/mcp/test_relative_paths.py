"""Audit #4 and #5 for ``run_pipeline``: relative paths and "the config's own paths".

A relative payload / target list is looked up in the work dir first and then in the
content root; a file that is missing or outside the sandbox fails BEFORE a job is
submitted; and the job opens the very files that validation opened, whatever the
server's working directory is.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from payload_fixtures import REPO_ROOT
from run_fixtures import HEADER, FakeJobs, make_project, work_dir_of

from exorad.mcp import configuration, jobs, rules, tools_run
from exorad.mcp.sandbox import PathNotAllowedError, Sandbox


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeJobs:
    recorder = FakeJobs()
    monkeypatch.setattr(jobs, "JOBS", recorder)
    return recorder


def test_run_pipeline_payload_resolved_from_work_dir(
    tmp_path: Path, fake: FakeJobs
) -> None:
    payload, targets = make_project(tmp_path)
    result = tools_run.run_pipeline(payload, targets)
    assert result["payload"] == f"work:{payload}"
    assert result["target_list"] == f"work:{targets}"


def test_work_dir_wins_over_the_content_root(tmp_path: Path, fake: FakeJobs) -> None:
    mine = work_dir_of(tmp_path) / "examples" / "test_target.csv"
    mine.parent.mkdir(parents=True)
    mine.write_text(f"{HEADER}\nonly,1,5000,1,20\n")
    payload, _ = make_project(tmp_path)
    tools_run.run_pipeline(payload, "examples/test_target.csv")
    assert fake.specs[0]["expected_targets"] == ["only"]
    assert Path(fake.specs[0]["target_list"]) == mine


def test_content_root_is_the_fallback(tmp_path: Path, fake: FakeJobs) -> None:
    tools_run.run_pipeline("examples/payload_example.xml", "examples/test_target.csv")
    assert (
        Path(fake.specs[0]["target_list"]) == REPO_ROOT / "examples" / "test_target.csv"
    )


def test_server_working_directory_does_not_matter(
    tmp_path: Path, fake: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "somewhere" / "else"
    elsewhere.mkdir(parents=True)
    monkeypatch.chdir(elsewhere)
    tools_run.run_pipeline("examples/payload_example.xml", "examples/test_target.csv")
    root = ET.parse(fake.specs[0]["payload"]).getroot()
    config_path = Path(root.findtext("ConfigPath", "").strip())
    assert config_path == REPO_ROOT, "the examples are written for a repo-root cwd"
    assert Path.cwd() == elsewhere


def test_run_pipeline_missing_payload_fails_before_submit(
    tmp_path: Path, fake: FakeJobs
) -> None:
    _, targets = make_project(tmp_path)
    with pytest.raises(FileNotFoundError, match=r"nothing.xml"):
        tools_run.run_pipeline("proj/nothing.xml", targets)
    assert fake.specs == []
    assert not (work_dir_of(tmp_path) / "runs").exists()


def test_run_pipeline_missing_target_list_fails_before_submit(
    tmp_path: Path, fake: FakeJobs
) -> None:
    payload, _ = make_project(tmp_path)
    with pytest.raises(FileNotFoundError, match=r"nothing.csv"):
        tools_run.run_pipeline(payload, "proj/nothing.csv")
    assert fake.specs == []
    assert not (work_dir_of(tmp_path) / "runs").exists()


@pytest.mark.parametrize("target", ["/etc/passwd.csv", "../../outside.csv"])
def test_run_pipeline_target_list_outside_sandbox_rejected(
    tmp_path: Path, fake: FakeJobs, target: str
) -> None:
    payload, _ = make_project(tmp_path)
    with pytest.raises(PathNotAllowedError, match="outside"):
        tools_run.run_pipeline(payload, target)
    assert fake.specs == []


@pytest.mark.parametrize("payload", ["/etc/payload.xml", "../../outside.xml"])
def test_run_pipeline_payload_outside_sandbox_rejected(
    tmp_path: Path, fake: FakeJobs, payload: str
) -> None:
    _, targets = make_project(tmp_path)
    with pytest.raises(PathNotAllowedError, match="outside"):
        tools_run.run_pipeline(payload, targets)
    assert fake.specs == []


def test_symlink_out_of_the_sandbox_is_rejected(tmp_path: Path, fake: FakeJobs) -> None:
    payload, targets = make_project(tmp_path)
    secret = tmp_path / "secret" / "payload.xml"
    secret.parent.mkdir()
    secret.write_text((work_dir_of(tmp_path) / payload).read_text())
    link = work_dir_of(tmp_path) / "link.xml"
    link.symlink_to(secret)
    with pytest.raises(PathNotAllowedError, match="resolves outside"):
        tools_run.run_pipeline("link.xml", targets)
    assert fake.specs == []


def test_wrong_suffixes_are_refused_before_the_file_is_read(
    tmp_path: Path, fake: FakeJobs
) -> None:
    payload, targets = make_project(tmp_path)
    with pytest.raises(ValueError, match=r"\.xml"):
        tools_run.run_pipeline(targets, targets)
    with pytest.raises(ValueError, match=r"\.csv"):
        tools_run.run_pipeline(payload, payload)
    with pytest.raises(ValueError, match=r"\.csv"):
        tools_run.run_pipeline(payload, "proj/targets.xlsx")
    assert fake.specs == []


def test_a_directory_is_not_a_payload(tmp_path: Path, fake: FakeJobs) -> None:
    _, targets = make_project(tmp_path)
    (work_dir_of(tmp_path) / "dir.xml").mkdir()
    with pytest.raises(PathNotAllowedError, match="not a regular file"):
        tools_run.run_pipeline("dir.xml", targets)


def test_oversized_inputs_are_refused(
    tmp_path: Path, fake: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload, _targets = make_project(tmp_path)
    big = work_dir_of(tmp_path) / "proj" / "big.csv"
    big.write_text(HEADER + "\n" + "x" * (3 * 1_048_576))
    with pytest.raises(PathNotAllowedError, match="MB"):
        tools_run.run_pipeline(payload, "proj/big.csv")


def test_job_opens_the_same_files_as_validate_config(
    tmp_path: Path, fake: FakeJobs
) -> None:
    """Audit #5: validation and the job read exactly the same files."""
    payload, targets = make_project(tmp_path)
    box = Sandbox.from_env()
    validated = configuration.validate_configuration_file(
        payload, "payload", sandbox=box
    )
    assert validated["valid"], validated["findings"]
    tools_run.run_pipeline(payload, targets)
    root = ET.parse(fake.specs[0]["payload"]).getroot()
    opened = set()
    for element in root.iter():
        text = (element.text or "").strip()
        if element.tag in rules.PATH_TAGS and text and os.path.isabs(text):
            if not Path(text).is_file():
                continue  # e.g. StellarModels, unused by the custom source
            opened.add(box.display_path(text))
    referenced = {ref["path"] for ref in validated["referenced_files"] if ref["exists"]}
    assert referenced, "the example references tables"
    assert referenced <= opened, (
        f"validation saw files the job does not open: {referenced - opened}"
    )
    # no relative path is left in the copy that a different cwd could resolve elsewhere
    for element in root.iter():
        text = (element.text or "").strip()
        if element.tag in rules.PATH_TAGS and text:
            assert os.path.isabs(text), f"<{element.tag}> is still relative: {text}"


def test_user_payload_in_the_work_dir_uses_its_own_directory(
    tmp_path: Path, fake: FakeJobs
) -> None:
    """A payload under `<work>` must not be mistaken for a shipped example."""
    payload, targets = make_project(tmp_path)
    tools_run.run_pipeline(payload, targets)
    root = ET.parse(fake.specs[0]["payload"]).getroot()
    assert (
        Path(root.findtext("ConfigPath", "").strip()) == work_dir_of(tmp_path) / "proj"
    )
