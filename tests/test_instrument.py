import logging
import os
import pathlib
import unittest

import h5py

from exorad.log import setLogLevel
from exorad.models.instruments import Photometer, Spectrometer
from exorad.output.hdf5 import HDF5Output
from exorad.tasks import MergeChannelsOutput
from exorad.tasks.instrumentHandler import BuildChannels, LoadPayload
from exorad.tasks.loadOptions import LoadOptions

path = pathlib.Path(__file__).parent.absolute()
data_dir = os.path.join(path.parent.absolute(), 'examples')

loadOptions = LoadOptions()
options = loadOptions(filename=os.path.join(data_dir, 'payload_example.xml'))


class PhotometerTest(unittest.TestCase):
    setLogLevel(logging.DEBUG)
    photometer = Photometer('Phot', options['channel']['Phot'], options)
    photometer.build()

    def test_photometer_table(self):
        self.assertEqual(self.photometer.table['Wavelength'].value, 0.55)
        # self.assertEqual(self.photometer.table['TR'].value, 0.5)
        self.assertEqual(self.photometer.table['QE'].value, 0.55)


class SpectrometerTest(unittest.TestCase):
    setLogLevel(logging.DEBUG)
    spectrometer = Spectrometer('Spec', options['channel']['Spec'], options)
    spectrometer.build()

    def test_spectrometer_table(self):
        self.assertEqual(self.spectrometer.table['Wavelength'].size, 12)
        # self.assertListEqual(list(self.spectrometer.table['TR'].value), [0.5] * 12)
        self.assertListEqual(list(self.spectrometer.table['QE'].value), [0.7] * 12)


class InstrumentBuilderTest(unittest.TestCase):
    setLogLevel(logging.DEBUG)
    buildChannels = BuildChannels()
    channels = buildChannels(payload=options, write=False, output=None)

    def test_builder_dict(self):
        self.assertListEqual(list(self.channels.keys()), ['Phot', 'Spec'])


class IOTest(unittest.TestCase):
    setLogLevel(logging.INFO)

    buildChannels = BuildChannels()
    fname = 'test.h5'
    with HDF5Output(fname) as o:
        channels_built = buildChannels(payload=options, write=True, output=o)

    file = h5py.File(fname)
    loadPayload = LoadPayload()
    payload_loaded, channels_loaded = loadPayload(input=file)

    def test_instrument_list(self):
        self.assertListEqual(list(self.channels_built.keys()), list(self.channels_loaded.keys()))

    def test_instrument_build_from_file(self):
        with self.assertRaises(ValueError):
            self.channels_loaded['Phot'].build()
        with self.assertRaises(ValueError):
            self.channels_loaded['Spec'].build()

        os.remove(self.fname)


class MergeOutputTest(unittest.TestCase):
    setLogLevel(logging.INFO)
    buildChannels = BuildChannels()
    mergeChannelsOutput = MergeChannelsOutput()
    channels = buildChannels(payload=options, write=False, output=None)
    setLogLevel(logging.DEBUG)

    def test_table_output(self):
        table = self.mergeChannelsOutput(channels=self.channels)
