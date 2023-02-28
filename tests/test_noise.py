import logging
import os
import pathlib
import unittest

from test_options import payload_file

from exorad.log import disableLogging
from exorad.log import enableLogging
from exorad.log import setLogLevel
from exorad.tasks import EstimateZodi
from exorad.tasks import LoadSource
from exorad.tasks import LoadTargetList
from exorad.tasks import PreparePayload
from exorad.tasks import PrepareTarget
from exorad.tasks import PropagateForegroundLight
from exorad.tasks import PropagateTargetLight
from exorad.tasks import UpdateTargetTable

preparePayload = PreparePayload()
propagateTargetLight = PropagateTargetLight()
propagateForegroundLight = PropagateForegroundLight()
loadTargetList = LoadTargetList()
updateTargetTable = UpdateTargetTable()
loadSource = LoadSource()
prepareTarget = PrepareTarget()
estimateForeground = EstimateZodi()

path = pathlib.Path(__file__).parent.absolute()
data_dir = os.path.join(path.parent.absolute(), 'examples')

target_list = os.path.join(data_dir, 'test_target.csv')


class NoiseTest(unittest.TestCase):
    disableLogging()
    payload, channels, (wl_min, wl_max) = preparePayload(
        payload_file=payload_file(), output=None)
    targets = loadTargetList(target_list=target_list)
    target = targets.target[0]
    target = prepareTarget(target=target, channels=channels)
    target, sed = loadSource(target=target,
                             source=payload['common']['sourceSpectrum'],
                             wl_range=(wl_min, wl_max))
    target = propagateTargetLight(channels=channels, target=target)
    target = estimateForeground(
        zodi=payload['common']['foreground']['zodiacal'],
        target=target,
        wl_range=(wl_min, wl_max))
    target = propagateForegroundLight(channels=channels, target=target)

    enableLogging()
    setLogLevel(logging.DEBUG)

    from exorad.tasks.noiseHandler import EstimateNoise

    estimateNoise = EstimateNoise()
    target = estimateNoise(target=target, channels=channels)
    print(target.table.keys())
