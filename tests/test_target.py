import logging
import os
import pathlib
import unittest

import astropy.units as u

from exorad.log import setLogLevel
from exorad.output.hdf5 import HDF5Output
from exorad.tasks import LoadSource
from exorad.tasks.targetHandler import LoadTargetList, PrepareTarget

path = pathlib.Path(__file__).parent.absolute()
data_dir = os.path.join(path.parent.absolute(), 'examples')

setLogLevel(logging.DEBUG)


class TargetTest(unittest.TestCase):
    target_list = os.path.join(data_dir, 'test_target.csv')

    def test_load_target_list(self):
        loadTargetList = LoadTargetList()
        targets = loadTargetList(target_list=self.target_list)

    def test_write(self):
        loadTargetList = LoadTargetList()
        targets = loadTargetList(target_list=self.target_list)
        fname = 'test.h5'
        with HDF5Output(fname) as o:
            for target in targets.target:
                target.write(o)

        os.remove(fname)


class SourceTest(unittest.TestCase):
    loadTargetList = LoadTargetList()
    target_list = os.path.join(data_dir, 'test_target.csv')
    targets = loadTargetList(target_list=target_list)
    target = targets.target[0]
    loadSource = LoadSource()

    def test_planck(self):
        source = {'value': 'Planck'}
        target, sed = self.loadSource(target=self.target, source=source, wl_range=(0.45, 2.2) * u.um)
        target, sed = self.loadSource(target=self.target, source=source, wl_range=(0.45, 2.2))

    def test_phoenix(self):

        try:
            source = {'value': 'phoenix',
                      'StellarModels': {'value': '/usr/local/project_data/sed/'}}
            target, sed = self.loadSource(target=self.target, source=source, wl_range=(0.45, 2.2) * u.um)
        except:
            print('indicate the stellar model directory to test this option')

    def test_custom(self):
        source = {'value': 'custom',
                  'CustomSed': {'value': os.path.join(data_dir, 'customsed.csv')}}
        target, sed = self.loadSource(target=self.target, source=source, wl_range=(0.45, 2.2) * u.um)


class PrepareTargeTest(unittest.TestCase):
    from exorad.tasks import PreparePayload

    setLogLevel(logging.INFO)
    loadTargetList = LoadTargetList()
    target_list = os.path.join(data_dir, 'test_target.csv')
    targets = loadTargetList(target_list=target_list)
    target = targets.target[0]
    loadSource = LoadSource()
    target, sed = loadSource(target=target, source='planck', wl_range=(0.45, 2.2))

    preparePayload = PreparePayload()
    payload, channels, (wl_min, wl_max) = preparePayload(payload_file=os.path.join(data_dir, 'payload_example.xml'),
                                                         output=None)

    setLogLevel(logging.DEBUG)

    prepareTarget = PrepareTarget()
    target = prepareTarget(target=target, channels=channels)
    print(target.table)

    def test_write(self):
        print(self.target.to_dict())
        fname = 'test.h5'
        with HDF5Output(fname, append=True) as out:
            self.target.write(out)

        os.remove(fname)
