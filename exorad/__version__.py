"""Resolve the package version.

The version is derived from git tags by setuptools-scm at build/install time
and written to the git-ignored ``exorad/_version.py``. In a bare source
checkout that file may be missing, so we fall back to the installed
distribution metadata and finally to ``"unknown"``.
"""

from importlib.metadata import (
    PackageNotFoundError,
    version as _metadata_version,
)


def _resolve_version() -> str:
    scm_version: str | None
    try:
        from exorad._version import version as scm_version
    except Exception:
        scm_version = None
    if scm_version:
        return scm_version
    try:
        return _metadata_version("exorad")
    except PackageNotFoundError:
        return "unknown"


__version__ = _resolve_version()
