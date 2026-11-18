"""Tests for ``inspect_output`` against a small REAL ExoRad output file.

Fixture: ``tests/mcp/data/radiometric_small.h5.xz`` is the output of
``exorad.standard_pipeline`` for the example payload with ONE target
(``myTest``), ``working_R`` 1000, the demo SED and a decimated sky table, then
slimmed (PRF cropped, paths scrubbed) and xz-compressed (167 kB; 1.3 MB
unpacked). The recipe is the module docstring of
``tests/mcp/data/make_output_fixture.py``, which regenerates it::

    EXORAD_NO_VERSION_CHECK=1 python tests/mcp/data/make_output_fixture.py

The fixture is unpacked once per session into a temporary directory and copied
into each test's work directory.
"""

from __future__ import annotations

import json
import lzma
import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest

from exorad.mcp import tools_output
from exorad.mcp.sandbox import Sandbox

FIXTURE_XZ = Path(__file__).resolve().parent / "data" / "radiometric_small.h5.xz"


@pytest.fixture(scope="session")
def unpacked_fixture(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("exorad-fixture") / "radiometric_small.h5"
    path.write_bytes(lzma.decompress(FIXTURE_XZ.read_bytes()))
    return path


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    path = tmp_path / "mcp-work"
    path.mkdir(exist_ok=True)
    return path


@pytest.fixture
def real_output(unpacked_fixture: Path, work_dir: Path) -> Path:
    """The real fixture, copied into the work directory as ``out.h5``."""
    target = work_dir / "out.h5"
    shutil.copy(unpacked_fixture, target)
    return target


def test_fixture_is_small() -> None:
    assert FIXTURE_XZ.stat().st_size < 300_000


def test_inspect_real_output_summary(real_output: Path) -> None:
    result = tools_output.inspect_output("out.h5")
    assert result["format"] == "hdf5"
    assert result["path"] == "work:out.h5"
    assert result["root_attrs"]["program_name"] == "ExoRad2"
    summary = result["exorad"]
    assert summary["targets"] == ["myTest"]
    assert summary["n_targets"] == 1
    channels = {c["name"]: c for c in summary["channels"]}
    assert set(channels) == {"Phot", "Spec"}
    assert channels["Phot"]["class"] == "Photometer"
    assert channels["Spec"]["class"] == "Spectrometer"
    assert channels["Phot"]["n_bins"] == 1
    assert channels["Spec"]["n_bins"] == 12
    assert channels["Phot"]["wl_min_um"] == pytest.approx(0.5)
    assert channels["Phot"]["wl_max_um"] == pytest.approx(0.6)
    assert channels["Spec"]["wl_min_um"] == pytest.approx(1.1)
    # the last bin edge of the example spectrometer overshoots wl_max = 1.95 um
    assert channels["Spec"]["wl_max_um"] == pytest.approx(1.97544, rel=1e-4)
    assert "total_noise" in summary["table_columns"]
    assert "starSignal" in summary["table_columns"]
    json.dumps(result)  # JSON-serialisable


def test_inspect_walks_breadth_first_and_reports_truncation(real_output: Path) -> None:
    result = tools_output.inspect_output("out.h5", max_items=5)
    paths = [item["path"] for item in result["items"]]
    assert len(paths) == 5
    # breadth first: the three top-level groups come before any deep node
    assert {"info", "payload", "targets"} <= set(paths)
    assert all(p.count("/") <= 1 for p in paths)
    assert result["truncated"] is True
    assert result["total_nodes"] > 500


def test_inspect_items_are_annotated_by_the_output_map(real_output: Path) -> None:
    result = tools_output.inspect_output("out.h5", max_items=2000)
    by_path = {item["path"]: item for item in result["items"]}
    table = by_path["targets/myTest/table/table"]
    assert table["type"] == "dataset"
    assert table["shape"] == [13]
    assert "result table" in table["meaning"].lower()
    assert result["truncated"] is False


@pytest.mark.parametrize(("asked", "expected"), [(0, 1), (-3, 1), (10**6, 2000)])
def test_max_items_is_clamped(real_output: Path, asked: int, expected: int) -> None:
    result = tools_output.inspect_output("out.h5", max_items=asked)
    assert len(result["items"]) <= expected
    if expected == 1:
        assert len(result["items"]) == 1


def test_inspect_does_not_dump_arrays(real_output: Path) -> None:
    text = json.dumps(tools_output.inspect_output("out.h5", max_items=2000))
    assert len(text) < 400_000
    # scalars of the star block are shown, big arrays are not
    result = tools_output.inspect_output("out.h5", max_items=2000)
    star = {i["path"]: i for i in result["items"]}["targets/myTest/star/Teff/value"]
    assert star["value"] == 5000.0
    sed = {i["path"]: i for i in result["items"]}["targets/myTest/star/sed/data/value"]
    assert "value" not in sed


def test_inspect_by_bare_name_prefers_the_work_dir(real_output: Path) -> None:
    assert tools_output.inspect_output("out.h5")["path"] == "work:out.h5"
    absolute = tools_output.inspect_output(str(real_output))
    assert absolute["path"] == "work:out.h5"


def test_inspect_csv_and_ecsv(work_dir: Path) -> None:
    (work_dir / "t.csv").write_text("a,b\n1,2\n3,4\n")
    result = tools_output.inspect_output("t.csv")
    assert result["format"] == "csv"
    assert result["columns"] == ["a", "b"]
    assert result["row_count"] == 2


def test_inspect_reads_the_shipped_ecsv_tables_named_csv(work_dir: Path) -> None:
    """examples/*.csv are ECSV files (with a ``# %ECSV`` header): the library reads them so."""
    import shutil

    examples = Path(__file__).resolve().parents[2] / "examples"
    for name in ("QE.csv", "Spec-wl_sol.csv"):
        shutil.copy(examples / name, work_dir / name)
        result = tools_output.inspect_output(name)
        assert result["format"] == "csv"
        assert len(result["columns"]) >= 2, result
        assert result["row_count"] > 5
    (work_dir / "t.ecsv").write_text(
        "# %ECSV 1.0\n# ---\n# datatype:\n# - {name: a, datatype: int64}\n"
        "# - {name: b, datatype: int64}\na b\n1 2\n3 4\n"
    )
    assert tools_output.inspect_output("t.ecsv")["columns"] == ["a", "b"]


def test_inspect_rejects_unknown_suffix(work_dir: Path) -> None:
    (work_dir / "x.txt").write_text("hi")
    with pytest.raises(ValueError, match="Unsupported output format"):
        tools_output.inspect_output("x.txt")


def test_inspect_missing_file(work_dir: Path) -> None:
    with pytest.raises(FileNotFoundError) as caught:
        tools_output.inspect_output("nope.h5")
    assert str(work_dir) not in str(caught.value)


def test_inspect_not_an_hdf5_file(work_dir: Path) -> None:
    (work_dir / "bad.h5").write_text("this is not hdf5")
    with pytest.raises(OSError) as caught:
        tools_output.inspect_output("bad.h5")
    assert str(work_dir) not in str(caught.value)
    assert "bad.h5" in str(caught.value)


def test_inspect_refuses_a_directory(work_dir: Path) -> None:
    (work_dir / "dir.h5").mkdir()
    with pytest.raises(ValueError, match="not a regular file"):
        tools_output.inspect_output("dir.h5")


def test_inspect_outside_the_sandbox_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside" / "x.h5"
    outside.parent.mkdir()
    with h5py.File(outside, "w") as handle:
        handle.create_group("g")
    with pytest.raises(ValueError) as caught:
        tools_output.inspect_output(str(outside))
    assert str(tmp_path) not in str(caught.value).replace(str(outside), "")
    assert "outside" in str(caught.value)


def test_symlink_out_of_the_sandbox_is_refused(tmp_path: Path, work_dir: Path) -> None:
    secret = tmp_path / "elsewhere.h5"
    with h5py.File(secret, "w") as handle:
        handle.create_group("g")
    (work_dir / "link.h5").symlink_to(secret)
    with pytest.raises(ValueError, match="outside"):
        tools_output.inspect_output("link.h5")


def test_inspect_output_redacts_configpath(real_output: Path, work_dir: Path) -> None:
    """The payload description stores an absolute ConfigPath (H8): redacted."""
    leak = f"{work_dir}/some/config"
    with h5py.File(real_output, "r+") as handle:
        node = handle["payload/payload description/ConfigPath/value"]
        del handle["payload/payload description/ConfigPath/value"]
        handle["payload/payload description/ConfigPath/value"] = np.bytes_(leak)
        handle.attrs["note"] = f"made in {work_dir}/x"
        assert node is not None
    result = tools_output.inspect_output("out.h5", max_items=2000)
    text = json.dumps(result)
    assert str(work_dir) not in text
    sandbox = Sandbox.from_env()
    assert str(sandbox.repo_root) not in text
    by_path = {item["path"]: item for item in result["items"]}
    assert by_path["payload/payload description/ConfigPath/value"]["value"].startswith(
        "work:"
    )
    assert result["root_attrs"]["note"].startswith("made in work:")


def test_h5py_error_text_does_not_leak_the_path(work_dir: Path) -> None:
    broken = work_dir / "trunc.h5"
    broken.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\0" * 20)
    with pytest.raises(OSError) as caught:
        tools_output.inspect_output("trunc.h5")
    assert str(work_dir) not in str(caught.value)


def test_oversized_file_is_refused(
    real_output: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # EXORAD_MCP_MAX_OUTPUT_MB is an integer number of MB: shrink the file limit
    # by padding past 1 MB under a limit of 1.
    monkeypatch.setenv("EXORAD_MCP_MAX_OUTPUT_MB", "1")
    assert real_output.stat().st_size > 1_048_576
    with pytest.raises(ValueError, match="limit"):
        tools_output.inspect_output("out.h5")
