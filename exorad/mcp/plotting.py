"""Figures from an ExoRad HDF5 output, for the ``plot_output`` tool.

Two kinds:

``table``
    One PNG per target with the signal and noise panels of
    :meth:`exorad.utils.plotter.Plotter.plot_table`, built from
    ``read_table_hdf5(targets/<T>/table, path="table")`` (what ``exorad-plot``
    does).
``efficiency``
    One PNG for the payload: transmission, quantum efficiency and their product
    for every channel, drawn here with matplotlib's object API straight from
    ``payload/channels/<C>/built_instr/{transmission_data,qe_data}``. The
    library's own efficiency plot cannot be rebuilt from an HDF5 file alone (it
    fails with ``um2 vs um``: the loader returns Quantities and the plotter
    multiplies the unit again).

The work is split in two. :func:`prepare` runs in the server: it checks the file
for external links (H17), picks the targets and decides whether the file is
plottable. :func:`render` is the entry that runs in a one-shot child
(``exorad.mcp.plotting:render`` through ``JobManager.run_sync``), because
``pyplot`` and ``PassVal`` are process-global and the server serves concurrent
calls. ``render`` scans the file again before it reads anything.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import h5py
import numpy as np

from exorad.mcp import outputs
from exorad.tasks.targetHandler import safe_file_stem

if TYPE_CHECKING:
    from exorad.mcp.sandbox import Sandbox

KINDS = ("table", "efficiency")
DEFAULT_MAX_TARGETS = 5
RENDER_ENTRY = "exorad.mcp.plotting:render"
_BUILT = "built_instr"


def _text(value: Any) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def figure_names(targets: list[str]) -> list[str]:
    """File names ``table-<safe target>.png``, made unique if two stems collide."""
    seen: dict[str, int] = {}
    names: list[str] = []
    for target in targets:
        stem = f"table-{safe_file_stem(target)}"
        count = seen.get(stem, 0)
        seen[stem] = count + 1
        names.append(f"{stem}.png" if count == 0 else f"{stem}-{count + 1}.png")
    return names


def _efficiency_channels(handle: h5py.File) -> list[str]:
    """Channels that carry both transmission and QE data."""
    found: list[str] = []
    if "payload/channels" not in handle:
        return found
    for name in handle["payload/channels"]:
        base = f"payload/channels/{name}/{_BUILT}"
        needed = [
            f"{base}/{key}/{part}/value"
            for key in ("transmission_data", "qe_data")
            for part in ("wl_grid", "data")
        ]
        if all(path in handle for path in needed):
            found.append(name)
    return found


def output_stem(path: Path, sandbox: Sandbox) -> str:
    """Folder name for the figures of ``path`` (distinguishes ``runs/<id>/output.h5``)."""
    try:
        relative = path.relative_to(sandbox.work_dir)
        parts = [*relative.parent.parts, relative.stem]
    except ValueError:
        parts = [path.stem]
    # ``results/a-b.h5`` and ``results/a/b.h5`` (or ``x.h5`` and ``x.hdf5``) would
    # share a folder: a short hash of the resolved path keeps them apart
    digest = hashlib.sha1(str(path).encode("utf-8", "replace")).hexdigest()[:8]
    return f"{safe_file_stem('-'.join(parts))}-{digest}"


def prepare(
    path: Path, kind: str, target: str | None, sandbox: Sandbox
) -> dict[str, Any]:
    """Scan the file and decide what to draw; run in the server process.

    Returns either ``{"plottable": False, "reason": ...}`` or
    ``{"plottable": True, "spec": {...}, "total_targets": n}``.

    Raises
    ------
    ValueError
        Unknown ``kind``, an unsafe file (H17), or not an HDF5 file.
    KeyError
        ``target`` is not in the file.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}; got {kind!r}.")
    if kind == "efficiency" and target is not None:
        raise ValueError(
            "`target` applies to kind='table' only; the efficiency plot covers "
            "every channel of the payload. Drop `target` or use kind='table'."
        )
    if path.suffix.lower() not in {".h5", ".hdf5"}:
        raise ValueError("plot_output needs an HDF5 output file (.h5 or .hdf5).")
    display = sandbox.display_path(path)
    with outputs._open(path, display) as handle:
        outputs._scan_group(handle)
        spec: dict[str, Any] = {"path": str(path), "kind": kind}
        if kind == "efficiency":
            channels = _efficiency_channels(handle)
            if not channels:
                return {
                    "plottable": False,
                    "reason": "the file has no payload/channels/<C>/built_instr with "
                    "transmission_data and qe_data, so there is no efficiency to draw",
                }
            spec["channels"] = channels
            spec["figures"] = ["efficiency.png"]
            return {"plottable": True, "spec": spec, "total_targets": None}
        available = outputs._ordered_targets(handle)
        if not available:
            return {
                "plottable": False,
                "reason": "the file has no 'targets' group (a payload-only or "
                "unfinished output), so there is no target table to plot",
            }
        if target is not None:
            if target not in available:
                shown = ", ".join(available[:20]) or "(none)"
                raise KeyError(
                    f"target '{target}' not found in the file; available: {shown}"
                )
            chosen = [target]
        else:
            chosen = available[:DEFAULT_MAX_TARGETS]
        spec["targets"] = chosen
        spec["figures"] = figure_names(chosen)
        return {"plottable": True, "spec": spec, "total_targets": len(available)}


# --- child side -----------------------------------------------------------------
def render(spec: dict[str, Any]) -> dict[str, Any]:
    """Draw the figures of ``spec`` into ``spec["out_dir"]``; run in a child.

    A figure that cannot be drawn becomes a warning; the others are still
    written. Returns ``{"figures": [...], "warnings": [...], "channels"?: [...]}``.
    """
    os.environ.setdefault("MPLBACKEND", "Agg")
    import matplotlib

    matplotlib.use("Agg", force=True)

    path = Path(spec["path"])
    out_dir = Path(spec["out_dir"]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    kind = spec["kind"]
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}; got {kind!r}.")
    figures: list[str] = []
    warnings: list[str] = []
    extra: dict[str, Any] = {}
    with h5py.File(path, "r") as handle:
        outputs._scan_group(handle)  # H17 again, in the process that reads values
        if kind == "table":
            for target, name in zip(spec["targets"], spec["figures"], strict=True):
                try:
                    dest = _destination(out_dir, name)
                    _plot_table(handle, target, dest)
                    figures.append(name)
                except Exception as exc:
                    warnings.append(
                        f"target '{target}': {type(exc).__name__}: {_short(exc)}"
                    )
        else:
            dest = _destination(out_dir, spec["figures"][0])
            used, skipped = _plot_efficiency(handle, spec["channels"], dest)
            figures.append(spec["figures"][0])
            warnings.extend(skipped)
            extra["channels"] = used
    return {"figures": figures, "warnings": warnings, **extra}


def _short(exc: BaseException) -> str:
    text = str(exc).replace("\n", " ")
    return text[:200]


def _destination(out_dir: Path, name: str) -> Path:
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError(f"unsafe figure name {name!r}")
    dest = (out_dir / name).resolve()
    if dest.parent != out_dir:
        raise ValueError(f"figure {name!r} would leave the plot directory")
    return dest


def _plot_table(handle: h5py.File, target: str, dest: Path) -> None:
    import matplotlib.pyplot as plt
    from astropy.io.misc.hdf5 import read_table_hdf5

    from exorad.utils.plotter import Plotter

    if f"targets/{target}/table/table" not in handle:
        raise ValueError("the target has no result table")
    table = read_table_hdf5(handle[f"targets/{target}/table"], path="table")
    table.meta.setdefault("name", target)
    plotter = Plotter(input_table=table)
    fig, _ = plotter.plot_table()
    try:
        fig.savefig(dest, format="png", dpi=100)
    finally:
        plt.close(fig)


def _grid(handle: h5py.File, base: str) -> tuple[np.ndarray, np.ndarray]:
    """``(wavelength in micron, data)`` of a Signal group."""
    from astropy import units as u

    wl = np.asarray(handle[f"{base}/wl_grid/value"][()], dtype=float)
    unit = None
    unit_path = f"{base}/wl_grid/unit"
    if unit_path in handle:
        unit = u.Unit(_text(handle[unit_path][()]) or "micron")
    wl = (wl * (unit or u.micron)).to(u.micron).value
    data = np.asarray(handle[f"{base}/data/value"][()], dtype=float)
    return wl, data


def _plot_efficiency(
    handle: h5py.File, channels: list[str], dest: Path
) -> tuple[list[dict[str, Any]], list[str]]:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=(10, 8))
    FigureCanvasAgg(fig)
    ax = fig.subplots(1, 1)
    used: list[dict[str, Any]] = []
    warnings: list[str] = []
    styles = ("-", "--", ":", "-.")
    for index, name in enumerate(channels):
        base = f"payload/channels/{name}/{_BUILT}"
        try:
            wl_t, transmission = _grid(handle, f"{base}/transmission_data")
            wl_q, qe = _grid(handle, f"{base}/qe_data")
            qe_on_t = np.interp(wl_t, wl_q, qe)
        except Exception as exc:
            warnings.append(f"channel '{name}': {type(exc).__name__}: {_short(exc)}")
            continue
        style = styles[index % len(styles)]
        ax.plot(wl_t, transmission, color="C0", ls=style, label=f"{name} transmission")
        ax.plot(wl_q, qe, color="C1", ls=style, label=f"{name} QE")
        ax.plot(wl_t, transmission * qe_on_t, color="C2", ls=style, label=f"{name} PCE")
        used.append({"name": name, "n_points": int(wl_t.size)})
    if not used:
        raise ValueError("no channel had readable transmission and QE data")
    ax.grid(True)
    ax.set_xlabel(r"Wavelength [$\mu m$]")
    ax.set_ylabel("efficiency")
    ax.set_title("Payload photon conversion efficiency")
    ax.legend(ncol=2, fontsize=9)
    fig.tight_layout()
    fig.savefig(dest, format="png", dpi=100)
    return used, warnings
