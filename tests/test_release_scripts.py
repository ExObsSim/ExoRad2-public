"""Offline tests for scripts/release.py and scripts/changelog_extract.py."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = _load("release")
extract = _load("changelog_extract")

CHANGELOG = """# Changelog

<!-- scriv-insert-here -->

## [2.2.0] - Python 3.12+
### Added
- new thing

### Fixed
- a fix

## [2.1.127] - 2024-09-30
### Changed
- old thing
"""


@pytest.fixture
def changelog(tmp_path, monkeypatch):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG)
    monkeypatch.setattr(extract, "CHANGELOG", path)
    return path


def test_title_new_heading(changelog):
    assert extract.extract_title("2.2.0") == "Python 3.12+"


def test_title_old_heading_is_date(changelog):
    assert extract.extract_title("2.1.127") == "2024-09-30"


def test_title_missing_version_falls_back(changelog):
    assert extract.extract_title("9.9.9") == "9.9.9"


def test_body_stops_at_next_heading(changelog):
    body = extract.extract_body("2.2.0")
    assert body.startswith("### Added")
    assert "- a fix" in body
    assert "old thing" not in body


def test_body_old_heading(changelog):
    assert extract.extract_body("2.1.127") == "### Changed\n- old thing\n"


def test_cli_title(changelog, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["changelog_extract.py", "2.2.0", "--title"])
    assert extract.main() == 0
    assert capsys.readouterr().out == "Python 3.12+\n"


def test_changelog_heading_format():
    assert release.changelog_heading("2.2.0", "Python 3.12+") == (
        "[2.2.0] - Python 3.12+"
    )


def test_scriv_gets_title_only(monkeypatch, tmp_path):
    """scriv >= 1.8 rejects --version with --title: only --title is passed."""
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG)
    monkeypatch.setattr(release, "REPO_ROOT", tmp_path)
    calls = []
    monkeypatch.setattr(release, "run", lambda *a, **k: calls.append(a) or "")
    release.collect_changelog("2.3.0", "Named")
    (cmd,) = calls
    assert "--version" not in cmd
    assert cmd[-2:] == ("--title", "[2.3.0] - Named")


def test_collect_refuses_existing_version(monkeypatch, tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG)
    monkeypatch.setattr(release, "REPO_ROOT", tmp_path)
    with pytest.raises(release.ReleaseError):
        release.collect_changelog("2.2.0", "Again")


def test_choose_title_cli_and_prompt(monkeypatch):
    assert release.choose_title("  Hello  ") == "Hello"
    with pytest.raises(release.ReleaseError):
        release.choose_title("  ")
    answers = iter(["", "From prompt"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert release.choose_title() == "From prompt"


def test_update_citation_inserts_version(tmp_path):
    cff = tmp_path / "CITATION.cff"
    cff.write_text('title: "X"\ndoi: 10.1/x\ndate-released: 2023-09-26\n')
    release.update_citation("2.2.0", "2026-10-19", cff)
    assert cff.read_text() == (
        'title: "X"\ndoi: 10.1/x\nversion: 2.2.0\ndate-released: 2026-10-19\n'
    )


def test_update_citation_replaces_version(tmp_path):
    cff = tmp_path / "CITATION.cff"
    cff.write_text("version: 2.1.0\ndate-released: 2023-09-26\n")
    release.update_citation("2.2.0", "2026-10-19", cff)
    assert cff.read_text() == "version: 2.2.0\ndate-released: 2026-10-19\n"


def test_commit_message_matches_mirror_check(monkeypatch):
    """release.yml waits for 'release ${VERSION}' in the public commit message."""
    cmds = []
    monkeypatch.setattr(release, "git", lambda *a, **k: cmds.append(a) or "")
    monkeypatch.setattr(release, "confirm", lambda _: False)
    with pytest.raises(release.ReleaseError):
        release.commit_and_tag("2.2.0", "Python 3.12+")
    msg = next(c for c in cmds if c[0] == "commit")[2]
    assert msg == "docs: release 2.2.0 — Python 3.12+"
    assert "release 2.2.0" in msg


def test_changelog_extract_runs_as_script():
    out = subprocess.run(
        ["python3", str(SCRIPTS / "changelog_extract.py")],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 2
