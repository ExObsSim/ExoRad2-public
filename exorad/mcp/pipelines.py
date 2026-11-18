"""The ``standard`` pipeline for the MCP: preflight, the job entry and job reports.

``run_pipeline`` (in :mod:`exorad.mcp.tools_run`) is a thin wrapper; the logic
lives here so it can be tested without a server.

* :func:`plan_run` is the PREFLIGHT. Everything that can be checked without
  starting a process is checked here, in the order of the spec (3.4): execution
  enabled, pipeline known, argument ranges, payload and target list exist inside
  the sandbox, the static rules of :mod:`exorad.mcp.rules` and
  :mod:`exorad.mcp.targets` hold no error (this is where ``sourceSpectrum=sed``,
  URLs and pickles are refused, the only real control for ``n_threads > 1``
  because pool workers are not covered by the network guard), limits, output
  rules. It writes the NORMALISED COPY of the payload (absolute paths) that the
  job receives, so validation and the job open exactly the same files; nothing
  is written when a check fails.
* :func:`run_standard` is the entry that runs in the spawned job child. It first
  re-checks the target list and every file the copy names
  (:func:`revalidate_inputs`: they are opened later, from their original paths),
  then calls ``exorad.standard_pipeline`` on the copy (the library logs ``observing
  <name>`` when a target starts and ``target <name> observed`` when it is done;
  the job manager reports them as ``targets_started`` and ``targets_done``),
  compares the targets requested with the targets in the
  file and writes ``<output stem>.run.json``. If some targets are missing it
  raises ``RuntimeError("targets skipped: ...")``: the job is ``failed`` but the
  good targets stay in the output (the library keeps them).
* :func:`describe_job` turns a job-manager status into the tool result: it adds
  ``outcome`` (``complete``, ``partial``, ``failed``, ...), ``files`` and, for
  runs that produced a result, a ``summary``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import secrets
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from exorad.mcp import jobs, rules, targets
from exorad.mcp.sandbox import Sandbox

logger = logging.getLogger("exorad.mcp.pipelines")

ENTRY = "exorad.mcp.pipelines:run_standard"
PIPELINES = ("standard",)
OUTPUT_SUFFIXES = (".h5", ".hdf5")
#: Longest ``run_pipeline`` blocks for the job. Client tool-call timeouts are
#: usually short, so a long wait would fail on the client side while the job goes
#: on; poll with ``get_job_status`` instead.
MAX_WAIT_SECONDS = 50.0

# -- output size estimate (spec 2.7, H11) ------------------------------------
# Fitted to real runs of the example payload with the demo SED (the table
# ``MEASURED_RUNS`` in tests/mcp/test_pipelines.py; working_R 1000/3000/6000, 1
# and 3 targets, 1 and 2 channels, with and without ``full_contrib``). A file is
#   n_channels * (CHANNEL_BASE_MB + CHANNEL_MB_PER_1000_R * R/1000)      payload
# + n_targets * (TARGET_BASE_MB + TARGET_MB_PER_1000_R * R/1000          SED etc.
#                + spectral_bins * MB_PER_BIN)                           result table
# The per-target part is dominated by the arrays that sit on the working_R grid
# (star SED, foregrounds, sky transmission: about nine float64 arrays), the table
# part by the rows of the result table, which HDF5 stores twice (the structured
# array and one dataset per column).
CHANNEL_BASE_MB = 1.0
CHANNEL_MB_PER_1000_R = 0.32
TARGET_BASE_MB = 0.15
TARGET_MB_PER_1000_R = 0.075
MB_PER_BIN = 0.0005  #: 2 x 252 bytes per row (32 columns)
MB_PER_BIN_FULL_CONTRIB = 0.0008  #: 2 x 380 bytes per row (48 columns), a little more
#: Bins assumed for a spectrometer whose ``targetR`` is absent, ``native`` or a table.
ASSUMED_NATIVE_BINS = 1024
#: The estimate is padded: refusing late is worse than refusing a little early.
ESTIMATE_MARGIN = 1.25


def estimate_output_mb(
    n_targets: int,
    working_R: float,
    n_channels: int = 2,
    *,
    spectral_bins: int = 13,
    full_contrib: bool = False,
) -> float:
    """Estimated size of the HDF5 output in MB (padded by :data:`ESTIMATE_MARGIN`).

    Grows linearly with ``working_R`` (the arrays that sit on that grid), with
    the number of targets and channels, and with the total number of rows of the
    result table (``spectral_bins``: the spectrometer bins plus one row per
    photometer).
    """
    scale = float(working_R) / 1000.0
    channels = max(1, int(n_channels))
    payload = channels * (CHANNEL_BASE_MB + CHANNEL_MB_PER_1000_R * scale)
    per_bin = MB_PER_BIN_FULL_CONTRIB if full_contrib else MB_PER_BIN
    per_target = (
        TARGET_BASE_MB
        + TARGET_MB_PER_1000_R * scale
        + max(0, int(spectral_bins)) * per_bin
    )
    return (payload + max(0, int(n_targets)) * per_target) * ESTIMATE_MARGIN


def count_spectral_bins(payload: Path | str) -> int:
    """Rows of the result table: spectrometer bins plus one per photometer.

    Reads the (normalised) payload XML; a spectrometer's bin count is
    ``ceil(ln(wl_max/wl_min) / ln(1 + 1/targetR)) + 1`` as in the library, or
    :data:`ASSUMED_NATIVE_BINS` when ``targetR`` is not a number.
    """
    import math
    import xml.etree.ElementTree as ET

    from astropy import units as u

    def number(el: ET.Element | None) -> float | None:
        try:
            return float((el.text or "").strip()) if el is not None else None
        except ValueError:
            return None

    def micron(el: ET.Element | None) -> float | None:
        value = number(el)
        if value is None or el is None:
            return None
        unit = el.get("unit")
        try:
            return float((value * u.Unit(unit)).to(u.um).value) if unit else value
        except (ValueError, u.UnitsError):
            return None

    root = ET.parse(payload).getroot()
    total = 0
    for channel in root.findall("channel"):
        cls = (channel.findtext("channelClass") or "").strip().lower()
        if cls != "spectrometer":
            total += 1
            continue
        resolution = number(channel.find("targetR"))
        lo, hi = micron(channel.find("wl_min")), micron(channel.find("wl_max"))
        if resolution and resolution > 0 and lo and hi and 0 < lo < hi:
            total += math.ceil(math.log(hi / lo) / math.log1p(1.0 / resolution)) + 1
        else:
            total += ASSUMED_NATIVE_BINS
    return max(total, 1)


# -- the plan ---------------------------------------------------------------
@dataclass
class RunPlan:
    """Everything the preflight decided (all paths absolute)."""

    pipeline: str
    payload_original: Path
    payload: Path  #: the normalised copy the job opens
    target_list: Path
    output: Path
    run_dir: Path
    replace: bool
    n_threads: int
    n_threads_requested: int
    plot: bool
    full_contrib: bool
    target_names: list[str]
    working_R: float
    n_channels: int
    estimated_mb: float
    max_output_bytes: int
    runtime: float
    warnings: list[str] = field(default_factory=list)
    #: roots and limits the job child re-checks its inputs against
    sandbox_spec: dict[str, Any] = field(default_factory=dict)

    def spec(self) -> dict[str, Any]:
        """The job spec (the whitelist of what reaches the child)."""
        return {
            "entry": ENTRY,
            "pipeline": self.pipeline,
            "payload": str(self.payload),
            "target_list": str(self.target_list),
            "output": str(self.output),
            "n_thread": self.n_threads,
            "plot": self.plot,
            "full_contrib": self.full_contrib,
            "replace": self.replace,
            "expected_targets": list(self.target_names),
            "max_output_bytes": self.max_output_bytes,
            "sandbox": self.sandbox_spec,
        }


def _format_finding(finding: rules.Finding) -> str:
    return f"{finding.code} {finding.path}: {finding.message}"


def _check_suffix(path: str, suffix: str, what: str) -> None:
    if Path(str(path)).suffix.lower() != suffix:
        raise ValueError(
            f"{what} must be a {suffix} file, got '{Path(str(path)).name}'"
        )


def _resolve_output(
    sandbox: Sandbox, output: str, overwrite: bool, run_dir: Path
) -> Path:
    if not output:
        return run_dir / "output.h5"
    if "://" in str(output):
        raise ValueError("the output must be a path inside the working directory")
    path = sandbox.resolve_write(output)
    if path.suffix.lower() not in OUTPUT_SUFFIXES:
        raise ValueError(f"the output must end in .h5 or .hdf5, got '{path.name}'")
    if path.parent == sandbox.work_dir:
        raise ValueError(
            "the output must be inside a sub-directory of the working directory "
            "(the pipeline copies its input files next to it), for example "
            f"'results/{path.name}'; leave `output` empty for a fresh run directory"
        )
    roots = sandbox.writable_roots
    for ancestor in path.parents:
        if ancestor in roots or not any(root in ancestor.parents for root in roots):
            break  # only the part below a writable root is the client's choice
        if ancestor.exists() and not ancestor.is_dir():
            raise ValueError(
                f"'{sandbox.display_path(ancestor)}' is a file, not a directory, so the "
                f"output '{sandbox.display_path(path)}' cannot be created there; choose "
                "another output directory"
            )
    _refuse_if_in_use(path)
    if path.is_dir():
        raise ValueError(f"the output '{path.name}' is a directory")
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"the output {sandbox.display_path(path)} already exists; pass "
            "overwrite=True to replace it or choose another output name"
        )
    if path.exists() and not path.is_file():
        raise ValueError(f"the output '{path.name}' is not a regular file")
    return path


def _previous_copies(output: Path) -> set[str]:
    """Input copies an earlier run of THE SAME output left next to it.

    Read from ``<stem>.run.json`` (see :func:`run_standard`); empty when there is
    no such record.
    """
    info = _read_run_json(output)
    names = info.get("input_copies", []) if info else []
    return (
        {n for n in names if isinstance(n, str)} if isinstance(names, list) else set()
    )


def _refuse_if_in_use(path: Path) -> None:
    """Raise :class:`~exorad.mcp.jobs.OutputInUseError` if a running job owns ``path``."""
    clash = jobs.JOBS.output_clash(str(path))
    if clash is not None:
        raise jobs.OutputInUseError(*clash)


def _check_clash(
    parent: Path,
    copies: list[Path],
    sandbox: Sandbox,
    *,
    replaceable: frozenset[str] | set[str] = frozenset(),
) -> None:
    """Refuse an output directory where the library would overwrite another file.

    ``standard_pipeline`` copies the payload and the target list into the output
    directory. A different file with the same name there would be replaced.
    ``replaceable`` names the copies that an earlier run of the same output left
    (only with ``overwrite=True``): replacing those is the point of a re-run.
    """
    for source in copies:
        existing = parent / source.name
        if not existing.exists() and not existing.is_symlink():
            continue
        try:
            same = existing.samefile(source)
        except OSError:
            same = False
        if same:
            continue
        if (
            source.name in replaceable
            and existing.is_file()
            and not existing.is_symlink()
        ):
            continue
        raise FileExistsError(
            f"the output directory already holds a different file named "
            f"'{source.name}' (the pipeline copies its inputs next to the "
            "output and would overwrite it); choose another output directory "
            "or leave `output` empty"
        )


def plan_run(
    payload: str,
    target_list: str,
    output: str = "",
    *,
    n_threads: int = 1,
    plot: bool = False,
    full_contrib: bool = False,
    overwrite: bool = False,
    max_runtime_seconds: float | None = None,
    pipeline: str = "standard",
    sandbox: Sandbox | None = None,
) -> RunPlan:
    """Run every check that needs no process and write the normalised payload copy.

    Raises
    ------
    PermissionError
        Execution is disabled.
    ValueError
        Unknown pipeline, bad argument, or (as :class:`~exorad.mcp.rules.ConfigRuleError`)
        error findings; the message lists the findings, one per line.
    FileNotFoundError, PathNotAllowedError
        A file is missing or outside the sandbox.
    FileExistsError
        The output exists and ``overwrite`` is false, or would clobber an input copy.
    """
    box = sandbox or Sandbox.from_env()
    if not box.allow_exec:
        raise PermissionError(
            "pipeline execution is disabled on this server (EXORAD_MCP_NO_EXEC / "
            "--no-exec); the information and validation tools still work"
        )
    if pipeline not in PIPELINES:
        raise ValueError(
            f"unknown pipeline '{pipeline}'; known pipelines: {', '.join(PIPELINES)}"
        )
    if not isinstance(n_threads, int) or isinstance(n_threads, bool) or n_threads < 1:
        raise ValueError(f"n_threads must be an integer >= 1, got {n_threads!r}")
    runtime = jobs.effective_runtime(max_runtime_seconds)
    _check_suffix(payload, ".xml", "the payload")
    _check_suffix(target_list, ".csv", "the target list")
    payload_path = box.resolve_input_file(
        payload, prefer_work_dir=True, max_mb=box.max_file_mb
    )
    target_path = box.resolve_input_file(
        target_list, prefer_work_dir=True, max_mb=box.max_file_mb
    )

    report = targets.validate_target_list(target_path, sandbox=box)
    if not report.ok:
        raise rules.ConfigRuleError(report.findings)

    work = box.ensure_work_dir()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = work / "runs" / f"{stamp}-{secrets.token_hex(3)}"
    inputs = run_dir / "inputs"
    created = False
    try:
        # the copy is written only when the static rules found no error
        norm = rules.normalise_payload(payload_path, sandbox=box, dest_dir=inputs)
        if norm.path is None:
            raise rules.ConfigRuleError(norm.findings)
        created = True
        warnings = [
            _format_finding(f) for f in norm.findings if f.severity == rules.WARNING
        ]
        warnings += [
            _format_finding(f) for f in report.findings if f.severity == rules.WARNING
        ]
        if report.rows > box.max_targets:  # also a finding; belt and braces
            raise ValueError(
                f"{report.rows} targets, above the limit of {box.max_targets} "
                "(EXORAD_MCP_MAX_TARGETS)"
            )
        info = norm.info
        working_R = float(info.get("working_R") or rules.DEFAULT_WORKING_R)
        if working_R > rules.MAX_WORKING_R:
            raise ValueError(
                f"working_R {working_R:g} is above the limit of {rules.MAX_WORKING_R}"
            )
        n_channels = max(1, len(info.get("channels") or []))
        bins = count_spectral_bins(norm.path)
        estimate = estimate_output_mb(
            report.rows,
            working_R,
            n_channels,
            spectral_bins=bins,
            full_contrib=full_contrib,
        )
        if estimate > box.max_output_mb:
            raise ValueError(
                f"the estimated output is {estimate:.0f} MB ({report.rows} targets, "
                f"{n_channels} channels, {bins} result rows, working_R={working_R:g}), above the limit of "
                f"{box.max_output_mb} MB (EXORAD_MCP_MAX_OUTPUT_MB); use fewer targets "
                "or a smaller working_R"
            )
        out_path = _resolve_output(box, output, overwrite, run_dir)
        _check_clash(
            out_path.parent,
            [norm.path, target_path],
            box,
            replaceable=_previous_copies(out_path) if overwrite else set(),
        )

        if max_runtime_seconds is not None and runtime < float(max_runtime_seconds):
            warnings.append(
                f"max_runtime_seconds reduced from {max_runtime_seconds:g} to "
                f"{runtime:g} (server cap, EXORAD_MCP_MAX_RUNTIME)"
            )

        threads = box.clamp_threads(n_threads)
        threads = max(1, min(threads, report.rows))
        if threads != n_threads:
            warnings.append(
                f"n_threads reduced from {n_threads} to {threads} "
                f"(server limit {box.max_threads}, {report.rows} target(s))"
            )
        return RunPlan(
            pipeline=pipeline,
            payload_original=payload_path,
            payload=norm.path,
            target_list=target_path,
            output=out_path,
            run_dir=run_dir,
            replace=bool(overwrite),
            n_threads=threads,
            n_threads_requested=n_threads,
            plot=bool(plot),
            full_contrib=bool(full_contrib),
            target_names=list(report.names),
            working_R=working_R,
            n_channels=n_channels,
            estimated_mb=round(estimate, 1),
            max_output_bytes=int(box.max_output_mb * 1_048_576),
            runtime=runtime,
            warnings=warnings,
            sandbox_spec=dict(box.to_spec()),
        )
    except BaseException:
        if created or run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)
        raise


def discard_plan(plan: RunPlan) -> None:
    """Remove the run directory of a plan that was never submitted."""
    shutil.rmtree(plan.run_dir, ignore_errors=True)


# -- registry of the runs submitted by this server ----------------------------
_RUNS: dict[str, RunPlan] = {}
_RUNS_LOCK = threading.Lock()


def register_run(job_id: str, plan: RunPlan) -> None:
    """Remember the plan of a submitted job (jobs do not outlive the server)."""
    with _RUNS_LOCK:
        _RUNS[job_id] = plan


def registered_run(job_id: str) -> RunPlan | None:
    with _RUNS_LOCK:
        return _RUNS.get(job_id)


# -- the job child ---------------------------------------------------------------
def run_json_path(output: str | Path) -> Path:
    """``<output stem>.run.json`` beside the output."""
    out = Path(output)
    return out.with_name(f"{out.stem}.run.json")


def _targets_in(output: str | Path) -> tuple[list[str], list[dict[str, Any]]]:
    """Names of the targets and the channels in a finished file."""
    import h5py

    names: list[str] = []
    channels: list[dict[str, Any]] = []
    if not os.path.exists(output):
        return names, channels
    try:
        with h5py.File(output, "r") as handle:
            group = handle.get("targets")
            if isinstance(group, h5py.Group):
                names = list(group.keys())
            chans = handle.get("payload/channels")
            if isinstance(chans, h5py.Group):
                for name in chans:
                    table = chans[name].get(name)
                    rows = int(table.shape[0]) if hasattr(table, "shape") else None
                    channels.append({"name": str(name), "n_bins": rows})
    except OSError:
        return names, channels  # an incomplete file: reported as no targets
    return names, channels


def revalidate_inputs(spec: dict[str, Any]) -> None:
    """Check again, in the job child, the files the run is about to open.

    ``plan_run`` checked them when the job was submitted; the job starts later
    and the target list and every data file are opened from their ORIGINAL paths,
    so someone who can write there could have swapped a file for a symbolic
    link, a pipe or an HDF5 file with external links in between. This refuses
    (``ConfigRuleError``, names the file by its label, never an absolute path):
    the payload copy and every reference in it (regular file, no symbolic link on
    the way, inside the readable roots, within the size limits, HDF5 link scan,
    directory listings) and the target list.

    Residual race: it narrows the window, it does not close it. A process that
    can write to the work dir or to a directory the payload names can still swap a
    file between this check and the moment the library opens it. The only full
    protection is to keep those directories writable by trusted users only.
    """
    box = Sandbox.from_spec(spec["sandbox"])
    # ``payload_checks`` / tag lists are written by the extension's own planner (a
    # server-side spec, never client input); an ExoRad spec has none of them.
    findings = rules.recheck_payload(
        Path(str(spec["payload"])),
        box,
        payload_checks=bool(spec.get("payload_checks", True)),
        exclude_reference_tags=tuple(spec.get("exclude_reference_tags", ())),
        reference_tags=tuple(spec.get("reference_tags", ())),
    )
    problem = rules.strict_file_problem(
        Path(str(spec["target_list"])),
        box,
        max_bytes=int(box.max_file_mb * 1_048_576),
        label="the target list",
    )
    if problem is not None:
        findings.append(
            rules.Finding(rules.ERROR, "NOT_REGULAR_FILE", "target_list", problem)
        )
    else:
        report = targets.validate_target_list(
            Path(str(spec["target_list"])), sandbox=box
        )
        findings.extend(report.findings)
    if rules.errors_of(findings):
        raise rules.ConfigRuleError(findings)


def run_standard(spec: dict[str, Any]) -> dict[str, Any]:
    """Job entry: run ``standard_pipeline`` on the normalised copy and verify it.

    Writes ``<output stem>.run.json`` (no absolute paths) even when the run
    fails and raises
    ``RuntimeError("targets skipped: ...")`` when some requested target is
    missing. Paths in ``spec`` are absolute and the working directory is never
    changed.
    """
    import exorad
    from exorad.__version__ import __version__

    started = time.time()
    output = str(spec["output"])
    expected = [str(n) for n in spec.get("expected_targets", [])]
    # the library copies these two files next to the output; recorded BEFORE the
    # run so that even a killed run lets ``overwrite=True`` replace its copies
    copies = sorted(
        {Path(str(spec["payload"])).name, Path(str(spec["target_list"])).name}
    )
    with contextlib.suppress(OSError):
        run_json_path(output).parent.mkdir(parents=True, exist_ok=True)
        run_json_path(output).write_text(
            json.dumps({"input_copies": copies}), encoding="utf-8"
        )
    error: BaseException | None = None
    try:
        if spec.get("revalidate", True):  # only the backstop tests switch it off
            revalidate_inputs(spec)
        exorad.standard_pipeline(
            options=str(spec["payload"]),
            target_list=str(spec["target_list"]),
            output=output,
            plot=bool(spec.get("plot", False)),
            full_contrib=bool(spec.get("full_contrib", False)),
            n_thread=int(spec.get("n_thread", 1)),
            debug=False,
            log=False,
            replace=bool(spec.get("replace", False)),
        )
    except Exception as exc:  # reported after run.json is written
        error = exc

    written, channels = _targets_in(output)
    wanted = expected or written
    skipped = [name for name in wanted if name not in written]
    summary: dict[str, Any] = {
        "pipeline": spec.get("pipeline", "standard"),
        "version": __version__,
        "targets_requested": wanted,
        "targets_written": written,
        "skipped": skipped,
        "channels": channels,
        "input_copies": copies,
        "runtime_s": round(time.time() - started, 2),
    }
    if error is not None:
        summary["error"] = f"{type(error).__name__}: {error}"[:500]
    try:
        run_json_path(output).write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
    except OSError:
        logger.warning("could not write the run summary next to the output")
    if error is not None:
        raise error
    if skipped:
        raise RuntimeError(
            f"targets skipped: {', '.join(skipped)} "
            f"({len(written)} of {len(wanted)} written); see the log"
        )
    return summary


# -- reports -------------------------------------------------------------------
def _read_run_json(output: Path) -> dict[str, Any] | None:
    try:
        return json.loads(run_json_path(output).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _file_entry(path: Path, sandbox: Sandbox) -> dict[str, Any] | None:
    try:
        size = path.stat().st_size
    except OSError:
        return None
    return {"name": path.name, "path": sandbox.display_path(path), "size_bytes": size}


def list_files(plan: RunPlan, sandbox: Sandbox) -> list[dict[str, Any]]:
    """Files this run is known to have produced (not the whole directory)."""
    from exorad.tasks.targetHandler import safe_file_stem

    out = plan.output
    parent = out.parent
    candidates = [
        out,
        run_json_path(out),
        parent / plan.payload.name,
        parent / plan.target_list.name,
    ]
    if plan.plot:
        candidates.append(parent / "efficiency.png")
        candidates += [parent / f"{safe_file_stem(n)}.png" for n in plan.target_names]
    seen: set[Path] = set()
    files = []
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        entry = _file_entry(path, sandbox)
        if entry is not None:
            files.append(entry)
    return files


def describe_job(
    status: dict[str, Any], sandbox: Sandbox | None = None
) -> dict[str, Any]:
    """Enrich a job-manager status for the client.

    Adds ``outcome`` (``running``, ``complete``, ``partial``, ``failed``,
    ``cancelled``, ``timeout``), and for jobs started by this server
    ``targets_requested``, ``files`` and ``summary`` (targets written, skipped,
    channels) once the job has ended. A ``partial`` outcome (status ``failed``)
    means the output file exists and holds the targets in ``targets_written``;
    ``skipped_targets`` lists the others.
    """
    box = sandbox or Sandbox.from_env()
    result = dict(status)
    state = result.get("status")
    plan = registered_run(str(result.get("job_id")))
    result["outcome"] = state if state != "succeeded" else "complete"
    if plan is None:
        return result
    result["targets_requested"] = len(plan.target_names)
    if state == "running":
        return result
    warnings = list(plan.warnings)
    info = _read_run_json(plan.output)
    if info is not None and "targets_written" in info:  # not the early record
        written = list(info.get("targets_written", []))
        skipped = list(info.get("skipped", []))
        result["summary"] = {
            "targets_written": len(written),
            "targets_requested": len(info.get("targets_requested", [])),
            "target_names": written[:50],
            "channels": info.get("channels", []),
            "runtime_s": info.get("runtime_s"),
        }
        if skipped:
            result["skipped_targets"] = skipped
            if written and state == "failed":
                result["outcome"] = "partial"
                warnings.append(
                    f"{len(written)} of {len(info.get('targets_requested', []))} "
                    f"targets were written; skipped: {', '.join(skipped)}. The "
                    "output file keeps the good targets; see log_tail / the job log for the cause"
                )
    if state != "succeeded" and plan.output.exists() and result["outcome"] != "partial":
        warnings.append(
            "the output file may be incomplete (the run did not finish); do not use it"
        )
    result["files"] = list_files(plan, box)
    if warnings:
        result["warnings"] = warnings
    return result


__all__ = [
    "ENTRY",
    "PIPELINES",
    "RunPlan",
    "count_spectral_bins",
    "describe_job",
    "discard_plan",
    "estimate_output_mb",
    "list_files",
    "plan_run",
    "register_run",
    "registered_run",
    "revalidate_inputs",
    "run_json_path",
    "run_standard",
]
