"""PSF-format and encircled-energy aperture branches of the instruments."""

import copy

import astropy.units as u
import numpy as np
import pytest
from astropy.io import fits
from test_options import payload_file

from exorad.models.instruments import Photometer, Spectrometer
from exorad.tasks.loadOptions import LoadOptions

_OPTIONS = LoadOptions()(filename=payload_file())


@pytest.fixture
def options():
    return copy.deepcopy(_OPTIONS)


@pytest.fixture
def fits_psf(tmp_path):
    yy, xx = np.mgrid[-32:32, -32:32]
    img = np.exp(-(xx**2 + yy**2) / 40.0)
    img /= img.sum()
    hdr = fits.Header()
    hdr["CDELT1"] = hdr["CDELT2"] = 0.5
    hdr["CRPIX1"] = hdr["CRPIX2"] = 32
    hdr["WAVELEN"] = 0.55
    path = tmp_path / "psf.fits"
    fits.writeto(path, img.astype(np.float64), hdr)
    return str(path)


class TestPhotometerPSF:
    def test_ene_aperture_with_airy_psf(self, options):
        options["channel"]["Phot"]["aperture"] = {"EnE": {"value": 0.83}}
        phot = Photometer("Phot", options["channel"]["Phot"], options)
        phot.build()
        assert phot.built_instr["window_size_px"] is not None

    def test_paos_psf(self, options, paos_h5):
        options["channel"]["Phot"]["PSF"] = {
            "value": paos_h5,
            "format": {"value": "paos"},
        }
        phot = Photometer("Phot", options["channel"]["Phot"], options)
        phot.build()
        assert phot.built_instr["PRF"].ndim == 2

    def test_pixel_based_psf_with_ene(self, options, fits_psf):
        options["channel"]["Phot"]["PSF"] = {
            "value": fits_psf,
            "format": {"value": "pixel_based"},
        }
        options["channel"]["Phot"]["aperture"] = {"EnE": {"value": 0.83}}
        phot = Photometer("Phot", options["channel"]["Phot"], options)
        phot.build()
        assert phot.built_instr["window_size_px"] is not None


class TestSpectrometerPSF:
    def test_paos_psf(self, options, paos_h5):
        options["channel"]["Spec"]["PSF"] = {
            "value": paos_h5,
            "format": {"value": "paos"},
        }
        spec = Spectrometer("Spec", options["channel"]["Spec"], options)
        spec.build()
        assert "gain_prf_data" in spec.built_instr

    def test_pixel_based_psf(self, options, fits_psf):
        options["channel"]["Spec"]["PSF"] = {
            "value": fits_psf,
            "format": {"value": "pixel_based"},
        }
        spec = Spectrometer("Spec", options["channel"]["Spec"], options)
        spec.build()
        assert "gain_prf_data" in spec.built_instr

    def test_wfe_strehl(self, options):
        options["channel"]["Spec"]["WFErms"] = {"value": 100 * u.nm}
        spec = Spectrometer("Spec", options["channel"]["Spec"], options)
        spec.build()
        assert spec.built_instr is not None
