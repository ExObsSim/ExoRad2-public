import logging
import os
import pathlib
import unittest

from test_options import payload_file

from exorad.log import setLogLevel
from exorad.tasks import EstimateZodi
from exorad.tasks import LoadSource
from exorad.tasks import LoadTargetList
from exorad.tasks import PreparePayload
from exorad.tasks import PrepareTarget
from exorad.tasks import PropagateForegroundLight
from exorad.tasks import PropagateTargetLight

preparePayload = PreparePayload()
loadTargetList = LoadTargetList()
loadSource = LoadSource()
prepareTarget = PrepareTarget()
estimateBackground = EstimateZodi()

path = pathlib.Path(__file__).parent.absolute()
data_dir = os.path.join(path.parent.absolute(), 'examples')

options_filename = payload_file()
target_list = os.path.join(data_dir, 'test_target.csv')


class TargetPropagationTest(unittest.TestCase):
    payload, channels, (wl_min, wl_max) = preparePayload(
        payload_file=options_filename, output=None)
    targets = loadTargetList(target_list=target_list)
    target = targets.target[0]
    target, sed = loadSource(target=target,
                             source=payload['common']['sourceSpectrum'],
                             wl_range=(wl_min, wl_max))
    target = prepareTarget(target=target, channels=channels)

    setLogLevel(logging.DEBUG)

    def test_target(self):
        propagateTargetLight = PropagateTargetLight()
        target = propagateTargetLight(channels=self.channels,
                                      target=self.target)

        print(target.table)


class BackgroundPropagationTest(unittest.TestCase):
    setLogLevel(logging.INFO)
    payload, channels, (wl_min, wl_max) = preparePayload(
        payload_file=options_filename, output=None)
    targets = loadTargetList(target_list=target_list)
    target = targets.target[0]

    target = estimateBackground(
        zodi=payload['common']['foreground']['zodiacal'],
        target=target,
        wl_range=(wl_min, wl_max))
    target = prepareTarget(target=target, channels=channels)

    setLogLevel(logging.DEBUG)

    def test_target(self):
        setLogLevel(logging.DEBUG)
        propagateBackgroundLight = PropagateForegroundLight()
        target = propagateBackgroundLight(channels=self.channels,
                                          target=self.target)

        print(target.table)
