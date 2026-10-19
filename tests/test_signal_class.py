import astropy.units as u
import matplotlib.pyplot as plt
import numpy as np
import pytest

from exorad.models.signal import CountsPerSeconds, Radiance, Sed, Signal


def _wl(n=10):
    return np.linspace(0.5, 5.0, n) * u.um


class TestSignalConstruction:
    def test_dimensionless_data_gets_units(self):
        sig = Signal(wl_grid=_wl(), data=np.ones(10))
        assert sig.data.unit == u.dimensionless_unscaled
        assert sig.wl_grid.unit == u.um

    def test_quantity_conversion(self):
        sig = Signal(wl_grid=(_wl().to(u.nm)), data=np.ones(10))
        assert sig.wl_grid.unit == u.um

    def test_incompatible_units_raise(self):
        with pytest.raises(u.UnitConversionError):
            Signal(wl_grid=np.ones(10) * u.kg, data=np.ones(10))

    def test_multi_axis_wl_grid_rejected(self):
        with pytest.raises(ValueError):
            Signal(wl_grid=np.ones((2, 5)) * u.um, data=np.ones((2, 5)))

    def test_data_more_than_two_axes_rejected(self):
        with pytest.raises(ValueError):
            Signal(wl_grid=_wl(2), data=np.ones((2, 2, 2)))

    def test_wl_data_length_mismatch_rejected(self):
        with pytest.raises(ValueError):
            Signal(wl_grid=_wl(10), data=np.ones(8))


class TestSignalMethods:
    def test_spectral_rebin_updates_grid(self):
        sig = Signal(wl_grid=_wl(50), data=np.ones(50))
        new_grid = np.linspace(1.0, 4.0, 20) * u.um
        sig.spectral_rebin(new_grid)
        assert np.allclose(sig.wl_grid.value, new_grid.value)
        assert sig.data.shape == (20,)

    def test_temporal_rebin_not_implemented(self):
        sig = Signal(wl_grid=_wl(), data=np.ones(10))
        with pytest.raises(NotImplementedError):
            sig.temporal_rebin(np.linspace(0, 1, 10) * u.hr)

    def test_to_dict(self):
        sig = Signal(wl_grid=_wl(), data=np.ones(10))
        d = sig.to_dict()
        assert "data" in d
        assert "wl_grid" in d

    def test_plot_creates_and_reuses_axes(self):
        sig = Signal(wl_grid=_wl(), data=np.ones(10))
        fig, ax = sig.plot(yscale="log", xscale="linear", label="s")
        assert fig is not None
        _fig2, ax2 = sig.plot(fig=fig, ax=ax)
        assert ax2 is ax
        plt.close("all")


class TestCustomSignalSubclasses:
    def test_units(self):
        assert Sed(_wl(), np.ones(10)).data.unit.is_equivalent(u.W / u.m**2 / u.um)
        assert Radiance(_wl(), np.ones(10)).data.unit.is_equivalent(
            u.W / u.m**2 / u.um / u.sr
        )
        assert CountsPerSeconds(_wl(), np.ones(10)).data.unit.is_equivalent(u.ct / u.s)
