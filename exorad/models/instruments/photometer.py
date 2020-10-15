import astropy.constants as const
import astropy.units as u
import numpy as np
from astropy.table import QTable

from exorad.utils.exolib import binnedPSF
from .instrument import Instrument


class Photometer(Instrument):
    """
    Photometer instrument class.
    """

    def _wavelength_table(self):
        wl_c = 0.5 * (self.description['wl_min']['value']
                      + self.description['wl_max']['value'])
        bandwidth = (self.description['wl_max']['value']
                     - self.description['wl_min']['value'])
        left_bin_edge = wl_c - 0.5 * bandwidth
        right_bin_edge = wl_c + 0.5 * bandwidth
        self.table['chName'] = [self.name]
        self.table['Wavelength'] = [wl_c.value] * wl_c.unit
        self.table['Bandwidth'] = [bandwidth.value] * bandwidth.unit
        self.table['LeftBinEdge'] = [left_bin_edge.value] * left_bin_edge.unit
        self.table['RightBinEdge'] = [right_bin_edge.value] * right_bin_edge.unit
        self.debug('wavelength table: \n{}'.format(self.table))

    def builder(self):
        self.info('building {}'.format(self.name))
        self._wavelength_table()
        # self.table['TR'], transmission_data = self._get_transmission()
        # self._add_data_to_built('transmission_data', transmission_data.to_dict())

        self.table['QE'], qe_data = self._get_qe()
        self._add_data_to_built('qe_data', qe_data.to_dict())

        if 'PSF' in self.description.keys():
            self.debug('PSF found')
            psfFilename = self.description['PSF']['value']
        else:
            psfFilename = None

        prf, pixel_rf, extent = binnedPSF(self.description['Fnum_x']['value'],
                                          self.description['Fnum_y']['value'],
                                          self.table['Wavelength'],
                                          self.description['detector']['delta_pix']['value'],
                                          filename=psfFilename)
        self._add_data_to_built('PRF', prf)
        self._add_data_to_built('pixelRF', pixel_rf)
        self._add_data_to_built('extent', extent)

        window_size_px = self.description['aperture']['radius']['value'] ** 2 * \
                         self.description['Fnum_x']['value'] * self.table['Wavelength'] * \
                         self.description['Fnum_y']['value'] * self.table['Wavelength'] / \
                         self.description['detector']['delta_pix']['value'] ** 2
        self.debug('window size : {}'.format(window_size_px))
        self._add_data_to_built('window_size_px', window_size_px)
        self.table['WindowSize'] = window_size_px

        self._add_data_to_built('table', self.table)

    def propagate_target(self, target):
        out = QTable()
        wl = target.star.sed.wl_grid
        qe, transmission, wave_window = self._get_efficiency(wl, target)
        if 'sky TR' in self.table.keys():
            out['foreground_transmission'] = self.table['sky TR']

        if self.payload['optics']['ForceChannelWlEdge']['value']:
            self.debug('force channel wl edge enabled')
            idx = np.logical_or(wl < self.description['wl_min']['value'].to(self.table['Wavelength'].unit),
                                wl > self.description['wl_max']['value'].to(self.table['Wavelength'].unit))
            transmission[idx] = wave_window[idx] = 0.0

        star_flux = np.trapz(wave_window *
                             target.star.sed.data,
                             x=target.star.sed.wl_grid
                             ).to(u.W / u.m ** 2)
        out['starFlux'] = [star_flux.value] * star_flux.unit
        self.debug('star flux : {}'.format(out['starFlux']))

        star_signal = self.payload['optics']['Atel']['value'] * np.trapz(qe *
                                                                         target.star.sed.data *
                                                                         transmission *
                                                                         target.star.sed.wl_grid.to(
                                                                             u.m) / const.c / const.h,
                                                                         x=target.star.sed.wl_grid).si * u.count
        out['starSignal'] = [star_signal.value] * star_signal.unit
        self.debug('star signal : {}'.format(out['starSignal']))

        try:
            star_signal_aperture = star_signal * self.description['aperture']['apertureCorrection']['value']
        except KeyError:
            self.debug('aperture correction not found')
            star_signal_aperture = star_signal

        out['star_signal_inAperture'] = [star_signal_aperture.value] * star_signal_aperture.unit
        self.debug('star signal in aperture : {}'.format(out['star_signal_inAperture']))

        star_signal_in_pixel = self.built_instr['PRF'].max() * star_signal
        out['star_MaxSignal_inPixel'] = [star_signal_in_pixel.value] * star_signal_in_pixel.unit
        self.debug('star signal in pixel MAX : {}'.format(out['star_signal_inAperture']))
        return out
