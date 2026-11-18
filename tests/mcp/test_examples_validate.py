"""Every shipped example entry point validates, in the checkout and in the wheel layout."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from payload_fixtures import REPO_ROOT

from exorad.mcp import tools_config
from exorad.mcp.assets import collect_assets
from exorad.mcp.examples import list_example_configs

if TYPE_CHECKING:
    from pathlib import Path

_LISTING = list_example_configs(str(REPO_ROOT))["examples"]
_PAYLOADS = [e["path"] for e in _LISTING if e["kind"] == "payload"]
_TARGET_LISTS = [e["path"] for e in _LISTING if e["kind"] == "target_list"]


def test_entry_points_are_listed() -> None:
    assert "examples/payload_example.xml" in _PAYLOADS
    assert "examples/test_target.csv" in _TARGET_LISTS


@pytest.mark.parametrize("example", _PAYLOADS)
def test_example_entry_point_validates(example: str) -> None:
    result = tools_config.validate_config(example)
    assert result["valid"], result["findings"]
    assert result["findings"] == []


@pytest.mark.parametrize("example", _TARGET_LISTS)
def test_example_target_list_validates(example: str) -> None:
    result = tools_config.validate_config(example)
    assert result["valid"], result["findings"]


def test_every_example_entry_point_runs_validate_and_draft() -> None:
    """The reference example is also the draft_config base."""
    draft = tools_config.draft_config()
    assert draft["valid"], draft["findings"]
    assert tools_config.validate_config(draft["draft"])["valid"]
    drafted = tools_config.draft_target_list(
        [{"name": "x", "M": 1, "Teff": 5000, "R": 1, "D": 10}]
    )
    assert drafted["valid"]


@pytest.fixture
def packaged_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A content root built by the real wheel transform (``collect_assets``)."""
    data = tmp_path / "pkg" / "_data"
    collect_assets(REPO_ROOT, data, tracked_only=True)
    monkeypatch.setenv("EXORAD_MCP_REPO_ROOT", str(data))
    return data


def test_collected_tree_example_validates_with_the_demo_sed(
    packaged_tree: Path,
) -> None:
    assert not (packaged_tree / "examples" / "customsed.csv").exists()
    result = tools_config.validate_config("examples/payload_example.xml")
    assert result["valid"], result["findings"]
    sed = [r for r in result["referenced_files"] if r["tag"] == "CustomSed"]
    assert [r["path"] for r in sed] == ["content:examples/customsed_demo.csv"]
    assert (
        result["findings"] == []
    )  # the example range is inside the finely sampled segment
    assert tools_config.validate_config("examples/test_target.csv")["valid"]


def test_collected_tree_deep_validation_and_drafts(packaged_tree: Path) -> None:
    deep = tools_config.validate_config("examples/payload_example.xml", deep=True)
    assert deep["valid"], deep["findings"]
    assert {c["name"] for c in deep["channels"]} == {"Phot", "Spec"}
    draft = tools_config.draft_config({"common.wl_min": "0.5 micron"})
    assert draft["valid"], draft["findings"]
    assert tools_config.validate_config(draft["draft"], deep=True)["valid"]


def test_collected_tree_requirements_point_to_the_docs(packaged_tree: Path) -> None:
    result = tools_config.config_requirements("payload", "examples/payload_example.xml")
    assert result["missing"] == []
    assert any(row.get("see") for row in result["reference"])
