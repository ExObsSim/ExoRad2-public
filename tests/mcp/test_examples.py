"""Tests for ``list_examples``: the catalogue of the bundled example inputs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from exorad.mcp import tools_info
from exorad.mcp.examples import list_example_configs

if TYPE_CHECKING:
    from pathlib import Path


def _by_path(result: dict) -> dict[str, dict]:
    return {entry["path"]: entry for entry in result["examples"]}


def test_list_examples_in_a_checkout() -> None:
    result = tools_info.list_examples()
    entries = _by_path(result)
    assert result["count"] == len(result["examples"]) >= 3

    payload = entries["examples/payload_example.xml"]
    assert payload["kind"] == "payload"
    assert payload["runnable"] is True
    assert payload["needs"] == []
    assert payload["size_bytes"] > 1000
    assert payload["packaged"] is True

    target = entries["examples/test_target.csv"]
    assert target["kind"] == "target_list"
    assert target["runnable"] is True

    assert entries["examples/QE.csv"]["kind"] == "data_table"
    assert entries["examples/QE.csv"]["runnable"] is False


def test_the_full_sed_is_listed_but_not_packaged() -> None:
    entries = _by_path(list_example_configs())
    sed = entries["examples/customsed.csv"]
    assert sed["kind"] == "data_table"
    assert sed["packaged"] is False
    assert sed["size_bytes"] > 1_048_576


def test_payload_references_are_the_real_elements_not_comments() -> None:
    payload = _by_path(list_example_configs())["examples/payload_example.xml"]
    refs = {ref["path"] for ref in payload["references"]}
    assert {
        "examples/customsed.csv",
        "examples/QE.csv",
        "examples/Spec-wl_sol.csv",
        "examples/modtran_38km_sun_180az_55zd_los_45zd.csv",
    } <= refs
    # mentioned only inside XML comments in the example
    assert "examples/custom_noise.csv" not in refs
    assert all(ref["exists"] for ref in payload["references"])


def test_non_data_files_are_not_listed() -> None:
    paths = set(_by_path(list_example_configs()))
    assert "examples/quickstart.ipynb" not in paths
    assert "examples/quickstart.pdf" not in paths


@pytest.fixture
def packaged_like(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A content root as the wheel ships it: demo SED, no customsed.csv."""
    root = tmp_path / "content"
    (root / "examples").mkdir(parents=True)
    (root / "examples" / "payload_example.xml").write_text(
        "<root>\n"
        "  <ConfigPath>.</ConfigPath>\n"
        "  <common><sourceSpectrum>custom\n"
        "    <CustomSed>__ConfigPath__/examples/customsed_demo.csv</CustomSed>\n"
        "  </sourceSpectrum></common>\n"
        "  <channel>Spec<detector><datafile>__ConfigPath__/examples/QE.csv</datafile>"
        "</detector></channel>\n"
        "</root>\n",
        encoding="utf-8",
    )
    (root / "examples" / "QE.csv").write_text("Wavelength,Phot\n1,0.5\n")
    (root / "examples" / "customsed_demo.csv").write_text("Wavelength,Sed\n1,2\n")
    (root / "examples" / "test_target.csv").write_text(
        "star name,star M [M_sun]\nA,1\n"
    )
    monkeypatch.setenv("EXORAD_MCP_REPO_ROOT", str(root))
    return root


def test_packaged_payload_is_runnable_and_flags_the_demo_sed(
    packaged_like: Path,
) -> None:
    payload = _by_path(list_example_configs())["examples/payload_example.xml"]
    assert payload["runnable"] is True
    assert payload["note"] == "uses the reduced-resolution demo SED"
    assert any(
        r["path"] == "examples/customsed_demo.csv" for r in payload["references"]
    )


def test_missing_reference_makes_the_payload_not_runnable(packaged_like: Path) -> None:
    (packaged_like / "examples" / "QE.csv").unlink()
    payload = _by_path(list_example_configs())["examples/payload_example.xml"]
    assert payload["runnable"] is False
    assert payload["needs"] == ["examples/QE.csv"]


def test_phoenix_models_directory_is_a_reference_only_for_phoenix(
    packaged_like: Path,
) -> None:
    xml = (
        "<root><ConfigPath>.</ConfigPath><common><sourceSpectrum>{src}\n"
        "<StellarModels>/nonexistent/phoenix</StellarModels></sourceSpectrum></common></root>"
    )
    (packaged_like / "examples" / "phoenix.xml").write_text(xml.format(src="phoenix"))
    (packaged_like / "examples" / "planck.xml").write_text(xml.format(src="planck"))
    entries = _by_path(list_example_configs())
    assert entries["examples/phoenix.xml"]["runnable"] is False
    assert entries["examples/planck.xml"]["runnable"] is True


def test_unparsable_payload_is_listed_without_references(packaged_like: Path) -> None:
    (packaged_like / "examples" / "broken.xml").write_text("<root><oops></root>")
    entry = _by_path(list_example_configs())["examples/broken.xml"]
    assert entry["kind"] == "payload"
    assert entry["references"] == []


def test_empty_content_root_gives_an_empty_catalogue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXORAD_MCP_REPO_ROOT", str(tmp_path))
    assert list_example_configs() == {"examples": [], "count": 0}
