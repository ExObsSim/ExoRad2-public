"""Drafting payloads and target lists for the ExoRad MCP (spec 3.3, tools 10 and 11).

``draft_config`` starts from the shipped ``examples/payload_example.xml``, pins its
``<ConfigPath>`` to the absolute content root, applies dotted-path overrides,
checks the edited tree with the static rules BEFORE writing anything, writes
``<work dir>/drafts/<name>_draft.xml`` and validates it. It never overwrites a
draft silently and refuses overrides that would escape the sandbox, point at
executable files, use a URL, select the network SED, or exceed a limit.

The example is a data file, not documentation: XML comments are lost.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from exorad.mcp import configuration, rules, targets
from exorad.mcp.assets import require_content_file
from exorad.mcp.sandbox import PathNotAllowedError, Sandbox

__all__ = ["NAME_PATTERN", "check_override", "draft_payload", "draft_targets"]

NAME_PATTERN = r"^[A-Za-z0-9_-]{1,40}$"
_NAME_RE = re.compile(NAME_PATTERN)
EXAMPLE = "examples/payload_example.xml"
#: Finding codes that make an edited tree unacceptable: nothing is written.
_REFUSED = frozenset(
    {
        "PATH_OUTSIDE_SANDBOX",
        "SOURCE_SED_BLOCKED",
        "PICKLE_REFUSED",
        "HDF5_LINK_REFUSED",
        "LIMIT_EXCEEDED",
        "NOT_REGULAR_FILE",
        "UNSUPPORTED_FORMAT",
    }
)
_EXEC_SUFFIXES = (".pickle", ".pkl", ".py")
_H5_SUFFIXES = (".h5", ".hdf5")


def _check_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ValueError(
            f"name must match {NAME_PATTERN} (letters, digits, '_' and '-', 1-40 characters), "
            f"got {name!r}"
        )
    return name


def check_override(tag: str, value: str, *, sandbox: Sandbox, base: Path) -> None:
    """Refuse an override that would escape the sandbox or run arbitrary code.

    ``tag`` is the last segment of the dotted path. Path-like keys
    (``rules.PATH_TAGS``, ``ConfigPath``) and any value that uses
    ``__ConfigPath__`` or an absolute path must resolve inside the readable
    roots; a URL is never accepted; a pickle or Python file is refused for every
    path key, and ``datadict``/``config_dict`` must be ``.h5``/``.hdf5``.

    Raises
    ------
    PathNotAllowedError
        A path outside the sandbox, or a URL (a ``ValueError``).
    ValueError
        An executable pointer or an unsupported data format.
    """
    text = value.strip()
    lowered = text.lower()
    path_like = (
        tag in rules.PATH_TAGS
        or tag == "data"  # targetR/data names a table, the only ``data`` element
        or tag == "ConfigPath"
        or rules.KEYWORD in text
        or text.startswith("~")
        or Path(text).is_absolute()
    )
    if "://" in text and path_like:
        raise PathNotAllowedError(f"'{text}' looks like a URL: URLs are not allowed")
    if tag in {"datadict", "config_dict"} or (
        path_like and lowered.endswith(_EXEC_SUFFIXES)
    ):
        if lowered.endswith(_EXEC_SUFFIXES):
            raise ValueError(
                f"Override of '{tag}' points at a pickle or Python file ({text}); loading it "
                "would run arbitrary code, so it is refused (use an .h5 file)."
            )
        if tag in {"datadict", "config_dict"} and not lowered.endswith(_H5_SUFFIXES):
            raise ValueError(
                f"Override of '{tag}' must be an .h5 or .hdf5 file, got {text!r}."
            )
    if not path_like:
        return
    expanded = text.replace(rules.KEYWORD, str(base))
    candidate = Path(expanded).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    # Raises PathNotAllowedError (a ValueError) outside the readable roots.
    sandbox.resolve_read(candidate)


def draft_payload(
    overrides: dict[str, str] | None = None,
    overwrite: bool = False,
    name: str = "payload",
    *,
    sandbox: Sandbox | None = None,
) -> dict[str, Any]:
    """Draft a payload from the shipped example and validate it.

    Parameters
    ----------
    overrides : dict, optional
        ``"section.sub.key": "value"`` entries. A value may carry a unit
        (``"0.5 micron"``); repeated tags (``channel``, ``opticalElement``,
        ``foreground``) are named by the next segment (``channel.Spec.targetR``).
    overwrite : bool
        Replace an existing draft of the same name.
    name : str
        ``^[A-Za-z0-9_-]{1,40}$``; the file is ``drafts/<name>_draft.xml``.

    Returns
    -------
    dict
        ``based_on``, ``draft`` (path relative to the work dir, usable as the
        ``payload`` argument of the other tools), ``applied``, ``not_applied``,
        ``valid``, ``findings`` and ``top_level_sections``.

    Raises
    ------
    FileExistsError
        The draft exists and ``overwrite`` is false.
    ValueError
        A refused override (path outside the sandbox, URL, pickle/Python file,
        ``sourceSpectrum = sed``, a limit exceeded) or a bad ``name``. Nothing is
        written in that case.
    ContentMissingError
        The shipped example is not available.
    """
    _check_name(name)
    box = sandbox or Sandbox.from_env()
    example = require_content_file(
        box.resolve_read(EXAMPLE), f"Reference payload {EXAMPLE}"
    )
    root = ET.parse(example).getroot()
    base = box.repo_root
    config_el = root.find("ConfigPath")
    if config_el is None:
        config_el = ET.Element("ConfigPath")
        root.insert(0, config_el)
    config_el.text = str(base)

    draft_path = box.resolve_write(Path("drafts") / f"{name}_draft.xml")
    if draft_path.exists() and not overwrite:
        raise FileExistsError(
            f"Draft file already exists: {box.display_path(draft_path)}. "
            "Set overwrite=True to replace it."
        )

    applied, not_applied = _apply_overrides(
        root, overrides or {}, sandbox=box, base=base
    )
    refused = [
        finding
        for finding in rules.tree_findings(root, draft_path, sandbox=box)
        if finding.severity == "error" and finding.code in _REFUSED
    ]
    if refused:
        raise ValueError("; ".join(f"{f.path}: {f.message}" for f in refused))

    draft_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(draft_path, encoding="utf-8", xml_declaration=True)

    validation = configuration.validate_configuration_file(draft_path, sandbox=box)
    return {
        "based_on": EXAMPLE,
        "draft": draft_path.relative_to(box.work_dir).as_posix(),
        "applied": applied,
        "not_applied": not_applied,
        "valid": validation["valid"],
        "findings": validation["findings"],
        "top_level_sections": validation["summary"].get("top_level_sections"),
    }


def draft_targets(
    rows: list[dict[str, Any]],
    overwrite: bool = False,
    name: str = "targets",
    *,
    sandbox: Sandbox | None = None,
) -> dict[str, Any]:
    """Write ``drafts/<name>.csv`` from star dictionaries and validate it.

    Each row: ``name``, ``M`` (M_sun), ``Teff`` (K), ``R`` (R_sun), ``D`` (pc), and
    optionally ``magk``, ``ra`` and ``dec`` (deg; ``ra`` needs ``dec``).

    Returns
    -------
    dict
        ``draft`` (relative to the work dir), ``rows``, ``columns``, ``valid``,
        ``findings``.

    Raises
    ------
    FileExistsError
        The file exists and ``overwrite`` is false.
    ValueError
        A bad ``name``, row or more targets than ``EXORAD_MCP_MAX_TARGETS``.
        Nothing is written in that case.
    """
    _check_name(name)
    box = sandbox or Sandbox.from_env()
    if len(rows) > box.max_targets:
        raise ValueError(
            f"{len(rows)} targets, above the limit of {box.max_targets} "
            "(EXORAD_MCP_MAX_TARGETS)"
        )
    dest = box.resolve_write(Path("drafts") / f"{name}.csv")
    if dest.exists() and not overwrite:
        raise FileExistsError(
            f"Draft file already exists: {box.display_path(dest)}. "
            "Set overwrite=True to replace it."
        )
    columns = targets.write_target_csv(rows, dest)
    report = targets.validate_target_list(dest, sandbox=box)
    findings = list(report.findings)
    if report.ok:
        findings.extend(configuration._library_load(dest, box))
    return {
        "draft": dest.relative_to(box.work_dir).as_posix(),
        "rows": report.rows,
        "columns": columns,
        "valid": not rules.errors_of(findings),
        "findings": configuration._finding_dicts(findings),
    }


def _apply_overrides(
    root: ET.Element,
    overrides: dict[str, str],
    *,
    sandbox: Sandbox,
    base: Path,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    applied: list[dict[str, str]] = []
    not_applied: list[dict[str, Any]] = []
    for path, raw in overrides.items():
        segments = [s for s in str(path).split(".") if s]
        if not segments:
            not_applied.append(
                {"path": str(path), "reason": "empty path", "available": []}
            )
            continue
        value_text = str(raw)
        # Safety first, whether or not the element exists in the example.
        check_override(segments[-1], value_text, sandbox=sandbox, base=base)
        node, _walked, failure = _walk(root, segments)
        if failure is not None:
            failure["path"] = str(path)
            not_applied.append(failure)
            continue
        value, unit = _split_unit(value_text)
        node.text = value
        if unit is not None:
            node.set("unit", unit)
        if node.tag == "ConfigPath":
            base = Path(value).expanduser()
        applied.append({"path": str(path), "value": value_text})
    return applied, not_applied


def _walk(
    node: ET.Element, segments: list[str]
) -> tuple[ET.Element, list[str], dict[str, Any] | None]:
    """Descend ``node`` by ``segments``, disambiguating repeated tags by text.

    Repeated tags (several ``<channel>`` or ``<opticalElement>``) are selected by
    the next segment, matched against the first line of the element's text, so
    ``channel.Spec.detector.read_noise`` picks the ``Spec`` channel.
    """
    walked: list[str] = []
    index = 0
    while index < len(segments):
        segment = segments[index]
        by_tag = [child for child in node if child.tag == segment]
        if len(by_tag) == 1:
            node, index = by_tag[0], index + 1
            walked.append(segment)
            continue
        if len(by_tag) > 1:
            names = [_name(child) for child in by_tag]
            if index + 1 < len(segments):
                wanted = segments[index + 1]
                pick = next(
                    (c for c, n in zip(by_tag, names, strict=True) if n == wanted), None
                )
                if pick is not None:
                    node = pick
                    walked += [segment, segments[index + 1]]
                    index += 2
                    continue
            return (
                node,
                walked,
                {
                    "reason": f"'{segment}' is repeated; name the one you mean",
                    "available": names,
                },
            )
        by_text = next((child for child in node if _name(child) == segment), None)
        if by_text is not None:
            node, index = by_text, index + 1
            walked.append(segment)
            continue
        return (
            node,
            walked,
            {
                "reason": f"no '{segment}' under {'.'.join(walked) or '<root>'}",
                "available": sorted(
                    {child.tag for child in node if child.tag != "comment"}
                ),
            },
        )
    return node, walked, None


def _name(element: ET.Element) -> str:
    return (element.text or "").strip().split("\n")[0].strip()


def _split_unit(value: str) -> tuple[str, str | None]:
    parts = value.split()
    if len(parts) == 2:
        number, unit = parts
        try:
            float(number)
        except ValueError:
            return value, None
        return number, unit
    return value, None
