"""Static payload rules: one test per finding code, hazards and the ablation proof.

``static_findings`` must report what the ExoRad library would do with a payload,
without calling ``LoadOptions``. The ablation test removes every element of the
example in turn and checks the verdict against what ``PreparePayload`` and
``ObserveTarget`` really do (spec 2.1), so the required-key table cannot drift.
"""

from __future__ import annotations

import copy
import dataclasses
import os
import re
import warnings
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

import pytest
from payload_fixtures import (
    EXAMPLES,
    codes,
    example_tree,
    find,
    make_payload,
    remove,
    sandbox_for,
    write_tree,
)

from exorad.mcp import rules

if TYPE_CHECKING:
    from pathlib import Path

    from exorad.mcp.sandbox import Sandbox


@pytest.fixture
def box(tmp_path: Path) -> Sandbox:
    return sandbox_for(tmp_path)


@pytest.fixture
def udir(tmp_path: Path) -> Path:
    """A user project directory inside the work dir (so it is readable)."""
    path = tmp_path / "work" / "user"
    path.mkdir(parents=True)
    return path


def _errors(findings: list) -> list:
    return [f for f in findings if f.severity == "error"]


def _add(root: ET.Element, parent: str, tag: str, text: str, **attrs: str) -> None:
    child = ET.SubElement(find(root, parent) if parent else root, tag, attrs)
    child.text = text


# --------------------------------------------------------------------------------
# the shipped example
# --------------------------------------------------------------------------------
def test_example_payload_has_no_findings(box: Sandbox) -> None:
    assert rules.static_findings(EXAMPLES / "payload_example.xml", sandbox=box) == []


def test_user_copy_of_the_example_has_no_findings(box: Sandbox, udir: Path) -> None:
    assert rules.static_findings(make_payload(udir), sandbox=box) == []


def test_finding_to_dict_and_error_type() -> None:
    finding = rules.Finding("error", "XML_PARSE", "x", "boom")
    assert finding.to_dict() == {
        "severity": "error",
        "code": "XML_PARSE",
        "path": "x",
        "message": "boom",
    }
    assert issubclass(rules.ConfigRuleError, ValueError)
    assert "XML_PARSE" in str(rules.ConfigRuleError([finding]))


# --------------------------------------------------------------------------------
# XML level: XML_PARSE, XML_DOCTYPE, FILE_TOO_LARGE, NOT_REGULAR_FILE
# --------------------------------------------------------------------------------
def test_xml_parse_error(box: Sandbox, udir: Path) -> None:
    bad = udir / "bad.xml"
    bad.write_text("<root><common></root>", encoding="utf-8")
    assert codes(rules.static_findings(bad, sandbox=box), "error") == ["XML_PARSE"]


def test_missing_file_is_a_usage_error(box: Sandbox, udir: Path) -> None:
    with pytest.raises(FileNotFoundError):
        rules.static_findings(udir / "nope.xml", sandbox=box)


def test_non_xml_suffix_is_refused(box: Sandbox, udir: Path) -> None:
    other = udir / "payload.txt"
    other.write_text("<root/>", encoding="utf-8")
    with pytest.raises(ValueError, match=r"\.xml"):
        rules.static_findings(other, sandbox=box)


_DOCTYPE = (
    '<?xml version="1.0"?><!DOCTYPE root [<!ENTITY a "aaaa">]>'
    "<root><fileName>&a;</fileName></root>"
)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-16-le"])
def test_doctype_is_refused_whatever_the_encoding(
    box: Sandbox, udir: Path, encoding: str
) -> None:
    """A byte search for ``<!DOCTYPE`` misses UTF-16: the expat handler does not."""
    text = _DOCTYPE
    if encoding == "utf-16-le":  # no BOM, declared in the prolog instead
        text = text.replace(
            '<?xml version="1.0"?>', '<?xml version="1.0" encoding="UTF-16"?>'
        )
    path = udir / "doctype.xml"
    path.write_bytes(text.encode(encoding))
    assert "XML_DOCTYPE" in codes(rules.static_findings(path, sandbox=box), "error")


def test_xml_entity_expansion_is_refused(box: Sandbox, udir: Path) -> None:
    laughs = ['<!ENTITY l0 "lol">'] + [
        f'<!ENTITY l{i} "&l{i - 1};&l{i - 1};&l{i - 1};&l{i - 1};">'
        for i in range(1, 9)
    ]
    path = udir / "laughs.xml"
    path.write_text(
        f'<?xml version="1.0"?><!DOCTYPE r [{"".join(laughs)}]><r><a>&l8;</a></r>',
        encoding="utf-8",
    )
    assert "XML_DOCTYPE" in codes(rules.static_findings(path, sandbox=box), "error")


def test_file_too_large(box: Sandbox, udir: Path) -> None:
    root = example_tree()
    root.find("fileName").set("padding", "x" * (1_200_000))
    path = write_tree(root, udir / "big.xml")
    small = dataclasses.replace(box, max_file_mb=1)
    assert codes(rules.static_findings(path, sandbox=small), "error") == [
        "FILE_TOO_LARGE"
    ]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs POSIX fifos")
def test_fifo_payload_is_not_opened(box: Sandbox, udir: Path) -> None:
    fifo = udir / "pipe.xml"
    os.mkfifo(fifo)
    assert codes(rules.static_findings(fifo, sandbox=box), "error") == [
        "NOT_REGULAR_FILE"
    ]


# --------------------------------------------------------------------------------
# MISSING_ELEMENT, CONFIGPATH_ORDER
# --------------------------------------------------------------------------------
def test_missing_ForceChannelWlEdge_is_reported_as_required(
    box: Sandbox, udir: Path
) -> None:
    """The example comment says 'otherwise comment it out'; the library disagrees."""
    path = make_payload(udir, edit=lambda r: remove(r, "optics/ForceChannelWlEdge"))
    found = [
        f
        for f in rules.static_findings(path, sandbox=box)
        if f.code == "MISSING_ELEMENT"
    ]
    assert [f.path for f in found] == ["optics/ForceChannelWlEdge"]
    assert "build" in found[0].message


def test_configpath_used_before_definition(box: Sandbox, udir: Path) -> None:
    def move_last(root: ET.Element) -> None:
        node = root.find("ConfigPath")
        root.remove(node)
        root.append(node)

    path = make_payload(udir, edit=move_last)
    assert "CONFIGPATH_ORDER" in codes(
        rules.static_findings(path, sandbox=box), "error"
    )


def test_configpath_missing_but_used(box: Sandbox, udir: Path) -> None:
    path = make_payload(udir, edit=lambda r: r.remove(r.find("ConfigPath")))
    assert "CONFIGPATH_ORDER" in codes(
        rules.static_findings(path, sandbox=box), "error"
    )


def test_configpath_not_needed_when_no_keyword_is_used(
    box: Sandbox, udir: Path
) -> None:
    def no_keyword(root: ET.Element) -> None:
        for node in root.iter():
            if node.text and "__ConfigPath__/" in node.text:
                node.text = node.text.replace("__ConfigPath__/", "")
        root.remove(root.find("ConfigPath"))

    path = make_payload(udir, edit=no_keyword)
    assert not _errors(rules.static_findings(path, sandbox=box))


def test_unknown_channel_class_is_a_value_error(box: Sandbox, udir: Path) -> None:
    path = make_payload(
        udir,
        edit=lambda r: setattr(
            find(r, "channel[Phot]/channelClass"), "text", "Bolometer"
        ),
    )
    assert "VALUE_INVALID" in codes(rules.static_findings(path, sandbox=box), "error")


# --------------------------------------------------------------------------------
# source spectrum: SOURCE_SED_BLOCKED, SOURCE_UNKNOWN_FALLS_BACK_TO_PLANCK
# --------------------------------------------------------------------------------
def _source(root: ET.Element, value: str) -> None:
    find(root, "common/sourceSpectrum").text = value


@pytest.mark.parametrize("value", ["sed", "SED", " Sed "])
def test_sed_source_is_refused(box: Sandbox, udir: Path, value: str) -> None:
    path = make_payload(udir, edit=lambda r: _source(r, value))
    assert "SOURCE_SED_BLOCKED" in codes(
        rules.static_findings(path, sandbox=box), "error"
    )


def test_unknown_source_warns(box: Sandbox, udir: Path) -> None:
    path = make_payload(udir, edit=lambda r: _source(r, "blackbody"))
    findings = rules.static_findings(path, sandbox=box)
    assert codes(findings) == ["SOURCE_UNKNOWN_FALLS_BACK_TO_PLANCK"]
    assert findings[0].severity == "warning"


def test_planck_source_needs_nothing_else(box: Sandbox, udir: Path) -> None:
    path = make_payload(udir, edit=lambda r: _source(r, "planck"), tables=True)
    assert rules.static_findings(path, sandbox=box) == []


def test_custom_source_needs_customsed(box: Sandbox, udir: Path) -> None:
    path = make_payload(
        udir, edit=lambda r: remove(r, "common/sourceSpectrum/CustomSed")
    )
    assert "MISSING_ELEMENT" in codes(rules.static_findings(path, sandbox=box), "error")


def test_phoenix_needs_models_or_env(
    box: Sandbox, udir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PHOENIX_PATH", raising=False)
    path = make_payload(
        udir,
        edit=lambda r: (
            _source(r, "phoenix"),
            remove(r, "common/sourceSpectrum/StellarModels"),
        ),
    )
    assert "MISSING_ELEMENT" in codes(rules.static_findings(path, sandbox=box), "error")
    monkeypatch.setenv("PHOENIX_PATH", str(udir))
    assert not _errors(rules.static_findings(path, sandbox=box))


def test_phoenix_stellar_models_directory_is_checked(box: Sandbox, udir: Path) -> None:
    models = udir / "models"
    models.mkdir()

    def phoenix(root: ET.Element) -> None:
        _source(root, "phoenix")
        find(root, "common/sourceSpectrum/StellarModels").text = str(models)

    assert not _errors(
        rules.static_findings(make_payload(udir, edit=phoenix), sandbox=box)
    )

    def outside(root: ET.Element) -> None:
        _source(root, "phoenix")
        find(
            root, "common/sourceSpectrum/StellarModels"
        ).text = "/usr/local/project_data/sed"

    path = make_payload(udir, name="out.xml", edit=outside)
    assert "PATH_OUTSIDE_SANDBOX" in codes(
        rules.static_findings(path, sandbox=box), "error"
    )


# --------------------------------------------------------------------------------
# paths: FILE_MISSING, PATH_OUTSIDE_SANDBOX, URLs, symlinks, NOT_REGULAR_FILE
# --------------------------------------------------------------------------------
def test_missing_table_is_reported(box: Sandbox, udir: Path) -> None:
    path = make_payload(udir)
    (udir / "examples" / "QE.csv").unlink()
    found = [
        f for f in rules.static_findings(path, sandbox=box) if f.code == "FILE_MISSING"
    ]
    assert len(found) == 1
    assert "QE.csv" in found[0].message
    assert str(udir) not in found[0].message  # no absolute server path (H8)


@pytest.mark.parametrize(
    "value",
    [
        "/etc/hosts",
        "../../../../etc/hosts",
        "~/secret.csv",
        "__ConfigPath__/../../../../../etc/hosts",
    ],
)
def test_payload_datafile_outside_sandbox_is_refused(
    box: Sandbox, udir: Path, value: str
) -> None:
    def point(root: ET.Element) -> None:
        find(root, "channel[Spec]/detector/qe/datafile").text = value

    findings = rules.static_findings(make_payload(udir, edit=point), sandbox=box)
    assert "PATH_OUTSIDE_SANDBOX" in codes(findings, "error")


def test_symlink_out_of_sandbox_is_refused(
    box: Sandbox, udir: Path, tmp_path: Path
) -> None:
    secret = tmp_path / "outside.csv"
    secret.write_text("Wavelength,QE\n1,0.5\n", encoding="utf-8")
    path = make_payload(udir)
    (udir / "examples" / "QE.csv").unlink()
    (udir / "examples" / "QE.csv").symlink_to(secret)
    assert "PATH_OUTSIDE_SANDBOX" in codes(
        rules.static_findings(path, sandbox=box), "error"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/qe.csv",
        "https://example.com/x",
        "file:///etc/hosts",
        "ftp://h/x",
    ],
)
def test_url_values_are_refused(box: Sandbox, udir: Path, url: str) -> None:
    def point(root: ET.Element) -> None:
        find(root, "channel[Spec]/detector/qe/datafile").text = url

    findings = rules.static_findings(make_payload(udir, edit=point), sandbox=box)
    bad = [f for f in findings if f.code == "PATH_OUTSIDE_SANDBOX"]
    assert bad
    assert "URL" in bad[0].message


def test_url_in_any_value_is_refused_but_not_in_comments(
    box: Sandbox, udir: Path
) -> None:
    """The example comments quote https://phoenix... and must stay legal."""

    def odd(root: ET.Element) -> None:
        find(root, "fileName").text = "see https://example.com/x"

    findings = rules.static_findings(make_payload(udir, edit=odd), sandbox=box)
    assert "PATH_OUTSIDE_SANDBOX" in codes(findings, "error")
    assert not rules.static_findings(make_payload(udir, name="ok.xml"), sandbox=box)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs POSIX fifos")
def test_fifo_data_file_is_refused_and_never_opened(box: Sandbox, udir: Path) -> None:
    path = make_payload(udir)
    (udir / "examples" / "QE.csv").unlink()
    os.mkfifo(udir / "examples" / "QE.csv")
    assert "NOT_REGULAR_FILE" in codes(
        rules.static_findings(path, sandbox=box), "error"
    )


def test_directory_where_a_file_is_expected(box: Sandbox, udir: Path) -> None:
    path = make_payload(udir)
    (udir / "examples" / "QE.csv").unlink()
    (udir / "examples" / "QE.csv").mkdir()
    assert "NOT_REGULAR_FILE" in codes(
        rules.static_findings(path, sandbox=box), "error"
    )


def test_data_table_size_limit(box: Sandbox, udir: Path) -> None:
    path = make_payload(udir)
    with (udir / "examples" / "QE.csv").open("ab") as handle:
        handle.write(b"#" + b"x" * 1_300_000)
    small = dataclasses.replace(box, max_data_mb=1)
    assert "LIMIT_EXCEEDED" in codes(
        rules.static_findings(path, sandbox=small), "error"
    )


# --------------------------------------------------------------------------------
# executable pointers and HDF5 inputs: PICKLE_REFUSED, UNSUPPORTED_FORMAT, HDF5_LINK_REFUSED
# --------------------------------------------------------------------------------
@pytest.mark.parametrize("tag", ["datadict", "config_dict"])
@pytest.mark.parametrize("name", ["evil.pickle", "evil.PICKLE", "evil.pkl", "evil.py"])
def test_pickle_datadict_is_refused(
    box: Sandbox, udir: Path, tag: str, name: str
) -> None:
    (udir / name).write_bytes(b"not really a pickle")
    path = make_payload(
        udir, edit=lambda r: _add(r, "common", tag, f"__ConfigPath__/{name}")
    )
    assert "PICKLE_REFUSED" in codes(rules.static_findings(path, sandbox=box), "error")


def test_datadict_with_other_suffix_is_unsupported(box: Sandbox, udir: Path) -> None:
    (udir / "dd.txt").write_text("x", encoding="utf-8")
    path = make_payload(
        udir, edit=lambda r: _add(r, "common", "datadict", "__ConfigPath__/dd.txt")
    )
    assert "UNSUPPORTED_FORMAT" in codes(
        rules.static_findings(path, sandbox=box), "error"
    )


def _h5(path: Path, *, external: bool = False, virtual: bool = False) -> Path:
    h5py = pytest.importorskip("h5py")
    other = path.parent / "other.h5"
    with h5py.File(other, "w") as f:
        f.create_dataset("d", data=[1.0, 2.0, 3.0, 4.0])
    with h5py.File(path, "w") as f:
        f.create_dataset("plain", data=[1.0])
        if external:
            f["ext"] = h5py.ExternalLink("other.h5", "/d")
        if virtual:
            layout = h5py.VirtualLayout(shape=(4,), dtype="f8")
            layout[:] = h5py.VirtualSource("other.h5", "d", shape=(4,))
            f.create_virtual_dataset("virt", layout, fillvalue=0)
    return path


def test_clean_h5_datadict_is_accepted(box: Sandbox, udir: Path) -> None:
    _h5(udir / "dd.h5")
    path = make_payload(
        udir, edit=lambda r: _add(r, "common", "datadict", "__ConfigPath__/dd.h5")
    )
    assert not _errors(rules.static_findings(path, sandbox=box))


@pytest.mark.parametrize("kind", ["external", "virtual"])
def test_h5_datadict_with_external_link_is_refused(
    box: Sandbox, udir: Path, kind: str
) -> None:
    _h5(udir / "dd.h5", external=kind == "external", virtual=kind == "virtual")
    path = make_payload(
        udir, edit=lambda r: _add(r, "common", "datadict", "__ConfigPath__/dd.h5")
    )
    assert "HDF5_LINK_REFUSED" in codes(
        rules.static_findings(path, sandbox=box), "error"
    )


def test_hdf5_link_scan_helper(tmp_path: Path) -> None:
    clean = _h5(tmp_path / "clean.h5")
    assert rules.hdf5_link_problems(clean) == []
    ext = _h5(tmp_path / "ext.h5", external=True)
    assert any("external link" in p for p in rules.hdf5_link_problems(ext))
    virt = _h5(tmp_path / "virt.h5", virtual=True)
    assert any("virtual" in p for p in rules.hdf5_link_problems(virt))


def test_hdf5_link_scan_survives_hard_link_cycles(tmp_path: Path) -> None:
    h5py = pytest.importorskip("h5py")
    path = tmp_path / "cycle.h5"
    with h5py.File(path, "w") as f:
        group = f.create_group("a")
        group["back"] = f  # hard link to the root: a cycle
    assert rules.hdf5_link_problems(path) == []


# --------------------------------------------------------------------------------
# limits and units: LIMIT_EXCEEDED, UNIT_INVALID
# --------------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["30001", "1000000"])
def test_working_R_limit(box: Sandbox, udir: Path, value: str) -> None:
    path = make_payload(
        udir, edit=lambda r: setattr(find(r, "common/working_R"), "text", value)
    )
    assert "LIMIT_EXCEEDED" in codes(rules.static_findings(path, sandbox=box), "error")


def test_working_R_at_the_cap_is_accepted(box: Sandbox, udir: Path) -> None:
    path = make_payload(
        udir, edit=lambda r: setattr(find(r, "common/working_R"), "text", "30000")
    )
    assert not _errors(rules.static_findings(path, sandbox=box))


def test_non_integer_working_R_is_a_value_error(box: Sandbox, udir: Path) -> None:
    path = make_payload(
        udir, edit=lambda r: setattr(find(r, "common/working_R"), "text", "abc")
    )
    assert "VALUE_INVALID" in codes(rules.static_findings(path, sandbox=box), "error")


def test_targetR_bin_limit(box: Sandbox, udir: Path) -> None:
    """R = 1e6 over 1.1-1.95 um is about 6e5 bins: far above EXORAD_MCP_MAX_BINS."""
    path = make_payload(
        udir,
        edit=lambda r: setattr(find(r, "channel[Spec]/targetR"), "text", "1000000"),
    )
    found = [
        f
        for f in rules.static_findings(path, sandbox=box)
        if f.code == "LIMIT_EXCEEDED"
    ]
    assert found
    assert "Spec" in found[0].path


def test_targetR_native_is_not_a_bin_count(box: Sandbox, udir: Path) -> None:
    path = make_payload(
        udir, edit=lambda r: setattr(find(r, "channel[Spec]/targetR"), "text", "native")
    )
    assert "LIMIT_EXCEEDED" not in codes(rules.static_findings(path, sandbox=box))


def test_channel_count_limit(box: Sandbox, udir: Path) -> None:
    def many(root: ET.Element) -> None:
        template = find(root, "channel[Phot]")
        for i in range(17):
            clone = copy.deepcopy(template)
            clone.text = f"P{i}"
            root.append(clone)

    path = make_payload(udir, edit=many)
    assert "LIMIT_EXCEEDED" in codes(rules.static_findings(path, sandbox=box), "error")


def test_optical_element_count_limit(box: Sandbox, udir: Path) -> None:
    def many(root: ET.Element) -> None:
        optics = find(root, "optics")
        template = find(root, "optics/opticalElement[M1]")
        for i in range(70):
            clone = copy.deepcopy(template)
            clone.text = f"X{i}"
            optics.append(clone)

    path = make_payload(udir, edit=many)
    assert "LIMIT_EXCEEDED" in codes(rules.static_findings(path, sandbox=box), "error")


def test_invalid_unit(box: Sandbox, udir: Path) -> None:
    path = make_payload(
        udir,
        edit=lambda r: find(r, "common/wl_min").set("unit", "furlongs_per_fortnight_x"),
    )
    found = [
        f for f in rules.static_findings(path, sandbox=box) if f.code == "UNIT_INVALID"
    ]
    assert [f.path for f in found] == ["common/wl_min"]


def test_wavelength_with_a_non_length_unit(box: Sandbox, udir: Path) -> None:
    path = make_payload(udir, edit=lambda r: find(r, "common/wl_min").set("unit", "kg"))
    assert "UNIT_INVALID" in codes(rules.static_findings(path, sandbox=box), "error")


def test_dimensionless_and_empty_units_are_valid(box: Sandbox, udir: Path) -> None:
    def units(root: ET.Element) -> None:
        find(root, "channel[Phot]/Fnum_x").set("unit", "dimensionless")
        find(root, "channel[Phot]/Fnum_y").set("unit", "")

    assert not _errors(
        rules.static_findings(make_payload(udir, edit=units), sandbox=box)
    )


# --------------------------------------------------------------------------------
# demo SED: SED_COARSE_OUTSIDE_FINE_SEGMENT
# --------------------------------------------------------------------------------
def test_coarse_sed_warning_outside_the_fine_segment(box: Sandbox, udir: Path) -> None:
    def wide(root: ET.Element) -> None:
        find(root, "common/wl_max").text = "3.5"

    findings = rules.static_findings(make_payload(udir, edit=wide), sandbox=box)
    assert codes(findings) == ["SED_COARSE_OUTSIDE_FINE_SEGMENT"]
    assert findings[0].severity == "warning"


def test_no_coarse_sed_warning_for_the_full_sed(box: Sandbox, udir: Path) -> None:
    """Pointing at a file that is not the demo SED never warns."""
    make_payload(udir)  # writes the tables
    demo = udir / "examples" / "customsed_demo.csv"
    (udir / "examples" / "mysed.csv").write_bytes(demo.read_bytes())

    def wide(root: ET.Element) -> None:
        find(root, "common/wl_max").text = "3.5"
        find(
            root, "common/sourceSpectrum/CustomSed"
        ).text = "__ConfigPath__/examples/mysed.csv"

    findings = rules.static_findings(
        make_payload(udir, name="b.xml", edit=wide), sandbox=box
    )
    assert findings == []


# --------------------------------------------------------------------------------
# the requirement table is what the library does (ablation, spec 2.1)
# --------------------------------------------------------------------------------
def _paths(element: ET.Element, prefix: str = ""):
    repeated = ("channel", "opticalElement", "foreground", "customNoise")
    for child in element:
        if child.tag == "comment":
            continue
        name = child.tag
        if child.tag in repeated:
            name += "[" + (child.text or "").strip().split("\n")[0].strip() + "]"
        yield prefix + name, child
        yield from _paths(child, prefix + name + "/")


def _removal_cases() -> list:
    seen: set[str] = set()
    cases = []
    for path, _ in _paths(example_tree()):
        pattern = re.sub(r"\[[^\]]*\]", "[]", path)
        pattern = re.sub(r"opticalElement\[\]/", "opticalElement[]/", pattern)
        first = pattern not in seen
        seen.add(pattern)
        marks = [] if first else [pytest.mark.slow]
        cases.append(pytest.param(path, id=path, marks=marks))
    return cases


_first_target = None


def _library_stage(directory: Path) -> str:
    """What the library does with ``directory/payload.xml``: ok | build | observe."""
    global _first_target
    from exorad.tasks import LoadTargetList, ObserveTarget, PreparePayload
    from exorad.utils.passVal import PassVal

    xml = ET.parse(directory / "payload.xml").getroot()
    config = xml.find("ConfigPath")
    if config is not None:  # absolute: no cwd involved
        config.text = str(directory)
    absolute = write_tree(xml, directory / "absolute.xml")
    if _first_target is None:
        _first_target = LoadTargetList()(
            target_list=str(EXAMPLES / "test_target.csv")
        ).target[0]
    with rules.CONFIG_LOAD_LOCK, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        saved = PassVal.working_R
        try:
            try:
                payload, channels, wl = PreparePayload()(
                    payload_file=str(absolute), output=None
                )
            except Exception:
                return "build"
            try:
                ObserveTarget()(
                    target=copy.deepcopy(_first_target),
                    payload=payload,
                    channels=channels,
                    wl_range=wl,
                )
            except Exception:
                return "observe"
            return "ok"
        finally:
            PassVal.working_R = saved


@pytest.mark.parametrize("removed", _removal_cases())
def test_ablation_static_verdict_matches_the_library(
    removed: str, tmp_path: Path
) -> None:
    box = sandbox_for(tmp_path)
    directory = tmp_path / "work" / "ablate"
    directory.mkdir(parents=True)
    path = make_payload(directory, edit=lambda r: remove(r, removed))
    stage = _library_stage(directory)
    findings = rules.static_findings(path, sandbox=box)
    errs = _errors(findings)
    if stage == "ok":
        assert not errs, f"false positive for {removed}: {findings}"
        return
    assert errs, f"{removed}: the library fails at {stage} but nothing was reported"
    assert {f.code for f in errs} <= {"MISSING_ELEMENT", "CONFIGPATH_ORDER"}
    if removed == "ConfigPath":
        assert "CONFIGPATH_ORDER" in codes(errs)
    else:
        missing = [f for f in errs if f.code == "MISSING_ELEMENT"]
        assert missing
        assert any(f"at {stage}" in f.message for f in missing), (
            f"{removed}: library stage is {stage}, messages {[f.message for f in missing]}"
        )


def test_requirement_rows_are_documented() -> None:
    rows = rules.payload_requirements()
    assert rows
    assert {"path", "required", "unit", "values", "default", "note"} <= set(rows[0])
    by_path = {row["path"]: row for row in rows}
    assert by_path["optics/ForceChannelWlEdge"]["required"] == "build"
    assert by_path["optics/Atel"]["required"] == "observe"
    assert by_path["common/working_R"]["required"] == "optional"
    assert by_path["common/working_R"]["default"] == "6000"
    assert {row["required"] for row in rows} <= {"build", "observe", "optional"}
