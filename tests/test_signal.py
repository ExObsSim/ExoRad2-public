import logging
import unittest

import astropy.units as u
import numpy as np

from exorad.log import setLogLevel
from exorad.models.noise import Noise
from exorad.models.signal import CountsPerSeconds
from exorad.models.signal import Sed
from exorad.models.signal import Signal

setLogLevel(logging.DEBUG)


class SignalTest(unittest.TestCase):

    def test_quantity_check(self):
        try:
            wl = np.linspace(0.1, 1, 10) * u.um
            data = np.random.random_sample((10, 10))
            time_grid = np.linspace(1, 5, 10) * u.hr
            Signal(wl_grid=wl, data=data, time_grid=time_grid)
            CountsPerSeconds(wl_grid=wl, data=data * u.Unit('ct/s'),
                             time_grid=time_grid)
            Noise(wl_grid=wl, data=data * u.hr ** 0.5, time_grid=time_grid)
            Sed(wl_grid=wl, data=data * u.W / u.m ** 2 / u.um,
                time_grid=time_grid)

            wl = np.linspace(0.1, 1, 10) * u.m
            time_grid = np.linspace(1, 5, 10) * u.s
            Signal(wl_grid=wl, data=data, time_grid=time_grid)

            wl = np.linspace(0.1, 1, 10)
            data = np.random.random_sample(10)
            Signal(wl_grid=wl, data=data)
            CountsPerSeconds(wl_grid=wl, data=data)
            Noise(wl_grid=wl, data=data)
            Sed(wl_grid=wl, data=data)

        except u.UnitConversionError:
            self.fail("Signal raised Exception unexpectedly!")

        with self.assertRaises(u.UnitConversionError):
            wl = np.linspace(0.1, 1, 10) * u.s
            data = np.random.random_sample(10)
            Signal(wl_grid=wl, data=data)

    def test_time_dependency(self):
        wl = np.linspace(0.1, 1, 10)
        data = np.random.random_sample((10, 10))
        time_grid = np.linspace(1, 5, 10)
        sig = Signal(wl_grid=wl, data=data, time_grid=time_grid)
        with self.assertRaises(NotImplementedError):
            sig.time_dependent
        fl = CountsPerSeconds(wl_grid=wl, data=data, time_grid=time_grid)
        with self.assertRaises(NotImplementedError):
            fl.time_dependent

        data = np.random.random_sample(10)
        sig = Signal(wl_grid=wl, data=data)
        self.assertFalse(sig.time_dependent)
        fl = CountsPerSeconds(wl_grid=wl, data=data)
        self.assertFalse(fl.time_dependent)

    def test_dimension_check(self):
        with self.assertRaises(ValueError):
            wl = np.linspace(0.1, 1, 10) * u.um
            data = np.random.random_sample((10, 2))
            Signal(wl_grid=wl, data=data)

            wl = np.linspace(0.1, 1, 10) * u.um
            data = np.random.random_sample(10)
            time_grid = np.linspace(1, 5, 10) * u.hr
            Signal(wl_grid=wl, data=data, time_grid=time_grid)

    def test_rebins(self):
        pass
