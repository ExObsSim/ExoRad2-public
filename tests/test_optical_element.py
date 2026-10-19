import astropy.units as u
import numpy as np
import pytest
from astropy.table import QTable

from exorad.models.optics.opticalElement import OpticalElement
from exorad.models.utils import get_wl_col_name

WL = np.linspace(1.0, 10.0, 50) * u.um


def _desc(**extra):
    d = {"value": "M1", "type": {"value": "surface"}}
    d.update(extra)
    return d


class TestTransmission:
    def test_constant_transmission(self):
        el = OpticalElement(_desc(transmission={"value": 0.9}), WL)
        assert np.allclose(el.transmission, 0.9)
        assert el.position == "path"

    def test_reflectivity_fallback(self):
        el = OpticalElement(_desc(reflectivity={"value": 0.8}), WL)
        assert np.allclose(el.transmission, 0.8)

    def test_wavelength_bounds(self):
        el = OpticalElement(
            _desc(
                transmission={"value": 1.0},
                wl_min={"value": 3.0 * u.um},
                wl_max={"value": 7.0 * u.um},
            ),
            WL,
        )
        assert el.transmission[3.0 * u.um > WL].max() == 0.0
        assert el.transmission[7.0 * u.um < WL].max() == 0.0
        assert el.transmission[(4 * u.um < WL) & (6 * u.um > WL)].min() == 1.0

    def test_default_transmission_is_unity(self):
        el = OpticalElement(_desc(), WL)
        assert np.allclose(el.transmission, 1.0)

    def test_both_without_use_raises(self):
        with pytest.raises(KeyError):
            OpticalElement(
                _desc(transmission={"value": 0.9}, reflectivity={"value": 0.8}), WL
            )

    def test_both_with_use(self):
        el = OpticalElement(
            _desc(
                transmission={"value": 0.9},
                reflectivity={"value": 0.8},
                use={"value": "reflectivity"},
            ),
            WL,
        )
        assert np.allclose(el.transmission, 0.8)

    def test_from_data_table(self):
        data = QTable(
            {
                "Wavelength": [1.0, 10.0] * u.um,
                "Transmission": [0.5, 0.5],
                "Emissivity": [0.5, 0.5],
            }
        )
        el = OpticalElement(_desc(data=data), WL)
        assert np.allclose(el.transmission, 0.5)

    def test_data_table_missing_transmission_column_raises(self):
        data = QTable(
            {
                "Wavelength": [1.0, 10.0] * u.um,
                "Nonsense": [0.5, 0.5],
                "Emissivity": [0.5, 0.5],
            }
        )
        with pytest.raises(KeyError):
            OpticalElement(_desc(data=data), WL)


class TestEmissivityTemperatureAngle:
    def test_constant_emissivity_and_temperature(self):
        el = OpticalElement(
            _desc(
                transmission={"value": 1.0},
                emissivity={"value": 0.1},
                temperature={"value": 80 * u.K},
                solid_angle={"value": 0.5 * u.sr},
            ),
            WL,
        )
        assert np.allclose(el.emissivity, 0.1)
        assert el.temperature == 80 * u.K
        assert el.angle == 0.5 * u.sr

    def test_unitless_temperature_and_angle_get_units(self):
        el = OpticalElement(
            _desc(
                transmission={"value": 1.0},
                temperature={"value": 90},
                solid_angle={"value": 0.3},
            ),
            WL,
        )
        assert el.temperature.unit == u.K
        assert el.angle.unit == u.sr

    def test_detector_box_defaults(self):
        el = OpticalElement({"value": "det", "type": {"value": "detector box"}}, WL)
        assert np.allclose(el.emissivity, 1.0)
        assert el.position == "detector"

    def test_optics_box_position(self):
        el = OpticalElement({"value": "ob", "type": {"value": "optics box"}}, WL)
        assert el.position == "optics box"

    def test_default_emissivity_is_zero(self):
        el = OpticalElement(_desc(transmission={"value": 1.0}), WL)
        assert np.allclose(el.emissivity, 0.0)

    def test_emissivity_from_data_table(self):
        data = QTable(
            {
                "Wavelength": [1.0, 10.0] * u.um,
                "Transmission": [0.9, 0.9],
                "Emissivity": [0.2, 0.2],
            }
        )
        el = OpticalElement(_desc(data=data), WL)
        assert np.allclose(el.emissivity, 0.2)

    def test_emissivity_data_table_missing_column_raises(self):
        data = QTable(
            {
                "Wavelength": [1.0, 10.0] * u.um,
                "Transmission": [0.9, 0.9],
                "Nonsense": [0.2, 0.2],
            }
        )
        with pytest.raises(KeyError):
            OpticalElement(_desc(data=data), WL)


class TestGetWlColName:
    def test_explicit_name(self):
        d = QTable({"lam": [1, 2] * u.um})
        assert get_wl_col_name(d, {"wl_col_name": {"value": "lam"}}) == "lam"

    def test_missing_raises(self):
        d = QTable({"nope": [1, 2]})
        with pytest.raises(KeyError):
            get_wl_col_name(d)
