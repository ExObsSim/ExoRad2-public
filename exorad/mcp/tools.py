"""Registry of the MCP tools (and nothing else).

The tool functions live in per-group modules so that several people can add
tools without touching each other's files:

========================  ======================================================
``tools_info``            capabilities, project context, knowledge base, pipelines
``tools_config``          payload / target-list requirements, drafting, validation
``tools_run``             ``run_pipeline`` and the job tools
``tools_output``          ``inspect_output``, ``explain_output``, ``plot_output``
========================  ======================================================

This module owns the :data:`REGISTRY` table, the single source of truth for which
tool lives where. Modules are imported lazily, by :func:`load_tools`, so a group
that does not exist yet (or fails to import) is **skipped and reported**, never a
crash: ``capabilities`` lists it under ``tools.unavailable`` and the server logs
it at startup. To add a tool, add one row to :data:`REGISTRY`; the function must
be a plain Python function named like the tool, with type hints and a docstring
(they become the tool schema), that returns a JSON-serialisable dict and raises
the expected exception types (see ``server._EXPECTED_ERRORS``).
"""

from __future__ import annotations

import functools
import importlib
from typing import TYPE_CHECKING, Any, NamedTuple

from exorad.mcp import discovery

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence


class ToolEntry(NamedTuple):
    """One registry row."""

    name: str  #: tool name as the client sees it
    module: str  #: dotted module that defines the function
    function: str  #: attribute of ``module`` (normally equal to ``name``)
    execution_only: bool  #: registered only when execution is enabled


_INFO = "exorad.mcp.tools_info"
_CONFIG = "exorad.mcp.tools_config"
_RUN = "exorad.mcp.tools_run"
_OUTPUT = "exorad.mcp.tools_output"
_SELF = "exorad.mcp.tools"

#: The 21 tools. ``capabilities`` is served by this module's wrapper (below) so
#: that it can report the groups that failed to load.
REGISTRY: tuple[ToolEntry, ...] = (
    ToolEntry("capabilities", _SELF, "capabilities", False),
    ToolEntry("exorad_project_context", _INFO, "exorad_project_context", False),
    ToolEntry("knowledge_base_manifest", _INFO, "knowledge_base_manifest", False),
    ToolEntry("search_knowledge_base", _INFO, "search_knowledge_base", False),
    ToolEntry("customisation_guide", _INFO, "customisation_guide", False),
    ToolEntry("list_pipelines", _INFO, "list_pipelines", False),
    ToolEntry("describe_pipeline", _INFO, "describe_pipeline", False),
    ToolEntry("list_examples", _INFO, "list_examples", False),
    ToolEntry("config_requirements", _CONFIG, "config_requirements", False),
    ToolEntry("draft_config", _CONFIG, "draft_config", False),
    ToolEntry("draft_target_list", _CONFIG, "draft_target_list", False),
    ToolEntry("validate_config", _CONFIG, "validate_config", False),
    ToolEntry("compare_configs", _CONFIG, "compare_configs", False),
    ToolEntry("run_pipeline", _RUN, "run_pipeline", True),
    ToolEntry("get_job_status", _RUN, "get_job_status", True),
    ToolEntry("cancel_job", _RUN, "cancel_job", True),
    ToolEntry("list_jobs", _RUN, "list_jobs", True),
    ToolEntry("inspect_output", _OUTPUT, "inspect_output", False),
    ToolEntry("explain_output", _OUTPUT, "explain_output", False),
    ToolEntry("plot_output", _OUTPUT, "plot_output", True),
    ToolEntry("diagnose_error", _INFO, "diagnose_error", False),
)

TOOL_NAMES = tuple(entry.name for entry in REGISTRY)


class LoadedTools(NamedTuple):
    """Result of :func:`load_tools`."""

    registered: list[tuple[str, Any]]  #: (tool name, function) to register
    unavailable: list[dict[str, str]]  #: {tool, module, reason} for each skipped tool
    disabled: list[str]  #: execution-only tools left out because exec is off


def _import(module: str, function: str) -> tuple[Any | None, str | None]:
    """Return ``(callable, None)`` or ``(None, reason)``; never raises."""
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name == module or (exc.name and module.startswith(f"{exc.name}.")):
            return None, "module not present in this build"
        discovery.record_discovery_error(exc, module)
        return None, f"import failed: {type(exc).__name__}: {exc}"
    except Exception as exc:  # a broken group must not take the server down
        discovery.record_discovery_error(exc, module)
        return None, f"import failed: {type(exc).__name__}: {exc}"
    func = getattr(mod, function, None)
    if not callable(func):
        reason = f"{module} has no function {function}"
        discovery.record_discovery_error(AttributeError(reason), module)
        return None, reason
    return func, None


def effective_registry(
    registry: Sequence[ToolEntry] | None = None, hide: Iterable[str] = ()
) -> tuple[ToolEntry, ...]:
    """Return ``registry`` (default :data:`REGISTRY`) without the ``hide`` names.

    The registry is server-side Python data (an extension passes its own tuple
    from its own code); nothing here is reachable from a client. Duplicate tool
    names and hidden names that are not in the registry are refused, so a typo
    cannot silently leave a tool exposed.

    Raises
    ------
    ValueError
        A tool name appears twice, or ``hide`` names an unknown tool.
    """
    entries = tuple(REGISTRY if registry is None else registry)
    names = [entry.name for entry in entries]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(
            f"duplicate tool names in the registry: {', '.join(duplicates)}"
        )
    hidden = set(hide)
    unknown = sorted(hidden - set(names))
    if unknown:
        raise ValueError(f"cannot hide unknown tools: {', '.join(unknown)}")
    return tuple(entry for entry in entries if entry.name not in hidden)


def load_tools(
    *,
    allow_exec: bool,
    registry: Sequence[ToolEntry] | None = None,
    hide: Iterable[str] = (),
) -> LoadedTools:
    """Import the tool modules lazily and sort the registry into three lists.

    A module that is missing or fails to import does not raise: its tools go to
    ``unavailable`` with the reason (import failures are also recorded as
    discovery errors). Execution-only tools go to ``disabled`` when
    ``allow_exec`` is false.

    Parameters
    ----------
    allow_exec : bool
        Whether execution-only tools are loaded.
    registry : sequence of ToolEntry, optional
        The table to load instead of :data:`REGISTRY`; an extension package
        passes ExoRad's entries plus its own (``ToolEntry.module`` may be any
        importable module path). Nothing global is mutated.
    hide : iterable of str, optional
        Tool names left out entirely (neither registered nor reported).
    """
    registered: list[tuple[str, Any]] = []
    unavailable: list[dict[str, str]] = []
    disabled: list[str] = []
    for entry in effective_registry(registry, hide):
        if entry.execution_only and not allow_exec:
            disabled.append(entry.name)
            continue
        func, reason = _import(entry.module, entry.function)
        if func is None:
            unavailable.append(
                {"tool": entry.name, "module": entry.module, "reason": reason or ""}
            )
        else:
            registered.append((entry.name, func))
    return LoadedTools(registered, unavailable, disabled)


def capabilities_for(
    registry: Sequence[ToolEntry] | None = None, hide: Iterable[str] = ()
) -> Callable[[], dict[str, Any]]:
    """Return a ``capabilities`` tool bound to ``registry`` / ``hide``.

    The result has the name, signature and docstring of :func:`capabilities` (so
    the tool schema is the same) and reports the tools of THAT registry.
    """
    entries = effective_registry(registry, hide)

    @functools.wraps(capabilities)
    def bound() -> dict[str, Any]:
        return _capabilities(entries)

    return bound


def capabilities() -> dict[str, Any]:
    """Describe what this MCP server can do right now.

    Call this first: it reports the ExoRad and MCP SDK versions, the sandbox
    configuration and limits, the content report (where the knowledge base comes
    from and whether it is empty), whether pipeline execution is enabled, the
    retrieval backend, the network policy and which tools are available, so the
    model does not attempt a disabled operation or guess at the environment.
    Tools whose implementation could not be loaded are listed under
    ``tools.unavailable`` with the reason, and are not in the other lists. This
    is the one place the sandbox roots are shown in full. It never raises.

    Returns
    -------
    dict
        ``versions``, ``sandbox``, ``content``, ``limits``, ``execution_enabled``,
        ``network``, ``retrieval``, ``pipelines``, ``discovery_errors`` and
        ``tools`` (``always_available``, ``execution_only``, ``disabled``,
        ``unavailable``).
    """
    return _capabilities(REGISTRY)


def _capabilities(entries: tuple[ToolEntry, ...]) -> dict[str, Any]:
    from exorad.mcp import tools_info

    info = tools_info.capabilities()
    tools = dict(info.get("tools", {}))
    try:
        allow_exec = bool(info.get("execution_enabled"))
        loaded = load_tools(allow_exec=allow_exec, registry=entries)
        missing = {item["tool"] for item in loaded.unavailable}
        unavailable = loaded.unavailable
        if entries != REGISTRY:
            # the tool lists come from the registry that is actually served
            tools["always_available"] = [
                e.name for e in entries if not e.execution_only
            ]
            tools["execution_only"] = (
                [e.name for e in entries if e.execution_only] if allow_exec else []
            )
            tools["disabled"] = loaded.disabled
    except Exception as exc:  # capabilities must never raise
        missing, unavailable = (
            set(),
            [{"tool": "*", "module": "", "reason": f"{type(exc).__name__}: {exc}"}],
        )
    for key in ("always_available", "execution_only"):
        tools[key] = [name for name in tools.get(key, []) if name not in missing]
    tools["unavailable"] = unavailable
    info["tools"] = tools
    info["discovery_errors"] = discovery.discovery_errors()
    return info


__all__ = [
    "REGISTRY",
    "TOOL_NAMES",
    "LoadedTools",
    "ToolEntry",
    "capabilities",
    "capabilities_for",
    "effective_registry",
    "load_tools",
]
