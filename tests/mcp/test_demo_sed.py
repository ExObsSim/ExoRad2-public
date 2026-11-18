"""The reduced-resolution demo SED that ships in the wheel (spec 4.3).

``examples/customsed.csv`` (22 MB) is too large for the wheel; the packaged
example payload points at ``examples/customsed_demo.csv`` instead. These tests
check the file itself, that its generator is deterministic, and (slow) that the
radiometric results obtained with it match those of the full SED.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import h5py
import numpy as np
import pytest
from astropy import units as u
from astropy.io import ascii

REPO = Path(__file__).resolve().parents[2]
FULL_SED = REPO / "examples" / "customsed.csv"
DEMO_SED = REPO / "examples" / "customsed_demo.csv"
PAYLOAD = REPO / "examples" / "payload_example.xml"
TARGETS = REPO / "examples" / "test_target.csv"

SIGNAL_TOL = 5e-3  # 0.5 % on every bin of star_signal_inAperture
LUMINOSITY_TOL = 1e-3  # 0.1 % on the bolometric luminosity


def _load_generator():
    script = REPO / "scripts" / "make_demo_sed.py"
    if not script.exists():  # dev tooling: not part of the public mirror
        pytest.skip("scripts/make_demo_sed.py is not in this checkout (public mirror)")
    spec = importlib.util.spec_from_file_location("_make_demo_sed", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _trapezoid_flux(path: Path) -> float:
    """Bolometric flux exactly as ``CustomSed`` computes it (W m-2)."""
    table = ascii.read(str(path), format="ecsv")
    wl = table["Wavelength"].data * table["Wavelength"].unit
    sed = table["Sed"].data * table["Sed"].unit
    return float(np.trapezoid(sed, x=wl).to_value(u.W / u.m**2))


needs_full_sed = pytest.mark.skipif(
    not FULL_SED.is_file(), reason="examples/customsed.csv is not available"
)


# --------------------------------------------------------------------------
# The committed file
# --------------------------------------------------------------------------
def test_demo_sed_size_and_rows():
    size = DEMO_SED.stat().st_size
    assert 300_000 < size < 700_000, size
    assert size < 1_048_576  # the per-asset cap of the wheel
    table = ascii.read(str(DEMO_SED), format="ecsv")
    assert len(table) > 20_000


def test_demo_sed_keeps_the_ecsv_header():
    table = ascii.read(str(DEMO_SED), format="ecsv")
    assert table.colnames == ["Wavelength", "Sed"]
    assert table["Wavelength"].unit == u.um
    assert table["Sed"].unit == u.W / (u.m**2 * u.um)
    first = DEMO_SED.read_text().splitlines()[0]
    assert first.startswith("# %ECSV")


def test_demo_sed_grid_is_sorted_and_covers_the_source_range():
    table = ascii.read(str(DEMO_SED), format="ecsv")
    wl = np.asarray(table["Wavelength"], dtype=float)
    assert np.all(np.diff(wl) > 0)
    assert wl[0] < 0.0101
    assert wl[-1] > 29.9
    fine = (wl >= 0.4) & (wl <= 2.6)
    steps = np.diff(wl[fine])
    assert steps.max() < 1.01e-4  # finer than the pipeline grid (about 1.19e-4)
    assert np.all(np.isfinite(np.asarray(table["Sed"], dtype=float)))


def test_the_committed_file_is_ascii():
    DEMO_SED.read_bytes().decode("ascii")


def test_the_example_payload_still_points_at_the_full_sed():
    # The repository example does not switch to the demo file (decision Q3);
    # only the packaged copy is rewritten by ASSET_TRANSFORMS.
    text = PAYLOAD.read_text()
    assert "examples/customsed.csv" in text
    assert "customsed_demo.csv" not in text


# --------------------------------------------------------------------------
# The generator
# --------------------------------------------------------------------------
@needs_full_sed
def test_regeneration_is_byte_identical(tmp_path):
    generator = _load_generator()
    out = tmp_path / "customsed_demo.csv"
    generator.main(["--src", str(FULL_SED), "--out", str(out)])
    assert out.read_bytes() == DEMO_SED.read_bytes()


@needs_full_sed
def test_luminosity_matches_the_full_sed():
    full = _trapezoid_flux(FULL_SED)
    demo = _trapezoid_flux(DEMO_SED)
    assert abs(demo / full - 1) < LUMINOSITY_TOL, (demo, full)


@needs_full_sed
def test_the_first_draft_grid_would_fail_the_luminosity_tolerance(tmp_path):
    """Guard against a test that cannot fail: the 0.4-2.6 um, 2e-4 um file of the
    first spec draft (no tails) loses several per cent of the luminosity."""
    table = ascii.read(str(FULL_SED), format="ecsv")
    wl = np.asarray(table["Wavelength"], dtype=float)
    sed = np.asarray(table["Sed"], dtype=float)
    edges = 0.4 + 2e-4 * np.arange(11_001)
    idx = np.searchsorted(edges, wl, side="right") - 1
    keep = (idx >= 0) & (idx < 11_000)
    mean = np.bincount(idx[keep], sed[keep], 11_000) / np.bincount(
        idx[keep], None, 11_000
    )
    centres = 0.5 * (edges[:-1] + edges[1:])
    deviation = abs(np.trapezoid(mean, centres) / _trapezoid_flux(FULL_SED) - 1)
    assert deviation > 10 * LUMINOSITY_TOL, deviation


# --------------------------------------------------------------------------
# Acceptance: the pipeline with the demo SED vs with the full SED
# --------------------------------------------------------------------------
def _run(payload: Path, out: Path) -> dict[str, dict]:
    from exorad import standard_pipeline

    standard_pipeline(
        options=str(payload),
        target_list=str(TARGETS),
        output=str(out),
        plot=False,
        n_thread=1,
        replace=True,
    )
    result: dict[str, dict] = {}
    with h5py.File(out, "r") as handle:
        for name in handle["targets"]:
            group = handle["targets"][name]
            result[name] = {
                "signal": np.asarray(group["table/table"]["star_signal_inAperture"]),
                "luminosity": float(np.asarray(group["star/luminosity/value"])),
            }
    return result


@needs_full_sed
@pytest.mark.slow
def test_demo_sed_reproduces_full_sed_within_tolerance(tmp_path, monkeypatch):
    """Both example targets: signal within 0.5 % per bin, luminosity within 0.1 %."""
    monkeypatch.chdir(REPO)  # the example uses ``<ConfigPath>.``: repo-root relative
    demo_payload = tmp_path / "payload_demo.xml"
    text = PAYLOAD.read_text()
    assert "examples/customsed.csv</CustomSed>" in text
    demo_payload.write_text(text.replace("customsed.csv", "customsed_demo.csv"))

    full = _run(PAYLOAD, tmp_path / "full" / "out.h5")
    demo = _run(demo_payload, tmp_path / "demo" / "out.h5")

    assert set(full) == set(demo) == {"myTest", "myTest2"}
    for name in full:
        a, b = full[name], demo[name]
        assert a["signal"].shape == b["signal"].shape
        assert np.all(a["signal"] > 0)
        signal_dev = np.abs(b["signal"] / a["signal"] - 1).max()
        lum_dev = abs(b["luminosity"] / a["luminosity"] - 1)
        print(
            f"{name}: max signal deviation {signal_dev:.3e}, luminosity {lum_dev:.3e}"
        )
        assert signal_dev < SIGNAL_TOL, (name, signal_dev)
        assert lum_dev < LUMINOSITY_TOL, (name, lum_dev)
