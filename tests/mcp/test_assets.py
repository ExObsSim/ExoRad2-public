"""Tests for the MCP content root: precedence, packaged assets, build-time rules."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from exorad.mcp import assets
from exorad.mcp.assets import (
    ASSET_RULES,
    MAX_ASSET_BYTES,
    AssetTransformError,
    ContentMissingError,
    collect_assets,
    content_report,
    is_checkout,
    require_content_file,
    resolve_content_root,
)
from exorad.mcp.sandbox import Sandbox

REPO_ROOT = Path(__file__).resolve().parents[2]


def _fake_checkout(path: Path) -> Path:
    (path / "exorad").mkdir(parents=True)
    (path / "exorad" / "__init__.py").write_text("", encoding="utf-8")
    (path / "docs").mkdir()
    (path / "pyproject.toml").write_text("", encoding="utf-8")
    return path


def _write(root: Path, rel: str, text: str = "x", *, size: int | None = None) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if size is None:
        target.write_text(text, encoding="utf-8")
    else:
        with target.open("wb") as handle:
            handle.truncate(size)


@pytest.fixture
def packaged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "pkg" / "_data"
    data.mkdir(parents=True)
    monkeypatch.setattr(assets, "packaged_root", lambda: data)
    monkeypatch.setattr(assets, "_package_checkout", lambda: None)
    return data


class TestPrecedence:
    def test_explicit_beats_env_and_checkout(self, tmp_path: Path) -> None:
        cwd = _fake_checkout(tmp_path / "cwd")
        explicit = tmp_path / "explicit"
        explicit.mkdir()
        got = resolve_content_root(
            explicit, env={"EXORAD_MCP_REPO_ROOT": str(cwd)}, cwd=cwd
        )
        assert (got.path, got.source) == (explicit.resolve(), "override")

    def test_env_override(self, tmp_path: Path) -> None:
        got = resolve_content_root(env={"EXORAD_MCP_REPO_ROOT": str(tmp_path)})
        assert (got.path, got.source) == (tmp_path.resolve(), "override")

    def test_env_override_beats_a_checkout_cwd(self, tmp_path: Path) -> None:
        cwd = _fake_checkout(tmp_path / "cwd")
        other = tmp_path / "other"
        other.mkdir()
        got = resolve_content_root(env={"EXORAD_MCP_REPO_ROOT": str(other)}, cwd=cwd)
        assert got.path == other.resolve()

    def test_cwd_checkout(self, tmp_path: Path, packaged: Path) -> None:
        cwd = _fake_checkout(tmp_path / "co")
        got = resolve_content_root(env={}, cwd=cwd)
        assert (got.path, got.source) == (cwd.resolve(), "checkout")

    def test_package_checkout_when_cwd_is_elsewhere(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, packaged: Path
    ) -> None:
        co = _fake_checkout(tmp_path / "editable")
        monkeypatch.setattr(assets, "_package_checkout", lambda: co)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        got = resolve_content_root(env={}, cwd=elsewhere)
        assert (got.path, got.source) == (co, "checkout")

    def test_packaged_fallback(self, tmp_path: Path, packaged: Path) -> None:
        got = resolve_content_root(env={}, cwd=tmp_path)
        assert (got.path, got.source) == (packaged, "packaged")

    def test_none_when_nothing_available(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(assets, "packaged_root", lambda: None)
        monkeypatch.setattr(assets, "_package_checkout", lambda: None)
        got = resolve_content_root(env={}, cwd=tmp_path)
        assert (got.path, got.source) == (tmp_path.resolve(), "none")

    def test_repo_is_a_checkout(self) -> None:
        assert is_checkout(REPO_ROOT)

    def test_flat_layout_is_recognised_and_src_layout_is_not(
        self, tmp_path: Path
    ) -> None:
        assert is_checkout(_fake_checkout(tmp_path / "flat"))
        src = tmp_path / "srclayout"
        (src / "src" / "exorad").mkdir(parents=True)
        (src / "docs").mkdir()
        (src / "pyproject.toml").write_text("", encoding="utf-8")
        assert not is_checkout(src)

    def test_package_checkout_is_this_repository(self) -> None:
        # exorad/mcp/assets.py lives two levels below the repository root
        assert assets._package_checkout() == REPO_ROOT


class TestSandboxIntegration:
    def test_packaged_work_dir_is_not_in_site_packages(
        self,
        tmp_path: Path,
        packaged: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("EXORAD_MCP_REPO_ROOT")
        monkeypatch.delenv("EXORAD_MCP_WORK_DIR")
        monkeypatch.chdir(tmp_path)
        sandbox = Sandbox.from_env()
        assert sandbox.content_source == "packaged"
        assert sandbox.repo_root == packaged
        assert sandbox.work_dir == (tmp_path / "mcp-runs").resolve()

    def test_to_dict_reports_content(self) -> None:
        content = Sandbox.from_env().to_dict()["content"]
        assert content["source"] == "override"
        assert content["knowledge_base_files"] > 0
        assert content["example_configs"] > 0
        assert content["warnings"] == []

    def test_override_precedence_through_the_sandbox(
        self, tmp_path: Path, packaged: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mine = tmp_path / "mine"
        mine.mkdir()
        monkeypatch.setenv("EXORAD_MCP_REPO_ROOT", str(mine))
        monkeypatch.chdir(_fake_checkout(tmp_path / "cwd"))
        box = Sandbox.from_env()
        assert (box.repo_root, box.content_source) == (mine.resolve(), "override")


class TestEmptyContent:
    def test_report_warns_when_empty(self, tmp_path: Path) -> None:
        report = content_report(tmp_path, "packaged")
        assert report["knowledge_base_files"] == 0
        assert report["example_configs"] == 0
        assert len(report["warnings"]) == 2
        assert "--repo-root" in report["warnings"][0]
        assert "EXORAD_MCP_REPO_ROOT" in report["warnings"][0]

    def test_startup_logs_warning_once(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        assets._WARNED.discard(f"override:{tmp_path.resolve()}")
        with caplog.at_level(logging.WARNING, logger="exorad.mcp"):
            Sandbox.from_env(repo_root=tmp_path)
            Sandbox.from_env(repo_root=tmp_path)
        messages = [r.getMessage() for r in caplog.records]
        assert sum("Knowledge base is empty" in m for m in messages) == 1

    def test_require_content_file_raises_actionable_error(self, tmp_path: Path) -> None:
        with pytest.raises(ContentMissingError, match="--repo-root"):
            require_content_file(
                tmp_path / "examples" / "payload_example.xml", "payload"
            )
        present = tmp_path / "there.txt"
        present.write_text("x")
        assert require_content_file(present, "file") == present

    def test_empty_report_counts_only_kb_material(self, tmp_path: Path) -> None:
        # data tables alone are not a knowledge base
        _write(tmp_path, "examples/table.csv")
        assert content_report(tmp_path, "override")["knowledge_base_files"] == 0


class TestCollectAssets:
    def test_collects_expected_and_skips_large_and_internal(
        self, tmp_path: Path
    ) -> None:
        dest = tmp_path / "dest"
        copied = collect_assets(REPO_ROOT, dest)
        for name in (
            "AGENTS.md",
            "README.md",
            "examples/payload_example.xml",
            "examples/test_target.csv",
            "examples/QE.csv",
            "examples/Spec-wl_sol.csv",
            "exorad/exorad.py",
            "exorad/utils/plotter.py",
        ):
            assert name in copied
        assert "docs/ai-agents/mcp-plan.md" not in copied
        assert "docs/ai-agents/mcp-spec.md" not in copied
        assert "exorad/tasks/downloadSed.py" not in copied
        assert "exorad/utils/version_control.py" not in copied
        assert not any(name.endswith(".ipynb") for name in copied)
        assert not any(name.endswith(".pdf") for name in copied)
        assert not any("_static" in name for name in copied)
        assert not any(name.startswith(("mcp-runs/", "tests/")) for name in copied)

    def test_size_cap_keeps_the_21_mb_sed_out(self, tmp_path: Path) -> None:
        big = REPO_ROOT / "examples" / "customsed.csv"
        assert big.stat().st_size > 20_000_000, "the repo example SED changed"
        dest = tmp_path / "dest"
        copied = collect_assets(REPO_ROOT, dest)
        assert "examples/customsed.csv" not in copied
        assert not (dest / "examples" / "customsed.csv").exists()
        sizes = [p.stat().st_size for p in dest.rglob("*") if p.is_file()]
        assert max(sizes) <= MAX_ASSET_BYTES
        assert MAX_ASSET_BYTES == 1_048_576

    def test_collection_size_lower_bounds(self, tmp_path: Path) -> None:
        dest = tmp_path / "dest"
        copied = collect_assets(REPO_ROOT, dest)
        assert len(copied) > 40
        total = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
        assert total < 3_000_000

    def test_no_pycache_or_bytecode_is_collected(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _write(repo, "exorad/tasks/real.py", "x = 1")
        _write(repo, "exorad/tasks/__pycache__/real.cpython-312.pyc")
        _write(repo, "exorad/tasks/stale.pyc")
        _write(repo, "exorad/models/__pycache__/m.py")
        _write(repo, "exorad/models/sub/__pycache__/m.py")
        dest = tmp_path / "dest"
        copied = collect_assets(repo, dest, tracked_only=False, transforms={})
        assert copied == ["exorad/tasks/real.py"]
        assert not list(dest.rglob("__pycache__"))
        # and in the real tree, which has been imported (and so has bytecode)
        real = collect_assets(REPO_ROOT, tmp_path / "real")
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in real)

    def test_dot_directories_are_skipped(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _write(repo, "docs/source/user/.hidden/secret.rst")
        _write(repo, "docs/source/user/visible.rst")
        copied = collect_assets(
            repo, tmp_path / "dest", tracked_only=False, transforms={}
        )
        assert copied == ["docs/source/user/visible.rst"]

    def test_symlinks_are_not_followed_into_the_wheel(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        secret = tmp_path / "outside.rst"
        secret.write_text("private")
        _write(repo, "docs/source/user/ok.rst")
        try:
            os.symlink(secret, repo / "docs" / "source" / "user" / "leak.rst")
        except OSError:
            pytest.skip("symlinks unavailable")
        copied = collect_assets(
            repo, tmp_path / "dest", tracked_only=False, transforms={}
        )
        assert copied == ["docs/source/user/ok.rst"]

    def test_suffix_filter_on_examples(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        for name in ("a.xml", "b.csv", "c.ecsv", "d.txt", "e.ipynb", "f.pdf", "g.h5"):
            _write(repo, f"examples/{name}")
        copied = collect_assets(
            repo, tmp_path / "dest", tracked_only=False, transforms={}
        )
        assert sorted(copied) == [
            f"examples/{n}" for n in ("a.xml", "b.csv", "c.ecsv", "d.txt")
        ]

    def test_size_cap_on_a_synthetic_tree(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _write(repo, "examples/ok.csv", size=MAX_ASSET_BYTES)
        _write(repo, "examples/too_big.csv", size=MAX_ASSET_BYTES + 1)
        copied = collect_assets(
            repo, tmp_path / "dest", tracked_only=False, transforms={}
        )
        assert copied == ["examples/ok.csv"]

    def test_dest_that_contains_the_repo_is_refused(self, tmp_path: Path) -> None:
        repo = tmp_path / "outer" / "repo"
        repo.mkdir(parents=True)
        with pytest.raises(ValueError, match="refusing"):
            collect_assets(repo, tmp_path / "outer")
        with pytest.raises(ValueError, match="refusing"):
            collect_assets(repo, repo)
        assert repo.exists()

    def test_rules_cover_the_documented_tree(self) -> None:
        patterns = [pattern for pattern, _ in ASSET_RULES]
        for needed in (
            "AGENTS.md",
            "docs/ai-agents/*.md",
            "docs/source/user/**/*.rst",
            "examples/*",
            "exorad/tasks/*.py",
        ):
            assert needed in patterns

    def test_collected_tree_is_a_working_content_root(self, tmp_path: Path) -> None:
        dest = tmp_path / "dest"
        copied = collect_assets(REPO_ROOT, dest)
        report = content_report(dest, "packaged")
        assert report["warnings"] == []
        assert report["knowledge_base_files"] > 40
        assert report["example_configs"] >= 1
        assert is_checkout(dest) is False  # a packaged tree has no pyproject
        assert (
            Sandbox.from_env(repo_root=dest).resolve_read(
                "examples/payload_example.xml"
            )
            == (dest / "examples" / "payload_example.xml").resolve()
        )
        assert "examples/payload_example.xml" in copied


class TestUntrackedFilter:
    @pytest.fixture
    def git_repo(self, tmp_path: Path) -> Path:
        if shutil.which("git") is None:
            pytest.skip("git unavailable")
        repo = tmp_path / "gitrepo"
        _write(repo, "docs/source/user/tracked.rst", "tracked")
        _write(repo, "docs/source/user/stray.rst", "a stray local note")
        _write(repo, "examples/tracked.xml", "<r/>")
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(
            ["git", "add", "docs/source/user/tracked.rst", "examples/tracked.xml"],
            cwd=repo,
            check=True,
        )
        return repo

    def test_untracked_files_do_not_reach_the_assets(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        copied = collect_assets(git_repo, tmp_path / "dest", transforms={})
        assert "docs/source/user/tracked.rst" in copied
        assert "examples/tracked.xml" in copied
        assert "docs/source/user/stray.rst" not in copied
        assert not (tmp_path / "dest" / "docs/source/user/stray.rst").exists()

    def test_the_filter_can_be_switched_off(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        copied = collect_assets(
            git_repo, tmp_path / "dest", tracked_only=False, transforms={}
        )
        assert "docs/source/user/stray.rst" in copied

    def test_a_tree_without_git_is_collected_whole(self, tmp_path: Path) -> None:
        # an sdist has no .git: nothing to filter against
        repo = tmp_path / "sdist"
        _write(repo, "docs/source/user/a.rst")
        assert collect_assets(repo, tmp_path / "dest", transforms={}) == [
            "docs/source/user/a.rst"
        ]

    def test_git_failure_means_no_filtering(
        self, git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_a, **_k):
            raise FileNotFoundError("git")

        monkeypatch.setattr(assets.subprocess, "run", boom)
        copied = collect_assets(git_repo, tmp_path / "dest", transforms={})
        assert "docs/source/user/stray.rst" in copied


class TestTransforms:
    def test_demo_sed_substitution_is_applied(self, tmp_path: Path) -> None:
        dest = tmp_path / "dest"
        collect_assets(REPO_ROOT, dest)
        text = (dest / "examples" / "payload_example.xml").read_text(encoding="utf-8")
        assert "customsed.csv" not in text
        assert "customsed_demo.csv" in text
        # the repository file itself is untouched
        original = (REPO_ROOT / "examples" / "payload_example.xml").read_text(
            encoding="utf-8"
        )
        assert "customsed_demo.csv" not in original
        assert text.replace("customsed_demo.csv", "customsed.csv") == original

    def test_transform_failure_breaks_the_build(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(
            assets.ASSET_TRANSFORMS,
            "examples/payload_example.xml",
            (("this text is not in the file", "x"),),
        )
        with pytest.raises(AssetTransformError, match="not found"):
            collect_assets(REPO_ROOT, tmp_path / "dest")

    def test_transform_of_an_uncollected_file_breaks_the_build(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(
            assets.ASSET_TRANSFORMS, "examples/missing.xml", (("a", "b"),)
        )
        with pytest.raises(AssetTransformError, match="not collected"):
            collect_assets(REPO_ROOT, tmp_path / "dest")
