import logging
import os
import pathlib
import unittest

import astropy.units as u
import h5py
import numpy as np

from exorad.log import setLogLevel
from exorad.models.instruments import Photometer, Spectrometer
from exorad.models.optics.opticalPath import OpticalPath
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


class InstrumentDiffuseLightTest(unittest.TestCase):
    wl_grid = np.logspace(np.log10(0.45),
                          np.log10(2.2), 6000) * u.um

    print(wl_grid)

    def test_transmission(self):
        telescope = OpticalPath(wl=self.wl_grid, description=options)
        tel = telescope.chain()

        phot = OpticalPath(wl=self.wl_grid, description=options['channel']['Phot'])
        phot.prepend_optical_elements(telescope.optical_element_dict)
        phot.build_transmission_table()
        phot = phot.chain()
        #
        spec = OpticalPath(wl=self.wl_grid, description=options['channel']['Spec'])
        spec.prepend_optical_elements(telescope.optical_element_dict)
        spec.build_transmission_table()

        import matplotlib.pyplot as plt
        fig = plt.figure(11)
        tab = spec.transmission_table
        for o in tab.keys():
            if o == 'Wavelength': continue
            plt.plot(tab['Wavelength'], tab[o], label=o)
        plt.legend()
        plt.show()

        spec = spec.chain()

        fig, ax = plt.subplots(1, 1)
        for o in phot:
            phot[o].plot(fig=fig, ax=ax, label=o, yscale='log')
        for o in spec:
            spec[o].plot(fig=fig, ax=ax, label=o, yscale='log')
        plt.legend()
        plt.show()

    def test_signal(self):
        setLogLevel(logging.INFO)
        photometer = Photometer('Phot', options['channel']['Phot'], options)
        photometer.build()

        spectrometer = Spectrometer('Spec', options['channel']['Spec'], options)
        spectrometer.build()

        setLogLevel(logging.DEBUG)

        telescope = OpticalPath(wl=self.wl_grid, description=options)
        phot = OpticalPath(wl=self.wl_grid, description=options['channel']['Phot'])
        phot.prepend_optical_elements(telescope.optical_element_dict)
        phot.build_transmission_table()
        phot.chain()
        phot.compute_signal(photometer.table, photometer.built_instr)
        print(phot.signal_table)

        telescope = OpticalPath(wl=self.wl_grid, description=options)
        spec = OpticalPath(wl=self.wl_grid, description=options['channel']['Spec'])
        spec.prepend_optical_elements(telescope.optical_element_dict)
        spec.build_transmission_table()
        spec.chain()
        table_signal = spec.compute_signal(spectrometer.table, spectrometer.built_instr)
        print(spec.signal_table)

        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(1, 1)
        wl = spectrometer.table['Wavelength']
        for col in spec.signal_table.keys():
            ax.plot(wl, spec.signal_table[col], label=col)
        ax.set_yscale('log')
        plt.legend()
        plt.show()
