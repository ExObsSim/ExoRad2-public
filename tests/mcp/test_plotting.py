"""``plot_output``: table and efficiency figures from a REAL output file.

The fixture is the one described in ``test_outputs.py``. Plots are rendered by
``exorad.mcp.plotting:render`` through ``JobManager.run_sync`` (in-process with
the ``inline`` backend used by the test suite; one test uses the real spawned
child).
"""

from __future__ import annotations

import lzma
import re
import shutil
from pathlib import Path

import h5py
import pytest

from exorad.mcp import tools_output
from exorad.mcp.sandbox import Sandbox

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
FIXTURE_XZ = Path(__file__).resolve().parent / "data" / "radiometric_small.h5.xz"


@pytest.fixture(scope="session")
def unpacked_fixture(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("exorad-fixture-p") / "radiometric_small.h5"
    path.write_bytes(lzma.decompress(FIXTURE_XZ.read_bytes()))
    return path


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    path = tmp_path / "mcp-work"
    path.mkdir(exist_ok=True)
    return path


@pytest.fixture
def real_output(unpacked_fixture: Path, work_dir: Path) -> Path:
    target = work_dir / "out.h5"
    shutil.copy(unpacked_fixture, target)
    return target


def _check_png(path: Path) -> None:
    assert path.is_file()
    data = path.read_bytes()
    assert len(data) > 2000
    assert data.startswith(PNG_MAGIC)


def test_plot_table_writes_one_png_per_target(
    real_output: Path, work_dir: Path
) -> None:
    result = tools_output.plot_output("out.h5")
    assert result["kind"] == "table"
    assert result["figures"] == ["table-myTest.png"]
    assert result["warnings"] == []
    assert result["output_dir"].startswith("work:plots/")
    folder = work_dir / "plots" / result["output_dir"].split("plots/")[1]
    _check_png(folder / "table-myTest.png")
    assert str(work_dir) not in str(result)


def test_plot_efficiency_writes_one_png(real_output: Path, work_dir: Path) -> None:
    result = tools_output.plot_output("out.h5", kind="efficiency")
    assert result["kind"] == "efficiency"
    assert result["figures"] == ["efficiency.png"]
    folder = work_dir / "plots" / result["output_dir"].split("plots/")[1]
    _check_png(folder / "efficiency.png")
    assert {c["name"] for c in result["channels"]} == {"Phot", "Spec"}


def test_plot_output_stays_under_the_work_dir(
    real_output: Path, work_dir: Path
) -> None:
    before = set(real_output.parent.rglob("*"))
    tools_output.plot_output("out.h5")
    tools_output.plot_output("out.h5", kind="efficiency")
    created = set(real_output.parent.rglob("*")) - before
    assert created
    assert all(p == work_dir or work_dir in p.parents for p in created)
    assert all(p.suffix == ".png" or p.is_dir() for p in created)


def test_plot_png_never_leaves_run_dir(real_output: Path, work_dir: Path) -> None:
    """Hostile target names are sanitised to file names inside the plot folder."""
    with h5py.File(real_output, "r+") as handle:
        handle.move("targets/myTest", "targets/..")
        handle.copy("targets/..", "targets/..%2f..%2fevil")
        handle.copy("targets/..", "targets/.hidden: a*b?")
    result = tools_output.plot_output("out.h5")
    assert len(result["figures"]) == 3
    assert result["warnings"] == []
    folder = work_dir / "plots" / result["output_dir"].split("plots/")[1]
    assert sorted(p.name for p in folder.iterdir()) == sorted(result["figures"])
    assert "table-target.png" in result["figures"]  # the target literally named ".."
    for name in result["figures"]:
        assert re.fullmatch(r"[\w.+\-() ]+", name), name  # no %, :, *, ? ...
        assert "/" not in name
        assert not name.startswith(".")
        assert (folder / name).resolve().parent == folder.resolve()
        _check_png(folder / name)
    assert not (work_dir.parent / "evil.png").exists()


def test_two_targets_with_the_same_safe_stem_do_not_overwrite(
    real_output: Path, work_dir: Path
) -> None:
    with h5py.File(real_output, "r+") as handle:
        handle.copy("targets/myTest", "targets/a:b")
        handle.copy("targets/myTest", "targets/a*b")
    result = tools_output.plot_output("out.h5", target=None)
    assert len(set(result["figures"])) == len(result["figures"]) == 3


def test_plot_selects_a_target_and_rejects_unknown(real_output: Path) -> None:
    result = tools_output.plot_output("out.h5", target="myTest")
    assert result["figures"] == ["table-myTest.png"]
    with pytest.raises(KeyError, match="nope"):
        tools_output.plot_output("out.h5", target="nope")


def test_plot_bad_kind_is_a_valueerror(real_output: Path) -> None:
    with pytest.raises(ValueError, match="kind"):
        tools_output.plot_output("out.h5", kind="movie")


def test_plot_first_five_targets_by_default(real_output: Path) -> None:
    with h5py.File(real_output, "r+") as handle:
        for index in range(6):
            handle.copy("targets/myTest", f"targets/extra{index}")
    result = tools_output.plot_output("out.h5")
    assert len(result["figures"]) == 5
    assert result["total_targets"] == 7


def test_plot_a_broken_table_is_a_warning_not_a_failure(
    real_output: Path, work_dir: Path
) -> None:
    with h5py.File(real_output, "r+") as handle:
        handle.copy("targets/myTest", "targets/broken")
        del handle["targets/broken/table/table"]
    result = tools_output.plot_output("out.h5")
    assert result["figures"] == ["table-myTest.png"]
    assert len(result["warnings"]) == 1
    assert "broken" in result["warnings"][0]
    assert str(work_dir) not in result["warnings"][0]


def test_not_plottable_is_a_structured_result(real_output: Path) -> None:
    with h5py.File(real_output, "r+") as handle:
        del handle["targets"]
    result = tools_output.plot_output("out.h5")
    assert result["plottable"] is False
    assert result["figures"] == []
    assert "targets" in result["reason"]
    efficiency = tools_output.plot_output("out.h5", kind="efficiency")
    assert efficiency["plottable"] is True


def test_efficiency_without_built_instrument_is_not_plottable(
    real_output: Path,
) -> None:
    with h5py.File(real_output, "r+") as handle:
        del handle["payload/channels"]
    result = tools_output.plot_output("out.h5", kind="efficiency")
    assert result["plottable"] is False
    assert "channels" in result["reason"]


def test_plot_refuses_non_hdf5_input(work_dir: Path) -> None:
    (work_dir / "t.csv").write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="HDF5"):
        tools_output.plot_output("t.csv")


def test_plots_dir_symlinked_out_of_the_sandbox_is_refused(
    real_output: Path, work_dir: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (work_dir / "plots").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ValueError, match="outside"):
        tools_output.plot_output("out.h5")
    assert list(elsewhere.iterdir()) == []


def test_plot_output_is_an_execution_only_tool_run_in_a_child() -> None:
    from exorad.mcp import tools

    entries = {e.name: e for e in tools.REGISTRY}
    assert entries["plot_output"].execution_only is True
    assert entries["inspect_output"].execution_only is False
    assert entries["explain_output"].execution_only is False


def test_render_entry_is_allowed_by_the_job_manager() -> None:
    from exorad.mcp import jobs

    jobs._check_entry("exorad.mcp.plotting:render")


def test_plot_in_a_real_spawned_child(
    real_output: Path, work_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real process backend: plots are rendered by a spawned child."""
    monkeypatch.setenv("EXORAD_MCP_EXEC_BACKEND", "process")
    result = tools_output.plot_output("out.h5", kind="efficiency")
    assert result["figures"] == ["efficiency.png"]
    folder = work_dir / "plots" / result["output_dir"].split("plots/")[1]
    _check_png(folder / "efficiency.png")
    sandbox = Sandbox.from_env()
    assert sandbox.work_dir == work_dir.resolve()


def test_child_crash_is_returned_as_an_error_with_no_paths(
    real_output: Path, work_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from exorad.mcp import jobs

    def boom(entry, spec, *, timeout, **_kw):
        raise RuntimeError(f"child failed in {work_dir}/secret/place")

    monkeypatch.setattr(jobs.JOBS, "run_sync", boom)
    result = tools_output.plot_output("out.h5")
    assert result["figures"] == []
    assert "error" in result
    assert str(work_dir) not in result["error"]
