import astropy.units as u
import numpy as np
import pytest
from astropy.io import fits

from exorad.utils import exolib


@pytest.fixture
def psf_fits_dir(tmp_path):
    """A directory of tiny gaussian-PSF FITS files with WAVELEN headers."""
    yy, xx = np.mgrid[-32:32, -32:32]
    for wl in (2.0, 3.0, 4.0):
        img = np.exp(-(xx**2 + yy**2) / (2 * (4 * wl) ** 2))
        img /= img.sum()
        hdr = fits.Header()
        hdr["WAVELEN"] = wl
        hdr["CDELT1"] = hdr["CDELT2"] = 0.5
        hdr["CRPIX1"] = hdr["CRPIX2"] = 32
        fits.writeto(tmp_path / f"psf_{wl:.1f}.fits", img.astype(np.float64), hdr)
    return str(tmp_path) + "/"


class TestRebin:
    def test_interpolation_path(self):
        xp = np.linspace(1.0, 10.0, 60) * u.um
        fp = (2.0 * xp.value + 1.0) * u.W  # linear -> exact under linear interp
        x = np.linspace(2.0, 9.0, 200) * u.um

        new_x, new_f = exolib.rebin(x, xp, fp)

        assert new_f.unit == u.W
        np.testing.assert_allclose(new_x.value, x.value)
        np.testing.assert_allclose(new_f.value, 2.0 * x.value + 1.0, rtol=1e-6)

    def test_binning_path(self):
        # input grid finer than output -> triggers the binned_statistic branch
        xp = np.linspace(1.0, 10.0, 5000) * u.um
        fp = np.ones_like(xp.value) * u.Jy
        x = np.linspace(2.0, 9.0, 20) * u.um

        _, new_f = exolib.rebin(x, xp, fp)

        assert new_f.unit == u.Jy
        np.testing.assert_allclose(new_f.value, 1.0, rtol=1e-6)

    def test_unit_mismatch_raises(self):
        xp = np.linspace(1, 10, 10) * u.um
        fp = np.ones(10) * u.W
        x = np.linspace(2, 9, 5) * u.nm
        with pytest.raises(ValueError):
            exolib.rebin(x, xp, fp)

    def test_dimensionless_fp_gets_a_unit(self):
        xp = np.linspace(1.0, 10.0, 200) * u.um
        fp = np.linspace(1.0, 10.0, 200)  # plain ndarray, no unit
        x = np.linspace(2.0, 9.0, 30) * u.um

        _, new_f = exolib.rebin(x, xp, fp)
        assert hasattr(new_f, "unit")

    def test_nan_and_duplicates_are_removed(self):
        xp = np.linspace(1.0, 10.0, 200) * u.um
        fp = np.ones(200) * u.W
        xp.value[10] = np.nan
        xp.value[50] = xp.value[51]  # duplicate
        x = np.linspace(2.0, 9.0, 40) * u.um
        x.value[5] = x.value[6]  # duplicate in the target grid

        _, new_f = exolib.rebin(x, xp, fp)
        assert np.all(np.isfinite(new_f.value))


class TestPlanck:
    def test_spectrum_shape_and_units(self):
        wl = np.linspace(1, 20, 50) * u.um
        bb = exolib.planck(wl, 300 * u.K)
        assert bb.shape == wl.shape
        assert bb.unit.is_equivalent(u.W / u.m**2 / u.sr / u.um)
        assert np.all(bb.value > 0)

    def test_wien_peak_moves_with_temperature(self):
        wl = np.linspace(1, 30, 400) * u.um
        hot = exolib.planck(wl, 600 * u.K)
        cold = exolib.planck(wl, 200 * u.K)
        assert wl[np.argmax(hot)] < wl[np.argmax(cold)]


class TestOmegaPix:
    def test_circular_matches_small_angle_formula(self):
        omega = exolib.OmegaPix(10.0)
        sigma = np.arctan(1.0 / (2 * 10.0))
        approx = 2 * np.pi * (1 - np.cos(sigma))
        assert omega.unit == u.sr
        assert float(omega.value) == pytest.approx(approx, rel=1e-3)

    def test_single_argument_defaults_fnum_y(self):
        assert exolib.OmegaPix(7.0).value == pytest.approx(
            exolib.OmegaPix(7.0, 7.0).value
        )

    def test_elliptical_branch_is_symmetric(self):
        a = exolib.OmegaPix(5.0, 8.0)
        b = exolib.OmegaPix(8.0, 5.0)
        assert a.value == pytest.approx(b.value)


class TestBinnedPSF:
    def test_airy_kernel_without_file(self):
        wl = [3.0] * u.um
        delta_pix = 18.0 * u.um
        imac, kernel, extent = exolib.binnedPSF(
            F_x=5.0, F_y=5.0, wl=wl, delta_pix=delta_pix
        )
        assert imac.ndim == 2
        assert kernel.ndim == 2
        assert len(extent) == 4

    def test_plot_path_uses_agg(self):
        wl = [3.0] * u.um
        # plot=True exercises plot_imac; the Agg backend makes it a no-op
        exolib.binnedPSF(F_x=5.0, F_y=5.0, wl=wl, delta_pix=18.0 * u.um, plot=True)


class TestEncircledEnergy:
    def test_grows_monotonically_and_saturates(self):
        imac, _, _ = exolib.binnedPSF(
            F_x=5.0, F_y=5.0, wl=[3.0] * u.um, delta_pix=18.0 * u.um
        )
        wl = 3.0 * u.um
        e_small = exolib.encircled_energy(2, imac, 5.0, 5.0, wl)
        e_large = exolib.encircled_energy(20, imac, 5.0, 5.0, wl)
        assert 0 <= e_small <= e_large <= 1.0 + 1e-6

    def test_find_aperture_radius(self):
        imac, _, _ = exolib.binnedPSF(
            F_x=5.0, F_y=5.0, wl=[3.0] * u.um, delta_pix=18.0 * u.um
        )
        r = exolib.find_aperture_radius(imac, 0.83, 5.0, 5.0, 3.0 * u.um)
        assert float(r) > 0


class TestPsfHeaderHelpers:
    HDR = {
        "CDELT1": 0.5,
        "CDELT2": 0.5,
        "CRPIX1": 64,
        "CRPIX2": 64,
        "NAXIS1": 128,
        "NAXIS2": 128,
    }

    def test_load_standard_psf(self):
        k_x, k_y, extent = exolib.load_standard_psf(
            F_x=5.0, F_y=5.0, wl=3.0 * u.um, delta_pix=18.0 * u.um, hdr=self.HDR
        )
        assert k_x > 0
        assert k_y > 0
        assert len(extent) == 4

    def test_load_pixel_psf_size(self):
        extent = exolib.load_pixel_psf_size(18.0 * u.um, self.HDR)
        assert len(extent) == 4
        assert all(e.unit == u.micron for e in extent)


class TestPsfFromFits:
    def test_binned_psf_from_fits_directory(self, psf_fits_dir):
        imac, _kernel, extent = exolib.binnedPSF(
            F_x=5.0,
            F_y=5.0,
            wl=3.1 * u.um,
            delta_pix=18.0 * u.um,
            filename=psf_fits_dir,
        )
        assert imac.ndim == 2
        assert len(extent) == 4

    def test_binned_psf_from_single_fits_file(self, psf_fits_dir):
        imac, _, _ = exolib.binnedPSF(
            F_x=5.0,
            F_y=5.0,
            wl=3.0 * u.um,
            delta_pix=18.0 * u.um,
            filename=psf_fits_dir + "psf_3.0.fits",
        )
        assert imac.ndim == 2

    def test_pixel_based_psf_directory(self, psf_fits_dir):
        ima, scale, extent = exolib.pixel_based_psf(
            3.1 * u.um, 18.0 * u.um, psf_fits_dir
        )
        assert ima.ndim == 2
        assert scale.tolist() == [1.0]
        assert len(extent) == 4

    def test_pixel_based_psf_single_file(self, psf_fits_dir):
        ima, _, _ = exolib.pixel_based_psf(
            3.0 * u.um, 18.0 * u.um, psf_fits_dir + "psf_3.0.fits"
        )
        assert ima.ndim == 2

    def test_find_aperture_radius_pixel_units(self, psf_fits_dir):
        ima, _, _ = exolib.pixel_based_psf(
            3.0 * u.um, 18.0 * u.um, psf_fits_dir + "psf_3.0.fits"
        )
        r = exolib.find_aperture_radius(ima, 0.83, 1, 1, 1 * u.micron)
        assert float(r) > 0
