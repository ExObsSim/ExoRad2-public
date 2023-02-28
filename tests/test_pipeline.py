import logging
import os
import pathlib
import unittest

from test_options import payload_file

import exorad.tasks as tasks
from exorad.log import setLogLevel

path = pathlib.Path(__file__).parent.absolute()
data_dir = os.path.join(path.parent.absolute(), 'examples')

setLogLevel(logging.DEBUG)


class PipelineTest(unittest.TestCase):
    loadOptions = tasks.LoadOptions()
    buildChannels = tasks.BuildChannels()
    buildInstrument = tasks.BuildInstrument()
    loadPayload = tasks.LoadPayload()
    loadTargetList = tasks.LoadTargetList()

    payload = loadOptions(filename=payload_file())
    wl_min, wl_max = payload['common']['wl_min']['value'], \
                     payload['common']['wl_max']['value']
    channels = buildChannels(payload=payload, write=False, output=None)
    targets = loadTargetList(
        target_list=os.path.join(data_dir, 'test_target.csv'))

    def test_full_pipe(self):
        prepareTarget = tasks.PrepareTarget()
        estimateForegrounds = tasks.EstimateForegrounds()
        propagateForegroundLight = tasks.PropagateForegroundLight()
        propagateTargetLight = tasks.PropagateTargetLight()
        estimateNoise = tasks.EstimateNoise()
        loadSource = tasks.LoadSource()

        for target in self.targets.target:
            target = prepareTarget(target=target, channels=self.channels)

            if 'foreground' in self.payload['common']:
                target = estimateForegrounds(
                    foregrounds=self.payload['common']['foreground'],
                    target=target,
                    wl_range=(self.wl_min, self.wl_max))
                target = propagateForegroundLight(channels=self.channels,
                                                  target=target)

            target, sed = loadSource(target=target,
                                     source=self.payload['common'][
                                         'sourceSpectrum'],
                                     wl_range=(self.wl_min, self.wl_max))
            target = propagateTargetLight(channels=self.channels,
                                          target=target)

            target = estimateNoise(target=target, channels=self.channels)

    def test_obsTarget(self):
        observeTarget = tasks.ObserveTarget()

        for target in self.targets.target:
            target = observeTarget(target=target, payload=self.payload,
                                   channels=self.channels,
                                   wl_range=(self.wl_min, self.wl_max))

    def test_obsTargetList(self):
        observeTargetList = tasks.ObserveTargetlist()

        targets = observeTargetList(targets=self.targets.target,
                                    payload=self.payload,
                                    channels=self.channels,
                                    wl_range=(self.wl_min, self.wl_max),
                                    plot=False, out_dir=None)
