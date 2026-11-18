"""``validate_config`` and ``config_requirements`` (spec 3.3, tools 9 and 12)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from payload_fixtures import find, make_payload, remove

from exorad.mcp import configuration, rules, tools_config
from exorad.mcp.sandbox import PathNotAllowedError


@pytest.fixture
def udir(tmp_path: Path) -> Path:
    """A project directory inside the work dir the tools are configured with."""
    path = tmp_path / "mcp-work" / "user"
    path.mkdir(parents=True)
    return path


def _codes(result: dict, severity: str | None = None) -> list[str]:
    return [
        f["code"]
        for f in result["findings"]
        if severity is None or f["severity"] == severity
    ]


# --------------------------------------------------------------------------------
# the checkout examples
# --------------------------------------------------------------------------------
def test_example_entry_point_validates() -> None:
    result = tools_config.validate_config("examples/payload_example.xml")
    assert result["valid"], result["findings"]
    assert result["kind"] == "payload"
    assert result["findings"] == []
    assert result["configuration"] == "content:examples/payload_example.xml"
    assert {ref["tag"] for ref in result["referenced_files"]} == {
        "CustomSed",
        "datafile",
    }
    assert all(ref["exists"] and ref["allowed"] for ref in result["referenced_files"])
    summary = result["summary"]
    assert summary["working_R"] == 6000
    assert summary["source"] == "custom"
    assert [c["name"] for c in summary["channels"]] == ["Phot", "Spec"]
    assert "common" in summary["top_level_sections"]
    # nothing but display paths in the result
    assert str(Path(__file__).resolve().parents[2]) not in repr(result)


def test_example_target_list_validates() -> None:
    result = tools_config.validate_config("examples/test_target.csv")
    assert result["valid"], result["findings"]
    assert result["kind"] == "target_list"
    assert result["summary"]["targets"] == 2
    assert result["summary"]["names"] == ["myTest", "myTest2"]


def test_kind_can_be_given_explicitly() -> None:
    assert tools_config.validate_config("examples/test_target.csv", kind="target_list")[
        "valid"
    ]
    with pytest.raises(ValueError, match="payload"):
        tools_config.validate_config("examples/test_target.csv", kind="payload")
    with pytest.raises(ValueError, match="kind"):
        tools_config.validate_config("examples/test_target.csv", kind="recipe")


def test_unknown_suffix_is_a_usage_error() -> None:
    with pytest.raises(ValueError, match=r"\.xml.*\.csv"):
        tools_config.validate_config("README.md")


def test_missing_file_and_outside_paths_raise() -> None:
    with pytest.raises(FileNotFoundError):
        tools_config.validate_config("examples/nope.xml")
    with pytest.raises(PathNotAllowedError, match="outside"):
        tools_config.validate_config("/etc/hosts.xml")
    with pytest.raises(ValueError, match="URL"):
        tools_config.validate_config("http://example.com/p.xml")


# --------------------------------------------------------------------------------
# resolution: work dir first, normalised copy, no chdir
# --------------------------------------------------------------------------------
def test_work_dir_wins_over_content_root(tmp_path: Path) -> None:
    (tmp_path / "mcp-work" / "examples").mkdir(parents=True)
    (tmp_path / "mcp-work" / "examples" / "test_target.csv").write_text(
        "star name,star M [M_sun],star Teff [K],star R [R_sun],star D [pc]\nonly,1,5000,1,20\n",
        encoding="utf-8",
    )
    result = tools_config.validate_config("examples/test_target.csv")
    assert result["configuration"] == "work:examples/test_target.csv"
    assert result["summary"]["names"] == ["only"]


def test_relative_configpath_resolution_matches_exorad(
    udir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project payload with ConfigPath '.' validates from any cwd, on its own files."""
    path = make_payload(udir)
    monkeypatch.chdir(tmp_path)
    result = tools_config.validate_config(str(path))
    assert result["valid"], result["findings"]
    shown = {ref["path"] for ref in result["referenced_files"]}
    assert "work:user/examples/QE.csv" in shown
    # and it is the file the library opens: break that very file
    (udir / "examples" / "QE.csv").unlink()
    broken = tools_config.validate_config(str(path))
    assert not broken["valid"]
    assert "FILE_MISSING" in _codes(broken, "error")


def test_invalid_payload_is_returned_not_raised(udir: Path) -> None:
    path = make_payload(udir, edit=lambda r: remove(r, "optics/ForceChannelWlEdge"))
    result = tools_config.validate_config(str(path))
    assert result["valid"] is False
    assert _codes(result, "error") == ["MISSING_ELEMENT"]
    assert result["findings"][0]["path"] == "optics/ForceChannelWlEdge"
    assert "normalised_config" not in result or result["normalised_config"] is None


def test_loader_is_not_called_when_static_findings_hold_errors(
    udir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("LoadOptions must not run")

    monkeypatch.setattr(rules, "LoadOptions", boom)
    path = make_payload(
        udir,
        edit=lambda r: setattr(
            find(r, "channel[Spec]/detector/qe/datafile"), "text", "http://x.org/q.csv"
        ),
    )
    result = tools_config.validate_config(str(path))
    assert result["valid"] is False
    assert "PATH_OUTSIDE_SANDBOX" in _codes(result, "error")


def test_loader_failure_after_clean_static_rules(
    udir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Failing:
        def __call__(self, **_k: object) -> dict:
            raise KeyError("boom")

    monkeypatch.setattr(rules, "LoadOptions", Failing)
    result = tools_config.validate_config(str(make_payload(udir)))
    assert result["valid"] is False
    assert _codes(result, "error") == ["LOADER_FAILED"]
    assert "boom" in result["findings"][0]["message"]


def test_warnings_do_not_make_a_payload_invalid(udir: Path) -> None:
    path = make_payload(
        udir,
        edit=lambda r: setattr(find(r, "common/sourceSpectrum"), "text", "blackbody"),
    )
    result = tools_config.validate_config(str(path))
    assert result["valid"] is True
    assert _codes(result, "warning") == ["SOURCE_UNKNOWN_FALLS_BACK_TO_PLANCK"]


def test_scratch_directory_is_cleaned_up(udir: Path, tmp_path: Path) -> None:
    tools_config.validate_config(str(make_payload(udir)))
    leftovers = (
        list((tmp_path / "mcp-work" / ".tmp").glob("*"))
        if (tmp_path / "mcp-work" / ".tmp").exists()
        else []
    )
    assert leftovers == []


def test_errors_do_not_contain_absolute_paths(udir: Path, tmp_path: Path) -> None:
    path = make_payload(udir)
    (udir / "examples" / "QE.csv").unlink()
    text = repr(tools_config.validate_config(str(path)))
    assert str(tmp_path) not in text
    with pytest.raises(FileNotFoundError) as info:
        tools_config.validate_config("examples/nope.xml")
    assert str(tmp_path) not in str(info.value)


def test_validate_target_list_findings(udir: Path) -> None:
    bad = udir / "bad.csv"
    bad.write_text(
        "star name,star M [M_sun],star Teff [K],star R [R_sun],star D [pc]\na/b,1,5000,1,20\n",
        encoding="utf-8",
    )
    result = tools_config.validate_config(str(bad))
    assert result["valid"] is False
    assert _codes(result, "error") == ["TARGET_NAME_INVALID"]


def test_target_list_loader_failure_after_clean_static_rules(
    udir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import exorad.tasks

    class Failing:
        def __call__(self, **_k: object) -> None:
            raise OSError("unsupported target list format")

    monkeypatch.setattr(exorad.tasks, "LoadTargetList", Failing)
    path = udir / "t.csv"
    path.write_text(
        "star name,star M [M_sun],star Teff [K],star R [R_sun],star D [pc]\na,1,5000,1,20\n",
        encoding="utf-8",
    )
    result = tools_config.validate_config(str(path))
    assert result["valid"] is False
    assert _codes(result, "error") == ["LOADER_FAILED"]


def test_xlsx_target_list_is_refused() -> None:
    with pytest.raises(ValueError, match=r"\.xml.*\.csv"):
        tools_config.validate_config("examples/list.xlsx")


# --------------------------------------------------------------------------------
# deep validation (builds the channels in a child via run_sync)
# --------------------------------------------------------------------------------
def test_deep_requires_execution(udir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXORAD_MCP_NO_EXEC", "1")
    with pytest.raises(PermissionError, match="execution"):
        tools_config.validate_config(str(make_payload(udir)), deep=True)
    assert tools_config.validate_config(str(make_payload(udir)))[
        "valid"
    ]  # shallow is fine


def test_deep_builds_channels_inline(udir: Path) -> None:
    result = tools_config.validate_config(str(make_payload(udir)), deep=True)
    assert result["valid"], result["findings"]
    by_name = {c["name"]: c for c in result["channels"]}
    assert set(by_name) == {"Phot", "Spec"}
    assert by_name["Phot"]["class"] == "photometer"
    assert by_name["Phot"]["n_bins"] == 1
    assert by_name["Spec"]["class"] == "spectrometer"
    assert by_name["Spec"]["n_bins"] > 5
    assert 1.0 < by_name["Spec"]["wl_min_um"] < by_name["Spec"]["wl_max_um"] < 2.0


def test_deep_uses_run_sync_with_the_normalised_copy(
    udir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The child receives the normalised copy and the validation timeout (spec 3.3)."""
    from exorad.mcp import jobs

    calls: list[tuple] = []

    def fake(entry: str, spec: dict, *, timeout: float, slot_wait: float = 0.0) -> dict:
        # the copy only lives during the call: read it now
        calls.append(
            (entry, spec, timeout, Path(spec["payload"]).read_text(encoding="utf-8"))
        )
        return {"ok": True, "channels": []}

    monkeypatch.setattr(jobs.JOBS, "run_sync", fake)
    monkeypatch.setenv("EXORAD_MCP_VALIDATE_TIMEOUT", "7")
    path = make_payload(udir)
    result = tools_config.validate_config(str(path), deep=True)
    assert result["valid"]
    ((entry, spec, timeout, copy_text),) = calls
    assert entry == "exorad.mcp.configuration:build_payload_check"
    assert timeout == 7.0
    assert Path(spec["payload"]).name == "payload.xml"
    assert Path(spec["payload"]) != path  # the copy, not the original
    assert "__ConfigPath__" not in copy_text


def test_deep_build_failure_is_a_finding(udir: Path) -> None:
    def wide(root: ET.Element) -> None:
        node = find(root, "channel[Phot]/Fnum_x")
        node.attrib.pop("unit")  # with a unit the loader itself would fail first
        node.text = "wide"

    path = make_payload(udir, edit=wide)
    result = tools_config.validate_config(str(path), deep=True)
    assert result["valid"] is False
    assert _codes(result, "error") == ["DEEP_BUILD_FAILED"]


def test_deep_not_run_when_static_findings_hold_errors(
    udir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from exorad.mcp import jobs

    monkeypatch.setattr(
        jobs.JOBS,
        "run_sync",
        lambda *a, **k: pytest.fail("no child for an invalid payload"),
    )
    path = make_payload(udir, edit=lambda r: remove(r, "optics/Atel"))
    assert tools_config.validate_config(str(path), deep=True)["valid"] is False


@pytest.mark.slow
def test_validate_deep_builds_channels(
    udir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through a real spawned child (the process backend)."""
    monkeypatch.setenv("EXORAD_MCP_EXEC_BACKEND", "process")
    result = tools_config.validate_config(str(make_payload(udir)), deep=True)
    assert result["valid"], result["findings"]
    assert {c["name"] for c in result["channels"]} == {"Phot", "Spec"}


@pytest.mark.slow
def test_deep_timeout_raises(udir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXORAD_MCP_EXEC_BACKEND", "process")
    monkeypatch.setenv("EXORAD_MCP_VALIDATE_TIMEOUT", "0.01")
    with pytest.raises(TimeoutError):
        tools_config.validate_config(str(make_payload(udir)), deep=True)


# --------------------------------------------------------------------------------
# config_requirements
# --------------------------------------------------------------------------------
def test_requirements_payload_reference() -> None:
    result = tools_config.config_requirements()
    assert result["kind"] == "payload"
    assert result["reference_example"] == "examples/payload_example.xml"
    by_path = {row["path"]: row for row in result["reference"]}
    assert by_path["optics/ForceChannelWlEdge"]["required"] == "build"
    assert by_path["common/sourceSpectrum"]["required"] == "observe"
    assert "see" in by_path["common/wl_min"]
    docs = [row["see"] for row in result["reference"] if row.get("see")]
    assert docs
    assert any(d.startswith("docs/source/") for d in docs)
    assert "present" not in result


def test_requirements_target_list_reference() -> None:
    result = tools_config.config_requirements("target_list")
    assert result["reference_example"] == "examples/test_target.csv"
    assert {row["path"] for row in result["reference"]} >= {
        "star name",
        "star Teff [K]",
    }


def test_requirements_bad_kind() -> None:
    with pytest.raises(ValueError, match="kind"):
        tools_config.config_requirements("recipe")


def test_requirements_against_a_configuration(udir: Path) -> None:
    path = make_payload(udir, edit=lambda r: remove(r, "optics/Atel"))
    result = tools_config.config_requirements("payload", str(path))
    assert "common/wl_min" in result["present"]
    assert "optics/Atel" in result["missing"]
    assert "optics/Atel" not in result["present"]
    assert any(f["code"] == "MISSING_ELEMENT" for f in result["findings"])


def test_config_requirements_extra_excludes_framework_keys(udir: Path) -> None:
    """ConfigPath, fileName and comment are framework keys, never 'extra' (ExoSim e5c66ed4)."""

    def add(root: ET.Element) -> None:
        ET.SubElement(find(root, "common"), "mystery").text = "1"
        ET.SubElement(root, "comment").text = "free text"

    path = make_payload(udir, edit=add)
    result = tools_config.config_requirements("payload", str(path))
    assert result["extra"] == ["common/mystery"]
    for key in ("ConfigPath", "fileName", "comment", "unit", "value"):
        assert not any(
            key == part for item in result["extra"] for part in item.split("/")
        )


def test_requirements_of_the_example_has_nothing_extra() -> None:
    result = tools_config.config_requirements("payload", "examples/payload_example.xml")
    assert result["extra"] == []
    assert result["missing"] == []


def test_requirements_target_list_against_a_file(udir: Path) -> None:
    path = udir / "t.csv"
    path.write_text("star name,star M [M_sun],star ra [deg]\na,1,3\n", encoding="utf-8")
    result = tools_config.config_requirements("target_list", str(path))
    assert "star Teff [K]" in result["missing"]
    assert "star name" in result["present"]
    assert result["findings"]


def test_module_exposes_the_load_lock() -> None:
    assert configuration.CONFIG_LOAD_LOCK is rules.CONFIG_LOAD_LOCK
