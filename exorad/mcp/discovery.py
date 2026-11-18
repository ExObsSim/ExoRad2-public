"""Discovery of the ExoRad pipeline and health of its imports (audit lesson 7).

ExoRad has ONE pipeline, ``standard``, which wraps :func:`exorad.standard_pipeline`.
Discovery imports it and reads its signature and docstring, so the MCP never
documents a parameter that does not exist.

An import failure must never turn into a silently empty answer: every failure is
recorded with :func:`record_discovery_error` and reported by ``capabilities``,
``list_pipelines`` and ``describe_pipeline`` together with a fix hint.
"""

from __future__ import annotations

import importlib
import inspect
import re
from typing import Any

PIPELINE_NAME = "standard"
PIPELINE_MODULE = "exorad.exorad"
PIPELINE_FUNCTION = "standard_pipeline"

# Import failures met while discovering the pipeline or checking the modules the
# server needs. A missing optional module must not vanish silently.
_DISCOVERY_ERRORS: list[dict[str, str | None]] = []

# Modules a working server needs; ``import_health`` imports each one.
HEALTH_MODULES = (
    "exorad.tasks",
    "h5py",
    "openpyxl",
    "matplotlib",
    "astropy.io.misc.hdf5",
)

_HINTS = {
    "h5py": "h5py reads and writes the output file: pip install h5py",
    "openpyxl": "openpyxl reads xlsx target lists in the library: pip install openpyxl",
    "matplotlib": "matplotlib draws the plots: pip install matplotlib",
    "astropy": "astropy provides units and table I/O: pip install astropy",
    "exorad": "reinstall the package: pip install --force-reinstall exorad",
}

# MCP argument that fills each parameter of ``standard_pipeline`` (None = not exposed).
_MCP_ARGUMENT = {
    "options": "payload",
    "target_list": "target_list",
    "output": "output",
    "plot": "plot",
    "full_contrib": "full_contrib",
    "n_thread": "n_threads",
    "replace": "overwrite",
    "debug": None,
    "log": None,
}
_NOT_EXPOSED = {
    "debug": "not exposed: the server keeps the library logging untouched",
    "log": "not exposed: logs go to the per-job log file",
}


def record_discovery_error(exc: BaseException, module: str) -> dict[str, str | None]:
    """Remember an import failure and return its structured description.

    Parameters
    ----------
    exc : BaseException
        The (typically ``ImportError``) exception that was caught.
    module : str
        The module whose import was attempted (e.g. ``exorad.exorad``).

    Returns
    -------
    dict
        ``module``, ``missing_module``, ``error`` and ``hint`` entries.
    """
    missing = getattr(exc, "name", None)
    root = (missing or "").split(".")[0]
    entry: dict[str, str | None] = {
        "module": module,
        "missing_module": missing,
        "error": f"{type(exc).__name__}: {exc}",
        "hint": _HINTS.get(root)
        or (f"Install the missing module: pip install {root}" if root else None),
    }
    if entry not in _DISCOVERY_ERRORS:
        _DISCOVERY_ERRORS.append(entry)
    return entry


def discovery_errors() -> list[dict[str, str | None]]:
    """Return the import errors recorded so far (a copy)."""
    return [dict(entry) for entry in _DISCOVERY_ERRORS]


def clear_discovery_errors() -> None:
    """Forget the recorded errors (used by tests)."""
    _DISCOVERY_ERRORS.clear()


def import_health(modules: tuple[str, ...] = HEALTH_MODULES) -> dict[str, bool]:
    """Import every module the server relies on and record the failures.

    Returns
    -------
    dict
        Module name -> ``True`` when it imported. Failures are also recorded and
        therefore appear in :func:`discovery_errors`.
    """
    health: dict[str, bool] = {}
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as exc:  # any failure to import is a health problem
            record_discovery_error(exc, name)
            health[name] = False
        else:
            health[name] = True
    return health


def _numpydoc_params(doc: str | None) -> dict[str, str]:
    """Parse the ``Parameters`` section of a numpydoc string."""
    if not doc:
        return {}
    lines = doc.splitlines()
    out: dict[str, str] = {}
    current: str | None = None
    in_section = False
    skip_underline = False
    for i, raw in enumerate(lines):
        line = raw.strip()
        if line in {"Parameters", "Attributes"}:
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            in_section = bool(nxt) and set(nxt) <= {"-"}
            skip_underline = in_section
            current = None
            continue
        if not in_section:
            continue
        if skip_underline:
            skip_underline = False
            continue
        if line and set(line) <= {"-"}:  # underline of the next section title
            in_section = False
            continue
        header = re.match(r"^(\w+)\s*:\s*\S.*$", line)
        if header:
            current = header.group(1)
            out.setdefault(current, "")
        elif current and line:
            out[current] = (out[current] + " " + line).strip()
    return out


def _fallback_definition() -> dict[str, Any]:
    """Static description used when the library cannot be imported."""
    return {
        "name": PIPELINE_NAME,
        "entry_point": f"exorad.{PIPELINE_FUNCTION}",
        "cli_command": "exorad -p payload.xml -t targets.csv -o out.h5",
        "required_inputs": ["payload", "target_list"],
        "optional_inputs": ["output", "n_threads", "plot", "full_contrib", "overwrite"],
        "output_description": (
            "One HDF5 file with the payload description, the channel tables and, "
            "per target, the signal and noise tables."
        ),
        "available": False,
    }


def _load_entry_point() -> Any | None:
    """Import ``standard_pipeline``; record the failure and return ``None``."""
    try:
        module = importlib.import_module(PIPELINE_MODULE)
    except Exception as exc:  # a broken library import must never be silent
        record_discovery_error(exc, PIPELINE_MODULE)
        return None
    function = getattr(module, PIPELINE_FUNCTION, None)
    if function is None:
        record_discovery_error(
            ImportError(
                f"{PIPELINE_MODULE} has no attribute {PIPELINE_FUNCTION!r}",
                name=PIPELINE_MODULE,
            ),
            PIPELINE_MODULE,
        )
    return function


def pipeline_definition() -> dict[str, Any]:
    """Return the ``standard`` pipeline definition.

    The definition is read from the live function. When the import fails the
    error is recorded (see :func:`discovery_errors`) and a static definition with
    ``available: false`` is returned, so the answer is never an empty list.
    """
    function = _load_entry_point()
    if function is None:
        return _fallback_definition()
    definition = _fallback_definition()
    definition["available"] = True
    params = inspect.signature(function).parameters
    definition["required_inputs"] = [
        _MCP_ARGUMENT[name]
        for name, p in params.items()
        if p.default is inspect.Parameter.empty and _MCP_ARGUMENT.get(name)
    ]
    definition["optional_inputs"] = [
        _MCP_ARGUMENT[name]
        for name, p in params.items()
        if p.default is not inspect.Parameter.empty and _MCP_ARGUMENT.get(name)
    ]
    return definition


def list_pipeline_definitions() -> list[dict[str, Any]]:
    """Return the exposed pipelines (always the single ``standard`` pipeline)."""
    return [pipeline_definition()]


def describe_pipeline_definition(pipeline: str = PIPELINE_NAME) -> dict[str, Any]:
    """Describe the pipeline and the parameters of its library function.

    Raises
    ------
    ValueError
        For an unknown pipeline name.
    ImportError
        If the library function cannot be imported (also recorded).
    """
    if pipeline.strip().lower() != PIPELINE_NAME:
        raise ValueError(
            f"Unsupported pipeline: {pipeline}. Available: {PIPELINE_NAME}"
        )
    module = importlib.import_module(PIPELINE_MODULE)
    function = getattr(module, PIPELINE_FUNCTION)
    descriptions = _numpydoc_params(inspect.getdoc(function))
    parameters = []
    for name, param in inspect.signature(function).parameters.items():
        has_default = param.default is not inspect.Parameter.empty
        mcp_arg = _MCP_ARGUMENT.get(name)
        description = descriptions.get(name, "")
        if mcp_arg is None and name in _NOT_EXPOSED:
            description = f"{description} ({_NOT_EXPOSED[name]})".strip()
        parameters.append(
            {
                "name": name,
                "type": _numpydoc_type(inspect.getdoc(function), name),
                "required": not has_default,
                "default": param.default if has_default else None,
                "description": description,
                "mcp_argument": mcp_arg,
            }
        )
    data = pipeline_definition()
    first_para = (inspect.getdoc(function) or "").split("\n\n", 1)[0]
    data["summary"] = " ".join(first_para.split())
    data["parameters"] = parameters
    return data


def _numpydoc_type(doc: str | None, name: str) -> str | None:
    """Type text of ``name`` in the numpydoc ``Parameters`` section."""
    if not doc:
        return None
    match = re.search(rf"^\s*{re.escape(name)}\s*:\s*(\S.*)$", doc, flags=re.MULTILINE)
    return match.group(1).strip() if match else None
