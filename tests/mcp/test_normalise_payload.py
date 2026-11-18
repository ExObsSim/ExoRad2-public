"""The normalised copy: validation and the job open the SAME files (spec 2.1).

A relative ``<ConfigPath>`` and relative data paths are resolved by ExoRad against
the process working directory. The MCP never changes directory: ``normalise_payload``
writes a copy with absolute paths and both the validation and the job use it.
"""

from __future__ import annotations

import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from astropy.io import ascii as astropy_ascii
from payload_fixtures import (
    EXAMPLES,
    TABLES,
    codes,
    example_tree,
    find,
    make_payload,
    sandbox_for,
    write_tree,
)

from exorad.mcp import rules
from exorad.mcp.sandbox import Sandbox


@pytest.fixture
def box(tmp_path: Path) -> Sandbox:
    return sandbox_for(tmp_path)


@pytest.fixture
def udir(tmp_path: Path) -> Path:
    path = tmp_path / "work" / "user"
    path.mkdir(parents=True)
    return path


def _make_relative(root: ET.Element) -> None:
    """Rewrite every keyword path to a plain relative path (no ``__ConfigPath__``)."""
    for node in root.iter():
        if node.text and node.text.startswith("__ConfigPath__/"):
            node.text = node.text.removeprefix("__ConfigPath__/")


def _record_reads(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Log every file ``LoadOptions`` hands to the astropy table reader."""
    seen: list[Path] = []
    real = astropy_ascii.read

    def spy(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(Path(os.path.expanduser(str(path))).resolve())
        return real(path, *args, **kwargs)

    monkeypatch.setattr(astropy_ascii, "read", spy)
    return seen


def test_relative_datafile_without_configpath_matches_job(
    box: Sandbox, udir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validation (server cwd) and job (another cwd) open the same absolute files."""
    original = make_payload(udir, edit=_make_relative)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    # Without the copy the library resolves "examples/QE.csv" against the cwd: it
    # works only where that happens to be the project directory.
    monkeypatch.chdir(elsewhere)
    with pytest.raises(OSError):
        rules.load_options(original)

    norm = rules.normalise_payload(original, sandbox=box, dest_dir=tmp_path / "copy")
    assert norm.path is not None
    assert not rules.errors_of(norm.findings)

    reads = _record_reads(monkeypatch)
    monkeypatch.chdir(tmp_path)  # "the server's cwd"
    rules.load_options(norm.path)
    validation = list(reads)
    reads.clear()

    from exorad.tasks import PreparePayload

    monkeypatch.chdir(elsewhere)  # "the job's cwd"
    with rules.CONFIG_LOAD_LOCK:
        PreparePayload()(payload_file=str(norm.path), output=None)
    job = list(reads)

    expected = {
        (udir / "examples" / t).resolve() for t in TABLES if t != "customsed_demo.csv"
    }
    assert expected <= set(validation)
    assert set(validation) == set(job)
    assert all(p.is_absolute() for p in validation)


def test_copy_has_absolute_configpath_and_paths(
    box: Sandbox, udir: Path, tmp_path: Path
) -> None:
    original = make_payload(udir)
    norm = rules.normalise_payload(original, sandbox=box, dest_dir=tmp_path / "copy")
    assert norm.path == tmp_path / "copy" / "payload.xml"
    assert norm.base == udir
    root = ET.parse(norm.path).getroot()
    assert root.find("ConfigPath").text == str(udir)
    qe = find(root, "channel[Spec]/detector/qe/datafile").text
    assert qe == str(udir / "examples" / "QE.csv")
    # the original is untouched
    assert "__ConfigPath__" in original.read_text(encoding="utf-8")


def test_configpath_is_inserted_when_absent_and_unused(
    box: Sandbox, udir: Path, tmp_path: Path
) -> None:
    def strip(root: ET.Element) -> None:
        _make_relative(root)
        root.remove(root.find("ConfigPath"))

    norm = rules.normalise_payload(
        make_payload(udir, edit=strip), sandbox=box, dest_dir=tmp_path / "copy"
    )
    assert norm.path is not None
    assert ET.parse(norm.path).getroot().find("ConfigPath").text == str(udir)
    rules.load_options(norm.path)  # a datadict-free payload still parses


def test_no_copy_is_written_when_there_are_errors(
    box: Sandbox, udir: Path, tmp_path: Path
) -> None:
    path = make_payload(
        udir, edit=lambda r: setattr(find(r, "common/sourceSpectrum"), "text", "sed")
    )
    norm = rules.normalise_payload(path, sandbox=box, dest_dir=tmp_path / "copy")
    assert norm.path is None
    assert not norm.ok
    assert "SOURCE_SED_BLOCKED" in codes(norm.findings, "error")
    assert not (tmp_path / "copy").exists()


def test_copy_round_trips_through_the_loader(
    box: Sandbox, udir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = make_payload(udir)
    monkeypatch.chdir(udir)
    # relative ConfigPath "." and cwd == project dir: the library alone works
    expected = rules.load_options(original)
    norm = rules.normalise_payload(original, sandbox=box, dest_dir=tmp_path / "copy")
    monkeypatch.chdir(tmp_path)
    actual = rules.load_options(norm.path)
    assert list(actual) == list(expected)
    assert actual["common"]["wl_min"]["value"] == expected["common"]["wl_min"]["value"]
    assert len(actual["channel"]["Spec"]["wlSolution"]["data"]) == len(
        expected["channel"]["Spec"]["wlSolution"]["data"]
    )


def test_user_payload_in_mcp_runs_uses_its_own_directory(tmp_path: Path) -> None:
    """A payload kept in <content root>/mcp-runs is NOT resolved against the content root."""
    content = tmp_path / "content"
    shutil.copytree(
        EXAMPLES,
        content / "examples",
        ignore=shutil.ignore_patterns("customsed.csv", "*.ipynb", "*.pdf"),
    )
    work = content / "mcp-runs"
    project = work / "proj"
    project.mkdir(parents=True)
    path = make_payload(project)
    sb = Sandbox.from_env(repo_root=content, work_dir=work)
    norm = rules.normalise_payload(path, sandbox=sb, dest_dir=tmp_path / "copy")
    assert norm.base == project
    root = ET.parse(norm.path).getroot()
    assert root.find("ConfigPath").text == str(project)
    assert find(root, "channel[Spec]/detector/qe/datafile").text == str(
        project / "examples" / "QE.csv"
    )


def test_examples_payload_uses_content_root(tmp_path: Path) -> None:
    """The shipped examples mean '.' = the content root (they are written for a repo-root cwd)."""
    content = tmp_path / "content"
    examples = content / "examples"
    examples.mkdir(parents=True)
    for table in TABLES:
        shutil.copy2(EXAMPLES / table, examples / table)
    write_tree(example_tree(), examples / "payload_example.xml")
    sb = Sandbox.from_env(repo_root=content, work_dir=tmp_path / "work")
    norm = rules.normalise_payload(
        examples / "payload_example.xml", sandbox=sb, dest_dir=tmp_path / "copy"
    )
    assert norm.path is not None, norm.findings
    assert norm.base == content
    root = ET.parse(norm.path).getroot()
    assert root.find("ConfigPath").text == str(content)
    assert find(root, "channel[Spec]/detector/qe/datafile").text == str(
        examples / "QE.csv"
    )


def test_example_in_a_subdirectory_of_examples_uses_its_own_directory(
    tmp_path: Path,
) -> None:
    content = tmp_path / "content"
    (content / "examples" / "sub").mkdir(parents=True)
    path = content / "examples" / "sub" / "p.xml"
    path.write_text("<root/>", encoding="utf-8")
    sb = Sandbox.from_env(repo_root=content, work_dir=tmp_path / "work")
    assert rules.payload_base(path, sb) == content / "examples" / "sub"


def test_only_selected_source_keys_checked(box: Sandbox, udir: Path) -> None:
    """The example keeps /usr/local/project_data/sed in StellarModels: irrelevant for 'custom'."""

    # custom: StellarModels may be anything
    def custom(root: ET.Element) -> None:
        find(root, "common/sourceSpectrum/StellarModels").text = "/definitely/not/here"

    assert rules.static_findings(make_payload(udir, edit=custom), sandbox=box) == []

    # planck: neither CustomSed nor StellarModels is read
    def planck(root: ET.Element) -> None:
        find(root, "common/sourceSpectrum").text = "planck"
        find(
            root, "common/sourceSpectrum/CustomSed"
        ).text = "__ConfigPath__/missing.csv"

    assert (
        rules.static_findings(
            make_payload(udir, name="b.xml", edit=planck), sandbox=box
        )
        == []
    )

    # phoenix: StellarModels is read, CustomSed is not
    def phoenix(root: ET.Element) -> None:
        find(root, "common/sourceSpectrum").text = "phoenix"
        find(
            root, "common/sourceSpectrum/CustomSed"
        ).text = "__ConfigPath__/missing.csv"

    found = rules.static_findings(
        make_payload(udir, name="c.xml", edit=phoenix), sandbox=box
    )
    assert [f.path for f in found] == ["common/sourceSpectrum/StellarModels"]


def test_comment_text_is_skipped(box: Sandbox, udir: Path) -> None:
    def comments(root: ET.Element) -> None:
        note = ET.SubElement(find(root, "common"), "comment")
        note.text = (
            "see https://example.com/qe.csv or /etc/hosts or __ConfigPath__/nope.csv"
        )

    assert rules.static_findings(make_payload(udir, edit=comments), sandbox=box) == []


def test_targetR_data_is_a_path_key(box: Sandbox, udir: Path, tmp_path: Path) -> None:
    (udir / "res.tsv").write_text("W\tR\n1.0\t10\n2.0\t20\n", encoding="utf-8")

    def point(text: str):  # type: ignore[no-untyped-def]
        def edit(root: ET.Element) -> None:
            target = find(root, "channel[Spec]/targetR")
            target.text = None
            ET.SubElement(target, "data").text = text

        return edit

    good = make_payload(udir, name="good.xml", edit=point("res.tsv"))
    norm = rules.normalise_payload(good, sandbox=box, dest_dir=tmp_path / "copy")
    assert norm.path is not None, norm.findings
    data = find(ET.parse(norm.path).getroot(), "channel[Spec]/targetR/data").text
    assert data == str(udir / "res.tsv")

    outside = make_payload(udir, name="bad.xml", edit=point("/etc/hosts"))
    assert "PATH_OUTSIDE_SANDBOX" in codes(
        rules.static_findings(outside, sandbox=box), "error"
    )
    missing = make_payload(udir, name="gone.xml", edit=point("nope.tsv"))
    assert "FILE_MISSING" in codes(rules.static_findings(missing, sandbox=box), "error")


def test_data_element_outside_targetR_is_not_a_path(box: Sandbox, udir: Path) -> None:
    def other(root: ET.Element) -> None:
        ET.SubElement(find(root, "common"), "data").text = "nothing.csv"

    assert rules.static_findings(make_payload(udir, edit=other), sandbox=box) == []


def test_url_value_refused_and_loader_never_called(
    box: Sandbox, udir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A payload with a URL is rejected before the library parses (and fetches) it."""

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError(
            "LoadOptions must not be called when static findings hold errors"
        )

    monkeypatch.setattr(rules, "LoadOptions", boom)

    def url(root: ET.Element) -> None:
        find(
            root, "channel[Spec]/detector/qe/datafile"
        ).text = "http://example.com/qe.csv"

    path = make_payload(udir, edit=url)
    with pytest.raises(rules.ConfigRuleError, match="URL"):
        rules.load_payload_dict(path, sandbox=box)


def test_fifo_data_file_gives_no_copy(box: Sandbox, udir: Path, tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("needs POSIX fifos")
    path = make_payload(udir)
    (udir / "examples" / "QE.csv").unlink()
    os.mkfifo(udir / "examples" / "QE.csv")
    norm = rules.normalise_payload(path, sandbox=box, dest_dir=tmp_path / "copy")
    assert norm.path is None
    assert "NOT_REGULAR_FILE" in codes(norm.findings, "error")


def test_symlink_inside_the_sandbox_is_resolved_in_the_copy(
    box: Sandbox, udir: Path, tmp_path: Path
) -> None:
    path = make_payload(udir)
    real = udir / "real_qe.csv"
    shutil.copy2(EXAMPLES / "QE.csv", real)
    (udir / "examples" / "QE.csv").unlink()
    (udir / "examples" / "QE.csv").symlink_to(real)
    norm = rules.normalise_payload(path, sandbox=box, dest_dir=tmp_path / "copy")
    assert norm.path is not None, norm.findings
    assert find(
        ET.parse(norm.path).getroot(), "channel[Spec]/detector/qe/datafile"
    ).text == str(real.resolve())


def test_references_and_info_are_reported(
    box: Sandbox, udir: Path, tmp_path: Path
) -> None:
    norm = rules.normalise_payload(
        make_payload(udir), sandbox=box, dest_dir=tmp_path / "copy"
    )
    tags = sorted({ref["tag"] for ref in norm.references})
    assert tags == ["CustomSed", "datafile"]
    assert all(ref["exists"] and ref["allowed"] for ref in norm.references)
    assert not any(str(udir) in ref["path"] for ref in norm.references)  # display paths
    assert norm.info["working_R"] == 6000
    assert norm.info["source"] == "custom"
    assert [c["class"] for c in norm.info["channels"]] == ["photometer", "spectrometer"]


def test_load_leaves_no_global_state_behind(box: Sandbox, udir: Path) -> None:
    """LoadOptions writes PassVal.working_R; load_options restores it."""
    from exorad.utils.passVal import PassVal

    before = PassVal.working_R
    PassVal.working_R = 1234
    try:
        options = rules.load_payload_dict(make_payload(udir), sandbox=box)
        assert options["common"]["working_R"]["value"] == 6000
        assert PassVal.working_R == 1234
    finally:
        PassVal.working_R = before
