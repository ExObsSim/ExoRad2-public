"""Execution tools of the ExoRad MCP server: run a pipeline and supervise its job.

Plain Python functions (unit tests call them directly); the server registers them
through ``_expose_errors``. All four are execution tools: they exist only when
execution is enabled. The pipeline runs in a spawned child process
(:mod:`exorad.mcp.jobs`), never in the server.
"""

from __future__ import annotations

from typing import Any

from exorad.mcp import jobs, pipelines
from exorad.mcp.sandbox import Sandbox


def run_pipeline(
    payload: str,
    target_list: str,
    output: str = "",
    n_threads: int = 1,
    plot: bool = False,
    full_contrib: bool = False,
    overwrite: bool = False,
    wait_seconds: float = 30.0,
    max_runtime_seconds: float | None = None,
    pipeline: str = "standard",
) -> dict[str, Any]:
    """Run the ExoRad radiometric pipeline on a payload and a target list.

    Everything is checked before a process starts (files exist inside the
    sandbox, the payload and target list follow the rules of ``validate_config``,
    ``sourceSpectrum=sed`` and every other network access are refused, limits,
    output rules); a problem is raised as an error that lists the findings. The
    job then runs in a separate process on a normalised copy of the payload with
    absolute paths. Wait for it with ``get_job_status``. The first call can take
    tens of seconds just to import ExoRad, so ``wait_seconds`` may return
    ``status="running"``.

    Parameters
    ----------
    payload : str
        Payload XML. A relative path is tried in the working directory first,
        then in the content root (``examples/payload_example.xml`` works).
    target_list : str
        Target list CSV, resolved the same way.
    output : str
        HDF5 output (``.h5``/``.hdf5``) inside a sub-directory of the working
        directory. Empty (default) writes ``runs/<time>-<id>/output.h5``. The
        pipeline copies the payload and target list next to the output.
    n_threads : int
        Worker processes for the targets (``>= 1``); reduced to the server limit
        ``EXORAD_MCP_MAX_THREADS`` and to the number of targets.
    plot : bool
        Also write ``efficiency.png`` and one PNG per target next to the output.
    full_contrib : bool
        Add the per-element contribution columns to the channel tables.
    overwrite : bool
        Replace an existing output (and the input copies an earlier run of the
        same output left beside it). By default an existing output is refused.
        It never applies to a running job's files: an output, or an output
        directory, that a running job uses is refused (``status="refused"``).
    wait_seconds : float
        Block up to this long for the job, then return ``running``. At most 50
        seconds (client tool-call timeouts are short): poll with ``get_job_status``.
    max_runtime_seconds : float, optional
        Deadline of the job; never above the server cap ``EXORAD_MCP_MAX_RUNTIME``.
    pipeline : str
        Only ``standard`` exists.

    Returns
    -------
    dict
        The job status (``job_id``, ``status``, ``outcome``, ``output``,
        ``log_file``, ``targets_started``, ``targets_done`` ...) plus
        ``payload``, ``target_list``, ``targets`` (count), ``n_threads``,
        ``estimated_output_mb`` and ``warnings``. When the job ended within ``wait_seconds`` the result also
        has ``files`` and ``summary``. ``status="refused"`` means nothing was started:
        either too many jobs are running (``limit`` and ``running_jobs``) or a running
        job already uses this output or output directory
        (``reason="output_in_use"``, ``conflicting_job``).
        ``outcome="partial"`` means some targets failed: the output keeps the
        good ones and ``skipped_targets`` names the others.
    """
    if not isinstance(wait_seconds, int | float) or not wait_seconds >= 0:
        raise ValueError(f"wait_seconds must be >= 0, got {wait_seconds!r}")
    box = Sandbox.from_env()
    try:
        plan = pipelines.plan_run(
            payload,
            target_list,
            output,
            n_threads=n_threads,
            plot=plot,
            full_contrib=full_contrib,
            overwrite=overwrite,
            max_runtime_seconds=max_runtime_seconds,
            pipeline=pipeline,
            sandbox=box,
        )
    except jobs.OutputInUseError as exc:  # a running job owns this output
        return jobs.refusal_result(exc, pipeline)
    try:
        job_id = jobs.JOBS.submit(
            plan.spec(), log_dir=box.log_dir(), max_runtime=plan.runtime
        )
    except (jobs.JobLimitError, jobs.OutputInUseError) as exc:
        pipelines.discard_plan(plan)
        return jobs.refusal_result(exc, pipeline)
    except BaseException:
        pipelines.discard_plan(plan)
        raise
    pipelines.register_run(job_id, plan)
    wait = min(float(wait_seconds), pipelines.MAX_WAIT_SECONDS)
    status = jobs.JOBS.wait(job_id, wait) if wait > 0 else jobs.JOBS.status(job_id)
    result = pipelines.describe_job(status, box)
    result.update(
        {
            "payload": box.display_path(plan.payload_original),
            "normalised_payload": box.display_path(plan.payload),
            "target_list": box.display_path(plan.target_list),
            "targets": len(plan.target_names),
            "n_threads": plan.n_threads,
            "estimated_output_mb": plan.estimated_mb,
        }
    )
    warnings = list(result.get("warnings", []))
    for text in plan.warnings:
        if text not in warnings:
            warnings.append(text)
    result["warnings"] = warnings
    return result


def get_job_status(job_id: str) -> dict[str, Any]:
    """Report the state of a pipeline job.

    Parameters
    ----------
    job_id : str
        The id returned by ``run_pipeline``.

    Returns
    -------
    dict
        ``job_id``, ``status`` (``running``, ``succeeded``, ``failed``,
        ``cancelled``, ``timeout``), ``outcome`` (``complete``, ``partial``,
        ``failed``, ...), ``output``, ``log_file``, times, ``targets_started``
        (targets whose observation began), ``targets_done`` (targets that
        finished observing; they are written to the output at the end),
        ``reason`` and a ``log_tail`` for a job that did not succeed, with the
        server's directories, the interpreter and the home directory redacted.
        Once the job has ended: ``files`` (name, ``work:`` path and size of what
        it produced) and ``summary`` (targets written, channels). A ``partial`` job lists ``skipped_targets``. An unknown id
        returns ``status="unknown"`` with an ``error`` message.
    """
    try:
        status = jobs.JOBS.status(job_id)
    except KeyError as exc:
        return _unknown(job_id, exc)
    return pipelines.describe_job(status)


def cancel_job(job_id: str) -> dict[str, Any]:
    """Cancel a running job (its whole process group, pool workers included).

    Parameters
    ----------
    job_id : str
        The id returned by ``run_pipeline``.

    Returns
    -------
    dict
        The job status as ``get_job_status`` reports it (``status="cancelled"``,
        or the final state if the job had already ended); unknown id returns
        ``status="unknown"``. A cancelled run leaves an incomplete output file.
    """
    try:
        status = jobs.JOBS.cancel(job_id)
    except KeyError as exc:
        return _unknown(job_id, exc)
    return pipelines.describe_job(status)


def list_jobs() -> dict[str, Any]:
    """List the jobs this server has run, oldest first.

    Returns
    -------
    dict
        ``jobs``: one status dict per job (as ``get_job_status``) and ``count``.
    """
    items = [pipelines.describe_job(item) for item in jobs.JOBS.list_jobs()]
    return {"jobs": items, "count": len(items)}


def _unknown(job_id: str, exc: KeyError) -> dict[str, Any]:
    message = exc.args[0] if exc.args else f"Unknown job id: {job_id}"
    return {"status": "unknown", "job_id": job_id, "error": str(message)}


__all__ = ["cancel_job", "get_job_status", "list_jobs", "run_pipeline"]
