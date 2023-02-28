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
from exorad.models.instruments import Photometer
from exorad.models.instruments import Spectrometer
from exorad.models.optics.opticalPath import OpticalPath
from exorad.tasks.loadOptions import LoadOptions

path = pathlib.Path(__file__).parent.absolute()
data_dir = os.path.join(path.parent.absolute(), 'examples')

loadOptions = LoadOptions()
options = loadOptions(filename=payload_file())


class InstrumentDiffuseLightTest(unittest.TestCase):

    def test_transmission(self):

        wl_grid = np.logspace(np.log10(
            options['channel']['Phot']['detector']['wl_min']['value'].value),
                              np.log10(options['channel']['Phot']['detector'][
                                           'cut_off']['value'].value),
                              6000) * u.um
        telescope = OpticalPath(wl=wl_grid, description=options)
        tel = telescope.chain()
        phot = OpticalPath(wl=wl_grid, description=options['channel']['Phot'])
        phot.prepend_optical_elements(telescope.optical_element_dict)
        phot.build_transmission_table()
        phot = phot.chain()
        #
        wl_grid = np.logspace(np.log10(
            options['channel']['Spec']['detector']['wl_min']['value'].value),
                              np.log10(options['channel']['Spec']['detector'][
                                           'cut_off']['value'].value),
                              6000) * u.um
        telescope = OpticalPath(wl=wl_grid, description=options)
        tel = telescope.chain()
        spec = OpticalPath(wl=wl_grid, description=options['channel']['Spec'])
        spec.prepend_optical_elements(telescope.optical_element_dict)
        spec.build_transmission_table()

        if not skip_plot:
            fig = plt.figure(11)
            tab = spec.transmission_table
            for o in tab.keys():
                if o == 'Wavelength': continue
                plt.plot(tab['Wavelength'], tab[o], label=o)
            plt.title('test_optical.test_transmission')
            plt.legend()
            plt.show()

        spec = spec.chain()

        if not skip_plot:
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

        spectrometer = Spectrometer('Spec', options['channel']['Spec'],
                                    options)
        spectrometer.build()

        setLogLevel(logging.DEBUG)

        wl_grid = np.logspace(np.log10(
            options['channel']['Phot']['detector']['wl_min']['value'].value),
                              np.log10(options['channel']['Phot']['detector'][
                                           'cut_off']['value'].value),
                              6000) * u.um
        telescope = OpticalPath(wl=wl_grid, description=options)
        telescope.chain()
        phot = OpticalPath(wl=wl_grid, description=options['channel']['Phot'])
        phot.prepend_optical_elements(telescope.optical_element_dict)
        phot.build_transmission_table()
        phot.chain()
        phot.compute_signal(photometer.table, photometer.built_instr)
        print(phot.signal_table)

        wl_grid = np.logspace(np.log10(
            options['channel']['Spec']['detector']['wl_min']['value'].value),
                              np.log10(options['channel']['Spec']['detector'][
                                           'cut_off']['value'].value),
                              6000) * u.um
        telescope = OpticalPath(wl=wl_grid, description=options)
        telescope.chain()
        spec = OpticalPath(wl=wl_grid, description=options['channel']['Spec'])
        spec.prepend_optical_elements(telescope.optical_element_dict)
        spec.build_transmission_table()
        spec.chain()
        spec.compute_signal(spectrometer.table, spectrometer.built_instr)
        print(spec.signal_table)

        if not skip_plot:
            fig, ax = plt.subplots(1, 1)
            wl = spectrometer.table['Wavelength']
            for col in spec.signal_table.keys():
                ax.plot(wl, spec.signal_table[col], alpha=0.5, label=col)
            ax.set_yscale('log')
            ax.set_title('test_optical.test_signal')
            plt.legend()
            plt.show()

    def test_values(self):

        # set constant qe
        options['channel']['Spec']['detector']['qe'] = {'value': 0.7}

        # prepare channel
        setLogLevel(logging.INFO)
        wl_grid = np.logspace(np.log10(
            options['channel']['Spec']['detector']['wl_min']['value'].value),
                              np.log10(options['channel']['Spec']['detector'][
                                           'cut_off']['value'].value),
                              6000) * u.um
        spectrometer = Spectrometer('Spec', options['channel']['Spec'],
                                    options)
        spectrometer.build()
        spec = OpticalPath(wl=wl_grid, description=options['channel']['Spec'])
        spec.build_transmission_table()
        spec.chain()
        spec.compute_signal(spectrometer.table, spectrometer.built_instr)

        setLogLevel(logging.DEBUG)

        # prepare elements to compute
        D1 = options['channel']['Spec']['optics']['opticalElement']['D1']
        M5 = options['channel']['Spec']['optics']['opticalElement']['M5']
        M6 = options['channel']['Spec']['optics']['opticalElement']['M6']
        optics = options['channel']['Spec']['optics']['opticalElement'][
            'optics']
        detector = options['channel']['Spec']['optics']['opticalElement'][
            'detector']
        qe = 0.7
        D = (options['channel']['Spec']['detector']['delta_pix']['value'])
        Windows = spectrometer.built_instr['window_size_px']
        Windows_spatial = spectrometer.built_instr['window_spatial_width']

        from exorad.utils.exolib import planck
        import astropy.constants as const
        from astropy.table import Table
        check_table = Table()

        # check detector: pi acceptance angle
        detector_radiance = planck(wl=wl_grid,
                                   T=detector['temperature']['value']).to(
            u.W / (u.m ** 2 * u.micron * u.sr))
        detector_radiance *= D ** 2 * np.pi * u.sr * qe * (
                    wl_grid / const.c / const.h).to(
            1. / u.W / u.s) * u.count
        detector_signal = (np.trapz(detector_radiance, x=wl_grid)).to(
            u.count / u.s)
        check_table['detector signal'] = detector_signal * Windows

        # check optic box: pi-omega_pix acceptance angle
        from exorad.utils.exolib import OmegaPix
        omega_pix = OmegaPix(
            options['channel']['Spec']['Fnum_x']['value'].value,
            options['channel']['Spec']['Fnum_y']['value'].value)
        optics_radiance = planck(wl=wl_grid,
                                 T=optics['temperature']['value']).to(
            u.W / (u.m ** 2 * u.micron * u.sr))
        optics_radiance *= D ** 2 * (np.pi * u.sr - omega_pix) * qe * (
                    wl_grid / const.c / const.h).to(
            1. / u.W / u.s) * u.count
        optics_signal = (np.trapz(optics_radiance, x=wl_grid)).to(
            u.count / u.s)
        check_table['optics signal'] = optics_signal * Windows

        # check M6: omega_pix acceptance angle
        M6_radiance = planck(wl=wl_grid, T=M6['temperature']['value']).to(
            u.W / (u.m ** 2 * u.micron * u.sr))
        M6_radiance *= M6['emissivity']['value']
        M6_radiance *= D ** 2 * omega_pix * qe * (
                    wl_grid / const.c / const.h).to(
            1. / u.W / u.s) * u.count
        M6_signal = (np.trapz(M6_radiance, x=wl_grid)).to(
            u.count / u.s)
        check_table['M6 signal'] = M6_signal * Windows

        # check M5: omega_pix acceptance angle, transmission applied (also D1) and slit
        slit_width = spectrometer.built_instr['slit_width']
        wl_pix = spectrometer.built_instr['wl_pix_center']
        dwl_pic = spectrometer.built_instr['pixel_bandwidth']
        ch_table = spectrometer.table
        slit_kernel = np.ones(int(slit_width / D.to(u.um)))

        M5_radiance = planck(wl=wl_grid, T=M5['temperature']['value']).to(
            u.W / (u.m ** 2 * u.micron * u.sr))
        M5_radiance *= M5['emissivity']['value'] * M6['transmission'][
            'value'] * D1['transmission']['value']

        wl_min, wl_max = D1['wl_min']['value'], D1['wl_max']['value']
        idx = np.where(wl_grid < wl_min)
        M5_radiance[idx] = 0.0
        idx = np.where(wl_grid > wl_max)
        M5_radiance[idx] = 0.0
        M5_radiance *= D ** 2 * omega_pix * qe * (
                    wl_grid / const.c / const.h).to(
            1. / u.W / u.s) * u.count
        from exorad.utils.exolib import rebin
        _, M5_radiance = rebin(wl_pix, wl_grid, M5_radiance)
        M5_signal_tmp = (
            np.convolve(M5_radiance * dwl_pic, slit_kernel, 'same')).to(
            u.count / u.s)
        idx = [np.logical_and(wl_pix > wlow, wl_pix <= whigh)
               for wlow, whigh in
               zip(ch_table['LeftBinEdge'], ch_table['RightBinEdge'])]
        M5_signal = [M5_signal_tmp[idx[k]].value.sum() for k in
                     range(len(idx))]
        check_table['M5 signal'] = M5_signal * u.ct / u.s * Windows_spatial

        spec.signal_table.remove_column('D1 signal')

        if not skip_plot:
            fig, ax = plt.subplots(1, 1)
            wl = spectrometer.table['Wavelength']
            for col in spec.signal_table.keys():
                ax.plot(wl, spec.signal_table[col], alpha=0.5, lw=1, label=col)
                ax.plot(wl, check_table[col], alpha=0.5, ls=':', lw=3,
                        label='{} check'.format(col))
            ax.set_yscale('log')
            fig.suptitle('test_optical.test_values 1')
            ax.legend()
            plt.show()

            fig, ax = plt.subplots(1, 1)
            wl = spectrometer.table['Wavelength']
            for col in spec.signal_table.keys():
                ax.plot(wl, spec.signal_table[col] / check_table[col],
                        alpha=0.5, label=col)
            ax.set_yscale('log')
            fig.suptitle('test_optical.test_values 2')
            ax.legend()
            plt.show()

        for col in spec.signal_table.keys():
            # check absolute equality up to 1e-40
            np.testing.assert_almost_equal(spec.signal_table[col].value,
                                           check_table[col], decimal=40,
                                           err_msg='',
                                           verbose=True)

        for col in spec.signal_table.keys():
            # check relative equality up to 1%
            np.testing.assert_almost_equal(
                spec.signal_table[col].value / check_table[col],
                np.ones(len(check_table[col])), decimal=2, err_msg='',
                verbose=True)
