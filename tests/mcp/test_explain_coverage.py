"""``explain_output`` and the output map, checked against a REAL ExoRad output.

The fixture is the one described in ``test_outputs.py`` (recipe:
``tests/mcp/data/make_output_fixture.py``). The coverage test walks EVERY node
of the file, so an output node ExoRad starts writing without an entry in
``output_map`` makes it fail.
"""

from __future__ import annotations

import json
import lzma
import math
import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest
from astropy import units as u
from astropy.io.misc.hdf5 import read_table_hdf5

from exorad.mcp import output_map, tools_output

REPO = Path(__file__).resolve().parents[2]
FIXTURE_XZ = Path(__file__).resolve().parent / "data" / "radiometric_small.h5.xz"


@pytest.fixture(scope="session")
def unpacked_fixture(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("exorad-fixture-x") / "radiometric_small.h5"
    path.write_bytes(lzma.decompress(FIXTURE_XZ.read_bytes()))
    return path


@pytest.fixture
def real_output(unpacked_fixture: Path, tmp_path: Path) -> Path:
    work = tmp_path / "mcp-work"
    work.mkdir(exist_ok=True)
    target = work / "out.h5"
    shutil.copy(unpacked_fixture, target)
    return target


def _all_nodes(path: Path) -> list[str]:
    nodes: list[str] = []
    with h5py.File(path, "r") as handle:
        handle.visit(nodes.append)
    return nodes


def test_every_node_of_a_real_run_is_explained(real_output: Path) -> None:
    result = tools_output.explain_output("out.h5")
    assert result["pipeline"] == "standard"
    assert result["unexplained"] == []
    assert result["unexplained_count"] == 0
    nodes = _all_nodes(real_output)
    assert result["total_nodes"] == len(nodes)
    assert result["explained_count"] == len(nodes)
    assert result["truncated"] is False
    json.dumps(result)


def test_explained_entries_are_complete_and_documented(real_output: Path) -> None:
    result = tools_output.explain_output("out.h5")
    assert len(result["explained"]) >= 30
    for entry in result["explained"]:
        assert entry["path_pattern"]
        assert entry["example_path"]
        assert len(entry["meaning"]) > 15, entry
        assert entry["produced_by"], entry
        assert entry["count"] >= 1
        doc = entry["doc"]
        assert doc is None or (REPO / doc).exists(), (entry["path_pattern"], doc)
    patterns = [e["path_pattern"] for e in result["explained"]]
    assert len(patterns) == len(set(patterns))


def test_an_unknown_node_is_reported_as_unexplained(real_output: Path) -> None:
    with h5py.File(real_output, "r+") as handle:
        handle.create_group("targets/myTest/brand_new_block").create_dataset(
            "x", data=[1.0]
        )
        handle.create_group("mystery")
    result = tools_output.explain_output("out.h5")
    assert set(result["unexplained"]) == {
        "targets/myTest/brand_new_block",
        "targets/myTest/brand_new_block/x",
        "mystery",
    }
    assert result["unexplained_count"] == 3


def test_unexplained_list_is_capped_but_counted(real_output: Path) -> None:
    with h5py.File(real_output, "r+") as handle:
        for index in range(30):
            handle.create_group(f"junk/g{index}")
    result = tools_output.explain_output("out.h5", max_items=10)
    assert len(result["unexplained"]) == 10
    assert result["unexplained_count"] == 31
    assert result["truncated"] is True


def test_explain_unknown_target_is_a_keyerror(real_output: Path) -> None:
    with pytest.raises(KeyError, match="nope"):
        tools_output.explain_output("out.h5", target="nope")


def test_every_map_pattern_that_the_fixture_misses_is_justified(
    real_output: Path,
) -> None:
    """Map hygiene: a pattern that matches nothing in a real run needs a reason."""
    nodes = _all_nodes(real_output)
    unmatched = [
        entry.display
        for entry in output_map.ENTRIES
        if not any(entry.regex.fullmatch(n) for n in nodes)
    ]
    assert set(unmatched) <= output_map.OPTIONAL_PATTERNS, sorted(
        set(unmatched) - output_map.OPTIONAL_PATTERNS
    )


# --- column semantics and the noise budget ------------------------------------
def _table(path: Path, target: str = "myTest"):
    with h5py.File(path, "r") as handle:
        return read_table_hdf5(handle[f"targets/{target}/table"], path="table")


def test_columns_follow_outputs_rst(real_output: Path) -> None:
    result = tools_output.explain_output("out.h5")
    columns = {c["name"]: c for c in result["columns"]}
    table = _table(real_output)
    assert set(columns) == set(table.colnames)
    assert columns["total_noise"]["unit"] == "h(1/2)"
    assert "relative" in columns["total_noise"]["meaning"].lower()
    assert columns["starSignal"]["unit"] == "ct / s"
    assert "ct/s" in columns["star_signal_inAperture"]["meaning"]
    assert "one-hour" in columns["zodi_signal_noise"]["meaning"].lower()
    assert "custom" in columns["gain_noise"]["meaning"].lower()
    for name, column in columns.items():
        assert column["meaning"], name


def test_noise_budget_matches_the_documented_total_noise(real_output: Path) -> None:
    """Independent recomputation of outputs.rst / total_noise.rst on the fixture."""
    result = tools_output.explain_output("out.h5")
    budget = result["noise_budget"]["myTest"]
    assert set(budget["channels"]) == {"Phot", "Spec"}
    assert "total_noise" in budget["note"]
    table = _table(real_output)
    star = np.asarray(table["star_signal_inAperture"].value, dtype=float)
    for name, info in budget["channels"].items():
        rows = np.asarray(table["chName"]) == name.encode()
        assert info["n_bins"] == int(rows.sum())
        # the components are expressed in sqrt(hr), rescaled by star_signal_inAperture
        for comp, stats in info["components"].items():
            column = table[comp]
            values = np.asarray(column.value, dtype=float)
            if column.unit != u.hr**0.5:
                values = values / star
            values = values[rows]
            assert stats["min"] == pytest.approx(np.nanmin(values), rel=1e-9)
            assert stats["max"] == pytest.approx(np.nanmax(values), rel=1e-9)
            assert stats["median"] == pytest.approx(np.nanmedian(values), rel=1e-9)
        total = np.asarray(table["total_noise"].value, dtype=float)[rows]
        assert info["total_noise"]["max"] == pytest.approx(np.nanmax(total), rel=1e-9)
        # total = sqrt(dc^2 + (1+NoiseX) photon^2 + rn^2)/S, plus custom in quadrature
        assert info["reconstruction"]["noiseX"] == pytest.approx(0.4)
        assert info["reconstruction"]["max_relative_difference"] < 1e-6
    # photometer band centre: stellar photon noise dominates for this star
    phot = budget["channels"]["Phot"]
    assert phot["dominant_component_at_band_centre"] == "star_signal_inAperture_noise"
    assert phot["band_centre_um"] == pytest.approx(0.55)
    assert set(phot["components"]) >= {
        "instrument_signal_noise",
        "skyFilter_signal_noise",
        "zodi_signal_noise",
        "star_signal_inAperture_noise",
        "darkcurrent_noise",
        "read_noise",
        "gain_noise",
    }
    assert phot["components"]["gain_noise"]["kind"] == "custom"
    assert phot["components"]["read_noise"]["kind"] == "detector"
    assert phot["components"]["zodi_signal_noise"]["kind"] == "photon"


def test_noise_budget_has_no_nan_in_json(real_output: Path) -> None:
    text = json.dumps(tools_output.explain_output("out.h5"), allow_nan=False)
    assert "NaN" not in text


def test_noise_budget_handles_zero_signal_rows(real_output: Path) -> None:
    """Rows with NaN total noise (zero aperture signal) do not break the stats."""
    with h5py.File(real_output, "r+") as handle:
        table = handle["targets/myTest/table/table"]
        data = table[()]
        data["total_noise"][3] = np.nan
        table[...] = data
    budget = tools_output.explain_output("out.h5")["noise_budget"]["myTest"]
    stats = budget["channels"]["Spec"]["total_noise"]
    assert all(
        v is None or math.isfinite(v) for v in stats.values() if not isinstance(v, str)
    )


def test_target_none_explains_at_most_five_targets(
    real_output: Path, tmp_path: Path
) -> None:
    with h5py.File(real_output, "r+") as handle:
        for index in range(7):
            handle.copy("targets/myTest", f"targets/extra{index}")
    result = tools_output.explain_output("out.h5")
    assert len(result["noise_budget"]) == 5
    one = tools_output.explain_output("out.h5", target="extra3")
    assert list(one["noise_budget"]) == ["extra3"]


def test_explain_on_a_table_file_gives_a_note(tmp_path: Path) -> None:
    work = tmp_path / "mcp-work"
    work.mkdir(exist_ok=True)
    (work / "t.csv").write_text("a,b\n1,2\n")
    result = tools_output.explain_output("t.csv")
    assert result["format"] == "csv"
    assert [c["name"] for c in result["columns"]] == ["a", "b"]
    assert result["pipeline"] == "standard"


def test_describe_path_handles_each_storage_form() -> None:
    """The three storage forms of a table share one meaning."""
    a = output_map.describe_path("targets/T/table/table")
    b = output_map.describe_path("targets/T/table/table.__table_column_meta__")
    c = output_map.describe_path("targets/T/table/table_to_group/total_noise/value")
    assert a
    assert b
    assert c
    assert a["path_pattern"] != b["path_pattern"]
    assert "total_noise" in c["meaning"] or "column" in c["meaning"].lower()
    assert output_map.describe_path("nothing/known/here") is None
