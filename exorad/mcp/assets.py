"""Content root of the ExoRad MCP server: knowledge base, examples, reference configs.

The server answers from documentation, example payloads and a few source files.
In a source checkout these are simply the repository files; in a
``pip install exorad[mcp]`` they are shipped *inside the wheel* under
``exorad/mcp/_data`` (same layout as the repository), so an installed server is
never empty.

This module has two halves:

* **Build time** (:func:`collect_assets`, :data:`ASSET_RULES`,
  :data:`ASSET_TRANSFORMS`): copies the repo files into a destination
  directory. ``setup.py`` calls it from ``build_py``, so the repository stays
  the single source of truth and nothing is committed twice. It uses the
  standard library only and is loaded by path from ``setup.py`` (``exorad`` is
  not importable at that point).
* **Run time** (:func:`resolve_content_root`, :func:`content_report`): picks the
  content root.

Precedence of the content root:

1. an explicit ``repo_root`` argument or ``EXORAD_MCP_REPO_ROOT`` (``override``,
   or ``packaged`` / ``checkout`` when an extension declares it with
   ``EXORAD_MCP_CONTENT_SOURCE``);
2. the current directory, if it is an ExoRad source checkout (``checkout``);
3. the checkout the ``exorad`` package was imported from, e.g. an editable
   install (``checkout``);
4. the packaged assets (``packaged``).

If none exists the current directory is used and ``source`` is ``none``.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "ASSET_RULES",
    "ASSET_TRANSFORMS",
    "ENV_CONTENT_SOURCE",
    "EXCLUDED_ASSETS",
    "INTERNAL_NOTES",
    "MAX_ASSET_BYTES",
    "AssetTransformError",
    "ContentMissingError",
    "ContentRoot",
    "collect_assets",
    "content_report",
    "is_checkout",
    "packaged_root",
    "require_content_file",
    "resolve_content_root",
    "warn_if_content_missing",
]

ENV_REPO_ROOT = "EXORAD_MCP_REPO_ROOT"
#: Lets an extension package that pins the root through ``ENV_REPO_ROOT`` say what
#: that root is (``packaged`` or ``checkout``) instead of ``override``. Only read
#: together with an explicit root, and only these two values count; it is set by
#: the extension's own ``setup`` hook (server-side), never by a client.
ENV_CONTENT_SOURCE = "EXORAD_MCP_CONTENT_SOURCE"
_DECLARABLE_SOURCES = ("packaged", "checkout")
DATA_DIRNAME = "_data"

# Files shipped in the wheel, relative to the repository root. ``(glob, suffixes)``:
# an empty suffix tuple means "any suffix". Files above ``MAX_ASSET_BYTES``,
# symbolic links, anything under a dot-directory and ``__pycache__`` are skipped,
# which keeps ``examples/customsed.csv`` (21 MB) and notebooks out of the wheel.
ASSET_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AGENTS.md", ()),
    ("README.md", ()),
    ("CHANGELOG.md", ()),
    ("docs/ai-agents/*.md", ()),
    ("docs/source/*.rst", ()),
    ("docs/source/*.md", ()),
    ("docs/source/user/**/*.rst", ()),
    ("docs/source/contributing/*.rst", ()),
    ("examples/*", (".xml", ".csv", ".ecsv", ".txt")),
    ("exorad/exorad.py", ()),
    ("exorad/tasks/*.py", ()),
    ("exorad/models/**/*.py", ()),
    ("exorad/output/**/*.py", ()),
    ("exorad/utils/plotter.py", ()),
)

# Internal planning notes: not knowledge about *using* ExoRad. ONE source of truth,
# imported by the knowledge-base indexer too, so the two exclusion lists cannot drift.
INTERNAL_NOTES = frozenset(
    {
        "docs/ai-agents/mcp-plan.md",
        "docs/ai-agents/mcp-spec.md",
    }
)
# Never shipped or indexed: the internal notes, the SED downloader (the MCP never
# touches the network) and the import-time version check.
EXCLUDED_ASSETS = INTERNAL_NOTES | frozenset(
    {
        "exorad/tasks/downloadSed.py",
        "exorad/utils/version_control.py",
    }
)
MAX_ASSET_BYTES = 1_048_576

# Text rewrites applied to the PACKAGED copy only: ``{relative path: ((old, new), ...)}``.
# The repository example points at the 21 MB ``examples/customsed.csv``; the wheel
# carries a reduced-resolution file instead and the example is rewritten to use it.
# A transform whose file was not collected, or whose ``old`` text is not found, breaks
# the build (:class:`AssetTransformError`) instead of shipping a broken example.
ASSET_TRANSFORMS: dict[str, tuple[tuple[str, str], ...]] = {
    "examples/payload_example.xml": (("customsed.csv", "customsed_demo.csv"),),
}


class AssetTransformError(RuntimeError):
    """An :data:`ASSET_TRANSFORMS` entry could not be applied (build must fail)."""


def _tracked_files(repo: Path) -> set[str] | None:
    """Git-tracked files of ``repo`` (posix, repo-relative), or ``None`` if unknown.

    ``None`` means "do not filter": ``repo`` is not a git work tree (an sdist), or
    git is unavailable.
    """
    if not (repo / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=repo,
            capture_output=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return {name for name in proc.stdout.decode("utf-8", "replace").split("\0") if name}


def _iter_assets(repo: Path, *, tracked_only: bool = True):
    tracked = _tracked_files(repo) if tracked_only else None
    seen: set[Path] = set()
    for pattern, suffixes in ASSET_RULES:
        for path in sorted(repo.glob(pattern)):
            if path in seen or path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(repo)
            if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
                continue
            if rel.as_posix() in EXCLUDED_ASSETS:
                continue
            if tracked is not None and rel.as_posix() not in tracked:
                continue  # a stray local file must not reach a wheel
            if suffixes and path.suffix.lower() not in suffixes:
                continue
            if path.stat().st_size > MAX_ASSET_BYTES:
                continue
            if path.suffix in {".pyc", ".pyo"}:
                continue
            seen.add(path)
            yield rel


def _apply_transforms(
    dest: Path, copied: list[str], transforms: Mapping[str, tuple[tuple[str, str], ...]]
) -> None:
    for rel, edits in transforms.items():
        if rel not in copied:
            raise AssetTransformError(
                f"asset transform for {rel} cannot be applied: the file was not collected"
            )
        target = dest / rel
        text = target.read_bytes().decode("utf-8")
        for old, new in edits:
            if old not in text:
                raise AssetTransformError(
                    f"asset transform for {rel}: {old!r} not found, nothing to replace"
                )
            text = text.replace(old, new)
        target.write_bytes(text.encode("utf-8"))


def collect_assets(
    repo: str | Path,
    dest: str | Path,
    *,
    tracked_only: bool = True,
    transforms: Mapping[str, tuple[tuple[str, str], ...]] | None = None,
) -> list[str]:
    """Copy the packaged-content files of a checkout into ``dest``.

    Parameters
    ----------
    repo : str or pathlib.Path
        Repository root (the single source of truth).
    dest : str or pathlib.Path
        Destination directory; recreated from scratch.
    tracked_only : bool
        In a git work tree, collect tracked files only, so a stray local file
        cannot reach a wheel. Ignored when ``repo`` is not a git work tree.
    transforms : mapping, optional
        Text rewrites to apply; defaults to :data:`ASSET_TRANSFORMS` (pass ``{}``
        to collect a tree that is not the ExoRad repository).

    Returns
    -------
    list of str
        Repository-relative paths copied.

    Raises
    ------
    AssetTransformError
        If an :data:`ASSET_TRANSFORMS` entry cannot be applied.
    """
    repo, dest = Path(repo).resolve(), Path(dest).resolve()
    if dest == repo or dest in repo.parents:
        raise ValueError(f"refusing to recreate {dest}: it contains the repository")
    if dest.exists():
        shutil.rmtree(dest)
    copied: list[str] = []
    for rel in _iter_assets(repo, tracked_only=tracked_only):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / rel, target)
        copied.append(rel.as_posix())
    _apply_transforms(
        dest, copied, ASSET_TRANSFORMS if transforms is None else transforms
    )
    return copied


# ---------------------------------------------------------------------------
# Run time
# ---------------------------------------------------------------------------
class ContentMissingError(RuntimeError):
    """The knowledge base / examples the tool needs are not available."""


@dataclass(frozen=True)
class ContentRoot:
    """Where the server reads its content from."""

    path: Path
    source: str  # "override" | "checkout" | "packaged" | "none"


def is_checkout(path: Path) -> bool:
    """True if ``path`` looks like an ExoRad source checkout (flat layout)."""
    return (
        (path / "pyproject.toml").is_file()
        and (path / "exorad" / "__init__.py").is_file()
        and (path / "docs").is_dir()
    )


def packaged_root() -> Path | None:
    """Directory of the assets shipped in the wheel, or ``None`` if absent."""
    from importlib.resources import files

    try:
        candidate = Path(str(files("exorad.mcp").joinpath(DATA_DIRNAME)))
    except (ModuleNotFoundError, TypeError, ValueError):  # pragma: no cover
        return None
    return candidate if candidate.is_dir() else None


def _package_checkout() -> Path | None:
    # exorad/mcp/assets.py -> repository root is parents[2].
    candidate = Path(__file__).resolve().parents[2]
    return candidate if is_checkout(candidate) else None


def resolve_content_root(
    repo_root: str | Path | None = None,
    *,
    env: dict[str, str] | None = None,
    cwd: str | Path | None = None,
) -> ContentRoot:
    """Resolve the content root following the documented precedence."""
    environ = os.environ if env is None else env
    explicit = repo_root or environ.get(ENV_REPO_ROOT)
    if explicit:
        declared = environ.get(ENV_CONTENT_SOURCE, "").strip().lower()
        source = declared if declared in _DECLARABLE_SOURCES else "override"
        return ContentRoot(Path(explicit).expanduser().resolve(), source)
    here = Path(cwd).resolve() if cwd else Path.cwd().resolve()
    if is_checkout(here):
        return ContentRoot(here, "checkout")
    checkout = _package_checkout()
    if checkout is not None:
        return ContentRoot(checkout, "checkout")
    packaged = packaged_root()
    if packaged is not None:
        return ContentRoot(packaged, "packaged")
    return ContentRoot(here, "none")


def _knowledge_files(root: Path) -> list[str]:
    """Documentation and source files of ``root`` the knowledge base can index.

    Counted with the build-time rules (without the git filter: a runtime root may
    be any directory). The example data tables are not knowledge-base material;
    only the payload XML and the target list are.
    """
    return [
        rel.as_posix()
        for rel in _iter_assets(root, tracked_only=False)
        if rel.parts[0] != "examples"
        or rel.suffix == ".xml"
        or rel.name == "test_target.csv"
    ]


def content_report(root: Path, source: str) -> dict[str, object]:
    """Describe the content at ``root``: source, file counts, warnings."""
    kb_files = len(_knowledge_files(root))
    examples = sum(
        1
        for p in root.glob("examples/**/*.xml")
        if not any(part.startswith(".") for part in p.relative_to(root).parts)
    )
    warnings: list[str] = []
    hint = (
        "Reinstall exorad (the wheel ships the content), or point the server at "
        "an ExoRad checkout with --repo-root / EXORAD_MCP_REPO_ROOT."
    )
    if kb_files == 0:
        warnings.append(
            f"Knowledge base is empty at {root}: search_knowledge_base cannot "
            f"answer. {hint}"
        )
    if examples == 0:
        warnings.append(
            f"No example payloads found at {root}: list_examples, "
            f"draft_config and config_requirements will not work. {hint}"
        )
    return {
        "source": source,
        "root": str(root),
        "knowledge_base_files": kb_files,
        "example_configs": examples,
        "warnings": warnings,
    }


_WARNED: set[str] = set()


def warn_if_content_missing(root: Path, source: str) -> None:
    """Log (once per root) a warning to stderr when the content is empty."""
    key = f"{source}:{root}"
    if key in _WARNED:
        return
    _WARNED.add(key)
    for message in content_report(root, source)["warnings"]:  # type: ignore[attr-defined]
        logging.getLogger("exorad.mcp").warning("%s", message)


def require_content_file(path: Path, what: str) -> Path:
    """Return ``path`` or raise an actionable :class:`ContentMissingError`."""
    if not path.exists():
        raise ContentMissingError(
            f"{what} not found at {path}. The ExoRad MCP content (examples and "
            "documentation) is missing: reinstall exorad, or run the server with "
            "--repo-root / EXORAD_MCP_REPO_ROOT pointing at an ExoRad checkout."
        )
    return path
