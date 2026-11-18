"""Defensive input checks added by the security-hardening pass.

Every hostile input here is harmless: a refusal is what is asserted, a refused input
must never reach ``LoadOptions`` or open the file it names, and nothing executes.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING

import h5py
import numpy as np
import pytest
from payload_fixtures import find, make_payload, sandbox_for
from run_fixtures import FakeJobs, make_project, work_dir_of

from exorad.mcp import configuration, jobs, pipelines, rules, tools_config

if TYPE_CHECKING:
    from exorad.mcp.sandbox import Sandbox


@pytest.fixture
def box(tmp_path: Path) -> Sandbox:
    return sandbox_for(tmp_path)


@pytest.fixture
def udir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EXORAD_MCP_WORK_DIR", str(tmp_path / "work"))
    path = tmp_path / "work" / "user"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def no_loader(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record (and fail on) any call into the library's ``LoadOptions``."""
    calls: list[str] = []

    def boom(*_a: object, **_k: object) -> None:
        calls.append("LoadOptions")
        raise RuntimeError("LoadOptions must not be reached")

    monkeypatch.setattr(rules, "LoadOptions", boom)
    return calls


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeJobs:
    recorder = FakeJobs()
    monkeypatch.setattr(jobs, "JOBS", recorder)
    return recorder


def _errors(findings: list) -> list[str]:
    return [f.code for f in findings if f.severity == "error"]


def _add(root: ET.Element, parent: str, tag: str, text: str) -> None:
    ET.SubElement(find(root, parent) if parent else root, tag).text = text


def _plain_h5(path: Path, **datasets: object) -> Path:
    with h5py.File(path, "w") as handle:
        handle.create_dataset("plain", data=[1.0])
        for name, value in datasets.items():
            handle.create_dataset(name, data=value)
    return path


# --------------------------------------------------------------------------------
# item 1: config_dict / datadict versus the numeric caps
# --------------------------------------------------------------------------------
def test_control_config_dict_replaces_the_element_and_datadict_only_adds_data(
    tmp_path: Path,
) -> None:
    """The loader facts the fix rests on (harmless handcrafted files, no MCP)."""
    _plain_h5(tmp_path / "big.h5", working_R=99_999_999)
    xml = tmp_path / "a.xml"
    xml.write_text(
        "<root><ConfigPath>.</ConfigPath><common>"
        "<working_R>1000</working_R>"
        f"<config_dict>{tmp_path / 'big.h5'}</config_dict></common></root>",
        encoding="utf-8",
    )
    common = rules.load_options(xml)["common"]
    assert int(np.asarray(common["working_R"])) == 99_999_999  # the XML value is gone
    xml.write_text(
        "<root><ConfigPath>.</ConfigPath><common>"
        "<working_R>1000</working_R>"
        f"<datadict>{tmp_path / 'big.h5'}</datadict></common></root>",
        encoding="utf-8",
    )
    common = rules.load_options(xml)["common"]
    assert common["working_R"]["value"] == 1000  # datadict never overwrites
    assert int(np.asarray(common["data"]["working_R"])) == 99_999_999


@pytest.mark.parametrize("parent", ["common", "channel[Phot]", "optics", ""])
@pytest.mark.parametrize("where", ["element", "comment"])
def test_config_dict_is_refused_even_when_the_file_is_harmless(
    parent: str,
    where: str,
    box: Sandbox,
    udir: Path,
    no_loader: list[str],
    tmp_path: Path,
) -> None:
    _plain_h5(udir / "cfg.h5")

    def edit(root: ET.Element) -> None:
        holder = find(root, parent) if parent else root
        if where == "comment":
            holder = ET.SubElement(holder, "comment")
        ET.SubElement(holder, "config_dict").text = "__ConfigPath__/cfg.h5"

    payload = make_payload(udir, edit=edit)
    assert "CONFIG_DICT_REFUSED" in _errors(rules.static_findings(payload, sandbox=box))
    norm = rules.normalise_payload(payload, sandbox=box, dest_dir=tmp_path / "copy")
    assert norm.path is None
    result = configuration.validate_configuration_file(str(payload), sandbox=box)
    assert result["valid"] is False
    assert no_loader == []


def test_config_dict_is_refused_without_the_file_existing(
    box: Sandbox, udir: Path
) -> None:
    payload = make_payload(
        udir, edit=lambda r: _add(r, "common", "config_dict", "__ConfigPath__/nope.h5")
    )
    assert "CONFIG_DICT_REFUSED" in _errors(rules.static_findings(payload, sandbox=box))


def test_plan_run_refuses_config_dict_and_leaves_no_run_dir(
    tmp_path: Path, fake: FakeJobs
) -> None:
    payload, targets = make_project(
        tmp_path, edit=lambda r: _add(r, "common", "config_dict", "x.h5")
    )
    with pytest.raises(rules.ConfigRuleError, match="CONFIG_DICT_REFUSED"):
        pipelines.plan_run(payload, targets)
    assert not (work_dir_of(tmp_path) / "runs").exists() or not list(
        (work_dir_of(tmp_path) / "runs").iterdir()
    )
    assert fake.specs == []


def test_clean_datadict_still_validates_and_the_caps_hold_on_the_xml(
    box: Sandbox, udir: Path
) -> None:
    """``datadict`` fills only ``data``: the caps computed on the XML stay valid."""
    _plain_h5(udir / "dd.h5", working_R=99_999_999)
    payload = make_payload(
        udir, edit=lambda r: _add(r, "common", "datadict", "__ConfigPath__/dd.h5")
    )
    assert _errors(rules.static_findings(payload, sandbox=box)) == []
    loaded = rules.load_payload_dict(payload, sandbox=box)
    assert loaded["common"]["working_R"]["value"] == 6000
    assert tools_config.validate_config is not None


def test_example_payload_still_validates(box: Sandbox, udir: Path) -> None:
    payload = make_payload(udir)
    result = configuration.validate_configuration_file(str(payload), sandbox=box)
    assert result["valid"] is True


# --------------------------------------------------------------------------------
# item 2: the HDF5 link scan does not depend on the file suffix
# --------------------------------------------------------------------------------
def _linked_h5(path: Path, *, userblock: int = 0) -> Path:
    """An HDF5 file with an external link (the target is never opened)."""
    with h5py.File(path, "w", userblock_size=userblock) as handle:
        handle.create_dataset("plain", data=[1.0])
        handle["ext"] = h5py.ExternalLink("other.h5", "/d")
    return path


def _add_psf(root: ET.Element, name: str, fmt: str | None = None) -> None:
    psf = ET.SubElement(find(root, "channel[Phot]"), "PSF")
    psf.text = name
    if fmt:
        ET.SubElement(psf, "format").text = fmt


@pytest.mark.parametrize("suffix", [".bin", ".dat", ".fits", ".csv", ""])
@pytest.mark.parametrize("userblock", [0, 512])
def test_hdf5_by_signature_is_scanned_whatever_the_suffix(
    suffix: str, userblock: int, box: Sandbox, udir: Path, no_loader: list[str]
) -> None:
    _linked_h5(udir / f"linked{suffix}", userblock=userblock)
    payload = make_payload(udir, edit=lambda r: _add_psf(r, f"linked{suffix}"))
    found = _errors(rules.static_findings(payload, sandbox=box))
    assert "HDF5_LINK_REFUSED" in found
    assert (
        configuration.validate_configuration_file(str(payload), sandbox=box)["valid"]
        is False
    )
    assert no_loader == []


@pytest.mark.parametrize("name", ["linked.bin", "linked.dat"])
def test_paos_psf_is_always_scanned(
    name: str, box: Sandbox, udir: Path, no_loader: list[str]
) -> None:
    _linked_h5(udir / name)
    payload = make_payload(udir, edit=lambda r: _add_psf(r, name, "paos"))
    assert "HDF5_LINK_REFUSED" in _errors(rules.static_findings(payload, sandbox=box))
    assert no_loader == []


def test_paos_psf_that_is_not_hdf5_is_refused(box: Sandbox, udir: Path) -> None:
    (udir / "psf.bin").write_bytes(b"not an hdf5 file at all")
    payload = make_payload(udir, edit=lambda r: _add_psf(r, "psf.bin", "paos"))
    assert "UNSUPPORTED_FORMAT" in _errors(rules.static_findings(payload, sandbox=box))


def test_clean_hdf5_with_odd_suffix_is_accepted(box: Sandbox, udir: Path) -> None:
    _plain_h5(udir / "psf.bin")
    payload = make_payload(udir, edit=lambda r: _add_psf(r, "psf.bin", "paos"))
    assert _errors(rules.static_findings(payload, sandbox=box)) == []


def test_signature_probe_does_not_open_a_fifo(tmp_path: Path) -> None:
    import os

    fifo = tmp_path / "pipe.bin"
    os.mkfifo(fifo)
    assert rules.has_hdf5_signature(fifo) is False


# --------------------------------------------------------------------------------
# item 3: PSF directories and StellarModels globs
# --------------------------------------------------------------------------------
def _psf_dir(udir: Path, name: str = "psfs") -> Path:
    folder = udir / name
    folder.mkdir()
    (folder / "a.fits").write_bytes(b"SIMPLE  = T")
    (folder / "b.fits").write_bytes(b"SIMPLE  = T")
    return folder


def _phoenix(root: ET.Element, path: str) -> None:
    find(root, "common/sourceSpectrum").text = "phoenix"
    find(root, "common/sourceSpectrum/StellarModels").text = path


@pytest.fixture
def no_fits_open(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fail if anything opens a FITS file (the static scan must not)."""
    from astropy.io import fits

    calls: list[str] = []

    def boom(*a: object, **_k: object) -> None:
        calls.append(str(a))
        raise RuntimeError("fits.open must not be reached")

    monkeypatch.setattr(fits, "open", boom)
    return calls


def test_psf_directory_keeps_a_trailing_separator_in_the_copy(
    box: Sandbox, udir: Path, tmp_path: Path
) -> None:
    """Control + fix: ``glob(name + '*.fits')`` must mean 'inside the directory'."""
    import glob
    import os

    folder = _psf_dir(udir)
    (udir / "psfs_sibling.fits").write_bytes(b"SIMPLE  = T")
    payload = make_payload(udir, edit=lambda r: _add_psf(r, "psfs"))
    norm = rules.normalise_payload(payload, sandbox=box, dest_dir=tmp_path / "copy")
    assert norm.path is not None
    text = find(ET.parse(norm.path).getroot(), "channel[Phot]/PSF").text.strip()
    assert text == str(folder) + os.sep
    # what binnedPSF / pixel_based_psf do with the value
    names = sorted(os.path.basename(f) for f in glob.glob(text + "*.fits"))
    assert names == ["a.fits", "b.fits"]
    # control: the old spelling matched the sibling and nothing inside the directory
    old = sorted(os.path.basename(f) for f in glob.glob(str(folder) + "*.fits"))
    assert old == ["psfs_sibling.fits"]


def test_clean_psf_directory_is_accepted(
    box: Sandbox, udir: Path, no_fits_open: list[str]
) -> None:
    _psf_dir(udir)
    payload = make_payload(udir, edit=lambda r: _add_psf(r, "psfs/"))
    assert _errors(rules.static_findings(payload, sandbox=box)) == []
    assert no_fits_open == []


@pytest.mark.parametrize("kind", ["symlink_out", "symlink_in", "fifo", "dir", "big"])
def test_every_file_a_psf_glob_can_return_is_checked(
    kind: str,
    box: Sandbox,
    udir: Path,
    tmp_path: Path,
    no_fits_open: list[str],
    no_loader: list[str],
) -> None:
    import dataclasses
    import os

    folder = _psf_dir(udir)
    outside = tmp_path / "outside.fits"
    outside.write_bytes(b"SIMPLE  = T")
    bad = folder / "z.fits"
    if kind == "symlink_out":
        bad.symlink_to(outside)
    elif kind == "symlink_in":
        bad.symlink_to(folder / "a.fits")
    elif kind == "fifo":
        os.mkfifo(bad)
    elif kind == "dir":
        bad.mkdir()
    else:
        bad.write_bytes(b"x" * 1_300_000)
        box = dataclasses.replace(box, max_data_mb=1)
    payload = make_payload(udir, edit=lambda r: _add_psf(r, "psfs"))
    found = _errors(rules.static_findings(payload, sandbox=box))
    assert found, kind
    assert set(found) <= {"NOT_REGULAR_FILE", "PATH_OUTSIDE_SANDBOX", "LIMIT_EXCEEDED"}
    message = " ".join(f.message for f in rules.static_findings(payload, sandbox=box))
    assert "z.fits" in message
    assert str(tmp_path) not in message
    assert (
        rules.normalise_payload(payload, sandbox=box, dest_dir=tmp_path / "c").path
        is None
    )
    assert no_fits_open == []
    assert no_loader == []


def test_psf_directory_that_is_a_sandbox_root_is_refused(
    box: Sandbox, udir: Path
) -> None:
    import dataclasses

    extra = dataclasses.replace(box, extra_roots=(udir.parent.parent,))
    for sandbox, target in (
        (box, str(box.work_dir)),
        (box, str(box.repo_root)),
        (extra, str(udir.parent.parent)),  # a parent of the work dir
        (extra, str(box.work_dir.parent)),
    ):
        payload = make_payload(udir, edit=lambda r, t=target: _add_psf(r, t))
        found = rules.static_findings(payload, sandbox=sandbox)
        assert "PATH_OUTSIDE_SANDBOX" in _errors(found), target
        assert "sandbox root" in " ".join(f.message for f in found)


def test_stellar_models_files_are_checked(
    box: Sandbox, udir: Path, tmp_path: Path, no_fits_open: list[str]
) -> None:
    models = udir / "models"
    models.mkdir()
    (models / "t5000.BT-Settl.spec.fits.gz").write_bytes(b"x")
    payload = make_payload(udir, edit=lambda r: _phoenix(r, "models"))
    assert _errors(rules.static_findings(payload, sandbox=box)) == []
    outside = tmp_path / "secret.fits.gz"
    outside.write_bytes(b"x")
    (models / "t6000.BT-Settl.spec.fits.gz").symlink_to(outside)
    found = rules.static_findings(payload, sandbox=box)
    assert _errors(found) == ["NOT_REGULAR_FILE"]
    assert "t6000" in found[0].message
    assert str(tmp_path) not in found[0].message
    assert no_fits_open == []


def test_stellar_models_directory_that_is_a_sandbox_root_is_refused(
    box: Sandbox, udir: Path
) -> None:
    payload = make_payload(udir, edit=lambda r: _phoenix(r, str(box.work_dir)))
    assert "PATH_OUTSIDE_SANDBOX" in _errors(
        rules.static_findings(payload, sandbox=box)
    )


def test_library_reads_a_psf_directory_through_the_normalised_value(
    box: Sandbox, udir: Path, tmp_path: Path
) -> None:
    """End to end with the real reader: the copy works, the old spelling did not."""
    import os

    from astropy import units as u
    from astropy.io import fits

    from exorad.utils.exolib import pixel_based_psf

    folder = udir / "psfs"
    folder.mkdir()
    for wavelength in (1.0, 2.0):
        header = fits.Header({"WAVELEN": wavelength})
        fits.PrimaryHDU(np.ones((4, 4)) * wavelength, header).writeto(
            folder / f"psf_{wavelength:g}.fits"
        )
    payload = make_payload(udir, edit=lambda r: _add_psf(r, "psfs"))
    norm = rules.normalise_payload(payload, sandbox=box, dest_dir=tmp_path / "copy")
    assert norm.path is not None
    text = find(ET.parse(norm.path).getroot(), "channel[Phot]/PSF").text.strip()
    image, _, _ = pixel_based_psf(1.9 * u.micron, 10 * u.micron, text)
    assert float(image[0, 0]) == 2.0
    with pytest.raises(ValueError):  # the old spelling: empty glob
        pixel_based_psf(1.9 * u.micron, 10 * u.micron, text.rstrip(os.sep))


# --------------------------------------------------------------------------------
# item 4: re-validation between the check and the use (TOCTOU)
# --------------------------------------------------------------------------------
def _swap_for_symlink(path: Path, target: Path) -> None:
    path.unlink()
    path.symlink_to(target)


def _swap_for_fifo(path: Path) -> None:
    import os

    path.unlink()
    os.mkfifo(path)


def _within(fn, seconds: float = 10.0):  # type: ignore[no-untyped-def]
    """Run ``fn`` in a thread and return its result or exception; fail on a hang."""
    import threading

    out: list[object] = []

    def target() -> None:
        try:
            out.append(fn())
        except BaseException as exc:
            out.append(exc)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), "the re-check blocked (a FIFO was opened)"
    return out[0] if out else None


def _env_sandbox() -> Sandbox:
    from exorad.mcp.sandbox import Sandbox as _Sandbox

    return _Sandbox.from_env()


def _planned(tmp_path: Path) -> tuple[pipelines.RunPlan, Path]:
    payload, targets = make_project(tmp_path)
    plan = pipelines.plan_run(payload, targets)
    return plan, work_dir_of(tmp_path) / "proj"


def _table_of(plan: pipelines.RunPlan) -> Path:
    """A table the normalised copy references (the QE curve)."""
    root = ET.parse(plan.payload).getroot()
    return Path(
        next(el.text.strip() for el in root.iter("datafile") if "QE" in el.text)
    )


def _guarded_pipeline(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    import exorad

    calls: list[dict] = []

    def standard_pipeline(**kwargs: object) -> None:
        calls.append(dict(kwargs))
        raise RuntimeError("stop after the re-validation")

    monkeypatch.setattr(exorad, "standard_pipeline", standard_pipeline)
    return calls


@pytest.mark.parametrize("swap", ["symlink", "fifo", "hdf5_link", "big", "parent_dir"])
def test_recheck_payload_refuses_a_referenced_file_swapped_after_planning(
    swap: str, tmp_path: Path, fake: FakeJobs
) -> None:
    import dataclasses

    plan, project = _planned(tmp_path)
    sandbox = _env_sandbox()
    assert rules.errors_of(rules.recheck_payload(plan.payload, sandbox)) == []
    table = _table_of(plan)
    if swap == "symlink":
        _swap_for_symlink(table, project / "targets.csv")
    elif swap == "fifo":
        _swap_for_fifo(table)
    elif swap == "hdf5_link":
        table.unlink()
        _linked_h5(table)
    elif swap == "big":
        with table.open("ab") as handle:
            handle.write(b"#" + b"x" * 1_300_000)
        sandbox = dataclasses.replace(sandbox, max_data_mb=1)
    else:
        real = project / "examples_real"
        (project / "examples").rename(real)
        (project / "examples").symlink_to(real)
    found = _within(lambda: rules.recheck_payload(plan.payload, sandbox))
    assert isinstance(found, list), found
    assert rules.errors_of(found), swap
    assert str(tmp_path) not in " ".join(f.message for f in found)


def test_job_spec_carries_the_sandbox(tmp_path: Path, fake: FakeJobs) -> None:
    plan, _ = _planned(tmp_path)
    spec = plan.spec()
    box = _env_sandbox()
    assert spec["sandbox"]["work_dir"] == str(box.work_dir)
    assert spec["sandbox"]["max_data_mb"] == box.max_data_mb


def test_run_standard_runs_when_nothing_changed(
    tmp_path: Path, fake: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _ = _planned(tmp_path)
    calls = _guarded_pipeline(monkeypatch)
    with pytest.raises(RuntimeError, match="stop after the re-validation"):
        pipelines.run_standard(plan.spec())
    assert len(calls) == 1


@pytest.mark.parametrize(
    "what", ["table_symlink", "table_fifo", "targets_symlink", "targets_fifo"]
)
def test_run_standard_refuses_inputs_swapped_after_planning(
    what: str, tmp_path: Path, fake: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    plan, project = _planned(tmp_path)
    calls = _guarded_pipeline(monkeypatch)
    victim = _table_of(plan) if what.startswith("table") else plan.target_list
    if what.endswith("symlink"):
        decoy = project / "decoy.csv"
        decoy.write_text(victim.read_text(encoding="utf-8"), encoding="utf-8")
        _swap_for_symlink(victim, decoy)
    else:
        _swap_for_fifo(victim)
    outcome = _within(lambda: pipelines.run_standard(plan.spec()))
    assert isinstance(outcome, rules.ConfigRuleError), outcome
    assert calls == [], "the library must not be reached"
    text = str(outcome)
    assert str(tmp_path) not in text
    assert victim.name in text or "target" in text.lower()
    info = json.loads(pipelines.run_json_path(plan.output).read_text(encoding="utf-8"))
    assert "ConfigRuleError" in info["error"]
    assert str(tmp_path) not in json.dumps(info)


def test_run_standard_refuses_a_swapped_payload_copy(
    tmp_path: Path, fake: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, project = _planned(tmp_path)
    calls = _guarded_pipeline(monkeypatch)
    decoy = project / "decoy.xml"
    decoy.write_bytes(plan.payload.read_bytes())
    _swap_for_symlink(plan.payload, decoy)
    outcome = _within(lambda: pipelines.run_standard(plan.spec()))
    assert isinstance(outcome, rules.ConfigRuleError), outcome
    assert calls == []


def _swap_after_normalise(monkeypatch: pytest.MonkeyPatch, victim_of) -> list[Path]:  # type: ignore[no-untyped-def]
    """Replace a referenced table by a symlink right after the copy is written."""
    real = rules.normalise_payload
    swapped: list[Path] = []

    def wrapper(payload, *, sandbox, dest_dir):  # type: ignore[no-untyped-def]
        norm = real(payload, sandbox=sandbox, dest_dir=dest_dir)
        if norm.path is not None and not swapped:
            root = ET.parse(norm.path).getroot()
            table = Path(
                next(e.text.strip() for e in root.iter("datafile") if "QE" in e.text)
            )
            _swap_for_symlink(table, victim_of(table))
            swapped.append(table)
        return norm

    monkeypatch.setattr(rules, "normalise_payload", wrapper)
    return swapped


def test_validate_config_rechecks_before_the_in_process_loader(
    box: Sandbox, udir: Path, no_loader: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = make_payload(udir)
    swapped = _swap_after_normalise(
        monkeypatch, lambda table: table.parent / "Spec-wl_sol.csv"
    )
    result = configuration.validate_configuration_file(str(payload), sandbox=box)
    assert swapped
    assert result["valid"] is False
    assert no_loader == []
    assert "NOT_REGULAR_FILE" in {f["code"] for f in result["findings"]}


def test_compare_configs_rechecks_before_the_in_process_loader(
    box: Sandbox, udir: Path, no_loader: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from exorad.mcp import comparison

    first = make_payload(udir, name="a.xml")
    second = make_payload(udir, name="b.xml")
    swapped = _swap_after_normalise(
        monkeypatch, lambda table: table.parent / "Spec-wl_sol.csv"
    )
    result = comparison.compare_payloads(first, second, sandbox=box)
    assert swapped
    assert result["valid"] is False
    assert no_loader == []


# --------------------------------------------------------------------------------
# item 5: decompression bombs (declared size versus stored size)
# --------------------------------------------------------------------------------
def _sparse_h5(path: Path, shape: tuple[int, ...] = (20_000, 20_000)) -> Path:
    """Declares ``prod(shape) * 8`` bytes, stores (almost) nothing."""
    with h5py.File(path, "w") as handle:
        handle.create_dataset(
            "big", shape=shape, dtype="f8", chunks=(100, 100), fillvalue=0.0
        )
        handle.create_dataset("plain", data=[1.0])
    assert path.stat().st_size < 100_000
    return path


@pytest.fixture
def no_h5_read(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fail if any dataset VALUE is read (the scan uses metadata only)."""
    calls: list[str] = []

    def boom(self, *a: object, **_k: object):  # type: ignore[no-untyped-def]
        calls.append("read")
        raise RuntimeError("a dataset must not be read by the scan")

    monkeypatch.setattr(h5py.Dataset, "__getitem__", boom)
    return calls


def test_hdf5_scan_reports_the_declared_size(
    tmp_path: Path, no_h5_read: list[str]
) -> None:
    problems, nbytes = rules.hdf5_scan(_sparse_h5(tmp_path / "s.h5"))
    assert problems == []
    assert nbytes == 20_000 * 20_000 * 8 + 8
    assert no_h5_read == []


@pytest.mark.parametrize("via", ["datadict", "paos_psf", "signature_only"])
def test_sparse_hdf5_above_the_expansion_cap_is_refused(
    via: str, box: Sandbox, udir: Path, no_loader: list[str], no_h5_read: list[str]
) -> None:
    name = "dd.h5" if via == "datadict" else "psf.bin"
    _sparse_h5(udir / name)
    if via == "datadict":
        payload = make_payload(
            udir, edit=lambda r: _add(r, "common", "datadict", f"__ConfigPath__/{name}")
        )
    else:
        payload = make_payload(
            udir,
            edit=lambda r: _add_psf(r, name, "paos" if via == "paos_psf" else None),
        )
    found = rules.static_findings(payload, sandbox=box)
    assert "LIMIT_EXCEEDED" in _errors(found)
    message = " ".join(f.message for f in found)
    assert "uncompressed" in message
    assert str(udir) not in message
    assert no_loader == []
    assert no_h5_read == []


def test_hdf5_cap_is_max_data_mb_times_the_constant(box: Sandbox, udir: Path) -> None:
    import dataclasses

    assert rules.HDF5_EXPANSION_FACTOR == 8
    _sparse_h5(udir / "dd.h5", shape=(1200, 1000))  # 9.6 MB declared
    payload = make_payload(
        udir, edit=lambda r: _add(r, "common", "datadict", "__ConfigPath__/dd.h5")
    )
    assert _errors(rules.static_findings(payload, sandbox=box)) == []
    tight = dataclasses.replace(box, max_data_mb=1)  # cap 8 MiB
    assert "LIMIT_EXCEEDED" in _errors(rules.static_findings(payload, sandbox=tight))


def test_recheck_applies_the_expansion_cap_too(tmp_path: Path, fake: FakeJobs) -> None:
    plan, _ = _planned(tmp_path)
    table = _table_of(plan)
    table.unlink()
    _sparse_h5(table)
    found = rules.recheck_payload(plan.payload, _env_sandbox())
    assert "LIMIT_EXCEEDED" in _errors(found)


@pytest.mark.parametrize("what", ["rows", "line", "columns"])
def test_text_table_limits(
    what: str, box: Sandbox, udir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rules, "MAX_TABLE_ROWS", 50)
    monkeypatch.setattr(rules, "MAX_TABLE_LINE_BYTES", 200)
    monkeypatch.setattr(rules, "MAX_TABLE_COLUMNS", 10)
    payload = make_payload(udir)
    qe = udir / "examples" / "QE.csv"
    assert _errors(rules.static_findings(payload, sandbox=box)) == [] or what
    if what == "rows":
        qe.write_text("a,b\n" + "1,2\n" * 60, encoding="utf-8")
    elif what == "line":
        qe.write_text("a,b\n1," + "9" * 500 + "\n", encoding="utf-8")
    else:
        qe.write_text(",".join(f"c{i}" for i in range(20)) + "\n1\n", encoding="utf-8")
    found = rules.static_findings(payload, sandbox=box)
    assert "LIMIT_EXCEEDED" in _errors(found)
    assert any("QE.csv" in f.message or "datafile" in f.message for f in found)


def test_text_table_within_the_limits_is_accepted_and_example_unchanged(
    box: Sandbox, udir: Path
) -> None:
    payload = make_payload(udir)
    assert _errors(rules.static_findings(payload, sandbox=box)) == []


# --------------------------------------------------------------------------------
# item 6: more than one <ConfigPath>
# --------------------------------------------------------------------------------
@pytest.mark.parametrize("where", ["root", "nested", "comment"])
def test_repeated_configpath_is_refused(
    where: str, box: Sandbox, udir: Path, tmp_path: Path, no_loader: list[str]
) -> None:
    def edit(root: ET.Element) -> None:
        holder = root
        if where == "nested":
            holder = find(root, "common")
        elif where == "comment":
            holder = ET.SubElement(root, "comment")
        ET.SubElement(holder, "ConfigPath").text = "/elsewhere"

    payload = make_payload(udir, edit=edit)
    found = rules.static_findings(payload, sandbox=box)
    assert "CONFIGPATH_MULTIPLE" in _errors(found)
    assert (
        rules.normalise_payload(payload, sandbox=box, dest_dir=tmp_path / "c").path
        is None
    )
    assert (
        configuration.validate_configuration_file(str(payload), sandbox=box)["valid"]
        is False
    )
    assert no_loader == []


def test_single_configpath_still_gives_a_consistent_copy(
    box: Sandbox, udir: Path, tmp_path: Path
) -> None:
    payload = make_payload(udir)
    norm = rules.normalise_payload(payload, sandbox=box, dest_dir=tmp_path / "c")
    assert norm.path is not None
    assert [e.text for e in ET.parse(norm.path).getroot().iter("ConfigPath")] == [
        str(udir)
    ]
