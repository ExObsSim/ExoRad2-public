import astropy.units as u
import numpy as np
import pytest

from exorad.utils.exolib import paosPSF


class TestPaosPSF:
    def test_exact_wavelength_match(self, paos_h5):
        prf, kernel, extent = paosPSF(
            wl=[1.0] * u.micron, delta_pix=18.0 * u.micron, filename=paos_h5
        )
        assert prf.ndim == 2
        assert kernel.ndim == 2
        assert np.asarray(extent).shape == (4,)

    def test_interpolated_wavelength(self, paos_h5):
        prf, _kernel, _extent = paosPSF(
            wl=[1.5] * u.micron, delta_pix=18.0 * u.micron, filename=paos_h5
        )
        assert prf.ndim == 2

    def test_extrapolated_wavelength(self, paos_h5):
        prf, _kernel, _extent = paosPSF(
            wl=[3.0] * u.micron, delta_pix=18.0 * u.micron, filename=paos_h5
        )
        assert prf.ndim == 2

    def test_plot_path(self, paos_h5):
        paosPSF(
            wl=[1.0] * u.micron,
            delta_pix=18.0 * u.micron,
            filename=paos_h5,
            plot=True,
        )

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            paosPSF(
                wl=[1.0] * u.micron,
                delta_pix=18.0 * u.micron,
                filename="/no/such/file.h5",
            )

    def test_wrong_unit_asserts(self):
        with pytest.raises(AssertionError):
            paosPSF(wl=[1.0] * u.nm, delta_pix=18.0 * u.micron, filename="x.h5")

    def test_single_wavelength_file_cannot_interpolate(self, tmp_path):
        import h5py

        path = tmp_path / "one.h5"
        yy, xx = np.mgrid[-16:16, -16:16]
        with h5py.File(path, "w") as fd:
            g = fd.create_group("1.0/0")
            g["amplitude"] = np.exp(-(xx**2 + yy**2) / 50.0)
            g["dx"] = 6.0
            g["dy"] = 6.0
            g["extent"] = np.array([-48.0, 48.0, -48.0, 48.0])
            g["fratio"] = 5.0
        with pytest.raises(ValueError):
            paosPSF(wl=[2.0] * u.micron, delta_pix=18.0 * u.micron, filename=str(path))
