import logging
import os
import pathlib
import unittest

import astropy.units as u
from astropy.table import Column
from astropy.table import QTable
from test_options import payload_file

from exorad.log import setLogLevel
from exorad.output.hdf5 import HDF5Output
from exorad.tasks import LoadSource
from exorad.tasks.targetHandler import LoadTargetList
from exorad.tasks.targetHandler import PrepareTarget

path = pathlib.Path(__file__).parent.absolute()
data_dir = os.path.join(path.parent.absolute(), 'examples')

setLogLevel(logging.DEBUG)


class TargetTest(unittest.TestCase):
    target_list = os.path.join(data_dir, 'test_target.csv')

    def test_load_target_list(self):
        loadTargetList = LoadTargetList()
        targets = loadTargetList(target_list=self.target_list)
        with self.assertRaises(IOError):
            targets = loadTargetList(target_list='test_target.abc')

    def test_load_QTable_target_list(self):
        loadTargetList = LoadTargetList()
        names = Column(['test1', 'test2'], name='star name')
        masses = Column([1, 2] * u.M_sun, name='star M')
        temperatures = Column([5000, 6000] * u.K, name='star Teff')
        radii = Column([1, 2] * u.R_sun, name='star R')
        distances = Column([10, 12] * u.pc, name='star D')
        raw_targetlist = QTable(
            [names, masses, temperatures, radii, distances])

        targets = loadTargetList(target_list=raw_targetlist)

        distances = Column([10, 12], name='star D')
        raw_targetlist = QTable(
            [names, masses, temperatures, radii, distances])
        with self.assertRaises(TypeError):
            targets = loadTargetList(target_list=raw_targetlist)

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
        target, sed = self.loadSource(target=self.target, source=source,
                                      wl_range=(0.45, 2.2) * u.um)
        target, sed = self.loadSource(target=self.target, source=source,
                                      wl_range=(0.45, 2.2))

    def test_phoenix(self):

        try:
            source = {'value': 'phoenix',
                      'StellarModels': {
                          'value': '/usr/local/project_data/sed/'}}
            target, sed = self.loadSource(target=self.target, source=source,
                                          wl_range=(0.45, 2.2) * u.um)
        except:
            print('indicate the stellar model directory to test this option')

    def test_custom(self):
        source = {'value': 'custom',
                  'CustomSed': {
                      'value': os.path.join(data_dir, 'customsed.csv')}}
        target, sed = self.loadSource(target=self.target, source=source,
                                      wl_range=(0.45, 2.2) * u.um)


class PrepareTargeTest(unittest.TestCase):
    from exorad.tasks import PreparePayload

    setLogLevel(logging.INFO)
    loadTargetList = LoadTargetList()
    target_list = os.path.join(data_dir, 'test_target.csv')
    targets = loadTargetList(target_list=target_list)
    target = targets.target[0]
    loadSource = LoadSource()
    target, sed = loadSource(target=target, source='planck',
                             wl_range=(0.45, 2.2))

    preparePayload = PreparePayload()
    payload, channels, (wl_min, wl_max) = preparePayload(
        payload_file=payload_file(),
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
