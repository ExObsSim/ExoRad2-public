"""Static rules for ExoRad payload XML files.

The payload is ONE XML file whose tables (QE curves, SEDs, ...) are referenced by
path. Before any ExoRad code reads it, this module answers three questions that
need no execution:

* **Is it safe to open?** Size, DOCTYPE (an expat handler, so UTF-16 input is
  covered), URLs, executable pointers (``.pickle``/``.py`` for ``datadict`` and
  ``config_dict``), files that are not regular files, HDF5 external links and
  virtual datasets, and every path resolved inside the sandbox.
* **Is it complete?** The required-element table (:data:`RULES`) was derived by
  removing each element of ``examples/payload_example.xml`` in turn and running
  ``PreparePayload`` (``build``) and ``ObserveTarget`` (``observe``); a test
  repeats that experiment, so the table cannot drift from the library.
* **Which files will the run open?** :func:`normalise_payload` writes a copy of
  the payload in which ``<ConfigPath>`` and every path the selected source
  actually reads are absolute. Validation and the job BOTH use that copy, so they
  open exactly the same files, and nobody has to ``chdir``.

``LoadOptions`` is never called here unless the static findings hold no error
(:func:`load_options` / :func:`load_payload_dict`). It writes the process-global
``PassVal.working_R``, so every call holds :data:`CONFIG_LOAD_LOCK` and restores it.
"""

from __future__ import annotations

import contextlib
import glob
import math
import os
import re
import stat
import tempfile
import threading
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from xml.parsers import expat

from astropy import units as u
from astropy.units import UnitsWarning

from exorad.mcp.sandbox import PathNotAllowedError
from exorad.tasks.loadOptions import LoadOptions

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from exorad.mcp.sandbox import Sandbox

__all__ = [
    "CONFIG_LOAD_LOCK",
    "FINDING_CODES",
    "KEYWORD",
    "MAX_CHANNELS",
    "MAX_OPTICAL_ELEMENTS",
    "MAX_WORKING_R",
    "PATH_KEYS",
    "RULES",
    "ConfigRuleError",
    "Finding",
    "NormalisedPayload",
    "Rule",
    "describe_payload",
    "errors_of",
    "has_hdf5_signature",
    "hdf5_link_problems",
    "hdf5_scan",
    "load_options",
    "load_payload_dict",
    "normalise_payload",
    "payload_findings",
    "payload_requirements",
    "recheck_payload",
    "scratch_dir",
    "static_findings",
    "strict_file_problem",
    "tree_findings",
]

#: Held around every ``LoadOptions`` call: the loader writes ``PassVal.working_R``
#: and sync tools run in worker threads.
CONFIG_LOAD_LOCK = threading.RLock()

KEYWORD = "__ConfigPath__"
MAX_WORKING_R = 30000
DEFAULT_WORKING_R = 6000
MAX_CHANNELS = 16
MAX_OPTICAL_ELEMENTS = 64
#: Wavelength range (micron) where the demo SED is sampled finely (spec 4.3).
FINE_SEGMENT_UM = (0.4, 2.6)
DEMO_SED_NAME = "customsed_demo.csv"

ERROR = "error"
WARNING = "warning"

#: The stable finding codes (spec 3.3) plus four additions: ``UNSUPPORTED_FORMAT``
#: (a file of a kind the loader cannot use), ``VALUE_INVALID`` (a value the library
#: cannot use), ``LOADER_FAILED`` (the library rejected a payload the static rules
#: accepted), ``DEEP_BUILD_FAILED`` (the optional channel build failed) and
#: ``ATTRIBUTE_REFUSED`` (an XML attribute other than ``unit``: the loader turns every
#: attribute into a key, so it could carry a path the scan would not see) and
#: ``CONFIG_DICT_REFUSED`` (``<config_dict>`` replaces the element that holds it with
#: the content of an HDF5 file, so the numeric caps computed on the XML would no
#: longer describe what the run uses) and ``CONFIGPATH_MULTIPLE`` (more than one
#: ``<ConfigPath>``: the loader keeps the last, the copy rewrites one place).
FINDING_CODES = (
    "XML_PARSE",
    "XML_DOCTYPE",
    "FILE_TOO_LARGE",
    "MISSING_ELEMENT",
    "CONFIGPATH_ORDER",
    "FILE_MISSING",
    "PATH_OUTSIDE_SANDBOX",
    "SOURCE_SED_BLOCKED",
    "SOURCE_UNKNOWN_FALLS_BACK_TO_PLANCK",
    "PICKLE_REFUSED",
    "LIMIT_EXCEEDED",
    "UNIT_INVALID",
    "TARGET_COLUMN_MISSING",
    "TARGET_UNIT_MISSING",
    "TARGET_NAME_INVALID",
    "TARGET_DUPLICATE",
    "TARGET_COUNT",
    "NOT_REGULAR_FILE",
    "HDF5_LINK_REFUSED",
    "SED_COARSE_OUTSIDE_FINE_SEGMENT",
    "PLANET_COLUMNS_IGNORED",
    "UNSUPPORTED_FORMAT",
    "VALUE_INVALID",
    "LOADER_FAILED",
    "DEEP_BUILD_FAILED",
    "ATTRIBUTE_REFUSED",
    "CONFIG_DICT_REFUSED",
    "CONFIGPATH_MULTIPLE",
)


@dataclass(frozen=True)
class Finding:
    """One result of a static check."""

    severity: str  #: ``"error"`` or ``"warning"``
    code: str  #: one of :data:`FINDING_CODES`
    path: str  #: element path (``channel/Spec/detector/qe``) or file/column name
    message: str  #: human text, never an absolute server path

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


def errors_of(findings: list[Finding]) -> list[Finding]:
    """The findings with severity ``error``."""
    return [f for f in findings if f.severity == ERROR]


class ConfigRuleError(ValueError):
    """Raised by callers that must not continue past error findings."""

    def __init__(self, findings: list[Finding]) -> None:
        self.findings = list(findings)
        lines = [f"{f.code} {f.path}: {f.message}" for f in errors_of(self.findings)]
        super().__init__("\n".join(lines) or "configuration rejected")


# --------------------------------------------------------------------------------
# the requirement table
# --------------------------------------------------------------------------------
#: Elements whose text is a path the library opens (spec 2.7). ``data`` counts only
#: under ``targetR`` (see :func:`_is_path_element`).
PATH_TAGS = frozenset(
    {"datafile", "datadict", "config_dict", "CustomSed", "StellarModels", "PSF"}
    | {"custom_map_file"}
)
PATH_KEYS = PATH_TAGS | {"targetR/data"}
_EXEC_SUFFIXES = (".pickle", ".pkl", ".py")
_H5_SUFFIXES = (".h5", ".hdf5")
#: First bytes of an HDF5 file; a user block moves it to offset 512 * 2**n.
HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
_DIRECTORY_TAGS = frozenset({"StellarModels"})
#: An HDF5 input may declare at most ``max_data_mb`` x this many MB once uncompressed
#: (dataset shape x item size, from the metadata; nothing is read). The file size
#: limit alone says nothing about a compressed or sparse dataset: gzip reaches
#: about 1000:1 on constant data, so a few KB can declare terabytes.
HDF5_EXPANSION_FACTOR = 8
#: Text tables (``ascii.read`` of a CSV/ECSV) are scanned before the library reads
#: them: the library has no limit of its own, and the size limit does not bound
#: the number of rows, the length of a line or the number of columns.
MAX_TABLE_ROWS = 5_000_000
MAX_TABLE_LINE_BYTES = 1_048_576
MAX_TABLE_COLUMNS = 1000
_TABLE_TAGS = frozenset({"datafile", "CustomSed", "data"})
_BINARY_SUFFIXES = (".fits", ".fit", ".fts", *_H5_SUFFIXES)
#: The most files a directory reference may list (the library opens them one by one).
MAX_GLOB_FILES = 5000
_FILE_OR_DIRECTORY_TAGS = frozenset({"PSF"})
#: Tags whose repeated siblings are named by their text (``LoadOptions``, 119-130).
_REPEATED = frozenset({"channel", "opticalElement", "foreground", "customNoise"})
#: Keys that are framework bookkeeping, never "extra" configuration.
FRAMEWORK_KEYS = frozenset({"ConfigPath", "fileName", "comment", "unit", "value"})


@dataclass(frozen=True)
class Rule:
    """One row of the payload requirement table."""

    pattern: str  #: ``/``-separated; ``*`` marks "each named repeat" and is a no-op
    required: str  #: ``build`` | ``observe`` | ``optional``
    unit: str | None = None
    values: str | None = None
    default: str | None = None
    note: str = ""
    when: str | None = None  #: condition on the parent (see :func:`_when_ok`)
    needs_text: bool = False  #: the element must carry a value ...
    text_alt: tuple[str, ...] = ()  #: ... or one of these children
    alt: tuple[str, ...] = ()  #: sibling elements that satisfy the rule instead

    @property
    def display(self) -> str:
        return self.pattern + ("|" + "|".join(self.alt) if self.alt else "")


def _r(pattern: str, required: str, **kw: Any) -> Rule:
    return Rule(pattern, required, **kw)


_OPTICAL: tuple[tuple[str, str, dict[str, str]], ...] = (
    (
        "type",
        "build",
        {"values": "surface | filter | slit | optics box | detector box"},
    ),
    (
        "width",
        "build",
        {"unit": "mm", "when": "slit", "note": "slit width; slits only"},
    ),
    ("temperature", "optional", {"unit": "K"}),
    ("emissivity", "optional", {}),
    ("transmission", "optional", {}),
    ("reflectivity", "optional", {}),
    ("use", "optional", {"values": "transmission | reflectivity"}),
    ("wl_min", "optional", {"unit": "micron"}),
    ("wl_max", "optional", {"unit": "micron"}),
    ("datafile", "optional", {"note": "table of the element's properties"}),
)


def _optical_rules(prefix: str) -> list[Rule]:
    rows = [
        _r(f"{prefix}/opticalElement", "optional", note="repeated; named by its text")
    ]
    for tag, level, kw in _OPTICAL:
        rows.append(_r(f"{prefix}/opticalElement/*/{tag}", level, **kw))
    return rows


RULES: tuple[Rule, ...] = (
    _r(
        "ConfigPath",
        "optional",
        note="needed when any value uses __ConfigPath__; must come first",
    ),
    _r("fileName", "optional"),
    _r("common", "build"),
    _r("common/wl_min", "build", unit="micron", note="shortest wavelength of the run"),
    _r("common/wl_max", "build", unit="micron", note="longest wavelength of the run"),
    _r(
        "common/sourceSpectrum",
        "observe",
        values="planck | phoenix | custom | sed",
        note="unknown values silently become planck; sed is blocked in the MCP",
        needs_text=True,
    ),
    _r(
        "common/sourceSpectrum/CustomSed",
        "observe",
        when="source:custom",
        needs_text=True,
    ),
    _r(
        "common/sourceSpectrum/StellarModels",
        "observe",
        when="source:phoenix",
        needs_text=True,
        note="or the PHOENIX_PATH environment variable",
    ),
    _r(
        "common/sourceSpectrum/SedModel",
        "optional",
        note="only for sed, which is blocked",
    ),
    _r("common/working_R", "optional", default="6000", note="grid size of every table"),
    _r("common/foreground", "optional", values="zodiacal | <name>", note="repeated"),
    _r(
        "common/foreground/*/datafile",
        "observe",
        when="foreground:other",
        note="Wavelength, Radiance and Transmission columns",
    ),
    _r("common/foreground/*/zodiacFactor", "optional"),
    _r("common/foreground/*/zodiacalMap", "optional", values="True | False"),
    _r("common/foreground/*/custom_map_file", "optional"),
    _r(
        "common/customNoise",
        "optional",
        unit="ppm",
        note="repeated; <name> or <datafile>",
    ),
    _r("common/customNoise/*/name", "optional"),
    _r("common/customNoise/*/datafile", "optional"),
    _r("optics", "build"),
    _r(
        "optics/ForceChannelWlEdge",
        "build",
        values="True | False",
        note="required although the example comment says it may be commented out",
    ),
    _r("optics/Atel", "observe", unit="m**2", note="telescope collecting area"),
    _r("optics/EncESolution", "optional"),
    *_optical_rules("optics"),
    _r("channel", "build", note="at least one; repeated, named by its text"),
    _r("channel/*/channelClass", "build", values="Photometer | Spectrometer"),
    _r("channel/*/wl_min", "build", unit="micron"),
    _r("channel/*/wl_max", "build", unit="micron"),
    _r("channel/*/Fnum_x", "build"),
    _r("channel/*/Fnum_y", "build"),
    _r("channel/*/NoiseX", "optional"),
    _r("channel/*/window_spatial_scale", "optional"),
    _r("channel/*/zodiacFactor", "optional"),
    _r(
        "channel/*/targetR",
        "optional",
        values="number | native | <data> file",
        note="spectral resolution of the output bins; spectrometers",
    ),
    _r("channel/*/targetR/data", "optional", note="tab-separated W and R columns"),
    _r(
        "channel/*/customNoise",
        "optional",
        unit="ppm",
        note="repeated; <name> or <datafile>",
    ),
    _r("channel/*/customNoise/*/name", "optional"),
    _r("channel/*/customNoise/*/datafile", "optional"),
    _r("channel/*/EncESolution", "optional"),
    _r("channel/*/WFErms", "optional", unit="micron"),
    _r("channel/*/PSF", "optional", note="FITS file, directory or PAOS HDF5"),
    _r("channel/*/PSF/format", "optional", values="paos"),
    _r("channel/*/aperture", "build", when="photometer"),
    _r(
        "channel/*/aperture/radius",
        "build",
        when="photometer",
        alt=("EnE",),
        note="in units of F-lambda; or EnE (encircled energy)",
    ),
    _r("channel/*/aperture/apertureCorrection", "optional", when="photometer"),
    _r("channel/*/wlSolution", "build", when="spectrometer"),
    _r(
        "channel/*/wlSolution/datafile",
        "build",
        when="spectrometer",
        note="Wavelength and x columns",
    ),
    _r("channel/*/optics", "build"),
    *_optical_rules("channel/*/optics"),
    _r("channel/*/detector", "build"),
    _r("channel/*/detector/delta_pix", "build", unit="micron"),
    _r(
        "channel/*/detector/qe",
        "build",
        needs_text=True,
        text_alt=("datafile",),
        note="a value, or a datafile with a column named like the channel",
    ),
    _r("channel/*/detector/qe/datafile", "optional"),
    _r("channel/*/detector/wl_min", "build", unit="micron"),
    _r("channel/*/detector/cut_off", "build", unit="micron"),
    _r("channel/*/detector/read_noise", "observe", unit="count"),
    _r("channel/*/detector/dark_current", "observe", unit="count/s"),
    _r("channel/*/detector/well_depth", "observe", unit="count"),
    _r("channel/*/detector/f_well_depth", "observe"),
    _r(
        "channel/*/detector/freqNDR", "observe", unit="Hz", note="0 selects CDS reading"
    ),
)

_PATTERN_PARTS = {
    rule.pattern: [p for p in rule.pattern.split("/") if p != "*"] for rule in RULES
}
_KNOWN_PATTERNS = frozenset(tuple(parts) for parts in _PATTERN_PARTS.values())


def payload_requirements() -> list[dict[str, Any]]:
    """The requirement table as plain rows (``config_requirements``, spec 3.3)."""
    return [
        {
            "path": rule.display,
            "required": rule.required,
            "unit": rule.unit,
            "values": rule.values,
            "default": rule.default,
            "note": rule.note,
            "when": rule.when,
        }
        for rule in RULES
    ]


# --------------------------------------------------------------------------------
# small XML helpers (they mirror what LoadOptions does to a value)
# --------------------------------------------------------------------------------
def _text(element: ET.Element) -> str:
    """The element text the way ``LoadOptions`` sees it (``compactString``)."""
    return (element.text or "").replace("\n", "").strip()


def _children(element: ET.Element, tag: str) -> list[ET.Element]:
    return [child for child in element if child.tag == tag]


def _label(element: ET.Element) -> str:
    """Path segment of an element: repeated tags carry their name."""
    if element.tag in _REPEATED:
        name = _text(element)
        return f"{element.tag}/{name}" if name else element.tag
    return element.tag


def _join(prefix: str, segment: str) -> str:
    return f"{prefix}/{segment}" if prefix else segment


def _number(element: ET.Element | None) -> float | None:
    if element is None:
        return None
    try:
        return float(_text(element))
    except ValueError:
        return None


def _length_um(element: ET.Element | None) -> float | None:
    """A wavelength element in micron (no unit means micron, as the library assumes)."""
    value = _number(element)
    if value is None or element is None:
        return None
    unit = element.get("unit")
    if not unit:
        return value
    try:
        return float((value * u.Unit(unit)).to(u.um).value)
    except (ValueError, u.UnitsError):
        return None


def _walk(
    element: ET.Element, prefix: str = ""
) -> Iterator[tuple[str, ET.Element, ET.Element]]:
    """``(path, element, parent)`` for every element outside ``<comment>`` subtrees.

    For the semantic checks (units, limits). The safety scan uses :func:`_walk_all`.
    """
    for child in element:
        if child.tag == "comment":
            continue
        path = _join(prefix, _label(child))
        yield path, child, element
        yield from _walk(child, path)


def _walk_all(
    element: ET.Element, prefix: str = "", in_comment: bool = False
) -> Iterator[tuple[str, ET.Element, ET.Element, bool]]:
    """``(path, element, parent, in_comment)`` for EVERY element, comments included.

    ``LoadOptions.__parser__`` recurses into every child (``<comment>`` is an
    ordinary tag to it), so the safety scan must too.
    """
    for child in element:
        path = _join(prefix, _label(child))
        inside = in_comment or child.tag == "comment"
        yield path, child, element, in_comment
        yield from _walk_all(child, path, inside)


# --------------------------------------------------------------------------------
# reading the file safely
# --------------------------------------------------------------------------------
class _DoctypeSeen(Exception):  # noqa: N818 - control flow, not an error type
    """Raised by the expat handler to stop at the first DOCTYPE declaration."""


def _read_payload(
    path: Path, sandbox: Sandbox
) -> tuple[ET.Element | None, list[Finding]]:
    """Read and parse ``path`` after the size/regular-file/DOCTYPE guards."""
    name = path.name
    try:
        info = os.stat(path)
    except FileNotFoundError:
        raise FileNotFoundError(f"file not found: {name}") from None
    if not stat.S_ISREG(info.st_mode):
        return None, [
            Finding(
                ERROR, "NOT_REGULAR_FILE", name, "the payload is not a regular file"
            )
        ]
    limit = sandbox.max_file_mb * 1_048_576
    if info.st_size > limit:
        return None, [
            Finding(
                ERROR,
                "FILE_TOO_LARGE",
                name,
                f"the payload is {info.st_size / 1_048_576:.1f} MB, above the "
                f"{sandbox.max_file_mb} MB limit (EXORAD_MCP_MAX_FILE_MB)",
            )
        ]
    data = path.read_bytes()
    parser = expat.ParserCreate()

    def refuse(*_args: object) -> None:
        raise _DoctypeSeen

    parser.StartDoctypeDeclHandler = refuse
    try:
        parser.Parse(data, True)
    except _DoctypeSeen:
        return None, [
            Finding(
                ERROR,
                "XML_DOCTYPE",
                name,
                "a DOCTYPE declaration is not allowed in a payload (entities are refused)",
            )
        ]
    except expat.ExpatError as exc:
        return None, [Finding(ERROR, "XML_PARSE", name, f"not well-formed XML: {exc}")]
    try:
        return ET.fromstring(data), []
    except ET.ParseError as exc:  # pragma: no cover - expat already accepted it
        return None, [Finding(ERROR, "XML_PARSE", name, f"not well-formed XML: {exc}")]


def _open_regular(path: str | Path) -> int:
    """Open ``path`` read-only WITHOUT following a symlink or blocking on a FIFO.

    Returns a file descriptor of a regular file; raises :class:`OSError` otherwise.
    """
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(f"{Path(path).name} is not a regular file")
    except BaseException:
        os.close(fd)
        raise
    return fd


def has_hdf5_signature(path: str | Path) -> bool:
    """True when ``path`` is a regular file that starts like an HDF5 file.

    Only the 8 signature bytes are read, at offset 0 and at the offsets a user
    block can move them to (512, 1024, 2048, ...). Nothing is followed: a symlink,
    a FIFO or an unreadable file simply answers ``False``.
    """
    try:
        fd = _open_regular(path)
    except OSError:
        return False
    try:
        size = os.fstat(fd).st_size
        offset = 0
        while offset + len(HDF5_SIGNATURE) <= size:
            if os.pread(fd, len(HDF5_SIGNATURE), offset) == HDF5_SIGNATURE:
                return True
            offset = 512 if offset == 0 else offset * 2
    except OSError:
        return False
    finally:
        os.close(fd)
    return False


def hdf5_scan(path: str | Path, *, max_nodes: int = 200_000) -> tuple[list[str], int]:
    """Scan an HDF5 file without following or reading anything.

    Returns ``(problems, uncompressed_bytes)``. ``problems`` lists the features that
    would make a reader leave the file (H17): external links, virtual datasets and
    datasets with external raw storage; they are found WITHOUT following them
    (links are inspected with ``getlink=True``, soft links are not followed,
    hard-link cycles are broken). ``uncompressed_bytes`` adds up, over the
    datasets, the product of the declared shape and the item size: what a reader
    that loads everything would allocate, however small the file is on disk
    (sparse, fill-valued and compressed datasets). Only metadata is touched.
    Raises :class:`OSError` when the file is not HDF5.
    """
    import h5py

    problems: list[str] = []
    seen: set[Any] = set()
    count = 0
    total = 0
    with h5py.File(path, "r") as handle:
        stack = [handle]
        seen.add(handle.id)
        while stack:
            group = stack.pop()
            for name in group:
                count += 1
                if count > max_nodes:
                    problems.append("too many nodes to scan")
                    return problems, total
                where = f"{group.name.rstrip('/')}/{name}"
                link = group.get(name, getlink=True)
                if isinstance(link, h5py.ExternalLink):
                    problems.append(f"external link at {where}")
                    continue
                if isinstance(link, h5py.SoftLink):
                    continue
                obj = group.get(name)
                if isinstance(obj, h5py.Group):
                    if obj.id not in seen:
                        seen.add(obj.id)
                        stack.append(obj)
                elif isinstance(obj, h5py.Dataset):
                    if obj.is_virtual:
                        problems.append(f"virtual dataset at {where}")
                    elif obj.external:
                        problems.append(f"dataset with external storage at {where}")
                    else:
                        total += math.prod(obj.shape or ()) * obj.dtype.itemsize
    return problems, total


def hdf5_link_problems(path: str | Path, *, max_nodes: int = 200_000) -> list[str]:
    """The ``problems`` of :func:`hdf5_scan` (links, virtual datasets, external storage)."""
    return hdf5_scan(path, max_nodes=max_nodes)[0]


def _table_problem(path: Path) -> str | None:
    """Why a text table is too big to hand to ``ascii.read``, or ``None``.

    Streams the file once (nothing is kept): the number of lines, the longest line
    and the number of columns of the first line that is not a ``#`` header line.
    """
    columns = 0
    rows = 0
    try:
        fd = _open_regular(path)
    except OSError as exc:
        return f"cannot be read ({exc.strerror or 'not a regular file'})"
    with os.fdopen(fd, "rb") as handle:
        while True:
            line = handle.readline(MAX_TABLE_LINE_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_TABLE_LINE_BYTES and not line.endswith(b"\n"):
                return f"has a line longer than {MAX_TABLE_LINE_BYTES} bytes"
            rows += 1
            if rows > MAX_TABLE_ROWS:
                return f"has more than {MAX_TABLE_ROWS} lines"
            if not columns and not line.lstrip().startswith(b"#") and line.strip():
                columns = len(re.split(rb"[,\s]+", line.strip()))
                if columns > MAX_TABLE_COLUMNS:
                    return (
                        f"has {columns} columns, above the limit of {MAX_TABLE_COLUMNS}"
                    )
    return None


# --------------------------------------------------------------------------------
# the analysis
# --------------------------------------------------------------------------------
@dataclass
class _Reference:
    tag: str
    raw: str
    path: str  #: element path
    element: ET.Element
    resolved: Path | None = None
    exists: bool = False
    allowed: bool = False
    packaged: bool = False
    is_dir: bool = False


@dataclass
class _Analysis:
    findings: list[Finding] = field(default_factory=list)
    references: list[_Reference] = field(default_factory=list)
    base: Path = field(default_factory=Path)
    config_path: Path | None = None
    source: str | None = None
    info: dict[str, Any] = field(default_factory=dict)
    missing_rules: set[str] = field(default_factory=set)
    #: Re-check of a normalised copy: every path is already resolved, so one that
    #: no longer is (a symlink swapped in since) is a finding.
    strict: bool = False
    #: ``False`` for a configuration that is not an ExoRad payload: only the
    #: generic loader-mirroring checks run, no payload-shape or semantic rules.
    payload_checks: bool = True
    #: Tags whose text is never collected as a file reference (e.g. an output
    #: directory); the URL / NUL checks still apply to their text.
    exclude_tags: frozenset[str] = frozenset()
    #: Extra tags whose text is always a file reference (an extension's own).
    extra_path_tags: frozenset[str] = frozenset()

    def add(self, severity: str, code: str, path: str, message: str) -> None:
        self.findings.append(Finding(severity, code, path, message))


def payload_base(payload: Path, sandbox: Sandbox) -> Path:
    """Directory that relative values of ``payload`` resolve against (spec 2.1).

    The payload's own directory, except for a payload directly under
    ``<content root>/examples/``: the shipped examples are written for a cwd that
    is the content root, so ``.`` means the content root there.
    """
    parent = payload.parent
    if parent == sandbox.repo_root / "examples":
        return sandbox.repo_root
    return parent


def _expand(raw: str, base: Path, config_path: Path | None) -> Path | None:
    """Absolute, symlink-free path for a value as written (``~``, keyword, base)."""
    candidate = _expand_unresolved(raw, base, config_path)
    return candidate.resolve() if candidate is not None else None


def _expand_unresolved(raw: str, base: Path, config_path: Path | None) -> Path | None:
    """:func:`_expand` without following symlinks (``..`` is not collapsed either)."""
    text = raw
    if KEYWORD in text:
        if config_path is None:
            return None
        text = text.replace(KEYWORD, str(config_path))
    try:
        candidate = Path(text).expanduser()
    except RuntimeError:
        return None
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate


def _is_path_element(tag: str, parent: ET.Element) -> bool:
    return tag in PATH_TAGS or (tag == "data" and parent.tag == "targetR")


def _looks_like_path(raw: str) -> bool:
    return KEYWORD in raw or raw.startswith("~") or os.path.isabs(raw)


def _analyse(
    root: ET.Element,
    payload: Path,
    sandbox: Sandbox,
    *,
    strict: bool = False,
    payload_checks: bool = True,
    exclude_reference_tags: Iterable[str] = (),
    reference_tags: Iterable[str] = (),
) -> _Analysis:
    result = _Analysis(
        base=payload_base(payload, sandbox),
        strict=strict,
        payload_checks=payload_checks,
        exclude_tags=frozenset(exclude_reference_tags),
        extra_path_tags=frozenset(reference_tags),
    )
    _config_path(root, result)
    _scan_values(root, result, sandbox)
    if not payload_checks:
        # what the loader reads is checked; the payload shape is not
        _check_references(result, sandbox)
        return result
    _check_required(root, result)
    _check_source(root, result)
    _check_references(result, sandbox)
    _check_limits(root, result, sandbox)
    _check_units(root, result)
    _check_demo_sed(root, result)
    return result


def _config_path(root: ET.Element, result: _Analysis) -> None:
    """Simulate the order in which ``LoadOptions`` sees ``ConfigPath`` and its uses.

    The loader handles an element's children first, then the element; a value that
    contains the keyword before any ``ConfigPath`` was handled raises
    ``TypeError`` (``replace() argument 2 must be str, not None``).
    """
    current: str | None = None
    reported = False
    if sum(1 for _ in root.iter("ConfigPath")) > 1:
        # The loader keeps the LAST one it meets, wherever it is, while the
        # normalised copy sets one element: the two would disagree about where
        # ``__ConfigPath__`` points. A payload has one.
        result.add(
            ERROR,
            "CONFIGPATH_MULTIPLE",
            "ConfigPath",
            "more than one <ConfigPath> (comments included): keep exactly one, "
            "as the first element of the file",
        )

    def visit(parent: ET.Element, prefix: str) -> None:
        nonlocal current, reported
        for child in parent:
            path = _join(prefix, _label(child))
            visit(child, path)
            value = _text(child)
            if KEYWORD in value and current is None and not reported:
                reported = True
                result.add(
                    ERROR,
                    "CONFIGPATH_ORDER",
                    path,
                    f"a value uses {KEYWORD} but no <ConfigPath> has been defined "
                    "before it: put <ConfigPath> first in the file",
                )
            if child.tag == "ConfigPath" and value:
                current = value

    visit(root, "")
    if current is not None:
        resolved = _expand(current, result.base, None)
        result.config_path = resolved
    else:
        result.config_path = None


def _scan_values(root: ET.Element, result: _Analysis, sandbox: Sandbox) -> None:
    """Collect path references; refuse URLs in any value."""
    source = _source_name(root)
    result.source = source
    for path, element, parent, in_comment in _walk_all(root):
        for name in element.attrib:
            if name != "unit":
                result.add(
                    ERROR,
                    "ATTRIBUTE_REFUSED",
                    path,
                    f"the attribute '{name}' is not allowed: the loader turns every "
                    "attribute into a key, so only 'unit' is accepted (write it as a "
                    "child element or as the element text)",
                )
        tag = element.tag
        if tag == "comment":
            continue  # the prose of a comment is never read as a value
        if tag == "config_dict":
            # ``LoadOptions`` REPLACES the whole element that holds it (``root_dict =
            # data``) with the contents of the file, so working_R, the channel and
            # optical-element counts, ``targetR`` ... that the semantic caps read
            # from the XML would never describe what the run uses. ``datadict`` only
            # adds a ``data`` key and cannot do that. Refused wherever it appears
            # (comments included: the loader parses them), whatever it names.
            result.add(
                ERROR,
                "CONFIG_DICT_REFUSED",
                path,
                "config_dict is not accepted: it replaces the element that holds it "
                "with the content of a file, which the static checks and the size "
                "limits cannot see; write the values in the payload XML instead",
            )
        raw = _text(element)
        if not raw:
            continue
        if "://" in raw:
            result.add(
                ERROR,
                "PATH_OUTSIDE_SANDBOX",
                path,
                "URLs are not allowed: only files inside the sandbox can be referenced",
            )
            continue
        if "\0" in raw:
            result.add(
                ERROR, "PATH_OUTSIDE_SANDBOX", path, "a value contains a NUL character"
            )
            continue
        if tag == "ConfigPath":
            continue
        if tag in result.exclude_tags:
            continue  # named by the caller: not a file reference
        if result.payload_checks:
            if not in_comment and tag == "CustomSed" and source != "custom":
                continue  # not read for this source
            if not in_comment and tag == "StellarModels" and source != "phoenix":
                continue
        if (
            _is_path_element(tag, parent)
            or tag in result.extra_path_tags
            or (not in_comment and _looks_like_path(raw))
        ):
            result.references.append(_Reference(tag, raw, path, element))


def _source_name(root: ET.Element) -> str | None:
    element = root.find("common/sourceSpectrum")
    if element is None:
        return None
    value = _text(element).lower()
    return value or None


def _check_source(root: ET.Element, result: _Analysis) -> None:
    source = result.source
    path = "common/sourceSpectrum"
    if source is None:
        return
    if source == "sed":
        result.add(
            ERROR,
            "SOURCE_SED_BLOCKED",
            path,
            "sourceSpectrum 'sed' downloads from the network and is disabled in the "
            "MCP; use planck, phoenix (local files) or custom",
        )
    elif source not in {"planck", "phoenix", "custom"}:
        result.add(
            WARNING,
            "SOURCE_UNKNOWN_FALLS_BACK_TO_PLANCK",
            path,
            f"unknown sourceSpectrum '{source}': ExoRad silently uses a Planck "
            "spectrum (valid: planck, phoenix, custom)",
        )


def _when_ok(
    when: str | None, parent: ET.Element, channel: ET.Element | None, result: _Analysis
) -> bool:
    if when is None:
        return True
    if when in {"photometer", "spectrometer"}:
        cls = channel.find("channelClass") if channel is not None else None
        return cls is not None and _text(cls).lower() == when
    if when == "slit":
        kind = parent.find("type")
        return kind is not None and _text(kind).lower() == "slit"
    if when == "source:custom":
        return result.source == "custom"
    if when == "source:phoenix":
        return result.source == "phoenix" and not os.environ.get("PHOENIX_PATH")
    if when == "foreground:other":
        return _text(parent).lower() != "zodiacal"
    return True


def _check_required(root: ET.Element, result: _Analysis) -> None:
    for rule in RULES:
        if rule.required == "optional":
            continue
        parts = _PATTERN_PARTS[rule.pattern]
        contexts: list[tuple[ET.Element, ET.Element | None, str]] = [(root, None, "")]
        for part in parts[:-1]:
            contexts = [
                (
                    child,
                    child if part == "channel" else channel,
                    _join(label, _label(child)),
                )
                for el, channel, label in contexts
                for child in _children(el, part)
            ]
        last = parts[-1]
        for el, channel, label in contexts:
            if not _when_ok(rule.when, el, channel, result):
                continue
            kids = _children(el, last)
            alt = [kid for name in rule.alt for kid in _children(el, name)]
            ok = bool(kids or alt)
            if ok and rule.needs_text and not alt:
                ok = any(
                    _text(kid) or any(_children(kid, name) for name in rule.text_alt)
                    for kid in kids
                )
            if not ok:
                result.missing_rules.add(rule.pattern)
                shown = "|".join((last, *rule.alt))
                result.add(
                    ERROR,
                    "MISSING_ELEMENT",
                    _join(label, shown),
                    f"{_join(label, shown)} is required at {rule.required} time"
                    + (f" ({rule.note})" if rule.note else ""),
                )


def _check_references(result: _Analysis, sandbox: Sandbox) -> None:
    for ref in result.references:
        _check_reference(ref, result, sandbox)


def _check_reference(ref: _Reference, result: _Analysis, sandbox: Sandbox) -> None:
    tag, shown = ref.tag, ref.path
    lowered = ref.raw.lower()
    if tag in {"datadict", "config_dict"}:
        if lowered.endswith(_EXEC_SUFFIXES):
            result.add(
                ERROR,
                "PICKLE_REFUSED",
                shown,
                f"{tag} points at a pickle or Python file, which would run arbitrary "
                "code when loaded: refused (use an .h5 file)",
            )
            return
        if not lowered.endswith(_H5_SUFFIXES):
            result.add(
                ERROR,
                "UNSUPPORTED_FORMAT",
                shown,
                f"{tag} must be an .h5 or .hdf5 file",
            )
            return
    resolved = _expand(ref.raw, result.base, result.config_path)
    if resolved is None:
        return  # CONFIGPATH_ORDER already says why
    if result.strict:
        written = _expand_unresolved(ref.raw, result.base, result.config_path)
        if written is not None and os.path.normpath(written) != str(resolved):
            result.add(
                ERROR,
                "NOT_REGULAR_FILE",
                shown,
                f"{tag} '{os.path.basename(ref.raw.rstrip('/'))}' now reaches its "
                "file through a symbolic link: it changed after the payload was "
                "validated, so it is refused",
            )
            return
    try:
        sandbox.resolve_read(resolved)
    except PathNotAllowedError:
        result.add(
            ERROR,
            "PATH_OUTSIDE_SANDBOX",
            shown,
            f"{tag} '{ref.raw}' resolves outside the directories this MCP server may "
            "read; keep the file in the content root, the work dir or an allowed dir",
        )
        return
    ref.resolved, ref.allowed = resolved, True
    ref.packaged = sandbox.content_source == "packaged" and _inside(
        resolved, sandbox.repo_root
    )
    display = sandbox.display_path(resolved)
    try:
        info = os.stat(resolved)
    except FileNotFoundError:
        result.add(ERROR, "FILE_MISSING", shown, f"{tag} file not found: {display}")
        return
    except OSError as exc:
        result.add(
            ERROR,
            "FILE_MISSING",
            shown,
            f"{tag} cannot be read: {display} ({exc.strerror})",
        )
        return
    ref.exists = True
    is_dir = stat.S_ISDIR(info.st_mode)
    if is_dir and (tag in _DIRECTORY_TAGS or tag in _FILE_OR_DIRECTORY_TAGS):
        ref.is_dir = True
        _check_directory(ref, resolved, result, sandbox)
        return
    if tag in _DIRECTORY_TAGS or not stat.S_ISREG(info.st_mode):
        wanted = "a directory" if tag in _DIRECTORY_TAGS else "a regular file"
        result.add(
            ERROR,
            "NOT_REGULAR_FILE",
            shown,
            f"{tag} must be {wanted} ({display} is not: pipes, devices and directories "
            "are not accepted)",
        )
        return
    if info.st_size > sandbox.max_data_mb * 1_048_576:
        result.add(
            ERROR,
            "LIMIT_EXCEEDED",
            shown,
            f"{display} is {info.st_size / 1_048_576:.1f} MB, above the "
            f"{sandbox.max_data_mb} MB data limit (EXORAD_MCP_MAX_DATA_MB)",
        )
        return
    paos = tag == "PSF" and _psf_format(ref.element) == "paos"
    # The PSF reader (``paosPSF``) hands ANY file name to ``h5py.File``, so the suffix
    # decides nothing: scan what is HDF5 by its signature, and every paos PSF.
    if paos or resolved.suffix.lower() in _H5_SUFFIXES or has_hdf5_signature(resolved):
        try:
            problems, expanded = hdf5_scan(resolved)
        except OSError as exc:
            result.add(
                ERROR,
                "UNSUPPORTED_FORMAT",
                shown,
                f"{display} is not readable HDF5: {exc}",
            )
            return
        if problems:
            result.add(
                ERROR,
                "HDF5_LINK_REFUSED",
                shown,
                f"{display} contains HDF5 external links, virtual datasets or external "
                f"storage and is refused ({problems[0]})",
            )
            return
        cap = sandbox.max_data_mb * 1_048_576 * HDF5_EXPANSION_FACTOR
        if expanded > cap:
            result.add(
                ERROR,
                "LIMIT_EXCEEDED",
                shown,
                f"{display} declares {expanded / 1_048_576:.0f} MB uncompressed, above "
                f"{sandbox.max_data_mb * HDF5_EXPANSION_FACTOR} MB ({HDF5_EXPANSION_FACTOR}"
                f" x the {sandbox.max_data_mb} MB data limit): a small file can declare "
                "far more than it stores",
            )
    elif (
        (tag in _TABLE_TAGS)
        and resolved.suffix.lower() not in _BINARY_SUFFIXES
        and (problem := _table_problem(resolved))
    ):
        result.add(ERROR, "LIMIT_EXCEEDED", shown, f"{display} {problem}")


def _psf_format(element: ET.Element) -> str:
    """The text of ``<PSF><format>`` (lower case), the way the instruments read it."""
    child = element.find("format")
    return _text(child).lower() if child is not None else ""


def _directory_pattern(tag: str, directory: Path) -> str:
    """The glob the library runs on a directory reference (as normalised).

    ``binnedPSF`` and ``pixel_based_psf`` call ``glob(filename + "*.fits")``, so the
    value must end with a separator for the pattern to mean 'inside the directory'
    (:func:`normalise_payload` writes it so); ``Star`` joins the directory and
    ``*.BT-Settl.spec.fits.gz``. The very same call is made here.
    """
    if tag == "StellarModels":
        return os.path.join(str(directory), "*.BT-Settl.spec.fits.gz")
    return str(directory) + os.sep + "*.fits"


def _listed_file_problem(match: str, sandbox: Sandbox) -> tuple[str, str] | None:
    """``(code, reason)`` when a file a glob returned must not be opened."""
    try:
        info = os.lstat(match)
    except OSError:
        return "FILE_MISSING", "cannot be read"
    if stat.S_ISLNK(info.st_mode):
        return "NOT_REGULAR_FILE", "is a symbolic link (links are not followed)"
    if not stat.S_ISREG(info.st_mode):
        return "NOT_REGULAR_FILE", "is not a regular file"
    try:
        sandbox.resolve_read(os.path.realpath(match))
    except PathNotAllowedError:
        return (
            "PATH_OUTSIDE_SANDBOX",
            "resolves outside the directories this MCP server may read",
        )
    if info.st_size > sandbox.max_data_mb * 1_048_576:
        return (
            "LIMIT_EXCEEDED",
            f"is {info.st_size / 1_048_576:.1f} MB, above the {sandbox.max_data_mb} MB "
            "data limit (EXORAD_MCP_MAX_DATA_MB)",
        )
    return None


def _check_directory(
    ref: _Reference, resolved: Path, result: _Analysis, sandbox: Sandbox
) -> None:
    """A PSF or StellarModels directory: refuse a root, then check every file in it."""
    tag, shown = ref.tag, ref.path
    for root in sandbox.readable_roots:
        if _inside(root, resolved):
            result.add(
                ERROR,
                "PATH_OUTSIDE_SANDBOX",
                shown,
                f"{tag} '{ref.raw}' is, or contains, a sandbox root (the working "
                "directory, the content root or an allowed directory): point it at a "
                "sub-directory that holds only the files to read",
            )
            return
    matches = sorted(glob.glob(_directory_pattern(tag, resolved)))
    if len(matches) > MAX_GLOB_FILES:
        result.add(
            ERROR,
            "LIMIT_EXCEEDED",
            shown,
            f"{tag} directory lists {len(matches)} files, above the limit of "
            f"{MAX_GLOB_FILES}",
        )
        return
    reported = 0
    for match in matches:
        problem = _listed_file_problem(match, sandbox)
        if problem is None:
            continue
        code, reason = problem
        result.add(
            ERROR,
            code,
            shown,
            f"{tag} directory file '{os.path.basename(match)}' {reason}; every file "
            "the library may open from a directory must be a regular file inside "
            "the readable directories",
        )
        reported += 1
        if reported >= 5:
            break


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _check_limits(root: ET.Element, result: _Analysis, sandbox: Sandbox) -> None:
    result.info["working_R"] = DEFAULT_WORKING_R
    working = root.find("common/working_R")
    if working is not None and _text(working):
        value = _number(working)
        if value is None or value != int(value) or value < 1:
            result.add(
                ERROR,
                "VALUE_INVALID",
                "common/working_R",
                "working_R must be a positive integer",
            )
        elif value > MAX_WORKING_R:
            result.add(
                ERROR,
                "LIMIT_EXCEEDED",
                "common/working_R",
                f"working_R {int(value)} is above the limit of {MAX_WORKING_R} "
                "(the size of every table and of the output scales with it)",
            )
        else:
            result.info["working_R"] = int(value)
    channels = _children(root, "channel")
    if len(channels) > MAX_CHANNELS:
        result.add(
            ERROR,
            "LIMIT_EXCEEDED",
            "channel",
            f"{len(channels)} channels, above the limit of {MAX_CHANNELS}",
        )
    containers = [("optics", el) for el in _children(root, "optics")]
    for channel in channels:
        containers += [
            (_join(_label(channel), "optics"), el)
            for el in _children(channel, "optics")
        ]
    for label, container in containers:
        count = len(_children(container, "opticalElement"))
        if count > MAX_OPTICAL_ELEMENTS:
            result.add(
                ERROR,
                "LIMIT_EXCEEDED",
                label,
                f"{count} optical elements, above the limit of {MAX_OPTICAL_ELEMENTS}",
            )
    infos = []
    for channel in channels:
        cls_el = channel.find("channelClass")
        cls = _text(cls_el).lower() if cls_el is not None else ""
        label = _label(channel)
        infos.append({"name": _text(channel), "class": cls})
        if cls_el is not None and cls not in {"photometer", "spectrometer"}:
            result.add(
                ERROR,
                "VALUE_INVALID",
                _join(label, "channelClass"),
                f"channelClass '{_text(cls_el)}' must be Photometer or Spectrometer",
            )
        if cls == "spectrometer":
            _check_bins(channel, label, result, sandbox)
    result.info["channels"] = infos


def _check_bins(
    channel: ET.Element, label: str, result: _Analysis, sandbox: Sandbox
) -> None:
    target = channel.find("targetR")
    if target is None:
        return
    text = _text(target)
    if not text or text.lower() == "native":
        return
    resolution = _number(target)
    path = _join(label, "targetR")
    if resolution is None or resolution <= 0:
        result.add(
            ERROR,
            "VALUE_INVALID",
            path,
            "targetR must be a positive number or 'native'",
        )
        return
    lo, hi = _length_um(channel.find("wl_min")), _length_um(channel.find("wl_max"))
    if lo is None or hi is None or not 0 < lo < hi:
        return
    bins = math.ceil(math.log(hi / lo) / math.log1p(1.0 / resolution)) + 1
    if bins > sandbox.max_bins:
        result.add(
            ERROR,
            "LIMIT_EXCEEDED",
            path,
            f"targetR {resolution:g} gives {bins} spectral bins, above the limit of "
            f"{sandbox.max_bins} (EXORAD_MCP_MAX_BINS)",
        )


#: element -> physical type of its unit (a wrong dimension fails later, deep in a build).
_UNIT_TYPES = {
    "wl_min": u.m,
    "wl_max": u.m,
    "cut_off": u.m,
    "delta_pix": u.m,
    "Atel": u.m**2,
}


def _check_units(root: ET.Element, result: _Analysis) -> None:
    for path, element, _parent in _walk(root):
        unit = element.get("unit")
        if not unit:
            continue
        try:
            parsed = u.Unit("" if unit == "dimensionless" else unit)
        except (ValueError, TypeError):
            result.add(ERROR, "UNIT_INVALID", path, f"'{unit}' is not a valid unit")
            continue
        expected = _UNIT_TYPES.get(element.tag)
        if expected is not None and not parsed.is_equivalent(expected):
            result.add(
                ERROR,
                "UNIT_INVALID",
                path,
                f"unit '{unit}' is not a unit of {expected.physical_type}",
            )


def _check_demo_sed(root: ET.Element, result: _Analysis) -> None:
    """Warn when the reduced demo SED is used outside its finely sampled segment."""
    if result.source != "custom":
        return
    uses_demo = any(
        ref.tag == "CustomSed"
        and ref.resolved is not None
        and ref.resolved.name == DEMO_SED_NAME
        for ref in result.references
    )
    if not uses_demo:
        return
    lo_fine, hi_fine = FINE_SEGMENT_UM
    ranges = [("common", root.find("common"))]
    ranges += [(_label(ch), ch) for ch in _children(root, "channel")]
    for label, node in ranges:
        if node is None:
            continue
        lo, hi = _length_um(node.find("wl_min")), _length_um(node.find("wl_max"))
        if (lo is not None and lo < lo_fine) or (hi is not None and hi > hi_fine):
            result.add(
                WARNING,
                "SED_COARSE_OUTSIDE_FINE_SEGMENT",
                label,
                f"the wavelength range of '{label}' exceeds {lo_fine}-{hi_fine} um, where the "
                "reduced demo SED is finely sampled; outside it the SED is coarse (R=300)",
            )
            return


# --------------------------------------------------------------------------------
# public entry points
# --------------------------------------------------------------------------------
def _checked_payload(payload: Path | str) -> Path:
    path = Path(payload)
    if path.suffix.lower() != ".xml":
        raise ValueError(f"a payload must be an .xml file, got '{path.name}'")
    return path


def static_findings(
    payload: Path | str,
    *,
    sandbox: Sandbox,
    payload_checks: bool = True,
    exclude_reference_tags: Iterable[str] = (),
    reference_tags: Iterable[str] = (),
) -> list[Finding]:
    """Check a payload XML without executing any ExoRad code.

    Parameters
    ----------
    payload : pathlib.Path
        An already resolved ``.xml`` file.
    sandbox : Sandbox
        Roots and limits.
    payload_checks : bool, optional
        ``False`` scans a configuration that is NOT an ExoRad payload (another
        package's run configuration): every check that mirrors what the loader
        reads still runs (every element including comments, attributes other than
        ``unit``, DOCTYPE, ``config_dict``, pickles, URLs and NUL, FIFO / symlink /
        regular-file, size limits, HDF5 link scan, directory listings, repeated
        ``ConfigPath``), but not the required-element, channel, optical-element,
        bin, unit or source-spectrum rules.
    exclude_reference_tags : iterable of str, optional
        Tags whose text is never collected as a file reference (an output
        directory, say). URLs and NUL characters are still refused there.
    reference_tags : iterable of str, optional
        Extra tags whose text is always a file reference, resolved against the
        configuration's directory like ExoRad's own path tags.

    Returns
    -------
    list of Finding
        Errors and warnings (empty when the payload is clean).

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If the suffix is not ``.xml``.
    """
    path = _checked_payload(payload)
    root, findings = _read_payload(path, sandbox)
    if root is None:
        return findings
    return _analyse(
        root,
        path,
        sandbox,
        payload_checks=payload_checks,
        exclude_reference_tags=exclude_reference_tags,
        reference_tags=reference_tags,
    ).findings


payload_findings = static_findings


def tree_findings(
    root: ET.Element,
    payload: Path | str,
    *,
    sandbox: Sandbox,
    payload_checks: bool = True,
    exclude_reference_tags: Iterable[str] = (),
    reference_tags: Iterable[str] = (),
) -> list[Finding]:
    """Static findings of an already parsed payload tree.

    ``payload`` is only used to decide the base of relative values (it need not
    exist yet). ``draft_config`` runs this on a tree it has just edited, before
    anything is written.
    """
    return _analyse(
        root,
        Path(payload),
        sandbox,
        payload_checks=payload_checks,
        exclude_reference_tags=exclude_reference_tags,
        reference_tags=reference_tags,
    ).findings


@dataclass
class NormalisedPayload:
    """Result of :func:`normalise_payload`."""

    path: Path | None  #: the normalised copy; ``None`` when there are error findings
    base: Path  #: directory relative values were resolved against
    findings: list[Finding]
    references: list[dict[str, Any]] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)  #: working_R, source, channels

    @property
    def ok(self) -> bool:
        """True when a copy was written (no error findings)."""
        return self.path is not None


def normalise_payload(
    payload: Path | str,
    *,
    sandbox: Sandbox,
    dest_dir: Path | str,
    payload_checks: bool = True,
    exclude_reference_tags: Iterable[str] = (),
    reference_tags: Iterable[str] = (),
) -> NormalisedPayload:
    """Write an absolute-path copy of ``payload`` into ``dest_dir`` (spec 2.1).

    The copy keeps the file name. ``<ConfigPath>`` is absolute (inserted when the
    file has none) and every path the selected source spectrum reads, plus any
    value that uses the keyword or an absolute path, is expanded and made
    absolute with symlinks resolved. No copy is written when there are error
    findings (``path`` is then ``None``). The run and the validation must both
    open this copy. XML ``<comment>`` elements are dropped from it.

    ``payload_checks``, ``exclude_reference_tags`` and ``reference_tags`` are
    described at :func:`static_findings`; with ``payload_checks=False`` an
    extension gets the absolute-path copy of its own configuration (the excluded
    tags keep their text as written).
    """
    path = _checked_payload(payload)
    root, findings = _read_payload(path, sandbox)
    if root is None:
        return NormalisedPayload(None, payload_base(path, sandbox), findings)
    analysis = _analyse(
        root,
        path,
        sandbox,
        payload_checks=payload_checks,
        exclude_reference_tags=exclude_reference_tags,
        reference_tags=reference_tags,
    )
    references = [
        {
            "tag": ref.tag,
            "path": sandbox.display_path(ref.resolved) if ref.resolved else ref.raw,
            "exists": ref.exists,
            "allowed": ref.allowed,
            "packaged": ref.packaged,
        }
        for ref in analysis.references
    ]
    info = {**analysis.info, "source": analysis.source}
    result = NormalisedPayload(
        None, analysis.base, analysis.findings, references=references, info=info
    )
    if errors_of(analysis.findings):
        return result
    _drop_comments(root)
    for ref in analysis.references:
        if ref.resolved is not None:
            ref.element.text = str(ref.resolved) + (
                # ``glob(filename + "*.fits")`` must mean 'inside the directory'
                os.sep if ref.is_dir and ref.tag == "PSF" else ""
            )
    config_path = analysis.config_path or analysis.base
    config_el = next(iter(root.iter("ConfigPath")), None)
    if config_el is None:
        config_el = ET.Element("ConfigPath")
        root.insert(0, config_el)
    config_el.text = str(config_path)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / path.name
    ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)
    result.path = target
    return result


def _drop_comments(root: ET.Element) -> None:
    """Remove every ``<comment>`` element: prose only, nothing in the library reads it.

    The static scan already checked their content; the copy the job opens then holds
    no subtree the loader could open files from without the scan having rewritten it.
    """
    for parent in list(root.iter()):
        for child in [c for c in parent if c.tag == "comment"]:
            parent.remove(child)


def _unknown_elements(root: ET.Element) -> list[str]:
    """Top-most elements that no rule row describes (framework keys excluded)."""
    unknown: list[str] = []

    def visit(element: ET.Element, tags: tuple[str, ...], label: str) -> None:
        for child in element:
            if child.tag in FRAMEWORK_KEYS:
                continue
            child_tags = (*tags, child.tag)
            child_label = _join(label, child.tag)
            if child_tags in _KNOWN_PATTERNS:
                visit(child, child_tags, child_label)
            elif child_label not in unknown:
                unknown.append(child_label)

    visit(root, (), "")
    return unknown


def _present_rules(root: ET.Element) -> list[str]:
    present = []
    for rule in RULES:
        parts = _PATTERN_PARTS[rule.pattern]
        level = [root]
        for part in parts:
            level = [child for el in level for child in _children(el, part)]
            if not level:
                break
        if level:
            present.append(rule.display)
    return present


def describe_payload(payload: Path | str, *, sandbox: Sandbox) -> dict[str, Any]:
    """Compare a payload with the requirement table (``config_requirements``).

    Returns ``present`` (table rows found), ``missing`` (required rows absent),
    ``extra`` (elements no row describes; framework keys excluded) and
    ``findings`` (the static findings). Rows are named like
    :func:`payload_requirements` paths.
    """
    path = _checked_payload(payload)
    root, findings = _read_payload(path, sandbox)
    if root is None:
        return {"present": [], "missing": [], "extra": [], "findings": findings}
    analysis = _analyse(root, path, sandbox)
    missing = [rule.display for rule in RULES if rule.pattern in analysis.missing_rules]
    return {
        "present": _present_rules(root),
        "missing": missing,
        "extra": _unknown_elements(root),
        "findings": analysis.findings,
    }


@contextlib.contextmanager
def scratch_dir(sandbox: Sandbox, prefix: str = "exorad-mcp-") -> Iterator[Path]:
    """A throw-away directory under ``<work dir>/.tmp``, removed on exit."""
    parent = sandbox.ensure_work_dir() / ".tmp"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=prefix, dir=parent) as name:
        yield Path(name)


def strict_file_problem(
    path: str | Path, sandbox: Sandbox, *, max_bytes: int, label: str
) -> str | None:
    """Why ``path`` may no longer be opened, or ``None``.

    For a file that was validated earlier and is about to be used: it must still be
    a regular file that is not a symbolic link and does not reach the disk through
    one (``realpath`` must equal the path), lie inside a readable root and be at
    most ``max_bytes``. The file is opened once with ``O_NOFOLLOW | O_NONBLOCK``
    (a FIFO swapped in cannot block, a symlink fails) and measured with ``fstat``.
    ``label`` is what the message calls the file (never an absolute path).

    This narrows the window between the check and the use; it does not close it:
    whoever can write the directory can still swap the file between this call and
    the library's own ``open``.
    """
    candidate = Path(path)
    if os.path.realpath(candidate) != os.path.normpath(candidate):
        return f"{label} now reaches its file through a symbolic link (it changed)"
    try:
        sandbox.resolve_read(candidate)
    except PathNotAllowedError:
        return f"{label} is outside the directories this MCP server may read"
    try:
        fd = _open_regular(candidate)
    except FileNotFoundError:
        return f"{label} no longer exists"
    except OSError:
        return f"{label} is no longer a plain regular file (link, pipe or device)"
    try:
        size = os.fstat(fd).st_size
    finally:
        os.close(fd)
    if size > max_bytes:
        return f"{label} is now {size / 1_048_576:.1f} MB, above its limit"
    return None


def recheck_payload(
    payload: Path | str,
    sandbox: Sandbox,
    *,
    payload_checks: bool = True,
    exclude_reference_tags: Iterable[str] = (),
    reference_tags: Iterable[str] = (),
) -> list[Finding]:
    """Re-run the file checks on a NORMALISED copy right before it is used.

    The copy holds absolute, symlink-free paths, so any of them that is now a
    symbolic link, a pipe, a different kind of file, larger than the limits or an
    HDF5 file with links is a change made since :func:`normalise_payload`. Returns
    the findings (errors mean: do not open it). The copy itself is checked too.
    A residual race remains by construction (see :func:`strict_file_problem`).
    The keyword arguments are those of :func:`static_findings`: pass the same ones
    that :func:`normalise_payload` got.
    """
    path = Path(payload)
    problem = strict_file_problem(
        path,
        sandbox,
        max_bytes=int(sandbox.max_file_mb * 1_048_576),
        label="the payload copy",
    )
    if problem is not None:
        return [Finding(ERROR, "NOT_REGULAR_FILE", path.name, problem)]
    root, findings = _read_payload(path, sandbox)
    if root is None:
        return findings
    return _analyse(
        root,
        path,
        sandbox,
        strict=True,
        payload_checks=payload_checks,
        exclude_reference_tags=exclude_reference_tags,
        reference_tags=reference_tags,
    ).findings


def load_options(path: str | Path) -> dict[str, Any]:
    """``LoadOptions()(filename=path)`` under :data:`CONFIG_LOAD_LOCK`.

    ``PassVal.working_R`` (written by the loader) is restored afterwards, so a
    validation leaves no trace in the process. Call it only on a payload whose
    static findings hold no error, normally the normalised copy.
    """
    from exorad.utils.passVal import PassVal

    with CONFIG_LOAD_LOCK:
        saved = PassVal.working_R
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UnitsWarning)
                return LoadOptions()(filename=str(path))
        finally:
            PassVal.working_R = saved


def load_payload_dict(
    payload: Path | str, *, sandbox: Sandbox, dest_dir: Path | str | None = None
) -> dict[str, Any]:
    """Parse a payload into the options dict, through the normalised copy.

    Raises :class:`ConfigRuleError` when the static rules find an error (the
    library is not called), otherwise whatever ``LoadOptions`` raises.
    """
    if dest_dir is not None:
        return _load_normalised(payload, sandbox, Path(dest_dir))
    with scratch_dir(sandbox, "exorad-mcp-load-") as scratch:
        return _load_normalised(payload, sandbox, scratch)


def _load_normalised(
    payload: Path | str, sandbox: Sandbox, dest: Path
) -> dict[str, Any]:
    normalised = normalise_payload(payload, sandbox=sandbox, dest_dir=dest)
    if normalised.path is None:
        raise ConfigRuleError(normalised.findings)
    # a second look right before the library opens the copy and what it names
    changed = recheck_payload(normalised.path, sandbox)
    if errors_of(changed):
        raise ConfigRuleError(changed)
    return load_options(normalised.path)
