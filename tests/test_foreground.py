import logging
import os
import pathlib
import unittest

import astropy.units as u
import matplotlib.pyplot as plt
import numpy as np
from conf import skip_plot
from test_options import payload_file

from exorad.log import setLogLevel
from exorad.models.foregrounds.zodiacalForeground import ZodiacalFrg
from exorad.tasks import LoadTargetList
from exorad.tasks import PreparePayload
from exorad.tasks import PrepareTarget

path = pathlib.Path(__file__).parent.absolute()
data_dir = os.path.join(path.parent.absolute(), 'examples')

options_filename = payload_file()
target_list = os.path.join(data_dir, 'test_target.csv')


class ZodiacalTest(unittest.TestCase):
    wl = np.logspace(np.log10(0.45), np.log10(2.2), 6000) * u.um

    def test_radiance(self):
        setLogLevel(logging.DEBUG)

        payload = {'zodiacal': {'zodiacFactor': {'value': 2.5},
                                'zodicalFrgMap': False}}

        zodi = ZodiacalFrg(wl=self.wl, description=payload['zodiacal'])

        if not skip_plot:
            zodi.radiance.plot()
            plt.show()

    def test_fit_coordinate(self):
        setLogLevel(logging.DEBUG)

        payload = {'zodiacal': {'zodiacalMap': {'value':True}}}

        zodi = ZodiacalFrg(wl=self.wl, description=payload['zodiacal'],
                           coordinates=(90.03841366076144 * u.deg,
                                        -66.55432012293919 * u.deg))

        payload = {'zodiacal': {'zodiacFactor': {'value': 1.4536394185097168},
                                'zodiacalMap': {'value': False}}}

        zodi_validation = ZodiacalFrg(wl=self.wl,
                                      description=payload['zodiacal'])

        self.assertListEqual(list(zodi.radiance.data.value),
                             list(zodi_validation.radiance.data.value))


class BackgroundHanderTest(unittest.TestCase):
    setLogLevel(logging.INFO)

    preparePayload = PreparePayload()
    loadTargetList = LoadTargetList()
    prepareTarget = PrepareTarget()
    payload, channels, (wl_min, wl_max) = preparePayload(
        payload_file=options_filename, output=None)
    targets = loadTargetList(target_list=target_list)
    target = targets.target[0]

    target = prepareTarget(target=target, channels=channels)

    def test_handler(self):
        setLogLevel(logging.DEBUG)

        from exorad.tasks.foregroundHandler import EstimateZodi
        estimateBackground = EstimateZodi()
        target = estimateBackground(
            zodi=self.payload['common']['foreground']['zodiacal'],
            target=self.target,
            wl_range=(self.wl_min, self.wl_max))
        print(target.foreground['zodi'].data)
