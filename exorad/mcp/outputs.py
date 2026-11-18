"""Inspection and explanation of ExoRad output files for the MCP tools.

Everything that opens an output file goes through :func:`scan_hdf5` first.
That scan walks the WHOLE file with link-level calls only (``H5Lget_info``,
which does not resolve a link) and refuses, with a ``ValueError`` that names the
node but never a target path:

* HDF5 **external links**: ``group.get(key)`` would open the file the link names,
  anywhere on the machine, and expose its attributes and values (hazard H17);
* **virtual datasets** and datasets with **external raw storage**: reading them
  pulls data from other files;
* more than :data:`MAX_SCAN_NODES` nodes (a hostile or runaway file).

Soft links are listed but never followed; hard-link cycles are cut with a
visited set. Only after the scan do the inspector, the explainer and the
plotter read attributes or values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import h5py
import numpy as np

from exorad.mcp import output_map
from exorad.mcp.sandbox import Sandbox

if TYPE_CHECKING:
    from pathlib import Path

MAX_SCAN_NODES = 200_000
MAX_ITEMS_LIMIT = 2000
MAX_TARGETS_LISTED = 200
DEFAULT_EXPLAIN_TARGETS = 5
_MAX_STRING = 300
_MAX_ATTR_ITEMS = 50
_PREVIEW_PATHS = (
    "info/ExoRad/",
    "payload/payload description/",
)
_PREVIEW_TARGET_LEAVES = ("id", "star/model", "star/magk")
_HDF5_SUFFIXES = {".h5", ".hdf5"}
_TABLE_SUFFIXES = {".csv", ".ecsv"}


@dataclass
class HdfScan:
    """Result of :func:`scan_hdf5`: every node of the file, links checked."""

    nodes: list[tuple[str, str]] = field(default_factory=list)  #: (path, kind)

    @property
    def paths(self) -> list[str]:
        return [path for path, _ in self.nodes]


# --- link scan (H17) -----------------------------------------------------------
def _refuse(message: str) -> ValueError:
    return ValueError(f"{message}; the file is refused and nothing was read from it")


def _scan_group(handle: h5py.File) -> HdfScan:
    scan = HdfScan()
    visited = {handle.id}
    stack: list[tuple[str, h5py.Group]] = [("", handle)]
    while stack:
        prefix, group = stack.pop()
        names: list[bytes] = []
        group.id.links.iterate(names.append)
        for raw in names:
            key = raw.decode("utf-8", "replace")
            path = f"{prefix}/{key}" if prefix else key
            info = group.id.links.get_info(raw)
            if info.type == h5py.h5l.TYPE_EXTERNAL:
                raise _refuse(
                    f"the file contains an HDF5 external link at '{path}' "
                    "(external links can read other files and are not followed)"
                )
            if info.type == h5py.h5l.TYPE_SOFT:
                scan.nodes.append((path, "softlink"))
            elif info.type == h5py.h5l.TYPE_HARD:
                obj = group[key]  # a hard link: opens an object of THIS file
                if isinstance(obj, h5py.Dataset):
                    if obj.is_virtual:
                        raise _refuse(
                            f"the file contains a virtual dataset at '{path}' "
                            "(its data come from other files)"
                        )
                    if obj.external:
                        raise _refuse(
                            f"the dataset '{path}' keeps its raw data in an "
                            "external file (external storage)"
                        )
                    scan.nodes.append((path, "dataset"))
                elif isinstance(obj, h5py.Group):
                    scan.nodes.append((path, "group"))
                    if obj.id not in visited:
                        visited.add(obj.id)
                        stack.append((path, obj))
                else:
                    scan.nodes.append((path, "datatype"))
            else:
                raise _refuse(f"the file contains an unsupported link type at '{path}'")
            if len(scan.nodes) > MAX_SCAN_NODES:
                raise ValueError(
                    f"the file has more than {MAX_SCAN_NODES} HDF5 nodes; refused"
                )
    return scan


def scan_hdf5(path: Path) -> HdfScan:
    """Scan an HDF5 file for links and datasets that leave it; return its nodes.

    Raises
    ------
    ValueError
        External link, virtual dataset, external storage or too many nodes.
    OSError
        Not a readable HDF5 file.
    """
    with _open(path) as handle:
        return _scan_group(handle)


def _open(path: Path, display: str | None = None) -> h5py.File:
    try:
        return h5py.File(path, "r")
    except OSError as exc:
        shown = display or path.name
        text = str(exc).replace(str(path), shown)
        sandbox = _sandbox()
        raise OSError(
            f"'{shown}' is not a readable HDF5 file: {sandbox.redact(text)}"
        ) from None


def _sandbox() -> Sandbox:
    return Sandbox.from_env()


# --- resolution -------------------------------------------------------------------
def resolve_output(path: str | Path, sandbox: Sandbox | None = None) -> Path:
    """Resolve an output file for reading (work dir first, then the sandbox roots)."""
    box = sandbox or _sandbox()
    return box.resolve_input_file(path, prefer_work_dir=True, max_mb=box.max_output_mb)


# --- JSON helpers -------------------------------------------------------------------
def _clean(value: Any, sandbox: Sandbox) -> Any:
    """A JSON-safe copy of an attribute or scalar, with server paths redacted."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str):
        return sandbox.redact(value)[:_MAX_STRING]
    if isinstance(value, np.ndarray):
        flat = value.reshape(-1)[:_MAX_ATTR_ITEMS].tolist()
        return [_clean(item, sandbox) for item in flat]
    if isinstance(value, np.generic):
        return _clean(value.item(), sandbox)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, bool | int) or value is None:
        return value
    return sandbox.redact(str(value))[:_MAX_STRING]


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _attrs(obj: h5py.HLObject, sandbox: Sandbox) -> dict[str, Any]:
    return {str(key): _clean(val, sandbox) for key, val in obj.attrs.items()}


def _previewable(path: str) -> bool:
    if path.startswith(_PREVIEW_PATHS):
        return True
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == "targets":
        rest = "/".join(parts[2:])
        if rest in _PREVIEW_TARGET_LEAVES:
            return True
        return (
            len(parts) == 5
            and parts[2] == "star"
            and parts[4] in {"value", "unit"}
            and parts[3] != "sed"
        )
    return False


def _describe_item(
    handle: h5py.File, path: str, kind: str, sandbox: Sandbox
) -> dict[str, Any]:
    item: dict[str, Any] = {"path": path, "type": kind}
    if kind == "softlink":
        return item
    obj = handle[path]
    if isinstance(obj, h5py.Dataset):
        item["shape"] = list(obj.shape)
        item["dtype"] = str(obj.dtype)[:200]
        if obj.shape == () and obj.dtype.kind in "biufSO" and _previewable(path):
            item["value"] = _clean(obj[()], sandbox)
    if obj.attrs:
        item["attrs"] = _attrs(obj, sandbox)
    meaning = output_map.describe_path(path)
    if meaning:
        item["meaning"] = meaning["meaning"]
        if meaning["units"]:
            item["units"] = meaning["units"]
    return item


def _bfs_order(nodes: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Shallow nodes first, so a small cap still reaches every top-level group."""
    return sorted(nodes, key=lambda node: node[0].count("/"))


# --- inspect ---------------------------------------------------------------------------
def inspect_output_file(
    path: str | Path,
    *,
    sandbox: Sandbox | None = None,
    max_items: int = 80,
) -> dict[str, Any]:
    """Structural summary of an HDF5 / CSV / ECSV output (see ``inspect_output``)."""
    box = sandbox or _sandbox()
    resolved = resolve_output(path, box)
    suffix = resolved.suffix.lower()
    if suffix in _HDF5_SUFFIXES:
        return _inspect_hdf5(resolved, box, max_items=max_items)
    if suffix in _TABLE_SUFFIXES:
        return _inspect_table(resolved, box)
    raise ValueError(f"Unsupported output format: {suffix or '(no suffix)'}")


def _inspect_hdf5(path: Path, sandbox: Sandbox, *, max_items: int) -> dict[str, Any]:
    limit = max(1, min(int(max_items), MAX_ITEMS_LIMIT))
    display = sandbox.display_path(path)
    with _open(path, display) as handle:
        scan = _scan_group(handle)
        chosen = _bfs_order(scan.nodes)[:limit]
        items = [_describe_item(handle, p, k, sandbox) for p, k in chosen]
        result: dict[str, Any] = {
            "path": display,
            "format": "hdf5",
            "root_attrs": _attrs(handle, sandbox),
            "items": items,
            "total_nodes": len(scan.nodes),
            "truncated": len(scan.nodes) > len(items),
        }
        summary = _exorad_summary(handle, sandbox)
        if summary is not None:
            result["exorad"] = summary
    return result


def _text(value: Any) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def _scalar(handle: h5py.File, path: str) -> Any:
    if path not in handle:
        return None
    obj = handle[path]
    if not isinstance(obj, h5py.Dataset) or obj.shape != ():
        return None
    return obj[()]


def _read_table(handle: h5py.File, group: str, name: str):
    from astropy.io.misc.hdf5 import read_table_hdf5

    return read_table_hdf5(handle[group], path=name)


def _exorad_summary(handle: h5py.File, sandbox: Sandbox) -> dict[str, Any] | None:
    """Targets, channels and table columns of a file produced by ExoRad."""
    if "payload" not in handle and "targets" not in handle:
        return None
    warnings: list[str] = []
    summary: dict[str, Any] = {}
    version = _scalar(handle, "info/ExoRad/program_version")
    summary["version"] = _clean(version, sandbox) if version is not None else None

    names: list[str] = []
    if "targets" in handle and isinstance(handle["targets"], h5py.Group):
        names = list(handle["targets"])
    summary["n_targets"] = len(names)
    summary["targets"] = names[:MAX_TARGETS_LISTED]

    channels: list[dict[str, Any]] = []
    if "payload/channels" in handle:
        channels.extend(
            _channel_summary(handle, name, warnings)
            for name in handle["payload/channels"]
        )
    summary["channels"] = channels

    columns: list[str] = []
    for name in names[:1]:
        table_path = f"targets/{name}/table/table"
        if table_path in handle and handle[table_path].dtype.names:
            columns = list(handle[table_path].dtype.names)
    if not columns and channels:
        first = channels[0]["name"]
        path = f"payload/channels/{first}/{first}"
        if path in handle and handle[path].dtype.names:
            columns = list(handle[path].dtype.names)
    summary["table_columns"] = columns
    if warnings:
        summary["warnings"] = [sandbox.redact(w) for w in warnings]
    return summary


def _channel_summary(
    handle: h5py.File, name: str, warnings: list[str]
) -> dict[str, Any]:
    info: dict[str, Any] = {"name": name, "class": None}
    for base in (
        f"payload/payload description/channel/{name}",
        f"payload/channels/{name}/description",
    ):
        value = _scalar(handle, f"{base}/channelClass/value")
        if value is not None:
            info["class"] = _text(value).strip()
            break
    try:
        table = _read_table(handle, f"payload/channels/{name}", name)
        info["n_bins"] = len(table)
        info["wl_min_um"] = _finite(_to_um(table["LeftBinEdge"]).min())
        info["wl_max_um"] = _finite(_to_um(table["RightBinEdge"]).max())
    except Exception as exc:  # a damaged table must not hide the rest
        warnings.append(f"channel {name}: table not readable ({type(exc).__name__})")
        info.update(n_bins=None, wl_min_um=None, wl_max_um=None)
    return info


def _to_um(column: Any) -> np.ndarray:
    from astropy import units as u

    unit = getattr(column, "unit", None)
    if unit is not None:
        try:
            return np.asarray(column.to(u.micron).value, dtype=float)
        except u.UnitConversionError:
            pass
    return np.asarray(getattr(column, "value", column), dtype=float)


def _inspect_table(path: Path, sandbox: Sandbox) -> dict[str, Any]:
    from astropy.table import Table

    # the shipped tables (examples/*.csv) are ECSV files named .csv: read them as
    # the library does, then fall back to plain CSV (unless the file CLAIMS to be
    # ECSV: a broken header must be reported, not read as a column "# %ECSV 1.0")
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            claims_ecsv = handle.readline().lstrip().startswith("# %ECSV")
    except OSError as exc:
        raise ValueError(f"cannot read {path.name}: {exc.strerror or exc}") from exc
    try:
        try:
            table = Table.read(path, format="ascii.ecsv")
        except Exception as exc:
            if claims_ecsv:
                raise ValueError(f"the ECSV header is not valid ({exc})") from exc
            table = Table.read(path, format="ascii.csv")
    except Exception as exc:
        raise ValueError(f"cannot read {path.name}: {exc}") from exc
    return {
        "path": sandbox.display_path(path),
        "format": path.suffix.lower().lstrip("."),
        "columns": list(table.colnames),
        "row_count": len(table),
        "metadata": {str(k): _clean(v, sandbox) for k, v in dict(table.meta).items()},
    }


# --- explain ------------------------------------------------------------------------------
def explain_output_file(
    path: str | Path,
    *,
    sandbox: Sandbox | None = None,
    max_items: int = 200,
    target: str | None = None,
) -> dict[str, Any]:
    """Explain every node of an output with the output map (see ``explain_output``)."""
    box = sandbox or _sandbox()
    resolved = resolve_output(path, box)
    suffix = resolved.suffix.lower()
    display = box.display_path(resolved)
    if suffix in _TABLE_SUFFIXES:
        table = _inspect_table(resolved, box)
        return {
            "path": display,
            "format": table["format"],
            "pipeline": "standard",
            "note": (
                "Tabular output. Column meanings follow docs/source/user/outputs.rst "
                "(the target table and the channel table)."
            ),
            "columns": [output_map.describe_column(name) for name in table["columns"]],
            "see": [output_map._OUTPUTS],
        }
    if suffix not in _HDF5_SUFFIXES:
        raise ValueError(f"Unsupported output format: {suffix or '(no suffix)'}")

    limit = max(1, min(int(max_items), MAX_ITEMS_LIMIT))
    with _open(resolved, display) as handle:
        scan = _scan_group(handle)
        groups: dict[str, dict[str, Any]] = {}
        unexplained: list[str] = []
        for node_path, kind in _bfs_order(scan.nodes):
            meaning: dict[str, Any] | None
            if kind == "softlink":
                meaning = {
                    "path_pattern": "(soft link)",
                    "meaning": "A soft link: an alias of another node of the same "
                    "file. It is listed but never followed.",
                    "units": None,
                    "produced_by": "unknown (not written by ExoRad)",
                    "doc": None,
                }
            else:
                meaning = output_map.describe_path(node_path)
            if meaning is None:
                unexplained.append(node_path)
                continue
            entry = groups.get(meaning["path_pattern"])
            if entry is None:
                groups[meaning["path_pattern"]] = {
                    **meaning,
                    "example_path": node_path,
                    "count": 1,
                }
            else:
                entry["count"] += 1
        explained = list(groups.values())
        explained_count = sum(entry["count"] for entry in explained)
        result: dict[str, Any] = {
            "path": display,
            "format": "hdf5",
            "pipeline": "standard",
            "explained": explained[:limit],
            "unexplained": unexplained[:limit],
            "explained_count": explained_count,
            "unexplained_count": len(unexplained),
            "total_nodes": len(scan.nodes),
            "truncated": len(explained) > limit or len(unexplained) > limit,
            "see": [output_map._OUTPUTS, f"{output_map._MODEL}total_noise.rst"],
        }
        result["columns"], result["noise_budget"] = _explain_targets(
            handle, box, target
        )
    return result


def _ordered_targets(handle: h5py.File) -> list[str]:
    if "targets" not in handle or not isinstance(handle["targets"], h5py.Group):
        return []

    def key(name: str) -> tuple[int, str]:
        raw = _scalar(handle, f"targets/{name}/id")
        try:
            return (int(raw), name)
        except (TypeError, ValueError):
            return (10**9, name)

    return sorted(handle["targets"], key=key)


def _explain_targets(
    handle: h5py.File, sandbox: Sandbox, target: str | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    available = _ordered_targets(handle)
    if target is not None:
        if target not in available:
            shown = ", ".join(available[:20]) or "(none)"
            raise KeyError(
                f"target '{target}' not found in the file; available: {shown}"
            )
        chosen = [target]
    else:
        chosen = available[:DEFAULT_EXPLAIN_TARGETS]
    columns: list[dict[str, Any]] = []
    budget: dict[str, Any] = {}
    for name in chosen:
        if f"targets/{name}/table/table" not in handle:
            budget[name] = {"error": "target has no result table"}
            continue
        try:
            table = _read_table(handle, f"targets/{name}/table", "table")
        except Exception as exc:
            budget[name] = {"error": f"table not readable ({type(exc).__name__})"}
            continue
        if not columns:
            columns = [
                output_map.describe_column(
                    col, None if table[col].unit is None else str(table[col].unit)
                )
                for col in table.colnames
            ]
        budget[name] = _noise_budget(handle, table)
    return columns, budget


def _stats(values: np.ndarray) -> dict[str, float | None]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {"min": None, "median": None, "max": None}
    return {
        "min": float(finite.min()),
        "median": float(np.median(finite)),
        "max": float(finite.max()),
    }


def _noise_budget(handle: h5py.File, table: Any) -> dict[str, Any]:
    """Per channel noise components in sqrt(hr), as in ``outputs.rst``.

    Components in ct s-1 sqrt(hr) are divided by ``star_signal_inAperture`` (what
    ``Plotter.plot_noise`` does); custom noises are already relative. The result
    includes a reconstruction of ``total_noise`` from the documented formula.
    """
    from astropy import units as u

    note = (
        "Components are relative noise in sqrt(hr). Columns in ct s-1 sqrt(hr) are "
        "divided by star_signal_inAperture (as Plotter.plot_noise does); custom "
        "noises are already relative. total_noise follows "
        "docs/source/user/radiometric_model/total_noise.rst: sqrt(darkcurrent^2 + "
        "(1+NoiseX) sum(photon^2) + read^2)/star_signal_inAperture, plus the custom "
        "noises in quadrature; 'reconstruction' checks that on this file. See "
        "docs/source/user/outputs.rst."
    )
    names = list(table.colnames)
    star = (
        np.asarray(table["star_signal_inAperture"].value, dtype=float)
        if "star_signal_inAperture" in names
        else None
    )
    relative = u.hr**0.5
    kinds: dict[str, str] = {}
    values: dict[str, np.ndarray] = {}
    skipped: list[str] = []
    for col in names:
        if not col.endswith("_noise") or col == "total_noise":
            continue
        data = np.asarray(table[col].value, dtype=float)
        if table[col].unit == relative:
            kinds[col] = "custom"
        else:
            if star is None:
                skipped.append(col)
                continue
            with np.errstate(divide="ignore", invalid="ignore"):
                data = data / star
            kinds[col] = (
                "detector" if col in {"darkcurrent_noise", "read_noise"} else "photon"
            )
        values[col] = data

    channel_names = (
        [_text(x) for x in np.asarray(table["chName"])] if "chName" in names else []
    )
    channels: dict[str, Any] = {}
    for name in dict.fromkeys(channel_names):
        rows = np.array([c == name for c in channel_names])
        info: dict[str, Any] = {
            "n_bins": int(rows.sum()),
            "components": {
                col: {**_stats(data[rows]), "kind": kinds[col]}
                for col, data in values.items()
            },
        }
        if "total_noise" in names:
            total = np.asarray(table["total_noise"].value, dtype=float)[rows]
            info["total_noise"] = _stats(total)
        if {"Wavelength", "LeftBinEdge", "RightBinEdge"} <= set(names):
            left = _to_um(table["LeftBinEdge"])[rows]
            right = _to_um(table["RightBinEdge"])[rows]
            wave = _to_um(table["Wavelength"])[rows]
            centre = float((np.nanmin(left) + np.nanmax(right)) / 2.0)
            index = int(np.nanargmin(np.abs(wave - centre)))
            info["band_centre_um"] = _finite(centre)
            best, best_value = None, -math.inf
            for col, data in values.items():
                val = data[rows][index]
                if math.isfinite(val) and val > best_value:
                    best, best_value = col, float(val)
            info["dominant_component_at_band_centre"] = best
        if "total_noise" in names and values:
            info["reconstruction"] = _reconstruct(
                handle, name, values, kinds, rows, table
            )
        channels[name] = info
    result: dict[str, Any] = {"channels": channels, "note": note}
    if skipped:
        result["skipped_components"] = skipped
    return result


def _reconstruct(
    handle: h5py.File,
    channel: str,
    values: dict[str, np.ndarray],
    kinds: dict[str, str],
    rows: np.ndarray,
    table: Any,
) -> dict[str, Any]:
    raw = _scalar(handle, f"payload/payload description/channel/{channel}/NoiseX/value")
    noise_x = _finite(raw) if raw is not None else 0.0
    noise_x = 0.0 if noise_x is None else noise_x
    square = {
        "detector": 0.0,
        "photon": 0.0,
        "custom": 0.0,
    }
    for col, data in values.items():
        square[kinds[col]] = square[kinds[col]] + data[rows] ** 2
    estimate = np.sqrt(
        square["detector"] + (1.0 + noise_x) * square["photon"] + square["custom"]
    )
    total = np.asarray(table["total_noise"].value, dtype=float)[rows]
    good = np.isfinite(estimate) & np.isfinite(total) & (total > 0)
    difference = (
        float(np.max(np.abs(estimate[good] - total[good]) / total[good]))
        if good.any()
        else None
    )
    return {"noiseX": noise_x, "max_relative_difference": difference}
