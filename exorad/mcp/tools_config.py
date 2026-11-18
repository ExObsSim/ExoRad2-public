"""Configuration tools of the ExoRad MCP server (spec 3.3, tools 9-13).

Plain Python functions (unit tests call them directly); the server registers them
through ``_expose_errors``. They never print and return JSON-serialisable dicts.
An invalid payload or target list is RETURNED (``valid: false`` with findings);
usage errors (a path outside the sandbox, a missing file, a refused override, an
existing draft) are RAISED as ``ValueError``, ``OSError`` subclasses or
``ContentMissingError``.

The ``configuration`` and ``payload`` arguments are paths: relative ones are
looked up in the working directory first (so a draft is found by its returned
name), then in the content root (``examples/...``).
"""

from __future__ import annotations

from typing import Any

from exorad.mcp import (
    authoring,
    comparison,
    configuration as configuration_module,
)


def config_requirements(
    kind: str = "payload", configuration: str | None = None
) -> dict[str, Any]:
    """List what an ExoRad payload XML or target-list CSV needs.

    ``kind="payload"`` returns the table of payload elements (``path``,
    ``required`` as ``build`` / ``observe`` / ``optional``, ``unit``, ``values``,
    ``default``, ``note``, ``see`` = the best documentation page) derived from
    what the library really requires, e.g. ``optics/ForceChannelWlEdge`` is
    required although the example comment says it may be commented out.
    ``kind="target_list"`` returns the CSV columns (``star name``, ``star M
    [M_sun]``, ``star Teff [K]``, ``star R [R_sun]``, ``star D [pc]``, ...).
    Give ``configuration`` (a payload XML or target CSV) to also get ``present``,
    ``missing``, ``extra`` and ``findings`` for that file. Start from
    ``examples/payload_example.xml`` and ``examples/test_target.csv``.

    Args:
        kind: ``payload`` or ``target_list``.
        configuration: Optional file to compare with the table.
    """
    return configuration_module.config_requirements_report(kind, configuration)


def draft_config(
    overrides: dict[str, str] | None = None,
    overwrite: bool = False,
    name: str = "payload",
) -> dict[str, Any]:
    """Draft an ExoRad payload XML from the shipped example and validate it.

    Starts from ``examples/payload_example.xml`` (``<ConfigPath>`` pinned to the
    content root), applies ``overrides`` (dotted paths such as
    ``"common.wl_min": "0.5 micron"`` or ``"channel.Spec.detector.read_noise":
    "20"``; repeated tags such as channels and optical elements are named by the
    next segment), writes ``drafts/<name>_draft.xml`` in the working directory
    and validates it. The returned ``draft`` path can be given to
    ``validate_config`` and ``run_pipeline`` as it is. Existing elements can be
    changed; new ones cannot be added (see ``not_applied`` and ``available``).
    XML comments of the example are not kept.

    Never overwrites a draft unless ``overwrite=True``. Refuses (and writes
    nothing): paths outside the allowed directories, URLs, pickle or Python files,
    ``sourceSpectrum`` ``sed`` (network download), and values beyond the limits
    (``working_R`` above 30000, too many spectral bins).

    Args:
        overrides: ``{"section.key": "value [unit]"}`` changes to apply.
        overwrite: Replace an existing draft of the same name.
        name: Draft name, letters, digits, ``_`` and ``-`` (1-40 characters).
    """
    return authoring.draft_payload(overrides, overwrite, name)


def draft_target_list(
    targets: list[dict[str, Any]],
    overwrite: bool = False,
    name: str = "targets",
) -> dict[str, Any]:
    """Write a target-list CSV from star parameters and validate it.

    Each target is a dict with ``name``, ``M`` (solar masses), ``Teff`` (K), ``R``
    (solar radii), ``D`` (parsec) and optionally ``magk`` (K magnitude), ``ra``
    and ``dec`` (degrees; ``ra`` needs ``dec``; optional keys must be given for
    every target or for none). Target names are letters, digits, spaces and
    ``_ . + - ( )`` (no ``/``, no leading dot), unique, at most 64 characters.
    Writes ``drafts/<name>.csv`` in the working directory; never overwrites
    unless ``overwrite=True``. The pipeline observes stars only.

    Args:
        targets: List of star dictionaries.
        overwrite: Replace an existing file of the same name.
        name: File name stem, letters, digits, ``_`` and ``-`` (1-40 characters).
    """
    return authoring.draft_targets(targets, overwrite, name)


def validate_config(
    configuration: str, kind: str = "auto", deep: bool = False
) -> dict[str, Any]:
    """Validate an ExoRad payload XML or a target-list CSV.

    Checks, without running the pipeline: size, XML structure (DOCTYPE refused),
    required elements, units, limits, that every referenced table exists, is a
    regular file and lies in an allowed directory (URLs, pickle files and
    ``sourceSpectrum`` ``sed`` are refused), then lets ExoRad parse the file. The
    payload is checked through a normalised copy with absolute paths, the same
    one a run uses, so a relative ``<ConfigPath>`` is resolved against the
    payload's own directory (``.`` is the content root for the shipped
    ``examples/``). Findings carry ``severity``, ``code``, ``path`` and
    ``message``; ``valid`` is false when any is an error. ``deep=True`` also
    builds the channels in a child process (needs execution enabled) and returns
    ``channels`` with bin counts.

    Args:
        configuration: Payload ``.xml`` or target list ``.csv``; relative paths
            are tried in the working directory first.
        kind: ``auto`` (by suffix), ``payload`` or ``target_list``.
        deep: Also build the channels.
    """
    return configuration_module.validate_configuration_file(configuration, kind, deep)


def compare_configs(config1: str, config2: str) -> dict[str, Any]:
    """Compare two ExoRad payload XML files.

    Both payloads are validated and parsed like ``validate_config`` does. Returns
    ``identical``, ``differences`` (each ``path`` with ``left``, ``right`` and a
    ``summary``), ``only_in_first`` and ``only_in_second``. Numbers are compared
    with an absolute tolerance of 1e-9, data tables column by column, referenced
    files by name. A payload that cannot be loaded is reported under ``errors``
    with ``valid: false``.

    Args:
        config1: First payload ``.xml``.
        config2: Second payload ``.xml``.
    """
    return comparison.compare_payloads(config1, config2)
