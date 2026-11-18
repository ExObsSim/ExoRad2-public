"""Packaging wiring: MANIFEST.in, pyproject extras, CI jobs and mirror excludes.

The expensive end-to-end check (wheel in a fresh venv, run from an empty
directory) is ``scripts/check_wheel_assets.py`` / ``nox -s check-wheel-assets``;
here the sdist is built for real (slow) and the static wiring is asserted.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tarfile
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
NOTES = ("docs/ai-agents/mcp-plan.md", "docs/ai-agents/mcp-spec.md")


def _need(path: Path) -> Path:
    """Dev tooling (CI, nox, scripts) is not part of the public mirror: skip without it."""
    if not path.exists():
        pytest.skip(f"{path.relative_to(REPO)} is not in this checkout (public mirror)")
    return path


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "_check_wheel_assets", _need(REPO / "scripts" / "check_wheel_assets.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest_lines() -> list[str]:
    lines = (REPO / "MANIFEST.in").read_text().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


# --------------------------------------------------------------------------
# MANIFEST.in
# --------------------------------------------------------------------------
def test_manifest_prunes_stale_build_hook_output():
    assert "prune exorad/mcp/_data" in _manifest_lines()


def test_manifest_excludes_bytecode():
    assert any(
        ln.startswith("global-exclude") and "__pycache__" in ln and "*.py[cod]" in ln
        for ln in _manifest_lines()
    )


def test_manifest_in_excludes_internal_notes():
    lines = _manifest_lines()
    for note in NOTES:
        assert f"exclude {note}" in lines
    # other docs/ai-agents files stay (they are knowledge base content)
    assert "include docs/ai-agents/*.md" in lines


def test_manifest_keeps_the_full_sed_in_the_sdist():
    # decision Q8: tests/test_star.py etc. read examples/customsed.csv
    text = "\n".join(_manifest_lines())
    assert "customsed" not in text
    assert "recursive-include examples *.xml *.csv" in text
    assert "graft exorad" in _manifest_lines()


# --------------------------------------------------------------------------
# pyproject / setup.py
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def pyproject():
    return tomllib.loads((REPO / "pyproject.toml").read_text())


def test_extras_and_console_script(pyproject):
    extras = pyproject["project"]["optional-dependencies"]
    assert extras["mcp"] == ["mcp>=2,<3"]
    assert extras["mcp-embeddings"] == ["sentence-transformers>=3,<6"]
    assert pyproject["project"]["scripts"]["exorad-mcp"] == "exorad.mcp.server:main"


def test_no_setuptools_runtime_dependency(pyproject):
    # decision Q5: the pipeline and exorad.mcp run with setuptools blocked
    names = list(pyproject["project"]["dependencies"])
    for group in pyproject["project"]["optional-dependencies"].values():
        names.extend(group)
    assert not [n for n in names if n.lower().startswith("setuptools")]


def test_slow_marker_is_registered(pyproject):
    markers = pyproject["tool"]["pytest"]["ini_options"]["markers"]
    assert any(m.startswith("slow:") for m in markers)


def test_setup_py_loads_assets_by_path_and_never_writes_to_the_source_tree():
    text = (REPO / "setup.py").read_text()
    assert "spec_from_file_location" in text
    assert '"exorad" / "mcp" / "assets.py"' in text
    assert "self.build_lib" in text
    assert "collect_assets(ROOT, dest)" in text


# --------------------------------------------------------------------------
# CI and mirror
# --------------------------------------------------------------------------
def test_ci_has_mcp_and_wheel_assets_jobs():
    text = _need(REPO / ".github" / "workflows" / "ci_linux.yml").read_text()
    assert "\n  mcp:\n" in text
    assert "\n  wheel-assets:\n" in text
    assert "pytest tests/mcp" in text
    assert "nox -s check-wheel-assets" in text
    assert text.count("--extra mcp") >= 2  # the test job and the mcp job


def test_noxfile_has_the_wheel_session():
    text = _need(REPO / "noxfile.py").read_text()
    assert 'name="check-wheel-assets"' in text
    assert "check_wheel_assets.py" in text


def test_sync_workflow_excludes_planning_notes_only():
    text = _need(REPO / ".github" / "workflows" / "sync-to-public.yml").read_text()
    for note in NOTES:
        assert f"--exclude='/{note}'" in text
    assert "--exclude='/mcp-runs'" in text
    # the other agent docs stay public
    assert "--exclude='/docs/ai-agents'" not in text
    assert "ai-agents/README.md" not in text


# --------------------------------------------------------------------------
# A real sdist
# --------------------------------------------------------------------------
def _working_tree_files() -> list[str]:
    out = subprocess.run(
        [
            "git",
            "-C",
            str(REPO),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    files = {f for f in out.split("\0") if f and (REPO / f).is_file()}
    files.add("exorad/mcp/assets.py")
    return sorted(files)


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
@pytest.mark.skipif(
    not (REPO / "exorad" / "mcp" / "assets.py").is_file(),
    reason="exorad/mcp/assets.py is not merged yet",
)
def test_sdist_contains_assets(tmp_path):
    """Build the sdist from the current tree: build inputs in, notes and stale out."""
    script = _load_script()
    src = tmp_path / "src"
    for rel in _working_tree_files():
        target = src / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, target)
    (src / "exorad" / "mcp" / "_data").mkdir(parents=True)
    (src / "exorad" / "mcp" / "_data" / "stale.txt").write_text("stale")
    env = {**os.environ, "SETUPTOOLS_SCM_PRETEND_VERSION": "2.3.0"}
    sdist = script.build(src, tmp_path / "dist", "sdist", env)
    script.check_sdist(sdist)  # SystemExit with the reason on failure
    with tarfile.open(sdist) as tf:
        names = tf.getnames()
    assert not any("_data/stale.txt" in n for n in names)
