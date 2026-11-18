"""Payload and target-list validation for the ExoRad MCP (spec 3.3, tools 9 and 12).

``validate_configuration_file`` is the engine behind ``validate_config``:

1. resolve the path (work dir first, then the content root) and detect the kind;
2. payload: static rules (:mod:`exorad.mcp.rules`) on the file, then a NORMALISED
   COPY with absolute paths; only when no error was found, ``LoadOptions`` parses
   that copy under :data:`CONFIG_LOAD_LOCK`; with ``deep`` a child process builds
   the channels from the same copy (``JobManager.run_sync``);
3. target list: the CSV rules of :mod:`exorad.mcp.targets`, then ``LoadTargetList``.

Invalid input is RETURNED (``valid: false`` plus findings); a bad argument (path
outside the sandbox, missing file, wrong suffix) is RAISED.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

from astropy import units as u

from exorad.mcp import jobs, rules, targets
from exorad.mcp.rules import (
    CONFIG_LOAD_LOCK,
    ERROR,
    Finding,
    errors_of,
)
from exorad.mcp.sandbox import Sandbox

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "BUILD_CHECK_ENTRY",
    "CONFIG_LOAD_LOCK",
    "build_payload_check",
    "config_requirements_report",
    "detect_kind",
    "resolve_config_file",
    "validate_configuration_file",
]

BUILD_CHECK_ENTRY = "exorad.mcp.configuration:build_payload_check"
KINDS = ("payload", "target_list")
REFERENCE_EXAMPLES = {
    "payload": "examples/payload_example.xml",
    "target_list": "examples/test_target.csv",
}


def resolve_config_file(
    configuration: str | Path, sandbox: Sandbox, kind: str = "auto"
) -> tuple[Path, str]:
    """Resolve a payload / target-list argument (work dir first).

    Returns ``(path, detected kind)``. The suffix is checked before existence, so
    an ``.xlsx`` is refused as a format, not reported as missing.
    """
    path = sandbox.resolve_read(configuration, prefer_work_dir=True)
    detected = detect_kind(path, kind)
    if not path.exists():
        raise FileNotFoundError(f"file not found: {sandbox.display_path(path)}")
    return path, detected


def detect_kind(path: Path, kind: str = "auto") -> str:
    """``payload`` (``.xml``) or ``target_list`` (``.csv``); validate an explicit ``kind``."""
    if kind not in {"auto", *KINDS}:
        raise ValueError(
            f"kind must be one of 'auto', 'payload', 'target_list', got {kind!r}"
        )
    suffix = path.suffix.lower()
    detected = {".xml": "payload", ".csv": "target_list"}.get(suffix)
    if detected is None:
        raise ValueError(
            f"cannot tell what '{path.name}' is: a payload is an .xml file and a target "
            "list is a .csv file (.xlsx and other formats are not accepted)"
        )
    if kind != "auto" and kind != detected:
        article = (
            "a payload (.xml)" if detected == "payload" else "a target list (.csv)"
        )
        raise ValueError(
            f"kind '{kind}' does not match '{path.name}': it is {article}, "
            "and a payload must be an .xml file, a target list a .csv file"
        )
    return detected


def _finding_dicts(findings: list[Finding]) -> list[dict[str, str]]:
    ordered = sorted(
        findings, key=lambda f: f.severity != ERROR
    )  # stable: errors first
    return [f.to_dict() for f in ordered]


def _describe_exception(exc: BaseException, sandbox: Sandbox) -> str:
    text = str(exc).strip() or "no message (see the server log)"
    return sandbox.redact(f"{type(exc).__name__}: {text}")


def validate_configuration_file(
    configuration: str | Path,
    kind: str = "auto",
    deep: bool = False,
    *,
    sandbox: Sandbox | None = None,
) -> dict[str, Any]:
    """Validate a payload XML or a target-list CSV and summarise it.

    Parameters
    ----------
    configuration : str or pathlib.Path
        File to check; relative paths are tried in the work dir first.
    kind : {"auto", "payload", "target_list"}
        ``auto`` decides by suffix.
    deep : bool
        Also build the channels in a child process (needs execution enabled).
    sandbox : Sandbox, optional
        Defaults to ``Sandbox.from_env()``.

    Returns
    -------
    dict
        ``valid``, ``kind``, ``configuration`` (display path), ``findings``
        (errors first), and for payloads ``referenced_files``, ``summary`` and,
        with ``deep``, ``channels``. The normalised copy is a scratch file removed
        before the call returns, so it is not offered.

    Raises
    ------
    FileNotFoundError
        The file does not exist.
    PathNotAllowedError
        The path is outside the sandbox (or a URL).
    PermissionError
        ``deep`` while execution is disabled.
    ValueError
        Unknown kind or suffix.
    TimeoutError
        The deep build exceeded ``EXORAD_MCP_VALIDATE_TIMEOUT``.
    """
    box = sandbox or Sandbox.from_env()
    if kind not in {"auto", *KINDS}:
        raise ValueError(
            f"kind must be one of 'auto', 'payload', 'target_list', got {kind!r}"
        )
    if deep and not box.allow_exec:
        raise PermissionError(
            "deep validation builds the channels in a child process and needs execution, "
            "which is disabled on this server (EXORAD_MCP_NO_EXEC / --no-exec); "
            "use deep=False for the static rules and the XML parse"
        )
    path, detected = resolve_config_file(configuration, box, kind)
    if detected == "target_list":
        return _validate_target_list(path, box)
    return _validate_payload(path, box, deep=deep)


def _validate_payload(path: Path, sandbox: Sandbox, *, deep: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": "payload",
        "configuration": sandbox.display_path(path),
    }
    with rules.scratch_dir(sandbox, "exorad-mcp-validate-") as scratch:
        norm = rules.normalise_payload(path, sandbox=sandbox, dest_dir=scratch)
        findings = list(norm.findings)
        summary: dict[str, Any] = {
            key: value for key, value in norm.info.items() if value is not None
        }
        channels: list[dict[str, Any]] | None = None
        busy: str | None = None
        # a second look right before the library opens the copy and what it names
        # (a file swapped for a link or a pipe since the first scan is refused)
        changed = (
            rules.errors_of(rules.recheck_payload(norm.path, sandbox))
            if norm.path
            else []
        )
        findings.extend(changed)
        if norm.path is not None and not changed:
            try:
                options = rules.load_options(norm.path)
            except Exception as exc:  # the library's own verdict on a payload we accept
                findings.append(
                    Finding(
                        ERROR,
                        "LOADER_FAILED",
                        path.name,
                        _describe_exception(exc, sandbox),
                    )
                )
            else:
                summary["top_level_sections"] = list(options)
                summary["structure"] = _summarise(options)
                if deep:
                    try:
                        channels = _deep_build(norm.path, sandbox, findings)
                    except jobs.SyncLimitError as exc:
                        busy = str(exc)
    if busy is not None and not errors_of(findings):
        # the static checks found nothing, the deep build could not run: say so
        # without calling the payload invalid
        result["valid"] = None
        result["status"] = "busy"
        result["message"] = (
            "the deep build could not run because every validation / plot child "
            "is busy; the payload was NOT found invalid (the static checks "
            "passed). Retry validate_config(deep=True) in a moment. " + busy
        )
    else:
        result["valid"] = not errors_of(findings)
    result["findings"] = _finding_dicts(findings)
    result["referenced_files"] = norm.references
    result["summary"] = summary
    if channels is not None:
        result["channels"] = channels
    return result


def _deep_build(
    payload: Path, sandbox: Sandbox, findings: list[Finding]
) -> list[dict[str, Any]] | None:
    """Build the channels from the normalised copy in a one-shot child."""
    try:
        outcome = jobs.JOBS.run_sync(
            BUILD_CHECK_ENTRY,
            {"payload": str(payload), "sandbox": sandbox.to_spec()},
            timeout=sandbox.validate_timeout,
            slot_wait=jobs.SYNC_SLOT_WAIT_SECONDS,
        )
    except jobs.SyncLimitError:
        # not a verdict on the payload: every one-shot child is busy
        raise
    except (
        RuntimeError
    ) as exc:  # the child itself failed (its log tail is in the message)
        findings.append(
            Finding(ERROR, "DEEP_BUILD_FAILED", "channel", sandbox.redact(str(exc)))
        )
        return None
    if not outcome.get("ok"):
        findings.append(
            Finding(
                ERROR,
                "DEEP_BUILD_FAILED",
                "channel",
                sandbox.redact(f"building the channels failed: {outcome.get('error')}"),
            )
        )
        return None
    return list(outcome.get("channels", []))


def build_payload_check(spec: dict[str, Any]) -> dict[str, Any]:
    """Child entry of ``validate_config(deep=True)``: ``PreparePayload(output=None)``.

    ``spec["payload"]`` is the normalised copy. Returns ``{"ok": True, "channels":
    [{name, class, n_bins, wl_min_um, wl_max_um}]}`` or ``{"ok": False, "error"}``
    when the build raises. Runs under :data:`CONFIG_LOAD_LOCK` (inline backend) and
    restores ``PassVal.working_R``.
    """
    from exorad.tasks import PreparePayload
    from exorad.utils.passVal import PassVal

    if "sandbox" in spec:  # the copy and its files may have changed since the scan
        changed = rules.errors_of(
            rules.recheck_payload(
                str(spec["payload"]), Sandbox.from_spec(spec["sandbox"])
            )
        )
        if changed:
            return {
                "ok": False,
                "error": "; ".join(f"{f.code} {f.path}: {f.message}" for f in changed),
            }

    with CONFIG_LOAD_LOCK:
        saved = PassVal.working_R
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                _payload, built, _range = PreparePayload()(
                    payload_file=str(spec["payload"]), output=None
                )
        except Exception as exc:  # any build error is the answer
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        finally:
            PassVal.working_R = saved
    channels = []
    for name, channel in built.items():
        table = channel.table
        channels.append(
            {
                "name": str(name),
                "class": type(channel).__name__.lower(),
                "n_bins": len(table),
                "wl_min_um": float(table["LeftBinEdge"].min().to(u.um).value),
                "wl_max_um": float(table["RightBinEdge"].max().to(u.um).value),
            }
        )
    return {"ok": True, "channels": channels}


def _validate_target_list(path: Path, sandbox: Sandbox) -> dict[str, Any]:
    report = targets.validate_target_list(path, sandbox=sandbox)
    findings = list(report.findings)
    if not errors_of(findings):
        findings.extend(_library_load(path, sandbox))
    return {
        "kind": "target_list",
        "configuration": sandbox.display_path(path),
        "valid": not errors_of(findings),
        "findings": _finding_dicts(findings),
        "summary": {
            "targets": report.rows,
            "names": report.names[:50],
            "columns": report.columns,
        },
    }


def _library_load(path: Path, sandbox: Sandbox) -> list[Finding]:
    """Let ``LoadTargetList`` read a list that passed the static rules."""
    from exorad.tasks import LoadTargetList

    try:
        LoadTargetList()(target_list=str(path))
    except Exception as exc:
        return [
            Finding(
                ERROR, "LOADER_FAILED", path.name, _describe_exception(exc, sandbox)
            )
        ]
    return []


# --------------------------------------------------------------------------------
# config_requirements
# --------------------------------------------------------------------------------
def _doc_for(term: str, kind: str, sandbox: Sandbox) -> str | None:
    """Best user-facing documentation page for a table row (``see``)."""
    from exorad.mcp.retrieval import search_knowledge_sources

    hits = search_knowledge_sources(
        f"{term} {kind.replace('_', ' ')}", repo_root=sandbox.repo_root, max_results=5
    )
    for hit in hits:
        if hit.path.startswith("docs/source/"):
            return hit.path
    return hits[0].path if hits else None


def _leaf(row_path: str) -> str:
    last = row_path.split("/")[-1].split("|")[0]
    return last.replace("star ", "").split(" [")[0]


def config_requirements_report(
    kind: str = "payload",
    configuration: str | Path | None = None,
    *,
    sandbox: Sandbox | None = None,
) -> dict[str, Any]:
    """What a payload or target list needs; optionally compared with a file.

    Returns ``kind``, ``reference`` (rows ``{path, required, unit, values,
    default, note, see}``), ``reference_example`` and, with ``configuration``,
    ``present``, ``missing``, ``extra`` and ``findings`` (as ``validate_config``).
    ``extra`` never lists the framework keys (``ConfigPath``, ``fileName``,
    ``comment``, ``unit``, ``value``).

    Raises
    ------
    ValueError
        Unknown ``kind``.
    """
    box = sandbox or Sandbox.from_env()
    if kind not in KINDS:
        raise ValueError(f"kind must be 'payload' or 'target_list', got {kind!r}")
    rows = (
        rules.payload_requirements()
        if kind == "payload"
        else targets.target_requirements()
    )
    cache: dict[str, str | None] = {}
    for row in rows:
        term = _leaf(row["path"])
        if term not in cache:
            cache[term] = _doc_for(term, kind, box)
        row["see"] = cache[term]
    result: dict[str, Any] = {
        "kind": kind,
        "reference_example": REFERENCE_EXAMPLES[kind],
        "reference": rows,
    }
    if configuration is not None:
        path, _ = resolve_config_file(configuration, box, kind)
        described = (
            rules.describe_payload(path, sandbox=box)
            if kind == "payload"
            else targets.describe_target_list(path, sandbox=box)
        )
        result["present"] = described["present"]
        result["missing"] = described["missing"]
        result["extra"] = described["extra"]
        result["findings"] = _finding_dicts(described["findings"])
    return result


def _summarise(value: Any, *, depth: int = 0, max_depth: int = 3) -> Any:
    """Compact structure of a parsed payload (types and units, not values)."""
    if depth >= max_depth:
        return type(value).__name__
    if isinstance(value, dict):
        return {
            str(key): _summarise(child, depth=depth + 1, max_depth=max_depth)
            for key, child in value.items()
        }
    if isinstance(value, u.Quantity):
        return {
            "type": "Quantity",
            "unit": str(value.unit),
            "shape": getattr(value.value, "shape", None),
        }
    return type(value).__name__
