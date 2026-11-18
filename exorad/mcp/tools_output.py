"""Output tools of the ExoRad MCP server: inspect, explain and plot a result file.

Plain Python functions (unit tests call them directly); the server registers
them through ``_expose_errors``. ``inspect_output`` and ``explain_output`` only
read; ``plot_output`` is an execution tool because the figures are drawn in a
spawned child (``exorad.mcp.plotting:render`` through ``JobManager.run_sync``).
All three refuse HDF5 files with external links or virtual datasets before
reading anything (hazard H17, see :mod:`exorad.mcp.outputs`).
"""

from __future__ import annotations

import time
from typing import Any

from exorad.mcp import outputs, plotting
from exorad.mcp.sandbox import Sandbox


def inspect_output(path: str, max_items: int = 80) -> dict[str, Any]:
    """Summarise the structure of an ExoRad output file (HDF5, CSV or ECSV).

    For an HDF5 file the nodes are listed breadth first (so a small ``max_items``
    still shows every top-level group), each with its type, shape, dtype,
    attributes and, where the output map knows it, its meaning. Arrays are never
    dumped; only scalars of ``info/ExoRad``, the payload description and
    ``targets/<T>/star`` are shown, with the server's directories redacted. When
    the file holds ``payload`` and ``targets`` the result also has ``exorad``: the
    ExoRad version, the target names, each channel (class, number of bins,
    wavelength range in micron) and the columns of the result table.

    Files with HDF5 external links or virtual datasets are refused with a
    ``ValueError`` before anything is read.

    Parameters
    ----------
    path : str
        File to inspect. A bare name is looked up in the working directory first
        (so ``output.h5`` from a run is found), then in the content root.
    max_items : int
        Maximum number of nodes listed, clamped to 1..2000.

    Returns
    -------
    dict
        ``path``, ``format``, ``root_attrs``, ``items``, ``total_nodes``,
        ``truncated`` and (ExoRad files) ``exorad``; for CSV/ECSV ``columns``,
        ``row_count`` and ``metadata``.
    """
    return outputs.inspect_output_file(path, max_items=max_items)


def explain_output(
    path: str, max_items: int = 200, target: str | None = None
) -> dict[str, Any]:
    """Explain what every node of an ExoRad output file means, and its noise budget.

    Walks the WHOLE file (links are checked first, see ``inspect_output``) and
    groups the nodes by path pattern; each pattern is explained from the output
    map (meaning, units, the code that writes it, the documentation page). Nodes
    with no entry are listed under ``unexplained``; ``explained_count`` plus
    ``unexplained_count`` equals ``total_nodes``. It also describes every column of
    the result table (``columns``, following ``docs/source/user/outputs.rst``)
    and, per target and per channel, a ``noise_budget``: minimum, median and
    maximum of each noise component in sqrt(hr), the dominant component at the
    band centre, ``total_noise`` and a reconstruction of it from the documented
    formula.

    Parameters
    ----------
    path : str
        HDF5 (or CSV/ECSV) output file.
    max_items : int
        Cap on the ``explained`` and ``unexplained`` lists (1..2000).
    target : str, optional
        Explain only this target; the default is the first five.

    Returns
    -------
    dict
        ``path``, ``format``, ``pipeline``, ``explained`` (entries with
        ``path_pattern``, ``example_path``, ``count``, ``meaning``, ``units``,
        ``produced_by``, ``doc``), ``unexplained``, the counts, ``truncated``,
        ``columns``, ``noise_budget`` and ``see``.

    Raises
    ------
    KeyError
        ``target`` is not in the file.
    """
    return outputs.explain_output_file(path, max_items=max_items, target=target)


def plot_output(
    path: str, target: str | None = None, kind: str = "table"
) -> dict[str, Any]:
    """Draw PNG figures from an ExoRad HDF5 output into ``<work dir>/plots/``.

    ``kind="table"`` draws, per target, the signal and noise panels (the first
    five targets, or the one named by ``target``). ``kind="efficiency"`` draws the
    payload's transmission, quantum efficiency and their product for every
    channel. Figures are rendered in a separate process. A file that cannot be
    plotted (no targets, no built instrument) yields ``plottable: false`` with a
    ``reason``; a figure that fails is reported under ``warnings`` while the others
    are still written. File names derive from the target names with every
    unsafe character replaced, and never leave the plot folder.

    Parameters
    ----------
    path : str
        HDF5 output file (links are checked first, see ``inspect_output``).
    target : str, optional
        Target name (``kind="table"`` only).
    kind : str
        ``"table"`` or ``"efficiency"``.

    Returns
    -------
    dict
        ``kind``, ``plottable``, ``output_dir`` (as ``work:plots/<name>``),
        ``figures`` (file names), ``warnings``, ``total_targets`` or ``channels``
        and, if the rendering process failed, ``error``.

    Raises
    ------
    ValueError
        Unknown ``kind``, not an HDF5 file, unsafe HDF5 content, or the plot
        folder resolves outside the working directory.
    KeyError
        ``target`` is not in the file.
    """
    from exorad.mcp import jobs

    sandbox = Sandbox.from_env()
    resolved = outputs.resolve_output(path, sandbox)
    plan = plotting.prepare(resolved, kind, target, sandbox)
    if not plan["plottable"]:
        return {
            "kind": kind,
            "plottable": False,
            "reason": plan["reason"],
            "figures": [],
            "warnings": [],
        }
    out_dir = sandbox.resolve_write(f"plots/{plotting.output_stem(resolved, sandbox)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir = sandbox.resolve_write(out_dir)  # re-check after creation
    spec = {**plan["spec"], "out_dir": str(out_dir)}
    result: dict[str, Any] = {
        "kind": kind,
        "plottable": True,
        "output_dir": sandbox.display_path(out_dir),
    }
    if plan["total_targets"] is not None:
        result["total_targets"] = plan["total_targets"]
    started = time.time() - 1.0
    try:
        done = jobs.JOBS.run_sync(
            plotting.RENDER_ENTRY,
            spec,
            timeout=sandbox.validate_timeout,
            slot_wait=jobs.SYNC_SLOT_WAIT_SECONDS,
        )
    except jobs.SyncLimitError as exc:  # nothing was drawn, and not because of the file
        return {
            "kind": kind,
            "plottable": None,
            "status": "busy",
            "figures": [],
            "warnings": [],
            "message": f"no figure was drawn: {sandbox.redact(str(exc))} "
            "The file was not found unplottable; retry in a moment.",
        }
    except RuntimeError as exc:  # the child failed; keep what it already wrote
        written = [
            name
            for name in spec["figures"]
            if (out_dir / name).is_file()
            and (out_dir / name).stat().st_mtime >= started
        ]
        result.update(
            figures=written,
            warnings=[],
            error=sandbox.redact(str(exc))[:2000],
        )
        return result
    result["figures"] = list(done.get("figures", []))
    result["warnings"] = [sandbox.redact(str(w)) for w in done.get("warnings", [])]
    if "channels" in done:
        result["channels"] = done["channels"]
    return result
