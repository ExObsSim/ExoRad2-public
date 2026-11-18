"""Internal planning notes must not reach the wheel or the knowledge base (audit #11)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from exorad.mcp import assets
from exorad.mcp.assets import EXCLUDED_ASSETS, INTERNAL_NOTES, collect_assets

REPO_ROOT = Path(__file__).resolve().parents[2]
NOTES = {"docs/ai-agents/mcp-plan.md", "docs/ai-agents/mcp-spec.md"}


def test_internal_notes_are_the_plan_and_the_spec() -> None:
    assert set(INTERNAL_NOTES) == NOTES
    assert INTERNAL_NOTES <= EXCLUDED_ASSETS


def test_downloader_and_version_check_are_excluded_from_the_content() -> None:
    assert "exorad/tasks/downloadSed.py" in EXCLUDED_ASSETS
    assert "exorad/utils/version_control.py" in EXCLUDED_ASSETS


def test_internal_notes_not_in_kb_or_wheel(tmp_path: Path) -> None:
    present = [note for note in NOTES if (REPO_ROOT / note).is_file()]
    if present:  # the notes are internal: the public mirror has neither of them
        assert set(present) == NOTES, f"a note moved: update INTERNAL_NOTES ({present})"
    dest = tmp_path / "dest"
    copied = collect_assets(REPO_ROOT, dest)
    for note in NOTES:
        assert note not in copied
        assert not (dest / note).exists()
    # the knowledge-base file count does not include them either
    kb = assets._knowledge_files(REPO_ROOT)
    assert not NOTES & set(kb)
    # the other agent docs are still shipped
    assert "docs/ai-agents/README.md" in copied


def test_a_note_dropped_into_a_root_is_not_indexed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "docs" / "ai-agents").mkdir(parents=True)
    for rel in (*NOTES, "docs/ai-agents/guide.md"):
        (root / rel).write_text("text", encoding="utf-8")
    assert assets._knowledge_files(root) == ["docs/ai-agents/guide.md"]


def test_tests_mcp_is_not_a_python_package() -> None:
    """``tests/mcp/__init__.py`` would shadow the ``mcp`` SDK for every test.

    ``tests/`` has no ``__init__.py`` and sits on ``sys.path`` (pytest rootdir
    mode), so a package ``tests/mcp`` is imported as top-level ``mcp`` and
    ``import mcp.server`` then fails.
    """
    assert not (REPO_ROOT / "tests" / "mcp" / "__init__.py").exists()
    spec = importlib.util.find_spec("mcp")
    assert spec is not None
    assert spec.origin is not None
    assert REPO_ROOT / "tests" not in Path(spec.origin).parents


def test_sync_workflow_excludes_internal_notes() -> None:
    workflow = REPO_ROOT / ".github" / "workflows" / "sync-to-public.yml"
    if not workflow.exists():  # not part of the public mirror
        pytest.skip(".github/workflows/sync-to-public.yml is not in this checkout")
    text = workflow.read_text(encoding="utf-8")
    for note in NOTES:
        assert f"/{note}'" in text or f"/{note}" in text
