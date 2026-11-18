"""The static scan for a configuration that is not an ExoRad payload (X4).

A ``runConfig.xml`` of another package has none of the ``common/channel/...``
elements; ``payload_checks=False`` keeps the generic checks that mirror what the
LOADER reads and drops the payload-shape rules.
"""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING, Any

import pytest
from payload_fixtures import sandbox_for

from exorad.mcp import pipelines, rules

if TYPE_CHECKING:
    from pathlib import Path

GENERIC = {"payload_checks": False, "exclude_reference_tags": ("outputDirectory",)}


@pytest.fixture
def udir(tmp_path: Path) -> Path:
    path = tmp_path / "work" / "user"
    path.mkdir(parents=True)
    return path


def _config(udir: Path, body: str = "", name: str = "runConfig.xml") -> Path:
    path = udir / name
    (udir / "out").mkdir(exist_ok=True)
    path.write_text(
        "<root><ConfigPath>.</ConfigPath>"
        f"<outputDirectory>{udir / 'out'}</outputDirectory>"
        "<targetList>x.csv</targetList>"
        f"{body}</root>"
    )
    return path


def _codes(findings: list[Any]) -> set[str]:
    return {f.code for f in findings if f.severity == "error"}


def test_runconfig_like_file_is_clean_with_payload_checks_off(
    tmp_path: Path, udir: Path
) -> None:
    box = sandbox_for(tmp_path)
    path = _config(udir)
    assert rules.static_findings(path, sandbox=box, **GENERIC) == []


def test_the_same_file_still_reports_the_payload_rules_by_default(
    tmp_path: Path, udir: Path
) -> None:
    box = sandbox_for(tmp_path)
    path = _config(udir)
    assert "MISSING_ELEMENT" in _codes(rules.static_findings(path, sandbox=box))
    # the directory is only skipped when the extension says so
    found = rules.static_findings(path, sandbox=box, payload_checks=False)
    assert "NOT_REGULAR_FILE" in _codes(found)


def test_payload_findings_alias_is_the_same_function() -> None:
    assert rules.payload_findings is rules.static_findings


def test_extra_reference_tags_are_collected_and_resolved(
    tmp_path: Path, udir: Path
) -> None:
    box = sandbox_for(tmp_path)
    path = _config(udir)
    found = rules.static_findings(
        path, sandbox=box, **GENERIC, reference_tags=("targetList",)
    )
    assert "FILE_MISSING" in _codes(found)  # x.csv does not exist
    (udir / "x.csv").write_text("a,b\n1,2\n")
    assert (
        rules.static_findings(
            path, sandbox=box, **GENERIC, reference_tags=("targetList",)
        )
        == []
    )


def _hostile_symlink(udir: Path, tmp_path: Path) -> str:
    outside = tmp_path / "outside.csv"
    outside.write_text("a\n1\n")
    (udir / "link.csv").symlink_to(outside)
    return f"<datafile>{udir / 'link.csv'}</datafile>"


def _hostile_fifo(udir: Path, tmp_path: Path) -> str:
    os.mkfifo(udir / "pipe.csv")
    return f"<datafile>{udir / 'pipe.csv'}</datafile>"


def _hostile_hdf5(udir: Path, tmp_path: Path) -> str:
    h5py = pytest.importorskip("h5py")
    with h5py.File(udir / "other.h5", "w") as f:
        f["d"] = [1.0, 2.0]
    with h5py.File(udir / "links.dat", "w") as f:  # any suffix
        f["ext"] = h5py.ExternalLink("other.h5", "/d")
    return f"<anything>{udir / 'links.dat'}</anything>"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("<comment><datadict>evil.pkl</datadict></comment>", "PICKLE_REFUSED"),
        ('<thing path="/etc/passwd">1</thing>', "ATTRIBUTE_REFUSED"),
        ("<config_dict>other.h5</config_dict>", "CONFIG_DICT_REFUSED"),
        ("<note>http://example.org/x</note>", "PATH_OUTSIDE_SANDBOX"),
        ("<ConfigPath>.</ConfigPath>", "CONFIGPATH_MULTIPLE"),
    ],
)
def test_hostile_content_is_still_refused(
    tmp_path: Path, udir: Path, body: str, expected: str
) -> None:
    box = sandbox_for(tmp_path)
    path = _config(udir, body)
    assert expected in _codes(rules.static_findings(path, sandbox=box, **GENERIC))


@pytest.mark.parametrize(
    ("make", "expected", "posix_only"),
    [
        (_hostile_symlink, "PATH_OUTSIDE_SANDBOX", False),
        (_hostile_fifo, "NOT_REGULAR_FILE", True),
        (_hostile_hdf5, "HDF5_LINK_REFUSED", False),
    ],
)
def test_hostile_files_are_still_refused(
    tmp_path: Path, udir: Path, make: Any, expected: str, posix_only: bool
) -> None:
    if posix_only and not hasattr(os, "mkfifo"):
        pytest.skip("needs POSIX fifos")
    box = sandbox_for(tmp_path)
    path = _config(udir, make(udir, tmp_path))
    assert expected in _codes(rules.static_findings(path, sandbox=box, **GENERIC))


def test_a_fifo_or_directory_as_the_configuration_itself_is_refused(
    tmp_path: Path, udir: Path
) -> None:
    box = sandbox_for(tmp_path)
    fifo = udir / "fifo.xml"
    os.mkfifo(fifo)
    assert "NOT_REGULAR_FILE" in _codes(
        rules.static_findings(fifo, sandbox=box, **GENERIC)
    )
    doctype = udir / "d.xml"
    doctype.write_text('<!DOCTYPE r [<!ENTITY e "x">]><r/>')
    assert "XML_DOCTYPE" in _codes(
        rules.static_findings(doctype, sandbox=box, **GENERIC)
    )


def test_normalise_writes_absolute_paths_without_payload_checks(
    tmp_path: Path, udir: Path
) -> None:
    box = sandbox_for(tmp_path)
    (udir / "data").mkdir()
    (udir / "data" / "t.csv").write_text("a\n1\n")
    path = _config(
        udir, "<datafile>~/../nothing</datafile>".replace("~/../nothing", "data/t.csv")
    )
    norm = rules.normalise_payload(
        path, sandbox=box, dest_dir=tmp_path / "work" / "norm", **GENERIC
    )
    assert norm.ok, norm.findings
    text = (tmp_path / "work" / "norm" / "runConfig.xml").read_text()
    assert str(udir / "data" / "t.csv") in text
    assert f"<ConfigPath>{udir}</ConfigPath>" in text
    assert f"<outputDirectory>{udir / 'out'}</outputDirectory>" in text
    # without the flag the same file is refused (ExoRad unchanged)
    refused = rules.normalise_payload(
        path, sandbox=box, dest_dir=tmp_path / "work" / "n2"
    )
    assert not refused.ok
    assert "MISSING_ELEMENT" in _codes(refused.findings)


def test_recheck_honours_the_flags(tmp_path: Path, udir: Path) -> None:
    box = sandbox_for(tmp_path)
    (udir / "t.csv").write_text("a\n1\n")
    path = _config(udir, "<datafile>t.csv</datafile>")
    norm = rules.normalise_payload(
        path, sandbox=box, dest_dir=tmp_path / "work" / "norm", **GENERIC
    )
    assert norm.path is not None
    assert rules.recheck_payload(norm.path, box, **GENERIC) == []
    assert "MISSING_ELEMENT" in _codes(rules.recheck_payload(norm.path, box))
    # a swap after normalisation is still caught on the generic path
    target = udir / "t.csv"
    target.unlink()
    outside = tmp_path / "outside.csv"
    outside.write_text("a\n")
    target.symlink_to(outside)
    assert _codes(rules.recheck_payload(norm.path, box, **GENERIC))


def test_revalidate_inputs_reads_the_flags_from_the_spec(
    tmp_path: Path, udir: Path
) -> None:
    box = sandbox_for(tmp_path)
    path = _config(udir)
    norm = rules.normalise_payload(
        path, sandbox=box, dest_dir=tmp_path / "work" / "norm", **GENERIC
    )
    targets = udir / "targets.csv"
    targets.write_text("name,M,Teff,R,D\n")
    spec = {
        "sandbox": box.to_spec(),
        "payload": str(norm.path),
        "target_list": str(targets),
        "payload_checks": False,
        "exclude_reference_tags": ["outputDirectory"],
    }
    with contextlib.suppress(rules.ConfigRuleError):
        # only the (ExoRad shaped) target list may be refused, never the payload part
        pipelines.revalidate_inputs(spec)
    spec.pop("payload_checks")
    with pytest.raises(rules.ConfigRuleError) as info:
        pipelines.revalidate_inputs(spec)
    assert "MISSING_ELEMENT" in {f.code for f in info.value.findings}
