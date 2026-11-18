"""Target list rules: columns, units, names, counts (spec 2.2) and the CSV writer."""

from __future__ import annotations

import dataclasses
import math
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from payload_fixtures import EXAMPLES, codes, sandbox_for

from exorad.mcp import targets

if TYPE_CHECKING:
    from exorad.mcp.sandbox import Sandbox

HEADER = "star name,star M [M_sun],star Teff [K],star R [R_sun],star D [pc]"
GOOD_ROW = "alpha,1,5000,1,20"


@pytest.fixture
def box(tmp_path: Path) -> Sandbox:
    return sandbox_for(tmp_path)


@pytest.fixture
def wdir(tmp_path: Path) -> Path:
    path = tmp_path / "work" / "t"
    path.mkdir(parents=True)
    return path


def _csv(
    directory: Path, *lines: str, name: str = "t.csv", newline: str = "\n"
) -> Path:
    path = directory / name
    path.write_bytes((newline.join(lines) + newline).encode("utf-8"))
    return path


def _errors(report: targets.TargetReport) -> list:
    return [f for f in report.findings if f.severity == "error"]


# --------------------------------------------------------------------------------
# the shipped example and library agreement
# --------------------------------------------------------------------------------
def test_example_target_list_is_valid(box: Sandbox) -> None:
    report = targets.validate_target_list(EXAMPLES / "test_target.csv", sandbox=box)
    assert report.findings == []
    assert report.ok
    assert report.rows == 2
    assert report.names == ["myTest", "myTest2"]
    assert report.columns[0] == "star name"
    assert "star ra [deg]" in report.columns


def test_what_we_accept_the_library_loads(box: Sandbox, wdir: Path) -> None:
    from exorad.tasks import LoadTargetList

    path = _csv(wdir, HEADER + ",star magk", GOOD_ROW + ",3.5", "b b,1.5,6000,1.2,10,4")
    assert targets.validate_target_list(path, sandbox=box).ok
    loaded = LoadTargetList()(target_list=str(path)).target
    assert [t.name for t in loaded] == ["alpha", "b b"]
    assert loaded[1].star.M.unit == "solMass"


def test_requirement_rows() -> None:
    rows = targets.target_requirements()
    by_path = {row["path"]: row for row in rows}
    assert by_path["star name"]["required"] == "observe"
    assert by_path["star Teff [K]"]["required"] == "observe"
    assert by_path["star magk"]["required"] == "optional"
    assert {"path", "required", "unit", "values", "default", "note"} <= set(rows[0])


# --------------------------------------------------------------------------------
# columns and units: TARGET_COLUMN_MISSING, TARGET_UNIT_MISSING, UNIT_INVALID
# --------------------------------------------------------------------------------
@pytest.mark.parametrize("missing", ["name", "M", "Teff", "R", "D"])
def test_required_column_missing(box: Sandbox, wdir: Path, missing: str) -> None:
    cells = dict(zip(HEADER.split(","), GOOD_ROW.split(","), strict=True))
    cells = {k: v for k, v in cells.items() if k.split(" ")[1] != missing}
    path = _csv(wdir, ",".join(cells), ",".join(cells.values()))
    report = targets.validate_target_list(path, sandbox=box)
    found = [f for f in report.findings if f.code == "TARGET_COLUMN_MISSING"]
    assert [f.path for f in found] == [f"star {missing}"]


@pytest.mark.parametrize("column", ["M", "Teff", "R", "D"])
def test_unit_missing(box: Sandbox, wdir: Path, column: str) -> None:
    header = HEADER.split(",")
    header = [h.split(" [")[0] if h.split(" ")[1] == column else h for h in header]
    path = _csv(wdir, ",".join(header), GOOD_ROW)
    found = [
        f
        for f in targets.validate_target_list(path, sandbox=box).findings
        if f.code == "TARGET_UNIT_MISSING"
    ]
    assert [f.path for f in found] == [f"star {column}"]


@pytest.mark.parametrize(
    ("column", "wrong"),
    [("M", "K"), ("Teff", "pc"), ("R", "M_sun"), ("D", "K"), ("M", "furlongs_x")],
)
def test_wrong_unit_type(box: Sandbox, wdir: Path, column: str, wrong: str) -> None:
    header = [
        f"star {column} [{wrong}]" if h.split(" ")[1] == column else h
        for h in HEADER.split(",")
    ]
    path = _csv(wdir, ",".join(header), GOOD_ROW)
    report = targets.validate_target_list(path, sandbox=box)
    assert "UNIT_INVALID" in codes(report.findings, "error")


def test_ra_without_dec(box: Sandbox, wdir: Path) -> None:
    path = _csv(wdir, HEADER + ",star ra [deg]", GOOD_ROW + ",90")
    found = [
        f
        for f in targets.validate_target_list(path, sandbox=box).findings
        if f.code == "TARGET_COLUMN_MISSING"
    ]
    assert [f.path for f in found] == ["star dec"]


def test_ra_dec_need_angle_units(box: Sandbox, wdir: Path) -> None:
    path = _csv(wdir, HEADER + ",star ra [pc],star dec [deg]", GOOD_ROW + ",90,10")
    assert "UNIT_INVALID" in codes(
        targets.validate_target_list(path, sandbox=box).findings, "error"
    )


def test_mrs_layout_is_not_accepted(box: Sandbox, wdir: Path) -> None:
    """Without star columns the library would try the Ariel MRS layout: the MCP says what is missing."""
    path = _csv(wdir, "Planet Name,Star Name,Teff", "p1,s1,5000")
    report = targets.validate_target_list(path, sandbox=box)
    missing = {f.path for f in report.findings if f.code == "TARGET_COLUMN_MISSING"}
    assert missing == {"star name", "star M", "star Teff", "star R", "star D"}


def test_planet_columns_warn_but_stay_valid(box: Sandbox, wdir: Path) -> None:
    path = _csv(wdir, HEADER + ",planet name,planet P [d]", GOOD_ROW + ",b,3.0")
    report = targets.validate_target_list(path, sandbox=box)
    assert codes(report.findings) == ["PLANET_COLUMNS_IGNORED"]
    assert report.findings[0].severity == "warning"
    assert report.ok


# --------------------------------------------------------------------------------
# names: TARGET_NAME_INVALID, TARGET_DUPLICATE
# --------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name",
    ["a/b", "../x", "..", ".hidden", "a\\b", "x" * 65, "-lead", "a;b", "a..b", "a\tb"],
)
def test_target_name_is_validated(box: Sandbox, wdir: Path, name: str) -> None:
    path = _csv(wdir, HEADER, f'"{name}",1,5000,1,20')
    report = targets.validate_target_list(path, sandbox=box)
    assert "TARGET_NAME_INVALID" in codes(report.findings, "error")


def test_target_name_with_slash_is_refused(box: Sandbox, wdir: Path) -> None:
    path = _csv(wdir, HEADER, "a/b,1,5000,1,20")
    found = [
        f
        for f in targets.validate_target_list(path, sandbox=box).findings
        if f.code == "TARGET_NAME_INVALID"
    ]
    assert found
    assert "a/b" in found[0].message


def test_empty_name_is_invalid(box: Sandbox, wdir: Path) -> None:
    path = _csv(wdir, HEADER, ",1,5000,1,20")
    assert "TARGET_NAME_INVALID" in codes(
        targets.validate_target_list(path, sandbox=box).findings
    )


@pytest.mark.parametrize(
    "name", ["HD 209458", "WASP-12", "K2-18 (b)", "tau_Boo.1", "a+b", "7"]
)
def test_reasonable_names_pass(box: Sandbox, wdir: Path, name: str) -> None:
    path = _csv(wdir, HEADER, f"{name},1,5000,1,20")
    assert targets.validate_target_list(path, sandbox=box).findings == []


def test_duplicate_target_names_refused(box: Sandbox, wdir: Path) -> None:
    path = _csv(wdir, HEADER, GOOD_ROW, GOOD_ROW)
    found = [
        f
        for f in targets.validate_target_list(path, sandbox=box).findings
        if f.code == "TARGET_DUPLICATE"
    ]
    assert len(found) == 1
    assert found[0].severity == "error"


def test_names_differing_only_by_case_warn(box: Sandbox, wdir: Path) -> None:
    """PNG file names collide on case-insensitive file systems."""
    path = _csv(wdir, HEADER, GOOD_ROW, "ALPHA,1,5000,1,20")
    report = targets.validate_target_list(path, sandbox=box)
    assert [(f.code, f.severity) for f in report.findings] == [
        ("TARGET_DUPLICATE", "warning")
    ]
    assert report.ok


# --------------------------------------------------------------------------------
# counts, values, file level: TARGET_COUNT, VALUE_INVALID, FILE_TOO_LARGE, NOT_REGULAR_FILE
# --------------------------------------------------------------------------------
def test_target_count_limit(box: Sandbox, wdir: Path) -> None:
    rows = [f"s{i},1,5000,1,20" for i in range(4)]
    path = _csv(wdir, HEADER, *rows)
    small = dataclasses.replace(box, max_targets=3)
    assert "TARGET_COUNT" in codes(
        targets.validate_target_list(path, sandbox=small).findings, "error"
    )
    assert targets.validate_target_list(path, sandbox=box).ok


def test_empty_list_is_refused(box: Sandbox, wdir: Path) -> None:
    path = _csv(wdir, HEADER)
    assert "TARGET_COUNT" in codes(
        targets.validate_target_list(path, sandbox=box).findings, "error"
    )


@pytest.mark.parametrize(
    "row",
    [
        "a,-1,5000,1,20",
        "a,1,0,1,20",
        "a,1,5000,nan,20",
        "a,1,5000,1,inf",
        "a,1,5000,1,",
        "a,x,5000,1,20",
    ],
)
def test_values_must_be_finite_and_positive(box: Sandbox, wdir: Path, row: str) -> None:
    path = _csv(wdir, HEADER, row)
    assert "VALUE_INVALID" in codes(
        targets.validate_target_list(path, sandbox=box).findings, "error"
    )


def test_row_with_the_wrong_number_of_cells(box: Sandbox, wdir: Path) -> None:
    path = _csv(wdir, HEADER, "a,1,5000")
    assert "VALUE_INVALID" in codes(
        targets.validate_target_list(path, sandbox=box).findings, "error"
    )


def test_bom_and_crlf_are_accepted(box: Sandbox, wdir: Path) -> None:
    path = wdir / "bom.csv"
    path.write_bytes(b"\xef\xbb\xbf" + (HEADER + "\r\n" + GOOD_ROW + "\r\n").encode())
    assert targets.validate_target_list(path, sandbox=box).findings == []


def test_not_utf8_text(box: Sandbox, wdir: Path) -> None:
    path = wdir / "latin.csv"
    path.write_bytes(HEADER.encode() + b"\n\xff\xfe,1,5000,1,20\n")
    assert "VALUE_INVALID" in codes(
        targets.validate_target_list(path, sandbox=box).findings, "error"
    )


def test_target_list_file_too_large(box: Sandbox, wdir: Path) -> None:
    path = _csv(wdir, HEADER, GOOD_ROW, "# " + "x" * 1_200_000)
    small = dataclasses.replace(box, max_file_mb=1)
    assert codes(
        targets.validate_target_list(path, sandbox=small).findings, "error"
    ) == ["FILE_TOO_LARGE"]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs POSIX fifos")
def test_fifo_target_list_is_not_opened(box: Sandbox, wdir: Path) -> None:
    fifo = wdir / "pipe.csv"
    os.mkfifo(fifo)
    assert codes(targets.validate_target_list(fifo, sandbox=box).findings, "error") == [
        "NOT_REGULAR_FILE"
    ]


def test_missing_file(box: Sandbox, wdir: Path) -> None:
    with pytest.raises(FileNotFoundError):
        targets.validate_target_list(wdir / "nope.csv", sandbox=box)


@pytest.mark.parametrize("name", ["list.xlsx", "list.txt", "list"])
def test_xlsx_target_list_is_refused(box: Sandbox, wdir: Path, name: str) -> None:
    path = wdir / name
    path.write_bytes(b"PK\x03\x04")
    with pytest.raises(ValueError, match=r"\.csv"):
        targets.validate_target_list(path, sandbox=box)


# --------------------------------------------------------------------------------
# the writer behind draft_target_list
# --------------------------------------------------------------------------------
ROWS = [
    {"name": "alpha", "M": 1.0, "Teff": 5000, "R": 1.0, "D": 20.0},
    {"name": "beta", "M": 1.5, "Teff": 6000.5, "R": 1.2, "D": 10.0},
]


def test_write_round_trip(box: Sandbox, wdir: Path) -> None:
    from exorad.tasks import LoadTargetList

    path = wdir / "out.csv"
    columns = targets.write_target_csv(ROWS, path)
    assert columns == HEADER.split(",")
    report = targets.validate_target_list(path, sandbox=box)
    assert report.ok, report.findings
    loaded = LoadTargetList()(target_list=str(path)).target
    assert [t.name for t in loaded] == ["alpha", "beta"]
    assert float(loaded[1].star.Teff.value) == 6000.5


def test_write_optional_columns(box: Sandbox, wdir: Path) -> None:
    rows = [
        {**ROWS[0], "magk": 3.0, "ra": 90.0, "dec": 18.0},
        {**ROWS[1], "magk": 4.0, "ra": 10.0, "dec": -5.0},
    ]
    path = wdir / "out.csv"
    columns = targets.write_target_csv(rows, path)
    assert columns[-3:] == ["star magk", "star ra [deg]", "star dec [deg]"]
    assert targets.validate_target_list(path, sandbox=box).ok


def test_write_header_matches_the_example() -> None:
    rows = [{**r, "magk": 0, "ra": 1, "dec": 2} for r in ROWS]
    columns = targets.write_target_csv(rows, Path(os.devnull))
    example_header = (EXAMPLES / "test_target.csv").read_text().splitlines()[0]
    assert ",".join(columns) == example_header


@pytest.mark.parametrize(
    ("rows", "match"),
    [
        ([{**ROWS[0], "colour": "red"}], "unknown"),
        ([{k: v for k, v in ROWS[0].items() if k != "Teff"}], "Teff"),
        ([{**ROWS[0], "M": "heavy"}], "number"),
        ([{**ROWS[0], "M": math.nan}], "finite"),
        ([{**ROWS[0], "D": -1}], "positive"),
        ([{**ROWS[0], "ra": 10.0}], "dec"),
        ([{**ROWS[0], "magk": 1.0}, ROWS[1]], "magk"),
        ([], "at least one"),
        ([{**ROWS[0], "name": "a/b"}], "name"),
        ([ROWS[0], ROWS[0]], "duplicate"),
    ],
)
def test_write_rejects_bad_rows(rows: list, match: str, wdir: Path) -> None:
    with pytest.raises(ValueError, match=match):
        targets.write_target_csv(rows, wdir / "x.csv")
    assert not (wdir / "x.csv").exists()
