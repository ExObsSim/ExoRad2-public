import os
from unittest.mock import patch

import astropy.units as u
import numpy as np
import pytest

from exorad.models.signal import Sed
from exorad.models.target import Target
from exorad.tasks.loadSource import LoadSource

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples"
)
CUSTOM_SED = os.path.join(DATA_DIR, "customsed.csv")


class _FakeDownloadSed:
    """Stand-in for the network-backed DownloadSed task."""

    captured: dict = {}

    def __call__(self, **kwargs):
        _FakeDownloadSed.captured = dict(kwargs)
        wl = np.linspace(0.3, 3.0, 800) * u.um
        data = np.full(800, 1e-15) * (u.W / u.m**2 / u.um)
        sed = Sed(wl_grid=wl, data=data)
        sed.meta = {
            "filename": "bt-settl-cifist_T5000.spec",
            "model": kwargs["model_name"],
        }
        return sed


def _target(**star_attrs):
    t = Target()
    t.star = Target()
    defaults = {
        "name": "star",
        "D": 12.0 * u.pc,
        "Teff": 5000.0 * u.K,
        "M": 1.0 * u.M_sun,
        "R": 1.0 * u.R_sun,
    }
    defaults.update(star_attrs)
    for k, v in defaults.items():
        setattr(t.star, k, v)
    return t


class TestLoadSource:
    task = LoadSource()

    def test_planck(self):
        target, sed = self.task(
            target=_target(), source={"value": "Planck"}, wl_range=(0.5, 3.0) * u.um
        )
        assert target.star.sed is not None
        assert sed.data.unit.is_equivalent(u.W / u.m**2 / u.um)

    def test_string_source_is_coerced_to_dict(self):
        target, _sed = self.task(
            target=_target(), source="Planck", wl_range=(0.5, 3.0) * u.um
        )
        assert target.star.model == "Planck"

    def test_wl_range_is_reordered_and_units_assumed(self):
        target, _sed = self.task(
            target=_target(), source={"value": "Planck"}, wl_range=(3.0, 0.5)
        )
        assert target.star.sed.wl_grid.min() < target.star.sed.wl_grid.max()

    def test_unknown_source_falls_back_to_planck(self):
        target, _sed = self.task(
            target=_target(), source={"value": "banana"}, wl_range=(0.5, 3.0) * u.um
        )
        assert target.star.model == "Planck"

    def test_custom_sed(self):
        target, _sed = self.task(
            target=_target(),
            source={"value": "custom", "CustomSed": {"value": CUSTOM_SED}},
            wl_range=(0.5, 2.0) * u.um,
        )
        assert target.star.model == "Custom"

    def test_custom_sed_incomplete_target_raises(self):
        bad = _target()
        bad.star.R = "not a quantity"
        with pytest.raises(AttributeError):
            self.task(
                target=bad,
                source={"value": "custom", "CustomSed": {"value": CUSTOM_SED}},
                wl_range=(0.5, 2.0) * u.um,
            )

    def test_incomplete_star_raises(self):
        bad = _target()
        bad.star.Teff = "nope"
        with pytest.raises(AttributeError):
            self.task(
                target=bad, source={"value": "Planck"}, wl_range=(0.5, 3.0) * u.um
            )

    def test_phoenix_without_path_raises(self):
        with pytest.raises(OSError):
            self.task(
                target=_target(),
                source={"value": "phoenix"},
                wl_range=(0.5, 3.0) * u.um,
            )

    def test_phoenix_nonexistent_path_raises(self):
        with pytest.raises(OSError):
            self.task(
                target=_target(),
                source={
                    "value": "phoenix",
                    "StellarModels": {"value": "/no/such/dir"},
                },
                wl_range=(0.5, 3.0) * u.um,
            )

    def test_phoenix_out_of_grid_falls_back_to_planck(self, phoenix_dir):
        # phoenix_dir fixture lives in tests/test_source.py; T well outside grid
        target, _sed = self.task(
            target=_target(Teff=50000 * u.K),
            source={"value": "phoenix", "StellarModels": {"value": phoenix_dir}},
            wl_range=(0.5, 3.0) * u.um,
        )
        assert target.star.model == "Planck"

    def test_phoenix_reads_spectrum(self, phoenix_dir):
        target, _sed = self.task(
            target=_target(Teff=3000 * u.K),
            source={"value": "phoenix", "StellarModels": {"value": phoenix_dir}},
            wl_range=(0.5, 3.0) * u.um,
        )
        assert "BT-Settl" in target.star.model

    def test_sed_download_branch(self):
        with patch("exorad.tasks.downloadSed.DownloadSed", _FakeDownloadSed):
            target, sed = self.task(
                target=_target(),
                source={"value": "sed", "SedModel": {"value": "bt-settl-cifist"}},
                wl_range=(0.5, 2.5) * u.um,
            )
        assert target.star.model == "bt-settl-cifist"
        assert target.star.luminosity.unit.is_equivalent(u.L_sun)
        assert sed.data.unit.is_equivalent(u.W / u.m**2 / u.um)
        assert _FakeDownloadSed.captured["model_name"] == "bt-settl-cifist"

    def test_sed_download_defaults_to_bt_settl_cifist(self):
        with patch("exorad.tasks.downloadSed.DownloadSed", _FakeDownloadSed):
            self.task(
                target=_target(),
                source={"value": "sed"},
                wl_range=(0.5, 2.5) * u.um,
            )
        assert _FakeDownloadSed.captured["model_name"] == "bt-settl-cifist"

    def test_sed_download_failure_falls_back_to_planck(self):
        boom = patch(
            "exorad.tasks.downloadSed.DownloadSed",
            side_effect=ConnectionError("no network"),
        )
        with boom:
            target, _sed = self.task(
                target=_target(),
                source={"value": "sed"},
                wl_range=(0.5, 2.5) * u.um,
            )
        assert target.star.model == "Planck"

    def test_star_metadata_added_to_table(self):
        from astropy.table import QTable

        target = _target(magk=8.0)
        target.table = QTable({"Wavelength": [1.0, 2.0] * u.um})
        out, _sed = self.task(
            target=target, source={"value": "Planck"}, wl_range=(0.5, 3.0) * u.um
        )
        assert out.table.meta["starName"] == "star"
        assert out.table.meta["starModel"] == "Planck"
        assert out.table.meta["starMagK"] == 8.0
