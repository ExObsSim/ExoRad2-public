"""compare_configs: payload differences, tables, safety (spec 3.3, tool 13)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from astropy.table import Table
from payload_fixtures import find, make_payload, remove

from exorad.mcp import comparison, rules, tools_config
from exorad.mcp.sandbox import Sandbox

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def udir(tmp_path: Path) -> Path:
    path = tmp_path / "mcp-work" / "user"
    path.mkdir(parents=True)
    return path


def _paths(items: list[dict]) -> list[str]:
    return [item["path"] for item in items]


def test_payload_compares_with_itself(udir: Path) -> None:
    path = str(make_payload(udir))
    result = tools_config.compare_configs(path, path)
    assert result["identical"] is True
    assert result["differences"] == []
    assert result["only_in_first"] == []
    assert result["only_in_second"] == []


def test_example_compares_with_its_draft() -> None:
    draft = tools_config.draft_config()
    result = tools_config.compare_configs(
        "examples/payload_example.xml", draft["draft"]
    )
    assert "error" not in result, result
    # the draft only differs by what draft_config pins (the absolute ConfigPath is the same)
    assert result["identical"] is True, result["differences"]


def test_value_difference_with_units(udir: Path) -> None:
    first = make_payload(udir, name="a.xml")
    second = make_payload(
        udir,
        name="b.xml",
        edit=lambda r: (
            setattr(find(r, "channel[Spec]/detector/read_noise"), "text", "30"),
            find(r, "common/wl_min").set("unit", "nm"),
            setattr(find(r, "common/wl_min"), "text", "450"),
        ),
    )
    result = tools_config.compare_configs(str(first), str(second))
    assert result["identical"] is False
    by_path = {d["path"]: d for d in result["differences"]}
    read_noise = by_path["channel.Spec.detector.read_noise.value"]
    assert (read_noise["left"], read_noise["right"]) == ("15 ct", "30 ct")
    assert "15" in read_noise["summary"]
    # 450 nm vs 0.45 micron: a different unit string is reported, not silently equal
    assert "common.wl_min.unit" in by_path


def test_numeric_tolerance(udir: Path) -> None:
    first = make_payload(udir, name="a.xml")
    second = make_payload(
        udir,
        name="b.xml",
        edit=lambda r: setattr(find(r, "optics/Atel"), "text", "0.50000000000001"),
    )
    assert tools_config.compare_configs(str(first), str(second))["identical"] is True


def test_only_in_one_side(udir: Path) -> None:
    first = make_payload(udir, name="a.xml")
    second = make_payload(udir, name="b.xml", edit=lambda r: remove(r, "channel[Phot]"))
    result = tools_config.compare_configs(str(first), str(second))
    assert any(p.startswith("channel.Phot") for p in result["only_in_first"])
    assert result["only_in_second"] == []
    assert result["identical"] is False


def test_data_tables_are_compared(udir: Path) -> None:
    first = make_payload(udir, name="a.xml")
    other = udir / "other"
    other.mkdir()
    second = make_payload(other, name="b.xml")
    qe = other / "examples" / "QE.csv"
    qe.write_text(
        qe.read_text(encoding="utf-8").replace("\n0.", "\n0.9", 1), encoding="utf-8"
    )
    result = tools_config.compare_configs(str(first), str(second))
    changed = [d for d in result["differences"] if d["path"].endswith("qe.data")]
    assert changed
    assert "table" in changed[0]["summary"]


def test_files_of_both_payloads_resolve_independently(
    udir: Path, tmp_path: Path
) -> None:
    """Two projects, same relative names, different content: each uses its own files."""
    a = udir / "a"
    b = udir / "b"
    a.mkdir()
    b.mkdir()
    first = make_payload(a)
    second = make_payload(b)
    assert tools_config.compare_configs(str(first), str(second))["identical"] is True


def test_unparsable_file_is_reported_inside_the_result(udir: Path) -> None:
    good = make_payload(udir, name="a.xml")
    bad = udir / "bad.xml"
    bad.write_text("<root><common></root>", encoding="utf-8")
    result = tools_config.compare_configs(str(good), str(bad))
    assert result["identical"] is False
    assert result["valid"] is False
    assert result["errors"][0]["config"] == "second"
    assert result["errors"][0]["findings"][0]["code"] == "XML_PARSE"


def test_usage_errors_are_raised(udir: Path) -> None:
    good = str(make_payload(udir))
    with pytest.raises(FileNotFoundError):
        tools_config.compare_configs(good, "nope.xml")
    with pytest.raises(ValueError, match="outside"):
        tools_config.compare_configs(good, "/etc/hosts.xml")


def test_compare_never_loads_a_payload_with_errors(
    udir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("LoadOptions must not run")

    monkeypatch.setattr(rules, "LoadOptions", boom)
    bad = make_payload(
        udir,
        name="bad.xml",
        edit=lambda r: setattr(find(r, "common/sourceSpectrum"), "text", "sed"),
    )
    result = tools_config.compare_configs(str(bad), str(bad))
    assert result["valid"] is False
    assert result["errors"][0]["findings"][0]["code"] == "SOURCE_SED_BLOCKED"


def test_compare_configs_never_shows_external_link_values(udir: Path) -> None:
    """An .h5 datadict that links to another file is refused before any value is read."""
    h5py = pytest.importorskip("h5py")
    secret = udir / "secret.h5"
    with h5py.File(secret, "w") as handle:
        handle.create_dataset("password", data=[4242.0])
    linked = udir / "dd.h5"
    with h5py.File(linked, "w") as handle:
        handle["leak"] = h5py.ExternalLink("secret.h5", "/password")

    def add(root):  # type: ignore[no-untyped-def]
        import xml.etree.ElementTree as ET

        ET.SubElement(find(root, "common"), "datadict").text = "__ConfigPath__/dd.h5"

    path = make_payload(udir, name="p.xml", edit=add)
    result = tools_config.compare_configs(str(path), str(path))
    assert result["valid"] is False
    assert result["errors"][0]["findings"][0]["code"] == "HDF5_LINK_REFUSED"
    assert "4242" not in repr(result)


def test_values_differ_handles_arrays_and_tables() -> None:
    differ = comparison._values_differ
    assert not differ(np.arange(3.0), np.arange(3.0))
    assert differ(np.arange(3.0), np.arange(3.0) + 1)
    assert differ(np.arange(3.0), np.arange(4.0))
    same = Table({"a": [1.0, 2.0]})
    assert not differ(same, Table({"a": [1.0, 2.0]}))
    assert differ(same, Table({"a": [1.0, 3.0]}))
    assert differ(same, Table({"b": [1.0, 2.0]}))
    assert not differ(1.0, 1.0 + 1e-12)
    assert differ("a", "b")
    assert differ(1, "1")


def test_left_right_values_are_redacted(udir: Path) -> None:
    work = Sandbox.from_env().work_dir
    first = make_payload(
        udir,
        name="a.xml",
        edit=lambda r: setattr(find(r, "fileName"), "text", f"see {work}/x"),
    )
    second = make_payload(
        udir, name="b.xml", edit=lambda r: setattr(find(r, "fileName"), "text", "other")
    )
    result = tools_config.compare_configs(str(first), str(second))
    (diff,) = [d for d in result["differences"] if d["path"] == "fileName.value"]
    assert str(work) not in repr(result)
    assert diff["left"].startswith("see work:")
