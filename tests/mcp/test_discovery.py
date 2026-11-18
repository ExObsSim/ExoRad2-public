"""Discovery of the ExoRad pipeline: import errors are surfaced, never swallowed."""

from __future__ import annotations

import importlib

import pytest

from exorad.mcp import discovery, tools_info


@pytest.fixture
def clean_errors():
    discovery.clear_discovery_errors()
    yield discovery
    discovery.clear_discovery_errors()


def _fail_import(missing: str, *prefixes: str):
    real = importlib.import_module

    def fake(name, *args, **kwargs):
        if name.startswith(prefixes):
            raise ModuleNotFoundError(f"No module named '{missing}'", name=missing)
        return real(name, *args, **kwargs)

    return fake


def test_discovery_finds_the_standard_pipeline(clean_errors) -> None:
    (definition,) = clean_errors.list_pipeline_definitions()
    assert definition["name"] == "standard"
    assert definition["entry_point"] == "exorad.standard_pipeline"
    assert definition["cli_command"].startswith("exorad -p ")
    assert definition["available"] is True
    assert definition["required_inputs"] == ["payload", "target_list"]
    assert {"output", "n_threads", "plot", "full_contrib", "overwrite"} <= set(
        definition["optional_inputs"]
    )
    assert clean_errors.discovery_errors() == []


def test_import_health_is_clean_on_a_working_install(clean_errors) -> None:
    health = clean_errors.import_health()
    assert set(health) == set(clean_errors.HEALTH_MODULES)
    assert all(health.values()), health
    assert clean_errors.discovery_errors() == []


def test_discovery_records_the_import_error(monkeypatch, clean_errors) -> None:
    """Audit #7: the import error must be recorded, not swallowed (red-first)."""
    monkeypatch.setattr(
        "importlib.import_module", _fail_import("h5py", "exorad.exorad")
    )
    definition = clean_errors.pipeline_definition()
    # never an empty answer: a fallback definition flagged unavailable
    assert definition["name"] == "standard"
    assert definition["available"] is False
    (error,) = clean_errors.discovery_errors()
    assert error["missing_module"] == "h5py"
    assert error["module"] == "exorad.exorad"
    assert "pip install h5py" in error["hint"]


def test_import_health_records_each_failed_module(monkeypatch, clean_errors) -> None:
    monkeypatch.setattr("importlib.import_module", _fail_import("openpyxl", "openpyxl"))
    health = clean_errors.import_health()
    assert health["openpyxl"] is False
    assert health["h5py"] is True
    (error,) = clean_errors.discovery_errors()
    assert error["missing_module"] == "openpyxl"
    assert "openpyxl" in error["hint"]


def test_a_non_import_failure_is_recorded_too(monkeypatch, clean_errors) -> None:
    real = importlib.import_module

    def fake(name, *args, **kwargs):
        if name == "exorad.exorad":
            raise SyntaxError("broken module")
        return real(name, *args, **kwargs)

    monkeypatch.setattr("importlib.import_module", fake)
    assert clean_errors.pipeline_definition()["available"] is False
    (error,) = clean_errors.discovery_errors()
    assert error["error"].startswith("SyntaxError")


def test_a_missing_entry_point_is_recorded(monkeypatch, clean_errors) -> None:
    import types

    real = importlib.import_module

    def fake(name, *args, **kwargs):
        if name == "exorad.exorad":
            return types.SimpleNamespace()
        return real(name, *args, **kwargs)

    monkeypatch.setattr("importlib.import_module", fake)
    assert clean_errors.pipeline_definition()["available"] is False
    assert "standard_pipeline" in clean_errors.discovery_errors()[0]["error"]


def test_errors_are_deduplicated_and_returned_as_copies(
    monkeypatch, clean_errors
) -> None:
    monkeypatch.setattr(
        "importlib.import_module", _fail_import("h5py", "exorad.exorad")
    )
    clean_errors.pipeline_definition()
    clean_errors.pipeline_definition()
    errors = clean_errors.discovery_errors()
    assert len(errors) == 1
    errors[0]["hint"] = "tampered"
    assert clean_errors.discovery_errors()[0]["hint"] != "tampered"


def test_capabilities_and_list_pipelines_surface_the_error(
    monkeypatch, clean_errors
) -> None:
    """Audit #7 (red-first): both tools report the recorded failure."""
    assert tools_info.capabilities()["discovery_errors"] == []
    monkeypatch.setattr(
        "importlib.import_module", _fail_import("h5py", "exorad.exorad")
    )
    clean_errors.pipeline_definition()
    monkeypatch.undo()
    assert tools_info.capabilities()["discovery_errors"][0]["missing_module"] == "h5py"
    listed = tools_info.list_pipelines()
    assert listed["discovery_errors"][0]["missing_module"] == "h5py"
    assert listed["pipelines"], "the list must never be silently empty"


def test_capabilities_reports_a_failed_health_check(monkeypatch, clean_errors) -> None:
    monkeypatch.setattr(
        "importlib.import_module", _fail_import("matplotlib", "matplotlib")
    )
    errors = tools_info.capabilities()["discovery_errors"]
    assert [e["missing_module"] for e in errors] == ["matplotlib"]


def test_describe_pipeline_returns_a_structured_import_error(
    monkeypatch, clean_errors
) -> None:
    monkeypatch.setattr(
        "importlib.import_module", _fail_import("h5py", "exorad.exorad")
    )
    result = tools_info.describe_pipeline("standard")
    assert result["missing_module"] == "h5py"
    assert "h5py" in result["error"]
    assert "pip install h5py" in result["hint"]
    assert clean_errors.discovery_errors()


def test_describe_pipeline_maps_the_library_parameters() -> None:
    result = tools_info.describe_pipeline("standard")
    params = {p["name"]: p for p in result["parameters"]}
    assert list(params) == [
        "options",
        "target_list",
        "output",
        "plot",
        "full_contrib",
        "n_thread",
        "debug",
        "log",
        "replace",
    ]
    assert params["options"]["mcp_argument"] == "payload"
    assert params["options"]["required"] is True
    assert params["n_thread"]["mcp_argument"] == "n_threads"
    assert params["replace"]["mcp_argument"] == "overwrite"
    assert params["replace"]["default"] is True
    assert params["debug"]["mcp_argument"] is None
    assert params["log"]["mcp_argument"] is None
    assert "not exposed" in params["debug"]["description"]
    assert "payload description" in params["options"]["description"].lower()
    assert result["summary"].startswith("Execute the complete ExoRad")


def test_describe_pipeline_signature_drift_is_visible() -> None:
    """Every library parameter is either mapped or explicitly not exposed."""
    import inspect

    from exorad import standard_pipeline

    for name in inspect.signature(standard_pipeline).parameters:
        assert name in discovery._MCP_ARGUMENT, f"unmapped parameter {name}"


def test_describe_unknown_pipeline_is_an_error_dict() -> None:
    result = tools_info.describe_pipeline("focalplane")
    assert "error" in result
    assert result["pipeline"] == "focalplane"


def test_only_one_pipeline_is_exposed() -> None:
    assert tools_info.capabilities()["pipelines"] == ["standard"]
    assert [p["name"] for p in tools_info.list_pipelines()["pipelines"]] == ["standard"]
