"""Tests for the ExoRad MCP filesystem sandbox (hazards H1, H2, H8, H10)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from exorad.mcp.sandbox import (
    ENV_ALLOW_DIRS,
    ENV_NO_EXEC,
    ENV_WORK_DIR,
    PathNotAllowedError,
    Sandbox,
    redact_runtime,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests drive the sandbox explicitly; drop the conftest env defaults."""
    for name in (
        "EXORAD_MCP_REPO_ROOT",
        "EXORAD_MCP_EXEC_BACKEND",
        ENV_WORK_DIR,
        ENV_ALLOW_DIRS,
        ENV_NO_EXEC,
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "examples").mkdir(parents=True)
    (root / "examples" / "config.xml").write_text("<root />", encoding="utf-8")
    return root


@pytest.fixture
def layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A content root and a *separate* work dir (as with packaged content)."""
    content = tmp_path / "content"
    work = tmp_path / "work"
    (content / "examples").mkdir(parents=True)
    work.mkdir()
    monkeypatch.setenv("EXORAD_MCP_REPO_ROOT", str(content))
    monkeypatch.setenv("EXORAD_MCP_WORK_DIR", str(work))
    cwd = tmp_path / "elsewhere"  # not readable: only content + work are
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return content, work


# -- ported from ExoSim ---------------------------------------------------------
def test_defaults_place_work_dir_inside_repo(repo: Path) -> None:
    box = Sandbox.from_env(repo_root=repo)
    assert box.repo_root == repo.resolve()
    assert box.work_dir == (repo / "mcp-runs").resolve()
    assert box.allow_exec is True


def test_read_allows_repo_and_work_dir(repo: Path) -> None:
    box = Sandbox.from_env(repo_root=repo)
    assert (
        box.resolve_read("examples/config.xml")
        == (repo / "examples/config.xml").resolve()
    )
    assert box.resolve_read(str(box.work_dir / "out.h5")) == box.work_dir / "out.h5"


def test_read_rejects_paths_outside_the_sandbox(repo: Path, tmp_path: Path) -> None:
    box = Sandbox.from_env(repo_root=repo)
    outside = tmp_path.parent / "somewhere-else"
    with pytest.raises(PathNotAllowedError):
        box.resolve_read(str(outside / "secret"))


def test_read_rejects_tilde(repo: Path, tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_rsa").write_text("key")
    monkeypatch.setenv("HOME", str(home))
    box = Sandbox.from_env(repo_root=repo)
    with pytest.raises(PathNotAllowedError):
        box.resolve_read("~/.ssh/id_rsa")
    with pytest.raises(PathNotAllowedError):
        box.resolve_read("~/.ssh/id_rsa", prefer_work_dir=True)
    with pytest.raises(PathNotAllowedError):
        box.resolve_write("~/stolen.h5")


def test_read_rejects_dotdot_traversal(repo: Path) -> None:
    box = Sandbox.from_env(repo_root=repo)
    with pytest.raises(PathNotAllowedError):
        box.resolve_read("examples/../../escape.txt")
    with pytest.raises(PathNotAllowedError):
        box.resolve_write("../escape.h5")


def test_write_confined_to_work_dir(repo: Path) -> None:
    box = Sandbox.from_env(repo_root=repo)
    assert box.resolve_write("run/out.h5") == (box.work_dir / "run/out.h5").resolve()
    # writing into the checkout itself is refused
    with pytest.raises(PathNotAllowedError):
        box.resolve_write(str(repo / "examples" / "out.h5"))


def test_extra_allow_dirs_extend_both_read_and_write(
    repo: Path, tmp_path: Path
) -> None:
    extra = tmp_path.parent / "project-configs"
    with patch.dict(os.environ, {ENV_ALLOW_DIRS: str(extra)}):
        box = Sandbox.from_env(repo_root=repo)
    assert box.resolve_read(str(extra / "my.xml")) == (extra / "my.xml").resolve()
    assert box.resolve_write(str(extra / "out.h5")) == (extra / "out.h5").resolve()


def test_explicit_work_dir_and_env(repo: Path, tmp_path: Path) -> None:
    with patch.dict(os.environ, {ENV_WORK_DIR: str(tmp_path / "env-work")}):
        box = Sandbox.from_env(repo_root=repo)
    assert box.work_dir == (tmp_path / "env-work").resolve()


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_no_exec_env_disables_execution(repo: Path, value: str) -> None:
    with patch.dict(os.environ, {ENV_NO_EXEC: value}):
        box = Sandbox.from_env(repo_root=repo)
    assert box.allow_exec is False


# -- relative paths: work dir first, then the content root ---------------------
def test_work_dir_wins_over_content_root(layout: tuple[Path, Path]) -> None:
    content, work = layout
    (content / "data.txt").write_text("content")
    (work / "data.txt").write_text("work")
    box = Sandbox.from_env()
    assert box.resolve_read("data.txt", prefer_work_dir=True) == work / "data.txt"
    # default behaviour unchanged: content root
    assert box.resolve_read("data.txt") == content / "data.txt"


def test_falls_back_to_content_root(layout: tuple[Path, Path]) -> None:
    content, _ = layout
    (content / "examples" / "a.xml").write_text("<r/>")
    box = Sandbox.from_env()
    got = box.resolve_read("examples/a.xml", prefer_work_dir=True)
    assert got == content / "examples" / "a.xml"


def test_missing_everywhere_resolves_to_content_root(
    layout: tuple[Path, Path],
) -> None:
    content, _ = layout
    box = Sandbox.from_env()
    assert box.resolve_read("nope.h5", prefer_work_dir=True) == content / "nope.h5"


def test_traversal_from_work_dir_is_still_rejected(
    layout: tuple[Path, Path], tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    box = Sandbox.from_env()
    with pytest.raises(PathNotAllowedError):
        box.resolve_read("../secret.txt", prefer_work_dir=True)
    with pytest.raises(PathNotAllowedError):
        box.resolve_read(str(secret), prefer_work_dir=True)


# -- H2: symlinks ---------------------------------------------------------------
def test_symlink_out_of_sandbox_rejected(
    layout: tuple[Path, Path], tmp_path: Path
) -> None:
    _, work = layout
    outside = tmp_path / "elsewhere" / "private.h5"
    outside.write_text("x")
    link = work / "link.h5"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("symlinks unavailable")
    box = Sandbox.from_env()
    # explicit path through the symlink: rejected
    with pytest.raises(PathNotAllowedError):
        box.resolve_read(str(link), prefer_work_dir=True)
    # bare name: the escaping work-dir candidate is never returned
    with pytest.raises(PathNotAllowedError):
        box.resolve_read("link.h5", prefer_work_dir=True)


def test_workdir_symlink_message_names_the_resolution(
    layout: tuple[Path, Path], tmp_path: Path
) -> None:
    _, work = layout
    outside = tmp_path / "elsewhere" / "private.h5"
    outside.write_text("x")
    try:
        os.symlink(outside, work / "link.h5")
    except OSError:
        pytest.skip("symlinks unavailable")
    box = Sandbox.from_env()
    with pytest.raises(PathNotAllowedError, match="resolves outside") as info:
        box.resolve_read("link.h5", prefer_work_dir=True)
    assert str(outside) not in str(info.value)


def test_symlinked_directory_in_work_dir_is_rejected(
    layout: tuple[Path, Path], tmp_path: Path
) -> None:
    _, work = layout
    secret_dir = tmp_path / "elsewhere" / "secrets"
    secret_dir.mkdir()
    (secret_dir / "payload.xml").write_text("<x/>")
    try:
        os.symlink(secret_dir, work / "innocent", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    box = Sandbox.from_env()
    with pytest.raises(PathNotAllowedError):
        box.resolve_read("innocent/payload.xml", prefer_work_dir=True)
    with pytest.raises(PathNotAllowedError):
        box.resolve_read(str(work / "innocent" / "payload.xml"))
    with pytest.raises(PathNotAllowedError):
        box.resolve_write("innocent/new.h5")


def test_symlink_inside_the_sandbox_is_followed(layout: tuple[Path, Path]) -> None:
    content, work = layout
    (content / "examples" / "real.xml").write_text("<r/>")
    try:
        os.symlink(content / "examples" / "real.xml", work / "alias.xml")
    except OSError:
        pytest.skip("symlinks unavailable")
    box = Sandbox.from_env()
    got = box.resolve_read("alias.xml", prefer_work_dir=True)
    assert got == (content / "examples" / "real.xml").resolve()


# -- H6: URLs; regular files; H10: size ---------------------------------------
@pytest.mark.parametrize(
    "value",
    [
        "http://example.com/x.csv",
        "https://example.com/x.csv",
        "file:///etc/passwd",
        "ftp://host/file",
    ],
)
def test_url_values_are_refused(repo: Path, value: str) -> None:
    box = Sandbox.from_env(repo_root=repo)
    with pytest.raises(PathNotAllowedError, match="URL"):
        box.resolve_read(value)
    with pytest.raises(PathNotAllowedError, match="URL"):
        box.resolve_read(value, prefer_work_dir=True)
    with pytest.raises(PathNotAllowedError, match="URL"):
        box.resolve_write(value)


def test_nul_byte_is_refused(repo: Path) -> None:
    box = Sandbox.from_env(repo_root=repo)
    with pytest.raises(PathNotAllowedError):
        box.resolve_read("examples/a\0.xml")


def test_fifo_is_not_a_regular_file(repo: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("no FIFOs on this platform")
    box = Sandbox.from_env(repo_root=repo)
    fifo = repo / "examples" / "pipe.csv"
    os.mkfifo(fifo)
    with pytest.raises(PathNotAllowedError, match="regular file"):
        box.resolve_input_file("examples/pipe.csv", max_mb=2)


def test_directory_is_not_a_regular_file(repo: Path) -> None:
    box = Sandbox.from_env(repo_root=repo)
    with pytest.raises(PathNotAllowedError, match="regular file"):
        box.resolve_input_file("examples")


def test_missing_input_file_is_file_not_found(repo: Path) -> None:
    box = Sandbox.from_env(repo_root=repo)
    with pytest.raises(FileNotFoundError):
        box.resolve_input_file("examples/nope.xml")


def test_giant_file_is_refused(repo: Path) -> None:
    box = Sandbox.from_env(repo_root=repo)
    big = repo / "examples" / "big.csv"
    with big.open("wb") as handle:
        handle.truncate(3 * 1_048_576)  # sparse: no real disk use
    with pytest.raises(PathNotAllowedError, match="limit"):
        box.resolve_input_file("examples/big.csv", max_mb=box.max_file_mb)
    # within the limit it is accepted, and without a limit nothing is checked
    assert box.resolve_input_file("examples/big.csv", max_mb=4) == big.resolve()
    assert box.resolve_input_file("examples/big.csv") == big.resolve()


def test_regular_file_within_limit_is_accepted(repo: Path) -> None:
    box = Sandbox.from_env(repo_root=repo)
    got = box.resolve_input_file("examples/config.xml", max_mb=box.max_file_mb)
    assert got == (repo / "examples" / "config.xml").resolve()


# -- limits, display, redaction -------------------------------------------------
def test_default_limits(repo: Path) -> None:
    box = Sandbox.from_env(repo_root=repo)
    assert 1 <= box.max_threads <= 4
    assert box.max_runtime == 3600.0
    assert box.max_jobs == 2
    assert box.max_targets == 200
    assert box.max_output_mb == 512
    assert box.max_bins == 20000
    assert box.max_data_mb == 64
    assert box.max_file_mb == 2
    assert box.validate_timeout == 120.0
    assert box.exec_backend == "process"


def test_limits_from_env(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "EXORAD_MCP_MAX_THREADS": "3",
        "EXORAD_MCP_MAX_RUNTIME": "90.5",
        "EXORAD_MCP_MAX_JOBS": "5",
        "EXORAD_MCP_MAX_TARGETS": "10",
        "EXORAD_MCP_MAX_OUTPUT_MB": "7",
        "EXORAD_MCP_MAX_BINS": "300",
        "EXORAD_MCP_MAX_DATA_MB": "9",
        "EXORAD_MCP_MAX_FILE_MB": "1",
        "EXORAD_MCP_VALIDATE_TIMEOUT": "15",
        "EXORAD_MCP_EXEC_BACKEND": "inline",
    }.items():
        monkeypatch.setenv(name, value)
    box = Sandbox.from_env(repo_root=repo)
    assert (box.max_threads, box.max_runtime, box.max_jobs) == (3, 90.5, 5)
    assert (box.max_targets, box.max_output_mb, box.max_bins) == (10, 7, 300)
    assert (box.max_data_mb, box.max_file_mb, box.validate_timeout) == (9, 1, 15.0)
    assert box.exec_backend == "inline"


@pytest.mark.parametrize("bad", ["0", "-3", "abc", "", "1.5"])
def test_max_jobs_invalid_falls_back(
    repo: Path, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setenv("EXORAD_MCP_MAX_JOBS", bad)
    assert Sandbox.from_env(repo_root=repo).max_jobs == 2


@pytest.mark.parametrize("bad", ["0", "-1", "soon"])
def test_other_invalid_limits_fall_back(
    repo: Path, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    for name in (
        "EXORAD_MCP_MAX_RUNTIME",
        "EXORAD_MCP_MAX_TARGETS",
        "EXORAD_MCP_MAX_FILE_MB",
        "EXORAD_MCP_MAX_THREADS",
    ):
        monkeypatch.setenv(name, bad)
    box = Sandbox.from_env(repo_root=repo)
    assert box.max_runtime == 3600.0
    assert box.max_targets == 200
    assert box.max_file_mb == 2
    assert box.max_threads >= 1


def test_clamp_threads(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXORAD_MCP_MAX_THREADS", "3")
    box = Sandbox.from_env(repo_root=repo)
    assert box.clamp_threads(None) == 1
    assert box.clamp_threads(0) == 1
    assert box.clamp_threads(2) == 2
    assert box.clamp_threads(99) == 3


def test_unknown_exec_backend_falls_back(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXORAD_MCP_EXEC_BACKEND", "magic")
    assert Sandbox.from_env(repo_root=repo).exec_backend == "process"


def test_display_path_prefixes(repo: Path, tmp_path: Path) -> None:
    extra = tmp_path / "extra"
    extra.mkdir()
    with patch.dict(os.environ, {ENV_ALLOW_DIRS: str(extra)}):
        box = Sandbox.from_env(repo_root=repo)
    assert box.display_path(box.work_dir / "run1" / "out.h5") == "work:run1/out.h5"
    assert box.display_path(repo / "examples" / "config.xml") == (
        "content:examples/config.xml"
    )
    assert box.display_path(extra / "my.xml") == "allow[0]:my.xml"
    # the work dir lives inside the repo in a checkout: the work label wins
    assert box.display_path(box.work_dir) == "work:."
    shown = box.display_path("/somewhere/secret/id_rsa")
    assert shown == "<outside>/id_rsa"
    assert "somewhere" not in shown


def test_redact_replaces_roots(repo: Path, tmp_path: Path) -> None:
    box = Sandbox.from_env(repo_root=repo)
    text = (
        f"error opening {box.work_dir}/run1/out.h5 and {repo.resolve()}/examples/a.xml"
        f" (work dir is {box.work_dir})"
    )
    out = box.redact(text)
    assert str(box.work_dir) not in out
    assert str(repo.resolve()) not in out
    assert "work:run1/out.h5" in out
    assert "content:examples/a.xml" in out
    assert "work dir is work:." in out


def test_redact_hides_interpreter_prefixes_and_the_home_directory(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sys
    import sysconfig

    home = tmp_path / "someone"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    site_dir = sysconfig.get_paths()["purelib"]
    box = Sandbox.from_env(repo_root=repo)
    text = (
        f'File "{site_dir}/astropy/a.py"\n File "{sys.prefix}/bin/x"\n'
        f' File "{home}/data/t.csv" and {home}\n'
    )
    out = box.redact(text)
    assert site_dir not in out
    assert sys.prefix not in out
    assert str(home) not in out
    assert "<site-packages>/astropy/a.py" in out
    assert "~/data/t.csv" in out
    assert redact_runtime(text) == out


def test_redact_does_not_touch_sibling_names(repo: Path) -> None:
    box = Sandbox.from_env(repo_root=repo)
    sibling = f"{box.work_dir}-other/file"
    out = box.redact(sibling)
    assert "work:" not in out  # "<work>-other" is not the work dir
    assert out.endswith("-other/file")


def test_to_dict_shows_roots_and_limits(repo: Path) -> None:
    info = Sandbox.from_env(repo_root=repo).to_dict()
    assert info["repo_root"] == str(repo.resolve())
    assert info["max_targets"] == 200
    assert info["execution_enabled"] is True
