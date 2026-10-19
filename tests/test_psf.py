import os
import unittest

import numpy as np
from astropy import units as u
from inputs import test_dir

from exorad.utils.exolib import binnedPSF, paosPSF, plot_imac


class CreatePrfTest(unittest.TestCase):
    def test_prf(self):
        prf, pixel_rf, extent = binnedPSF(
            F_x=10, F_y=12, wl=3.0 * u.micron, delta_pix=18.0 * u.micron, plot=False
        )
        print(prf.shape)
        assert isinstance(prf, np.ndarray)
        assert isinstance(pixel_rf, np.ndarray)
        assert isinstance(extent, tuple)

    def test_plot_prf(self):
        prf, _pixel_rf, extent = binnedPSF(
            F_x=33.5,
            F_y=33.5 * 1.1 / 0.73,
            wl=[0.55] * u.micron,
            delta_pix=18.0 * u.micron,
            plot=False,
        )

        _ = plot_imac(prf, extent, xlim=(-60, 60), ylim=(-60, 60))
        assert _ == 0


class LoadPAOSPhotTest(unittest.TestCase):
    paos_data = os.path.join(test_dir, "hdf5", "PAOS_Ariel_FGS-VISPhot.h5")
    parameters = {"grid_size": 512, "wavelength": 0.55}

    def setUp(self):
        if not os.path.exists(self.paos_data):
            self.skipTest("skipped test due to .h5 file not found")

    def test_loader(self):
        print(self.parameters["wavelength"])

        prf, _pixel_rf, extent = paosPSF(
            wl=[self.parameters["wavelength"]] * u.micron,
            delta_pix=18.0 * u.micron,
            filename=self.paos_data,
        )
        print("prf", prf.shape)
        print("extent", extent.shape)

    def test_shape(self):
        prf, _pixel_rf, extent = paosPSF(
            wl=[self.parameters["wavelength"]] * u.micron,
            delta_pix=18.0 * u.micron,
            filename=self.paos_data,
        )

        assert prf.shape == (
            self.parameters["grid_size"],
            self.parameters["grid_size"],
        ), "incorrect psf shape"
        assert extent.shape == (4,), "incorrect extent shape"

    def test_plot_prf(self):
        prf, _pixel_rf, extent = paosPSF(
            wl=[self.parameters["wavelength"]] * u.micron,
            delta_pix=18.0 * u.micron,
            filename=self.paos_data,
        )

        _ = plot_imac(prf, extent, xlim=(-60, 60), ylim=(-60, 60))
        assert _ == 0


class LoadPAOSSpecTest(unittest.TestCase):
    paos_data = os.path.join(test_dir, "hdf5", "PAOS_Ariel_FGS-NIRSpec.h5")
    parameters = {"grid_size": 512, "wavelength": 1.1}

    def setUp(self):
        if not os.path.exists(self.paos_data):
            self.skipTest("skipped test due to .h5 file not found")

    def test_loader(self):
        prf, _pixel_rf, extent = paosPSF(
            wl=[self.parameters["wavelength"]] * u.micron,
            delta_pix=18.0 * u.micron,
            filename=self.paos_data,
        )
        print("prf", prf.shape)
        print("extent", extent.shape)

    def test_loader_interp(self):
        prf, _pixel_rf, extent = paosPSF(
            wl=[1.5] * u.micron, delta_pix=18.0 * u.micron, filename=self.paos_data
        )
        print("prf", prf.shape)
        print("extent", extent.shape)

    def test_shape(self):
        prf, _pixel_rf, extent = paosPSF(
            wl=[self.parameters["wavelength"]] * u.micron,
            delta_pix=18.0 * u.micron,
            filename=self.paos_data,
        )

        assert prf.shape == (
            self.parameters["grid_size"],
            self.parameters["grid_size"],
        ), "incorrect psf shape"
        assert extent.shape == (4,), "incorrect extent shape"

    def test_plot_prf(self):
        prf, _pixel_rf, extent = paosPSF(
            wl=[self.parameters["wavelength"]] * u.micron,
            delta_pix=18.0 * u.micron,
            filename=self.paos_data,
        )

        _ = plot_imac(prf, extent, xlim=(-60, 60), ylim=(-60, 60))
        assert _ == 0
