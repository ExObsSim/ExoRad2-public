"""The ``work:`` / ``content:`` / ``allow[i]:`` paths the server SHOWS must be accepted back.

``run_pipeline`` returns ``output`` and ``files`` in display form (``work:runs/<id>/output.h5``)
so that no absolute server path leaks. A client then passes that string to
``inspect_output`` / ``explain_output`` / ``plot_output`` / ``validate_config``. It was found
(wheel check, 2026-11-12) that those tools refused the display form with "file not found",
so the natural flow "run, then inspect the result" failed. The display form must round-trip,
and it must go through exactly the same containment checks as any other path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from exorad.mcp.sandbox import (
    ENV_ALLOW_DIRS,
    ENV_WORK_DIR,
    PathNotAllowedError,
    Sandbox,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sandbox:
    content = tmp_path / "content"
    work = tmp_path / "work"
    extra = tmp_path / "extra"
    (content / "examples").mkdir(parents=True)
    (content / "examples" / "payload.xml").write_text("<root />", encoding="utf-8")
    (work / "runs" / "r1").mkdir(parents=True)
    (work / "runs" / "r1" / "output.h5").write_bytes(b"x")
    extra.mkdir()
    (extra / "mine.csv").write_text("a\n", encoding="utf-8")
    monkeypatch.setenv(ENV_WORK_DIR, str(work))
    monkeypatch.setenv(ENV_ALLOW_DIRS, str(extra))
    return Sandbox.from_env(repo_root=content)


@pytest.mark.parametrize(
    "relative",
    ["runs/r1/output.h5", "examples/payload.xml"],
)
def test_display_path_round_trips_through_resolve_read(
    box: Sandbox, relative: str
) -> None:
    found = box.resolve_read(relative, prefer_work_dir=True)
    shown = box.display_path(found)
    assert shown.split(":", 1)[0] in {"work", "content"}
    assert box.resolve_read(shown) == found
    assert box.resolve_read(shown, prefer_work_dir=True) == found


def test_work_label_resolves_to_the_work_dir(box: Sandbox) -> None:
    assert box.resolve_input_file("work:runs/r1/output.h5") == (
        box.work_dir / "runs" / "r1" / "output.h5"
    )


def test_content_label_resolves_to_the_content_root(box: Sandbox) -> None:
    assert box.resolve_read("content:examples/payload.xml") == (
        box.repo_root / "examples" / "payload.xml"
    )


def test_allow_label_resolves_to_the_extra_root(box: Sandbox) -> None:
    shown = box.display_path(box.extra_roots[0] / "mine.csv")
    assert shown.startswith("allow[0]:")
    assert box.resolve_read(shown) == box.extra_roots[0] / "mine.csv"


def test_write_accepts_the_work_label(box: Sandbox) -> None:
    assert box.resolve_write("work:plots/a.png") == box.work_dir / "plots" / "a.png"


def test_write_refuses_the_content_label(box: Sandbox) -> None:
    with pytest.raises(PathNotAllowedError):
        box.resolve_write("content:examples/new.xml")


@pytest.mark.parametrize(
    "hostile",
    [
        "work:../secret.txt",
        "work:../../etc/passwd",
        "work:/etc/passwd",
        "content:../outside.txt",
        "allow[0]:../outside.txt",
    ],
)
def test_a_label_never_widens_the_sandbox(box: Sandbox, hostile: str) -> None:
    with pytest.raises(PathNotAllowedError):
        box.resolve_read(hostile)


def test_label_with_a_symlink_out_of_the_sandbox_is_refused(
    box: Sandbox, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (box.work_dir / "link.txt").symlink_to(outside)
    with pytest.raises(PathNotAllowedError):
        box.resolve_read("work:link.txt")


def test_unknown_or_outside_labels_are_not_special(box: Sandbox) -> None:
    # ``<outside>/name`` is how a path OUTSIDE the sandbox is shown: it must not resolve.
    with pytest.raises((PathNotAllowedError, FileNotFoundError)):
        box.resolve_input_file("<outside>/output.h5")
    # a label for a root that does not exist (only one --allow-dir is configured)
    with pytest.raises(PathNotAllowedError):
        box.resolve_read("allow[7]:mine.csv")


def test_interpreter_paths_win_over_a_sandbox_root_that_contains_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A venv inside the checkout (the usual Linux/CI layout) must still show ``<site-packages>``.

    The sandbox roots are replaced first by :meth:`Sandbox.redact`; when the
    interpreter lives under the content root that turned
    ``<root>/.venv/lib/python3.12/site-packages/astropy/table.py`` into
    ``content:.venv/lib/...`` and the ``<site-packages>`` label never appeared
    (found by the CI on Linux, not on a laptop where the venv sits elsewhere).
    """
    import sys
    import sysconfig
    from pathlib import Path

    site_dir = sysconfig.get_paths()["purelib"]
    monkeypatch.setenv(ENV_WORK_DIR, str(tmp_path / "work"))
    # the content root is a directory that CONTAINS the running interpreter
    box = Sandbox.from_env(repo_root=Path(sys.prefix).parent)
    text = f'File "{site_dir}/astropy/table.py", line 3\nFile "{sys.prefix}/lib/x.py"\n'
    out = box.redact(text)
    assert "<site-packages>/astropy/table.py" in out, out
    assert "<python>/lib/x.py" in out, out
    assert site_dir not in out
    assert "content:" not in out.split("astropy")[0]
