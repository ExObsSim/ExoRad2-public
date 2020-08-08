import logging
import os
import pathlib
import unittest

import exorad.tasks as tasks
import exorad.tasks.loadSource
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
    loadSource = exorad.tasks.loadSource.LoadSource()

    # step 1 load options
    payload = loadOptions(filename=os.path.join(data_dir, 'payload_example.xml'))
    wl_min, wl_max = payload['common']['wl_min']['value'], payload['common']['wl_max']['value']
    channels = buildChannels(payload=payload, write=False, output=None)
    targets = loadTargetList(target_list=os.path.join(data_dir, 'test_target.csv'))
    for target in targets.target:
        target, sed = loadSource(target=target, source='planck', wl_range=(wl_min, wl_max))
