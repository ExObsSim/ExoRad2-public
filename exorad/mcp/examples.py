"""MCP helper: catalogue the bundled example inputs.

An AI client asked to run or explain something should start from a real example,
not an invented one. ``list_examples`` returns the payload XML, the target list
and the data tables found under ``examples/`` with their size, whether they can
be used as they are, and which files a payload points at.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from exorad.mcp.assets import MAX_ASSET_BYTES
from exorad.mcp.schemas import resolve_repo_path

_SUFFIXES = {".xml", ".csv", ".ecsv", ".txt"}

# Elements whose text is a path the library opens (spec 2.7). ``StellarModels``
# is a directory read only for ``sourceSpectrum = phoenix``; ``CustomSed`` only for
# ``custom``; both are handled in ``_references``.
_FILE_TAGS = frozenset(
    {"datafile", "datadict", "config_dict", "CustomSed", "PSF", "custom_map_file"}
)
_DEMO_SED = "customsed_demo.csv"

# Curated one-liners for the well-known files; anything else gets a structural
# description built from its contents.
_DESCRIPTIONS = {
    "examples/payload_example.xml": (
        "Worked payload: telescope optics, one photometer and one spectrometer "
        "channel, custom stellar SED, Modtran sky foreground and zodiacal light."
    ),
    "examples/test_target.csv": "Target list with two stars (myTest, myTest2).",
    "examples/QE.csv": "Quantum efficiency table referenced by the example payload.",
    "examples/Spec-wl_sol.csv": (
        "Spectrometer wavelength solution table referenced by the example payload."
    ),
    "examples/modtran_38km_sun_180az_55zd_los_45zd.csv": (
        "Modtran sky radiance and transmission table used as a foreground."
    ),
    "examples/customsed.csv": (
        "Full-resolution custom stellar SED (21 MB, not shipped in the wheel)."
    ),
    "examples/customsed_demo.csv": (
        "Reduced-resolution demo SED shipped with the wheel instead of customsed.csv."
    ),
}


def _kind(path: Path) -> str:
    if path.suffix.lower() == ".xml":
        return "payload"
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            header = handle.readline().lower()
    except OSError:
        return "data_table"
    return "target_list" if "star name" in header else "data_table"


def _text(element: ET.Element) -> str:
    return (element.text or "").strip()


def _references(path: Path, root: Path) -> list[dict[str, Any]]:
    """Files a payload points at (only the ones its source spectrum reads)."""
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError):
        return []
    top = tree.getroot()
    config_path = top.find("ConfigPath")
    base_text = _text(config_path) if config_path is not None else ""
    # The shipped examples are written for a cwd that is the content root.
    base = root if base_text in {"", "."} else Path(base_text).expanduser()
    source = top.find("common/sourceSpectrum")
    source_name = (
        _text(source).split()[0].lower() if source is not None and _text(source) else ""
    )

    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for element in top.iter():
        tag = element.tag
        wanted = tag in _FILE_TAGS
        if tag == "CustomSed" and source_name != "custom":
            wanted = False
        if tag == "StellarModels" and source_name == "phoenix":
            wanted = True
        raw = _text(element)
        if not wanted or not raw:
            continue
        expanded = raw.replace("__ConfigPath__", str(base))
        target = Path(expanded).expanduser()
        target = target if target.is_absolute() else base / target
        try:
            display = target.relative_to(root).as_posix()
        except ValueError:
            display = raw  # outside the content root: show as written
        if display in seen:
            continue
        seen.add(display)
        refs.append({"tag": tag, "path": display, "exists": target.exists()})
    return refs


def list_example_configs(repo_root: str | None = None) -> dict[str, Any]:
    """Return the bundled example inputs with a short description each.

    Each entry has ``path``, ``kind`` (``payload``, ``target_list`` or
    ``data_table``), ``description``, ``size_bytes``, ``runnable`` (can be given
    to ``run_pipeline`` as it is), ``packaged`` (included in the wheel),
    ``references`` (files a payload points at) and ``needs`` (referenced files
    that are missing from this content root).
    """
    root = resolve_repo_path(".", repo_root)
    entries: list[dict[str, Any]] = []
    for path in sorted((root / "examples").glob("*")):
        rel = path.relative_to(root)
        if (
            not path.is_file()
            or path.suffix.lower() not in _SUFFIXES
            or any(part.startswith(".") for part in rel.parts)
        ):
            continue
        rel_text = rel.as_posix()
        size = path.stat().st_size
        kind = _kind(path)
        references = _references(path, root) if kind == "payload" else []
        needs = [ref["path"] for ref in references if not ref["exists"]]
        entry: dict[str, Any] = {
            "path": rel_text,
            "kind": kind,
            "description": _DESCRIPTIONS.get(
                rel_text, f"Example {kind.replace('_', ' ')}."
            ),
            "size_bytes": size,
            "runnable": {"payload": not needs, "target_list": True}.get(kind, False),
            "packaged": size <= MAX_ASSET_BYTES,
            "references": references,
            "needs": needs,
        }
        if any(Path(ref["path"]).name == _DEMO_SED for ref in references):
            entry["note"] = "uses the reduced-resolution demo SED"
        entries.append(entry)
    return {"examples": entries, "count": len(entries)}
