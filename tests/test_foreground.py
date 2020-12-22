import logging
import os
import pathlib
import unittest

import astropy.units as u
import matplotlib.pyplot as plt
import numpy as np

from exorad.log import setLogLevel
from exorad.models.foregrounds.zodiacalForeground import ZodiacalFrg
from exorad.tasks import PreparePayload, PrepareTarget, LoadTargetList
from test_options import payload_file

path = pathlib.Path(__file__).parent.absolute()
data_dir = os.path.join(path.parent.absolute(), 'examples')

options_filename = payload_file()
target_list = os.path.join(data_dir, 'test_target.csv')


class ZodiacalTest(unittest.TestCase):
    wl = np.logspace(np.log10(0.45), np.log10(2.2), 6000) * u.um

    def test_radiance(self):
        setLogLevel(logging.DEBUG)

        payload = {'zodiacal': {'zodiacFactor': {'value': 2.5}}}

        zodi = ZodiacalFrg(wl=self.wl, description=payload['zodiacal'])

        zodi.radiance.plot()
        plt.show()


class BackgroundHanderTest(unittest.TestCase):
    setLogLevel(logging.INFO)

    preparePayload = PreparePayload()
    loadTargetList = LoadTargetList()
    prepareTarget = PrepareTarget()
    payload, channels, (wl_min, wl_max) = preparePayload(payload_file=options_filename, output=None)
    targets = loadTargetList(target_list=target_list)
    target = targets.target[0]

    target = prepareTarget(target=target, channels=channels)

    def test_handler(self):
        setLogLevel(logging.DEBUG)

        from exorad.tasks.foregroundHandler import EstimateZodi
        estimateBackground = EstimateZodi()
        target = estimateBackground(zodi=self.payload['common']['foreground']['zodiacal'],
                                    target=self.target,
                                    wl_range=(self.wl_min, self.wl_max))
        print(target.foreground['zodi'].data)
