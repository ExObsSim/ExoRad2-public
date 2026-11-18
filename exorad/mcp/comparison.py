"""Comparison of two ExoRad payloads for the MCP (spec 3.3, tool 13).

Both files go through the same gate as ``validate_config``: the static rules on
BOTH files first (the library is not called for either while one has an error),
then the normalised copy, then ``LoadOptions`` under ``CONFIG_LOAD_LOCK`` (the loader writes
``PassVal.working_R``). A payload with error findings is never parsed and is
reported inside the result; usage errors (missing file, path outside the sandbox)
are raised.

Leaves are compared with an absolute tolerance of ``1e-9``; data tables are
compared column by column. Values that are paths are compared by file name only
(two projects that keep the same table in different directories do not differ),
the tables they load are compared by content, and ``ConfigPath`` (a location, not
a setting) is skipped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from astropy import units as u
from astropy.table import Table

from exorad.mcp import configuration, rules
from exorad.mcp.sandbox import Sandbox

__all__ = ["compare_payloads"]

TOLERANCE = 1e-9
_SKIPPED_KEYS = frozenset({"ConfigPath"})
_MAX_SHOWN = 80


def compare_payloads(
    config1: str | Path, config2: str | Path, *, sandbox: Sandbox | None = None
) -> dict[str, Any]:
    """Compare two payload XML files.

    Returns
    -------
    dict
        ``identical``, ``differences`` (``{path, left, right, summary}``),
        ``only_in_first``, ``only_in_second`` and ``valid``. When a payload cannot
        be loaded, ``valid`` is false and ``errors`` lists, per file (``first`` or
        ``second``), the findings.

    Raises
    ------
    FileNotFoundError, PathNotAllowedError, ValueError
        As for ``validate_config``.
    """
    box = sandbox or Sandbox.from_env()
    paths = [
        configuration.resolve_config_file(config, box, "payload")[0]
        for config in (config1, config2)
    ]
    loaded: list[dict[str, Any] | None] = []
    errors: list[dict[str, Any]] = []
    # Static scan of BOTH inputs first: the library is not called for either one
    # while any of them has an error (a good first file must not be parsed, and a
    # hostile second one must not be reached, by a comparison that is going to refuse).
    for label, path in zip(("first", "second"), paths, strict=True):
        found = rules.errors_of(rules.static_findings(path, sandbox=box))
        if found:
            errors.append({"config": label, "findings": [f.to_dict() for f in found]})
    for label, path in zip(("first", "second"), paths, strict=True):
        if errors:
            loaded.append(None)
            continue
        try:
            loaded.append(rules.load_payload_dict(path, sandbox=box))
        except rules.ConfigRuleError as exc:
            loaded.append(None)
            errors.append(
                {"config": label, "findings": [f.to_dict() for f in exc.findings]}
            )
        except Exception as exc:
            loaded.append(None)
            text = configuration._describe_exception(exc, box)
            errors.append(
                {
                    "config": label,
                    "findings": [
                        rules.Finding(
                            "error", "LOADER_FAILED", path.name, text
                        ).to_dict()
                    ],
                }
            )
    result: dict[str, Any] = {
        "first": box.display_path(paths[0]),
        "second": box.display_path(paths[1]),
        "valid": not errors,
        "identical": False,
        "differences": [],
        "only_in_first": [],
        "only_in_second": [],
    }
    if errors:
        result["errors"] = errors
        return result
    first, second = loaded
    if first is None or second is None:  # pragma: no cover - errors handled above
        return result
    _diff(_with_named_repeats(first), _with_named_repeats(second), "", result, box)
    result["identical"] = not (
        result["differences"] or result["only_in_first"] or result["only_in_second"]
    )
    return result


_REPEATED = ("channel", "opticalElement", "foreground", "customNoise")


def _with_named_repeats(node: Any) -> Any:
    """Give a repeated tag with ONE occurrence the same shape as with several.

    ``LoadOptions`` keys repeated tags by their text only from the second
    occurrence on; a single ``<channel>`` is stored as the channel's own dict.
    """
    if not isinstance(node, dict):
        return node
    out: dict[Any, Any] = {}
    for key, value in node.items():
        if key in _REPEATED and type(value) is dict and "value" in value:
            value = {value["value"]: value}
        out[key] = _with_named_repeats(value)
    return out


def _diff(
    left: Any,
    right: Any,
    path: str,
    out: dict[str, Any],
    box: Sandbox,
    *,
    path_node: bool = False,
) -> None:
    if isinstance(left, dict) and isinstance(right, dict):
        for key in dict.fromkeys([*left, *right]):
            if str(key) in _SKIPPED_KEYS:
                continue
            here = f"{path}.{key}" if path else str(key)
            if key not in right:
                out["only_in_first"].append(here)
            elif key not in left:
                out["only_in_second"].append(here)
            else:
                a, b = left[key], right[key]
                if (
                    path_node
                    and key == "value"
                    and isinstance(a, str)
                    and isinstance(b, str)
                ):
                    a, b = Path(a).name, Path(b).name  # same file name = same reference
                is_path = str(key) in rules.PATH_TAGS or (
                    str(key) == "data" and path.endswith("targetR")
                )
                _diff(a, b, here, out, box, path_node=is_path)
        return
    if _values_differ(left, right):
        out["differences"].append(
            {
                "path": path,
                "left": _show(left, box),
                "right": _show(right, box),
                "summary": _summarise_difference(left, right),
            }
        )


def _values_differ(left: Any, right: Any, tolerance: float = TOLERANCE) -> bool:
    """True if two parsed values differ (tolerance for numbers, columns for tables)."""
    if isinstance(left, Table) or isinstance(right, Table):
        if not (isinstance(left, Table) and isinstance(right, Table)):
            return True
        if left.colnames != right.colnames or len(left) != len(right):
            return True
        return any(
            _values_differ(np.asarray(left[c]), np.asarray(right[c]), tolerance)
            for c in left.colnames
        )
    if isinstance(left, np.ndarray) or isinstance(right, np.ndarray):
        if not (isinstance(left, np.ndarray) and isinstance(right, np.ndarray)):
            return True
        if left.shape != right.shape or getattr(left, "unit", None) != getattr(
            right, "unit", None
        ):
            return True
        try:
            return not np.allclose(
                np.asarray(left, dtype=float),
                np.asarray(right, dtype=float),
                rtol=0.0,
                atol=tolerance,
                equal_nan=True,
            )
        except (TypeError, ValueError):
            return not np.array_equal(np.asarray(left), np.asarray(right))
    if isinstance(left, u.Quantity) or isinstance(right, u.Quantity):
        if not (isinstance(left, u.Quantity) and isinstance(right, u.Quantity)):
            return True
        if left.unit != right.unit:
            return True
        return _values_differ(
            np.asarray(left.value), np.asarray(right.value), tolerance
        )
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) != set(right) or any(
            _values_differ(left[k], right[k]) for k in left
        )
    if isinstance(left, list | tuple) and isinstance(right, list | tuple):
        return len(left) != len(right) or any(
            _values_differ(a, b) for a, b in zip(left, right, strict=True)
        )
    if _is_number(left) and _is_number(right):
        return abs(float(left) - float(right)) > tolerance
    if type(left) is not type(right):
        return True
    return bool(left != right)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float | np.number) and not isinstance(value, bool)


def _show(value: Any, box: Sandbox) -> str:
    if isinstance(value, Table):
        return f"table {len(value)} rows x {len(value.colnames)} columns"
    if isinstance(value, u.Quantity):
        if value.isscalar:
            return f"{value.value:g} {value.unit}".strip()
        return f"array{value.shape} {value.unit}".strip()
    if isinstance(value, np.ndarray):
        return f"array{value.shape}"
    text = box.redact(str(value))
    return text if len(text) <= _MAX_SHOWN else text[: _MAX_SHOWN - 3] + "..."


def _summarise_difference(left: Any, right: Any) -> str:
    if isinstance(left, Table) and isinstance(right, Table):
        if left.colnames != right.colnames:
            return f"table columns differ: {left.colnames} vs {right.colnames}"
        if len(left) != len(right):
            return f"table rows differ: {len(left)} vs {len(right)}"
        changed = [
            c
            for c in left.colnames
            if _values_differ(np.asarray(left[c]), np.asarray(right[c]))
        ]
        return f"table values differ in columns {changed}"
    if isinstance(left, u.Quantity) and isinstance(right, u.Quantity):
        if left.unit != right.unit:
            return f"unit {left.unit} vs {right.unit}"
        return f"{left.value!s:.40} vs {right.value!s:.40} {left.unit}".strip()
    if type(left) is not type(right) and not (_is_number(left) and _is_number(right)):
        return f"type {type(left).__name__} vs {type(right).__name__}"
    return f"{str(left)[:50]!r} vs {str(right)[:50]!r}"
