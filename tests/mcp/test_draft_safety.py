"""draft_config / draft_target_list never write unsafe values or overwrite silently."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

import pytest
from payload_fixtures import REPO_ROOT

from exorad.mcp import authoring, tools_config
from exorad.mcp.sandbox import Sandbox

if TYPE_CHECKING:
    from pathlib import Path


def _work() -> Path:
    return Sandbox.from_env().work_dir


def _draft_text(result: dict) -> str:
    return (_work() / result["draft"]).read_text(encoding="utf-8")


# --------------------------------------------------------------------------------
# the plain draft
# --------------------------------------------------------------------------------
def test_default_draft_is_valid_and_usable_by_the_other_tools() -> None:
    result = tools_config.draft_config()
    assert result["valid"], result["findings"]
    assert result["based_on"] == "examples/payload_example.xml"
    assert result["draft"] == "drafts/payload_draft.xml"  # relative to the work dir
    assert result["applied"] == []
    assert result["not_applied"] == []
    assert "common" in result["top_level_sections"]
    again = tools_config.validate_config(result["draft"])  # found in the work dir
    assert again["valid"], again["findings"]
    assert str(_work()) not in repr(result)


def test_draft_pins_configpath_absolute() -> None:
    result = tools_config.draft_config()
    root = ET.fromstring(_draft_text(result))
    assert root.find("ConfigPath").text == str(REPO_ROOT)


def test_draft_applies_overrides_with_units_and_repeated_tags() -> None:
    result = tools_config.draft_config(
        {
            "common.wl_min": "0.5 micron",
            "channel.Spec.detector.read_noise": "20",
            "channel.Phot.aperture.radius": "8.5",
        }
    )
    assert result["valid"], result["findings"]
    assert [a["path"] for a in result["applied"]] == [
        "common.wl_min",
        "channel.Spec.detector.read_noise",
        "channel.Phot.aperture.radius",
    ]
    root = ET.fromstring(_draft_text(result))
    wl = root.find("common/wl_min")
    assert (wl.text, wl.get("unit")) == ("0.5", "micron")
    spec = next(c for c in root.findall("channel") if (c.text or "").strip() == "Spec")
    assert spec.find("detector/read_noise").text == "20"


def test_unknown_paths_are_reported_not_applied() -> None:
    result = tools_config.draft_config(
        {
            "channel.Nope.detector.read_noise": "1",
            "common.nothing": "2",
            "common.wl_min": "0.6 micron",
        }
    )
    reasons = {item["path"]: item for item in result["not_applied"]}
    assert set(reasons) == {"channel.Nope.detector.read_noise", "common.nothing"}
    assert "Phot" in reasons["channel.Nope.detector.read_noise"]["available"]
    assert "wl_min" in reasons["common.nothing"]["available"]
    assert [a["path"] for a in result["applied"]] == ["common.wl_min"]


def test_draft_works_with_execution_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXORAD_MCP_NO_EXEC", "1")
    assert tools_config.draft_config()["valid"]


# --------------------------------------------------------------------------------
# name and overwrite
# --------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["../x", "a/b", "", "x" * 41, ".hidden", "a b", "a.b"])
def test_draft_name_validation(name: str) -> None:
    with pytest.raises(ValueError, match="name"):
        tools_config.draft_config(name=name)
    with pytest.raises(ValueError, match="name"):
        tools_config.draft_target_list(
            [{"name": "a", "M": 1, "Teff": 5000, "R": 1, "D": 10}], name=name
        )
    assert not (_work() / "drafts").exists()


def test_good_draft_names() -> None:
    result = tools_config.draft_config(name="my-draft_1")
    assert result["draft"] == "drafts/my-draft_1_draft.xml"


def test_existing_draft_is_not_overwritten_by_default() -> None:
    first = tools_config.draft_config()
    with pytest.raises(FileExistsError, match="overwrite=True"):
        tools_config.draft_config({"common.wl_min": "0.563 micron"})
    assert "0.563" not in _draft_text(first)  # the first draft is untouched

    again = tools_config.draft_config({"common.wl_min": "0.563 micron"}, overwrite=True)
    assert 'unit="micron">0.563<' in _draft_text(again)


# --------------------------------------------------------------------------------
# refusals: nothing is written
# --------------------------------------------------------------------------------
def test_config_path_outside_the_sandbox_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(ValueError, match="outside the directories"):
        tools_config.draft_config({"ConfigPath": str(outside)})


def test_config_path_inside_the_checkout_is_accepted() -> None:
    inside = str(REPO_ROOT / "examples")
    result = tools_config.draft_config({"ConfigPath": inside})
    assert {"path": "ConfigPath", "value": inside} in result["applied"]


def test_override_path_outside_sandbox_refused() -> None:
    for value in ("/etc/hosts", "../../../etc/hosts", "~/secret.csv"):
        with pytest.raises(ValueError, match="outside the directories"):
            tools_config.draft_config({"channel.Spec.detector.qe.datafile": value})
    assert not (_work() / "drafts").exists()


def test_unsafe_override_is_refused_even_when_the_element_does_not_exist() -> None:
    """Not applied is not enough: the request itself is refused."""
    with pytest.raises(ValueError, match="outside the directories"):
        tools_config.draft_config({"common.datafile": "/etc/hosts"})
    with pytest.raises(ValueError, match="URL"):
        tools_config.draft_config({"common.datafile": "https://example.com/x.csv"})
    assert not (_work() / "drafts").exists()


def test_refused_override_writes_no_draft() -> None:
    with pytest.raises(ValueError, match="outside the directories"):
        tools_config.draft_config({"ConfigPath": "/definitely/not/allowed"})
    assert not (_work() / "drafts").exists()


@pytest.mark.parametrize("value", ["http://example.com/qe.csv", "file:///etc/hosts"])
def test_url_override_is_refused(value: str) -> None:
    with pytest.raises(ValueError, match="URL"):
        tools_config.draft_config({"channel.Spec.detector.qe.datafile": value})
    assert not (_work() / "drafts").exists()


@pytest.mark.parametrize("tag", ["datadict", "config_dict"])
@pytest.mark.parametrize("value", ["evil.pickle", "/tmp/x.PKL", "run.py"])
def test_pickle_datadict_override_refused(tag: str, value: str) -> None:
    """The element need not exist in the example: the refusal comes first."""
    with pytest.raises(ValueError, match="arbitrary code"):
        tools_config.draft_config({f"common.{tag}": value})
    assert not (_work() / "drafts").exists()


def test_pickle_value_is_refused_for_any_path_key() -> None:
    with pytest.raises(ValueError, match="arbitrary code"):
        tools_config.draft_config({"channel.Spec.detector.qe.datafile": "x.pickle"})


@pytest.mark.parametrize("value", ["sed", "SED", " Sed "])
def test_draft_sed_override_refused(value: str) -> None:
    with pytest.raises(ValueError, match="network"):
        tools_config.draft_config({"common.sourceSpectrum": value})
    assert not (_work() / "drafts").exists()


def test_other_sources_may_be_chosen() -> None:
    result = tools_config.draft_config({"common.sourceSpectrum": "planck"})
    assert result["valid"], result["findings"]


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"common.working_R": "30001"}, "working_R"),
        ({"channel.Spec.targetR": "1000000"}, "bins"),
    ],
)
def test_limits_are_enforced_on_overrides(override: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        tools_config.draft_config(override)
    assert not (_work() / "drafts").exists()


def test_keyword_paths_inside_the_content_root_are_accepted() -> None:
    result = tools_config.draft_config(
        {"channel.Spec.wlSolution.datafile": "__ConfigPath__/examples/Spec-wl_sol.csv"}
    )
    assert result["valid"], result["findings"]


def test_draft_with_a_missing_file_is_written_but_invalid() -> None:
    result = tools_config.draft_config(
        {
            "channel.Spec.wlSolution.datafile": "__ConfigPath__/examples/does-not-exist.csv"
        }
    )
    assert result["valid"] is False
    assert [f["code"] for f in result["findings"]] == ["FILE_MISSING"]
    assert (_work() / result["draft"]).is_file()


def test_override_values_are_escaped() -> None:
    result = tools_config.draft_config({"fileName": "a<b>&c"})
    assert ET.fromstring(_draft_text(result)).find("fileName").text == "a<b>&c"


def test_check_override_unit() -> None:
    box = Sandbox.from_env()
    authoring.check_override("working_R", "6000", sandbox=box, base=REPO_ROOT)
    authoring.check_override(
        "fileName", "model.py", sandbox=box, base=REPO_ROOT
    )  # not a path key
    with pytest.raises(ValueError, match="arbitrary code"):
        authoring.check_override("datafile", "model.py", sandbox=box, base=REPO_ROOT)


def test_example_missing_is_an_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from exorad.mcp.assets import ContentMissingError

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("EXORAD_MCP_REPO_ROOT", str(empty))
    with pytest.raises(ContentMissingError, match="reinstall exorad"):
        tools_config.draft_config()


# --------------------------------------------------------------------------------
# draft_target_list
# --------------------------------------------------------------------------------
TARGETS = [
    {"name": "alpha", "M": 1.0, "Teff": 5000, "R": 1.0, "D": 20.0},
    {"name": "beta", "M": 1.5, "Teff": 6000, "R": 1.2, "D": 10.0},
]


def test_draft_target_list_round_trip() -> None:
    result = tools_config.draft_target_list(TARGETS)
    assert result["valid"], result["findings"]
    assert result["draft"] == "drafts/targets.csv"
    assert result["rows"] == 2
    assert result["columns"][0] == "star name"
    validated = tools_config.validate_config(result["draft"])
    assert validated["valid"]
    assert validated["summary"]["names"] == ["alpha", "beta"]


def test_draft_target_list_is_not_overwritten_by_default() -> None:
    tools_config.draft_target_list(TARGETS)
    with pytest.raises(FileExistsError, match="overwrite=True"):
        tools_config.draft_target_list(TARGETS[:1])
    again = tools_config.draft_target_list(TARGETS[:1], overwrite=True)
    assert again["rows"] == 1


def test_bad_rows_write_nothing() -> None:
    with pytest.raises(ValueError, match="Teff"):
        tools_config.draft_target_list([{"name": "a", "M": 1, "R": 1, "D": 10}])
    with pytest.raises(ValueError, match="name"):
        tools_config.draft_target_list([{**TARGETS[0], "name": "../x"}])
    assert not (_work() / "drafts").exists()


def test_target_count_limit_applies_to_drafts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXORAD_MCP_MAX_TARGETS", "1")
    with pytest.raises(ValueError, match="EXORAD_MCP_MAX_TARGETS"):
        tools_config.draft_target_list(TARGETS)
    assert not (_work() / "drafts").exists()


def test_optional_columns() -> None:
    rows = [{**r, "magk": 3.0, "ra": 10.0, "dec": 5.0} for r in TARGETS]
    result = tools_config.draft_target_list(rows, name="sky")
    assert result["valid"]
    assert result["columns"][-3:] == ["star magk", "star ra [deg]", "star dec [deg]"]


# --------------------------------------------------------------------------------
# through the real stdio server (real tools, no stubs)
# --------------------------------------------------------------------------------
def test_config_tools_over_stdio(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.mcpserver", reason="requires the 'mcp' extra")
    from stdio_helper import result_text, run_stdio_requests

    outside = tmp_path / "elsewhere"
    outside.mkdir()
    requests = [
        ("tools/list", {}),
        (
            "tools/call",
            {
                "name": "draft_config",
                "arguments": {"overrides": {"ConfigPath": str(outside)}},
            },
        ),
        (
            "tools/call",
            {
                "name": "validate_config",
                "arguments": {"configuration": "examples/test_target.csv"},
            },
        ),
        (
            "tools/call",
            {
                "name": "validate_config",
                "arguments": {"configuration": "examples/nope.xml"},
            },
        ),
    ]
    _, (listing, refused, valid, missing), _ = run_stdio_requests(
        requests, work_dir=tmp_path / "work", stubs=""
    )
    tools = {t["name"]: t for t in listing["result"]["tools"]}
    for name in (
        "config_requirements",
        "draft_config",
        "draft_target_list",
        "validate_config",
        "compare_configs",
    ):
        assert name in tools, sorted(tools)
    assert "targets" in tools["draft_target_list"]["inputSchema"]["properties"]
    assert refused["result"]["isError"] is True
    assert "outside the directories this MCP server may read" in result_text(refused)
    assert not (tmp_path / "work" / "drafts").exists()
    assert valid["result"]["isError"] is False
    assert '"valid": true' in result_text(valid)
    assert missing["result"]["isError"] is True
    assert "file not found: content:examples/nope.xml" in result_text(missing)
