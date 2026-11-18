"""Target list (CSV) rules and writer for the ExoRad MCP.

``LoadTargetList`` reads a CSV whose header holds ``star <field> [<unit>]``
columns (``exorad.models.targetlist.CSVTargetList``). The MCP checks the file
itself, with the standard ``csv`` module, before any ExoRad code reads it:

* ``.csv`` only (``.xlsx`` would open a zip/XML parser on a client file);
* the required columns ``name``, ``M``, ``Teff``, ``R``, ``D`` with units of the
  right physical type, values finite and positive;
* target names that cannot leave the output directory or nest HDF5 groups
  (``^[A-Za-z0-9][A-Za-z0-9 _.+\\-()]{0,63}$``, no ``..``), unique;
* a bounded number of rows (``EXORAD_MCP_MAX_TARGETS``) and file size
  (``EXORAD_MCP_MAX_FILE_MB``).

v1 is star-only: ``planet`` columns are read by the library (and turn the target
name into the planet name) but the pipeline ignores them, so they only warn.
"""

from __future__ import annotations

import csv
import io
import math
import os
import re
import stat
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from astropy import units as u

from exorad.mcp.rules import ERROR, WARNING, Finding, errors_of

if TYPE_CHECKING:
    from pathlib import Path

    from exorad.mcp.sandbox import Sandbox

__all__ = [
    "NAME_PATTERN",
    "STAR_COLUMNS",
    "TargetReport",
    "describe_target_list",
    "target_requirements",
    "validate_target_list",
    "write_target_csv",
]

NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9 _.+\-()]{0,63}$"
_NAME_RE = re.compile(NAME_PATTERN)
_MAX_FINDINGS = 50


@dataclass(frozen=True)
class _Column:
    field: str
    unit: u.UnitBase | None  #: required physical type (None: no unit expected)
    unit_text: str  #: unit written in the header by the writer
    required: bool
    positive: bool
    note: str


STAR_COLUMNS: tuple[_Column, ...] = (
    _Column("name", None, "", True, False, "target name, used as the HDF5 group name"),
    _Column("M", u.Msun, "M_sun", True, True, "stellar mass"),
    _Column("Teff", u.K, "K", True, True, "effective temperature"),
    _Column("R", u.Rsun, "R_sun", True, True, "stellar radius"),
    _Column("D", u.pc, "pc", True, True, "distance"),
    _Column("magk", None, "", False, False, "K magnitude (metadata only)"),
    _Column("ra", u.deg, "deg", False, False, "right ascension; needs dec"),
    _Column(
        "dec",
        u.deg,
        "deg",
        False,
        False,
        "declination; with ra and zodiacalMap the "
        "zodiacal level is fitted from the sky map",
    ),
)
_BY_FIELD = {column.field: column for column in STAR_COLUMNS}


def _header_of(column: _Column) -> str:
    return f"star {column.field}" + (
        f" [{column.unit_text}]" if column.unit_text else ""
    )


def target_requirements() -> list[dict[str, Any]]:
    """The target-list column table as plain rows (``config_requirements``)."""
    return [
        {
            "path": _header_of(column),
            "required": "observe" if column.required else "optional",
            "unit": column.unit_text or None,
            "values": "text matching " + NAME_PATTERN
            if column.field == "name"
            else ("finite number > 0" if column.positive else "finite number"),
            "default": None,
            "note": column.note,
        }
        for column in STAR_COLUMNS
    ]


@dataclass
class TargetReport:
    """Outcome of :func:`validate_target_list`."""

    rows: int = 0
    names: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)  #: the star columns of the header
    header: list[str] = field(default_factory=list)  #: every column of the header

    @property
    def ok(self) -> bool:
        """True when there is no error finding."""
        return not errors_of(self.findings)


def _check_suffix(path: Path) -> None:
    if path.suffix.lower() != ".csv":
        raise ValueError(
            f"a target list must be a .csv file, got '{path.name}' "
            "(.xlsx and other formats are not accepted by the MCP)"
        )


def _name_problem(name: str) -> str | None:
    if not name:
        return "the target name is empty"
    if ".." in name or not _NAME_RE.match(name):
        return (
            f"target name '{name}' is not allowed: use 1-64 letters, digits, spaces or "
            "_ . + - ( ), starting with a letter or digit (no '/', '..', leading dot)"
        )
    return None


def _number(cell: str) -> float | None:
    try:
        return float(cell)
    except ValueError:
        return None


def _read_rows(text: str) -> list[list[str]]:
    rows = []
    for row in csv.reader(io.StringIO(text)):
        cells = [cell.strip() for cell in row]
        if not any(cells) or cells[0].startswith("#"):
            continue
        rows.append(cells)
    return rows


def _parse_header(header: list[str], report: TargetReport) -> dict[str, int]:
    """Map star field -> column index; add header findings."""
    index: dict[str, int] = {}
    units: dict[str, str | None] = {}
    for position, cell in enumerate(header):
        if "planet" in cell:
            if not any(f.code == "PLANET_COLUMNS_IGNORED" for f in report.findings):
                report.findings.append(
                    Finding(
                        WARNING,
                        "PLANET_COLUMNS_IGNORED",
                        cell,
                        "planet columns are read by the library but the pipeline ignores "
                        "them (the target name then comes from the planet name)",
                    )
                )
            continue
        if "star" not in cell:
            continue
        parts = cell.split(" ")
        if len(parts) < 2:
            report.findings.append(
                Finding(
                    ERROR,
                    "VALUE_INVALID",
                    cell,
                    "a star column must be 'star <field> [<unit>]'",
                )
            )
            continue
        index.setdefault(parts[1], position)
        units.setdefault(
            parts[1],
            parts[2].replace("[", "").replace("]", "") if len(parts) == 3 else None,
        )
    for column in STAR_COLUMNS:
        shown = f"star {column.field}"
        if column.field not in index:
            if column.required:
                report.findings.append(
                    Finding(
                        ERROR,
                        "TARGET_COLUMN_MISSING",
                        shown,
                        f"required column '{_header_of(column)}' is missing ({column.note})",
                    )
                )
            continue
        if column.unit is None:
            continue
        unit_text = units.get(column.field)
        if unit_text is None:
            if column.required:
                report.findings.append(
                    Finding(
                        ERROR,
                        "TARGET_UNIT_MISSING",
                        shown,
                        f"column '{shown}' needs a unit in the header, e.g. '{_header_of(column)}'",
                    )
                )
            continue
        try:
            parsed = u.Unit(unit_text)
        except (ValueError, TypeError):
            report.findings.append(
                Finding(
                    ERROR, "UNIT_INVALID", shown, f"'{unit_text}' is not a valid unit"
                )
            )
            continue
        if not parsed.is_equivalent(column.unit):
            report.findings.append(
                Finding(
                    ERROR,
                    "UNIT_INVALID",
                    shown,
                    f"unit '{unit_text}' is not a unit of {column.unit.physical_type}",
                )
            )
    if "ra" in index and "dec" not in index:
        report.findings.append(
            Finding(
                ERROR,
                "TARGET_COLUMN_MISSING",
                "star dec",
                "column 'star ra' is present but 'star dec' is missing: the zodiacal "
                "foreground needs both coordinates",
            )
        )
    return index


def validate_target_list(path: Path, *, sandbox: Sandbox) -> TargetReport:
    """Check a target-list CSV without running ExoRad code.

    Parameters
    ----------
    path : pathlib.Path
        An already resolved ``.csv`` file.
    sandbox : Sandbox
        Limits (``max_targets``, ``max_file_mb``).

    Returns
    -------
    TargetReport
        Row count, names, columns and findings.

    Raises
    ------
    ValueError
        If the suffix is not ``.csv``.
    FileNotFoundError
        If the file does not exist.
    """
    _check_suffix(path)
    report = TargetReport()
    try:
        info = os.stat(path)
    except FileNotFoundError:
        raise FileNotFoundError(f"file not found: {path.name}") from None
    if not stat.S_ISREG(info.st_mode):
        report.findings.append(
            Finding(
                ERROR,
                "NOT_REGULAR_FILE",
                path.name,
                "the target list is not a regular file",
            )
        )
        return report
    if info.st_size > sandbox.max_file_mb * 1_048_576:
        report.findings.append(
            Finding(
                ERROR,
                "FILE_TOO_LARGE",
                path.name,
                f"the target list is {info.st_size / 1_048_576:.1f} MB, above the "
                f"{sandbox.max_file_mb} MB limit (EXORAD_MCP_MAX_FILE_MB)",
            )
        )
        return report
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        report.findings.append(
            Finding(
                ERROR,
                "VALUE_INVALID",
                path.name,
                "the target list is not valid UTF-8 text",
            )
        )
        return report
    rows = _read_rows(text)
    if not rows:
        report.findings.append(
            Finding(
                ERROR, "TARGET_COUNT", path.name, "the file is empty: no header found"
            )
        )
        return report
    header, data = rows[0], rows[1:]
    report.header = list(header)
    report.columns = [cell for cell in header if "star" in cell]
    index = _parse_header(header, report)
    report.rows = len(data)
    if not data:
        report.findings.append(
            Finding(ERROR, "TARGET_COUNT", path.name, "the target list has no targets")
        )
    elif len(data) > sandbox.max_targets:
        report.findings.append(
            Finding(
                ERROR,
                "TARGET_COUNT",
                path.name,
                f"{len(data)} targets, above the limit of {sandbox.max_targets} "
                "(EXORAD_MCP_MAX_TARGETS)",
            )
        )
        return report
    if (
        any(
            f.code in {"TARGET_COLUMN_MISSING", "TARGET_UNIT_MISSING"}
            and f.severity == ERROR
            for f in report.findings
        )
        and "name" not in index
    ):
        return report
    _check_rows(data, header, index, report)
    return report


def _check_rows(
    data: list[list[str]],
    header: list[str],
    index: dict[str, int],
    report: TargetReport,
) -> None:
    seen: dict[str, int] = {}
    folded: dict[str, str] = {}

    def add(severity: str, code: str, where: str, message: str) -> None:
        if len(report.findings) < _MAX_FINDINGS:
            report.findings.append(Finding(severity, code, where, message))

    for number, row in enumerate(data, start=1):
        where = f"row {number}"
        if len(row) != len(header):
            add(
                ERROR,
                "VALUE_INVALID",
                where,
                f"{len(row)} cells but the header has {len(header)} columns",
            )
            continue
        if "name" in index:
            name = row[index["name"]]
            report.names.append(name)
            problem = _name_problem(name)
            if problem:
                add(ERROR, "TARGET_NAME_INVALID", where, problem)
            elif name in seen:
                add(
                    ERROR,
                    "TARGET_DUPLICATE",
                    where,
                    f"target name '{name}' is already used in row {seen[name]}: "
                    "duplicate names collapse into one result",
                )
            else:
                seen[name] = number
                key = name.casefold()
                if key in folded:
                    add(
                        WARNING,
                        "TARGET_DUPLICATE",
                        where,
                        f"target name '{name}' differs from '{folded[key]}' only by case: "
                        "plot files collide on case-insensitive file systems",
                    )
                folded.setdefault(key, name)
        for column in STAR_COLUMNS[1:]:
            if column.field not in index:
                continue
            cell = row[index[column.field]]
            value = _number(cell)
            shown = f"{where} star {column.field}"
            if value is None or not math.isfinite(value):
                if column.required or cell:
                    add(
                        ERROR,
                        "VALUE_INVALID",
                        shown,
                        f"'{cell}' is not a finite number"
                        if cell
                        else "the value is empty",
                    )
            elif column.positive and value <= 0:
                add(
                    ERROR,
                    "VALUE_INVALID",
                    shown,
                    f"{column.field} must be > 0, got {cell}",
                )


def describe_target_list(path: Path, *, sandbox: Sandbox) -> dict[str, Any]:
    """Compare a target list with the column table (``config_requirements``).

    Returns ``present``, ``missing``, ``extra`` (columns the pipeline does not
    use) and ``findings``; columns are named like :func:`target_requirements`.
    """
    report = validate_target_list(path, sandbox=sandbox)
    fields = {cell.split(" ")[1] for cell in report.columns if len(cell.split(" ")) > 1}
    present = [_header_of(c) for c in STAR_COLUMNS if c.field in fields]
    missing = [
        _header_of(_BY_FIELD[f.path.split(" ")[1]])
        for f in report.findings
        if f.code == "TARGET_COLUMN_MISSING" and f.path.split(" ")[-1] in _BY_FIELD
    ]
    extra = [
        cell
        for cell in report.header
        if "planet" not in cell
        and not (
            "star" in cell
            and len(cell.split(" ")) > 1
            and cell.split(" ")[1] in _BY_FIELD
        )
    ]
    return {
        "present": present,
        "missing": missing,
        "extra": extra,
        "findings": report.findings,
    }


def write_target_csv(rows: list[dict[str, Any]], dest: Path) -> list[str]:
    """Write ``rows`` as a target-list CSV with the header of the shipped example.

    Each row has ``name`` (str), ``M`` (M_sun), ``Teff`` (K), ``R`` (R_sun), ``D``
    (pc) and optionally ``magk``, ``ra`` (deg), ``dec`` (deg); an optional key
    must be given for every row or for none, and ``ra`` needs ``dec``. Nothing is
    written when a row is invalid.

    Returns
    -------
    list of str
        The column headers written, in order.

    Raises
    ------
    ValueError
        For unknown or missing keys, non-numbers, non-finite or non-positive
        values, invalid or duplicate names, or no rows.
    """
    if not rows:
        raise ValueError("a target list needs at least one target")
    allowed = {column.field for column in STAR_COLUMNS}
    for number, row in enumerate(rows, start=1):
        unknown = sorted(set(row) - allowed)
        if unknown:
            raise ValueError(
                f"target {number}: unknown key(s) {unknown}; allowed: {sorted(allowed)}"
            )
        missing = [c.field for c in STAR_COLUMNS if c.required and c.field not in row]
        if missing:
            raise ValueError(f"target {number}: missing required key(s) {missing}")
    optional = [c.field for c in STAR_COLUMNS if not c.required]
    used = [key for key in optional if any(key in row for row in rows)]
    for key in used:
        if not all(key in row for row in rows):
            raise ValueError(f"'{key}' must be given for every target or for none")
    if ("ra" in used) != ("dec" in used):
        raise ValueError("'ra' and 'dec' must be given together")
    names: set[str] = set()
    cells: list[list[str]] = []
    fields = [c.field for c in STAR_COLUMNS if c.required or c.field in used]
    for number, row in enumerate(rows, start=1):
        name = row["name"]
        problem = (
            _name_problem(name) if isinstance(name, str) else "the name must be text"
        )
        if problem:
            raise ValueError(f"target {number}: {problem}")
        if name in names:
            raise ValueError(f"target {number}: duplicate target name '{name}'")
        names.add(name)
        line = [name]
        for key in fields[1:]:
            value = row[key]
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(
                    f"target {number}: '{key}' must be a number, got {value!r}"
                )
            if not math.isfinite(value):
                raise ValueError(f"target {number}: '{key}' must be finite")
            if _BY_FIELD[key].positive and value <= 0:
                raise ValueError(
                    f"target {number}: '{key}' must be positive, got {value}"
                )
            line.append(f"{float(value):.12g}")
        cells.append(line)
    columns = [_header_of(_BY_FIELD[key]) for key in fields]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(cells)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(buffer.getvalue(), encoding="utf-8")
    return columns
