from collections import OrderedDict

import astropy.units as u
import numpy as np
from astropy.table import QTable

from exorad.models.noise import (
    add_custom_noise,
    frame_time,
    multiaccum,
    photon_noise,
    photon_noise_variance,
)
from exorad.models.target import Target


def _target_table():
    t = Target()
    t.table = QTable(
        {
            "chName": ["Ch", "Ch"],
            "Wavelength": [1.0, 2.0] * u.um,
            "MaxSignal_inPixel": [100.0, 200.0] * u.ct / u.s,
            "signal": [10.0, 20.0] * u.ct / u.s,
        }
    )
    return t


class TestFrameTime:
    def test_explicit_frame_time(self):
        channel = {
            "value": "Ch",
            "detector": {
                "well_depth": {"value": 1000.0 * u.ct},
                "frame_time": {"value": 0.5 * u.s},
            },
        }
        out = frame_time(_target_table(), channel, QTable())
        assert np.allclose(out["frameTime"].value, 0.5)

    def test_derived_frame_time(self):
        channel = {
            "value": "Ch",
            "detector": {
                "well_depth": {"value": 1000.0 * u.ct},
                "f_well_depth": {"value": 0.8},
            },
        }
        out = frame_time(_target_table(), channel, QTable())
        assert out["frameTime"].size == 2


class TestMultiaccum:
    def test_with_multiaccum_m(self):
        channel = {
            "detector": {"freqNDR": {"value": 10.0 / u.s}, "multiaccumM": {"value": 4}}
        }
        read_gain, shot_gain = multiaccum(channel, 1.0 * u.s)
        assert read_gain > 0
        assert shot_gain > 0

    def test_without_multiaccum_forces_cds(self):
        channel = {"detector": {"freqNDR": {"value": 0.1 / u.s}}}
        read_gain, _shot_gain = multiaccum(channel, 1.0 * u.s)
        assert np.isfinite(read_gain)


class TestPhotonNoise:
    def test_photon_noise_and_variance(self):
        table = QTable(
            {
                "chName": ["Ch", "Ch"],
                "star_signal": [100.0, 400.0] * u.ct / u.s,
            }
        )
        out = QTable({"frameTime": [1.0, 1.0] * u.s})
        photon_noise(table, {"value": "Ch"}, 1.0, out)
        assert "star_signal_noise" in out.colnames
        var = photon_noise_variance(table, out)
        assert var.unit.is_equivalent((u.ct / u.s) ** 2 * u.hr)


class TestAddCustomNoise:
    def test_data_dict_form(self):
        wl = np.linspace(0.5, 5.0, 20) * u.um
        out = QTable({"total_noise": np.ones(20) * u.hr**0.5})
        custom = {
            "data": {
                "Wavelength": wl,
                "jitter": np.full(20, 1e-5),
            }
        }
        add_custom_noise(custom, wl, out)
        assert "jitter_noise" in out.colnames
        assert out["total_noise"].unit == u.hr**0.5
        assert out["total_noise"][0].value >= 1.0

    def test_ordered_dict_form(self):
        wl = np.linspace(0.5, 5.0, 5) * u.um
        out = QTable({"total_noise": np.ones(5) * u.hr**0.5})
        custom = OrderedDict(
            {"jit": {"value": 20.0, "name": {"value": "jitter_floor"}}}
        )
        add_custom_noise(custom, wl, out)
        assert "jitter_floor_noise" in out.colnames
