"""Information, grounding and help tools of the ExoRad MCP server.

Plain Python functions (unit tests call them directly); the server registers
them through ``_expose_errors``. Tools here never print and return
JSON-serialisable dicts. Covers spec 3.3 items 1-8 and 3.4 item 21:
``capabilities``, ``exorad_project_context``, ``knowledge_base_manifest``,
``search_knowledge_base``, ``customisation_guide``, ``list_pipelines``,
``describe_pipeline``, ``list_examples`` and ``diagnose_error``.
"""

from __future__ import annotations

import platform
import re
from importlib.metadata import (
    PackageNotFoundError,
    version as _pkg_version,
)
from typing import Any

from exorad.mcp import discovery, retrieval
from exorad.mcp.schemas import resolve_repo_path

PROJECT_CONTEXT_FILES = (
    "AGENTS.md",
    "docs/ai-agents/codebase-map.md",
    "docs/ai-agents/parameter-setup-guide.md",
    "docs/ai-agents/README.md",
)

#: Tools available whatever the execution setting is.
ALWAYS_AVAILABLE = (
    "capabilities",
    "exorad_project_context",
    "knowledge_base_manifest",
    "search_knowledge_base",
    "customisation_guide",
    "list_pipelines",
    "describe_pipeline",
    "list_examples",
    "config_requirements",
    "draft_config",
    "draft_target_list",
    "validate_config",
    "compare_configs",
    "inspect_output",
    "explain_output",
    "diagnose_error",
)
#: Tools registered only when execution is enabled (``validate_config(deep=True)``
#: is refused with ``PermissionError`` when it is not).
EXECUTION_ONLY = (
    "run_pipeline",
    "get_job_status",
    "cancel_job",
    "list_jobs",
    "plot_output",
)

_CUSTOMISATION_TERMS = (
    "custom noise custom sed foreground payload datafile optical element channel"
)
MAX_RESULTS_LIMIT = 20


def _version(package: str) -> str | None:
    try:
        return _pkg_version(package)
    except PackageNotFoundError:
        return None


def _exorad_version() -> str | None:
    found = _version("exorad")
    if found:
        return found
    try:
        from exorad.__version__ import __version__

        return str(__version__)
    except Exception:  # pragma: no cover - only without any metadata
        return None


def exorad_project_context() -> dict[str, Any]:
    """Return the curated ExoRad guidance files for AI clients.

    Returns
    -------
    dict
        ``files`` (content keyed by content-relative path), ``missing`` (the
        curated files that are absent from this content root) and
        ``capabilities``.
    """
    files: dict[str, str] = {}
    missing: list[str] = []
    for relative_path in PROJECT_CONTEXT_FILES:
        path = resolve_repo_path(relative_path)
        if path.is_file():
            files[relative_path] = path.read_text(encoding="utf-8", errors="replace")
        else:
            missing.append(relative_path)
    return {"files": files, "missing": missing, "capabilities": capabilities()}


def capabilities() -> dict[str, Any]:
    """Describe what this MCP server can do right now.

    Call this first: it reports the ExoRad and MCP SDK versions, the sandbox
    configuration and limits, the content report (where the knowledge base comes
    from and whether it is empty), whether pipeline execution is enabled, the
    retrieval backend, the network policy and which tools are available, so the
    model does not attempt a disabled operation or guess at the environment.
    This is the one place the sandbox roots are shown in full. It never raises.

    Returns
    -------
    dict
        ``versions``, ``sandbox``, ``content``, ``limits``, ``execution_enabled``,
        ``network``, ``retrieval``, ``pipelines``, ``discovery_errors`` (import
        failures with a fix hint; empty when healthy) and ``tools``.
    """
    from exorad.mcp.sandbox import Sandbox

    def _safe(call: Any, default: Any) -> Any:
        try:
            return call()
        except Exception as exc:  # capabilities must never raise
            return default(exc) if callable(default) else default

    sandbox = _safe(Sandbox.from_env, None)
    sandbox_dict = (
        _safe(sandbox.to_dict, lambda e: {"error": f"{type(e).__name__}: {e}"})
        if sandbox is not None
        else {"error": "sandbox could not be built from the environment"}
    )
    allow_exec = bool(getattr(sandbox, "allow_exec", False))
    discovery.import_health()
    pipelines = _safe(
        lambda: [d["name"] for d in discovery.list_pipeline_definitions()],
        [discovery.PIPELINE_NAME],
    )
    limits = {
        name: getattr(sandbox, attr, None)
        for name, attr in (
            ("max_threads", "max_threads"),
            ("max_runtime_seconds", "max_runtime"),
            ("max_jobs", "max_jobs"),
            ("max_targets", "max_targets"),
            ("max_output_mb", "max_output_mb"),
            ("max_bins", "max_bins"),
            ("max_data_mb", "max_data_mb"),
        )
    }
    return {
        "versions": {
            "exorad": _exorad_version(),
            "mcp_sdk": _version("mcp"),
            "sentence_transformers": _version("sentence-transformers"),
            "astropy": _version("astropy"),
            "h5py": _version("h5py"),
            "python": platform.python_version(),
        },
        "sandbox": sandbox_dict,
        "content": sandbox_dict.get("content")
        if isinstance(sandbox_dict, dict)
        else None,
        "limits": limits,
        "execution_enabled": allow_exec,
        "network": {
            "enabled": False,
            "sed_download": "blocked",
            "version_check": "off",
        },
        "transport_authentication": (
            "none: the stdio transport is private to the client; http and sse "
            "bind to loopback by default and have no authentication"
        ),
        "retrieval": {
            "backend": _safe(retrieval.active_backend, "bm25"),
            "embeddings_extra_installed": _version("sentence-transformers") is not None,
        },
        "pipelines": pipelines,
        "discovery_errors": discovery.discovery_errors(),
        "tools": {
            "always_available": list(ALWAYS_AVAILABLE),
            "execution_only": list(EXECUTION_ONLY) if allow_exec else [],
            "disabled": [] if allow_exec else list(EXECUTION_ONLY),
        },
    }


def search_knowledge_base(
    query: str,
    max_results: int = 5,
    max_chars: int = 0,
) -> dict[str, Any]:
    """Retrieve grounded passages for ExoRad questions.

    Parameters
    ----------
    query : str
        Natural-language query.
    max_results : int
        Maximum number of passages to return (clamped to 1..20).
    max_chars : int
        Total character budget for the returned passage text (0 = no limit).
        The budget is split evenly across the passages (at least 200 characters
        each); any passage cut short is marked ``truncated`` and keeps its
        ``path`` and line range so the full text can be fetched via the
        ``exorad://kb/<path>`` resource. Use this for clients with small
        context windows.

    Returns
    -------
    dict
        ``status`` (``ok`` or ``insufficient_evidence``), ``grounded``, ``query``,
        ``sources``, ``minimum_retrieval_score`` and ``truncated``.

    Raises
    ------
    ValueError
        If the query is empty.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    max_results = max(1, min(int(max_results), MAX_RESULTS_LIMIT))
    sources = retrieval.search_knowledge_sources(query, max_results=max_results)
    threshold = retrieval.MINIMUM_RETRIEVAL_SCORE
    if not sources:
        return {
            "status": "insufficient_evidence",
            "grounded": False,
            "query": query,
            "sources": [],
            "minimum_retrieval_score": threshold,
            "truncated": False,
            "message": (
                "No ExoRad source passage matched the query. Do not answer from "
                "general knowledge; tell the user the knowledge base has no "
                "evidence for this."
            ),
        }
    payload = [source.to_dict() for source in sources]
    truncated = False
    if max_chars and max_chars > 0:
        per_source = max(200, max_chars // len(payload))
        for item in payload:
            text = item["text"]
            if len(text) > per_source:
                item["text"] = text[:per_source].rstrip() + " ..."
                item["truncated"] = True
                item["full_text_chars"] = len(text)
                truncated = True
    return {
        "status": "ok",
        "grounded": True,
        "query": query,
        "sources": payload,
        "minimum_retrieval_score": threshold,
        "truncated": truncated,
    }


def knowledge_base_manifest() -> dict[str, Any]:
    """Return approved retrieval sources and grounding policy metadata.

    Returns
    -------
    dict
        Source patterns, matched files, retrieval backend and grounding policy.
    """
    return retrieval.knowledge_base_manifest()


knowledge_base_manifest_tool = knowledge_base_manifest


def customisation_guide(topic: str) -> dict[str, Any]:
    """Retrieve guidance for customising a payload (noise, SED, foregrounds, optics).

    Parameters
    ----------
    topic : str
        Customisation topic, e.g. ``"add a custom noise source"``.

    Returns
    -------
    dict
        The result of :func:`search_knowledge_base` for the topic.
    """
    return search_knowledge_base(f"{topic} {_CUSTOMISATION_TERMS}", max_results=5)


def list_pipelines() -> dict[str, Any]:
    """List the pipelines exposed through the MCP layer (just ``standard``).

    Returns
    -------
    dict
        ``pipelines`` and ``discovery_errors``: import failures met while
        discovering the pipeline (empty when healthy). When it is not empty the
        definition is a static fallback (``available: false``) and runs can fail.
    """
    discovery.import_health()
    return {
        "pipelines": discovery.list_pipeline_definitions(),
        "discovery_errors": discovery.discovery_errors(),
    }


def describe_pipeline(pipeline: str = "standard") -> dict[str, Any]:
    """Describe one pipeline and the parameters of ``exorad.standard_pipeline``.

    Parameters
    ----------
    pipeline : str
        Pipeline name from ``list_pipelines`` (only ``standard``).

    Returns
    -------
    dict
        The definition plus a ``parameters`` list (``name``, ``type``,
        ``required``, ``default``, ``description``, ``mcp_argument``). An unknown
        name or an import failure is returned as ``error`` (the latter with
        ``missing_module`` and ``hint``).
    """
    try:
        return discovery.describe_pipeline_definition(pipeline)
    except ValueError as exc:
        return {"error": str(exc), "pipeline": pipeline}
    except ImportError as exc:
        entry = discovery.record_discovery_error(exc, discovery.PIPELINE_MODULE)
        return {
            "error": f"Cannot import the pipeline '{pipeline}': {exc}",
            "pipeline": pipeline,
            "missing_module": entry["missing_module"],
            "hint": entry["hint"],
        }


def list_examples() -> dict[str, Any]:
    """List the bundled example inputs (payload XML, target list, data tables).

    Use it to pick a real starting point instead of inventing a file. Each entry
    says whether it is ``runnable`` as it is, whether it is ``packaged`` in the
    wheel, which files it ``references`` and which of those it ``needs`` but are
    missing.

    Returns
    -------
    dict
        ``examples`` (list) and ``count``.
    """
    from exorad.mcp.examples import list_example_configs

    return list_example_configs()


# ---------------------------------------------------------------------------
# diagnose_error
# ---------------------------------------------------------------------------
def _parse_traceback(text: str) -> dict[str, str]:
    """Pull the exception type/message and the last frame out of a traceback."""
    lines = [line for line in text.splitlines() if line.strip()]
    info: dict[str, str] = {}
    for line in reversed(lines):
        m = re.match(r"^([A-Za-z_][\w.]*(?:Error|Exception|Warning)):\s*(.*)$", line)
        if m:
            info["exception_type"] = m.group(1)
            info["exception_message"] = m.group(2).strip()
            break
    for line in reversed(lines):
        m = re.match(r'^\s*File "(.+?)", line (\d+), in (.+)$', line)
        if m:
            info["last_frame"] = f"{m.group(1)}:{m.group(2)} in {m.group(3)}"
            break
    return info


# (category, regex over the lower-cased message + traceback, suggestions, KB query).
# Matched in this order: the first hit wins (spec 3.4).
_CATEGORIES: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    (
        "network_blocked",
        r"network access is disabled|networkblockederror|source_sed_blocked"
        r"|sourcespectrum 'sed'|downloads from the network",
        (
            "The MCP never uses the network: sourceSpectrum 'sed' (the SED "
            "downloader) is disabled.",
            "Use planck (black body), phoenix (a local model directory) or custom "
            "(a local ECSV table with Wavelength and Sed columns).",
        ),
        "sourceSpectrum planck phoenix custom CustomSed StellarModels",
    ),
    (
        "pickle_refused",
        r"pickle",
        (
            "Pickle files can run arbitrary code and are always refused, even when "
            "execution is enabled.",
            "Point datadict at an .h5 file, or put the values in the XML or a "
            "datafile table (config_dict is not accepted).",
        ),
        "datadict config_dict datafile payload",
    ),
    (
        "skipped_target",
        r"target .* skipped|target information incomplete|targets skipped"
        r"|'nonetype' object has no attribute 'write'",
        (
            "A target was skipped and the run kept only the targets before it.",
            "Every star needs name, M [M_sun], Teff [K], R [R_sun] and D [pc] with "
            "units in the header brackets; run validate_config on the target list.",
            "Check the job log for the 'target <name> skipped' line and the "
            "exception that follows it.",
        ),
        "target list columns units star name M Teff R D",
    ),
    (
        "configpath",
        r"replace\(\) argument 2 must be str, not none|cannot read input file"
        r"|configpath_order",
        (
            "A value uses __ConfigPath__ before <ConfigPath> was read, or a file "
            "named by it cannot be opened.",
            "Put <ConfigPath> first in the payload and make it an absolute path "
            "(draft_config pins it for you).",
            "Run validate_config: referenced_files lists every path and whether "
            "it exists.",
        ),
        "ConfigPath __ConfigPath__ payload relative path",
    ),
    (
        "missing_file",
        # "file signature not found" is a truncated HDF5 file (output_exists)
        r"filenotfound|no such file|file_missing|(?<!signature) not found",
        (
            "Check that every file path in the payload and the target list exists "
            "and lies inside the allowed directories.",
            "Relative paths are looked up in the working directory first, then the "
            "content root; use list_examples for the shipped files.",
            "Run validate_config on the payload: referenced_files shows the "
            "resolved paths.",
        ),
        "payload datafile path FileNotFoundError ConfigPath",
    ),
    (
        "missing_element",
        r"keyerror|missing_element|window_size_px|unboundlocalerror",
        (
            "A required payload element is missing (for example ForceChannelWlEdge, "
            "Atel, read_noise, or a photometer aperture radius or EnE).",
            "Call config_requirements(kind='payload', configuration=<file>) to see "
            "what is missing, and compare with examples/payload_example.xml.",
        ),
        "payload required elements channel detector optics Atel ForceChannelWlEdge",
    ),
    (
        "unit",
        r"is not a valid unit|unitconversionerror|unitserror|unit_invalid"
        r"|target_unit_missing|did not parse as unit",
        (
            "A value or column has a missing or wrong unit.",
            "Use astropy unit names in the unit attribute (micron, K, hr, ...) and "
            "write target columns as 'star M [M_sun]'.",
        ),
        "units unit attribute astropy payload target list header",
    ),
    (
        "phoenix_path",
        r"no phoenix path|phoenix path does not exist|no stellar sed files",
        (
            "sourceSpectrum is phoenix but no model directory was found.",
            "Set <StellarModels> under <sourceSpectrum> or the PHOENIX_PATH "
            "environment variable of the server; the directory must hold "
            "*.BT-Settl.spec.fits.gz files.",
            "Otherwise use planck or custom.",
        ),
        "phoenix StellarModels PHOENIX_PATH sourceSpectrum",
    ),
    (
        "memory",
        r"memoryerror|out of memory|cannot allocate|exceeded the size limit",
        (
            "Lower common/working_R (it sets the size of every table and of the "
            "output) or the spectrometer targetR.",
            "Split the target list or reduce n_threads; every worker holds a copy "
            "of the payload.",
            "The server caps the output size (EXORAD_MCP_MAX_OUTPUT_MB).",
        ),
        "working_R targetR performance memory target list threads",
    ),
    (
        "output_exists",
        r"already exists|name already exists|unable to synchronously create"
        r"|fileexistserror|file signature not found",
        (
            "The output file already exists, or an interrupted run left a "
            "truncated HDF5 file.",
            "Pass overwrite=True to run_pipeline, or choose another output name; "
            "delete a truncated file and run again.",
        ),
        "output HDF5 file overwritten replace troubleshooting",
    ),
    (
        "dependency",
        r"importerror|modulenotfound|no module named",
        (
            "Install the missing package: pip install 'exorad[mcp]' (or the "
            "module named in the message).",
            "ExoRad needs Python 3.12 or newer.",
        ),
        "installation dependencies troubleshooting ModuleNotFoundError",
    ),
)

_GENERAL_SUGGESTIONS = (
    "Read the last lines of the job log (get_job_status) for the first exception.",
    "Run validate_config on the payload and on the target list.",
    "Search the knowledge base with the exact error text.",
)


def diagnose_error(
    error_message: str,
    context: str = "",
    traceback_text: str = "",
) -> dict[str, Any]:
    """Diagnose an ExoRad error and suggest fixes.

    Parameters
    ----------
    error_message : str
        The error message or exception line.
    context : str, optional
        Additional context (which payload, which step).
    traceback_text : str, optional
        The full Python traceback or the tail of the job log. The exception type
        and the failing frame are extracted from it.

    Returns
    -------
    dict
        ``error_type``, a ``category`` (``network_blocked``, ``pickle_refused``,
        ``skipped_target``, ``configpath``, ``missing_file``, ``missing_element``,
        ``unit``, ``phoenix_path``, ``memory``, ``output_exists``, ``dependency``
        or ``general``), concrete ``suggestions`` and ``related_docs``.
    """
    diagnosis: dict[str, Any] = {
        "error_message": error_message,
        "context": context,
        "error_type": None,
        "category": "general",
        "suggestions": list(_GENERAL_SUGGESTIONS),
        "related_docs": [],
    }
    parsed = _parse_traceback(traceback_text) if traceback_text else {}
    diagnosis.update(parsed)
    diagnosis["error_type"] = parsed.get("exception_type")

    haystack = f"{error_message} {traceback_text}".lower()
    kb_query = "troubleshooting error"
    for category, pattern, suggestions, query in _CATEGORIES:
        if re.search(pattern, haystack):
            diagnosis["category"] = category
            diagnosis["suggestions"] = list(suggestions)
            kb_query = query
            break

    try:
        found = search_knowledge_base(f"{kb_query} {context}".strip(), max_results=3)
    except ValueError:  # pragma: no cover - the query is never empty
        found = {"status": "insufficient_evidence", "sources": []}
    if found["status"] == "ok":
        diagnosis["related_docs"] = [
            {"path": s["path"], "score": s["score"]} for s in found["sources"]
        ]
    return diagnosis
