import astropy.constants as const
import astropy.units as u
import numpy as np
from astropy.table import QTable
from scipy.interpolate import interp1d

from exorad.models.signal import CustomSignal, Signal, CountsPerSeconds
from exorad.utils.exolib import binnedPSF
from .instrument import Instrument


class Spectrometer(Instrument):
    """
    Spectrometer instrument class.
    """

    def _wavelength_table(self):
        # check if R is defined
        if 'targetR' not in self.description:
            self.warning('Channel targetR missing: native R is assumed')
            self.description['targetR'] = {'value':'native'}

        # define the wavelength grid
        if 'value' in self.description['targetR'].keys():
            self.debug('spectral resolution set to {}'.format(self.description['targetR']['value']))
            # native R
            if self.description['targetR']['value'] == 'native':
                wl_bin_c = self.built_instr['wl_pix_center']
                wl_bin_width = self.built_instr['pixel_bandwidth']
                wl_bin = wl_bin_c - 0.5 * wl_bin_width
                wl_bin = np.append(wl_bin, wl_bin_c[-1] + 0.5 * wl_bin_width[-1])
            # fixed R
            else:
                number_of_spectral_bins = np.ceil(
                    np.log(self.description['wl_max']['value']
                           / self.description['wl_min']['value'])
                    / np.log(1.0 + 1.0 / self.description['targetR']['value'])) + 1
                wl_bin = self.description['wl_min']['value'] \
                         * (1.0 + 1.0 / self.description['targetR']['value']) ** np.arange(number_of_spectral_bins)
                wl_bin_c = 0.5 * (wl_bin[0:-1] + wl_bin[1:])
                wl_bin_width = wl_bin[1:] - wl_bin[0:-1]
        # wavelength dependent R
        elif 'data' in self.description['targetR'].keys():
            raise NotImplementedError
        else:
            self.error('Channel targetR format unsupported.')
            raise KeyError('Channel targetR format unsupported.')

        # preparing the table
        self.table['chName'] = [self.name] * wl_bin_c.size
        self.table['Wavelength'] = wl_bin_c
        self.table['Bandwidth'] = wl_bin_width
        self.table['LeftBinEdge'] = self.table['Wavelength'] - 0.5 * self.table['Bandwidth']
        self.table['RightBinEdge'] = self.table['Wavelength'] + 0.5 * self.table['Bandwidth']
        self.debug('wavelength table: \n{}'.format(self.table))
        return wl_bin

    def builder(self):
        self.info('building {}'.format(self.name))

        # building pixel grid
        try:
            wl_solution_data = CustomSignal(
                self.description['wlSolution']['data']['Wavelength'],
                self.description['wlSolution']['data']['x'],
                self.description['wlSolution']['data']['x'].unit)
        except KeyError:
            self.error('Wavelength solution not indicated')
            raise

        self._add_data_to_built('wl_solution_data', wl_solution_data.to_dict())
        wl_sol_func = interp1d(wl_solution_data.data, wl_solution_data.wl_grid,
                               assume_sorted=False, fill_value='extrapolate', bounds_error=False)

        wl_sol_func_reverse = interp1d(wl_solution_data.wl_grid, wl_solution_data.data,
                                       assume_sorted=False, fill_value='extrapolate', bounds_error=False)

        first_pixel = wl_sol_func_reverse(self.description['wl_min']['value']) * wl_solution_data.data.unit
        last_pixel = wl_sol_func_reverse(self.description['wl_max']['value']) * wl_solution_data.data.unit
        self.debug('first pixel: {}, last pixel: {}'.format(first_pixel, last_pixel))
        if last_pixel < first_pixel: last_pixel, first_pixel = first_pixel, last_pixel

        delta = self.description['detector']['delta_pix']['value'].to(first_pixel.unit)

        # coordinates of detector  pixel centres
        coord_pix_center = np.arange(first_pixel.value, last_pixel.value, delta.value) * delta.unit
        coord_pix_center = np.flip(coord_pix_center)
        self.debug('pix_center: {}'.format(coord_pix_center))
        self._add_data_to_built('pix_center', coord_pix_center)
        # wavelength sampled by the pixels
        pixel_wavelength = wl_sol_func(coord_pix_center) * wl_solution_data.wl_grid.unit
        self.debug('wl_pix_center: {}'.format(pixel_wavelength))
        self._add_data_to_built('wl_pix_center', pixel_wavelength)
        pixel_bandwidth = np.abs(wl_sol_func(coord_pix_center - 0.5 * delta) -
                                 wl_sol_func(coord_pix_center + 0.5 * delta)) * delta.unit
        self._add_data_to_built('pixel_bandwidth', pixel_bandwidth)

        # initializing channel table
        wl_bin = self._wavelength_table()
        self._add_data_to_built('wl_bin', wl_bin)
        self.table['QE'], qe_data = self._get_qe()
        self._add_data_to_built('qe_data', qe_data.to_dict())

        # window sizes
        pixel_window_edge = wl_sol_func_reverse(wl_bin) * wl_solution_data.data.unit
        window_spectral_width = (np.abs(pixel_window_edge[1:] - pixel_window_edge[0:-1]) / delta).to('')

        if 'EncESolution' in self.description.keys():
            self.debug('Encircle energy solution found')
            EncE_sol = interp1d(self.description['EncESolution']['data']['Wavelength'],
                                self.description['EncESolution']['data']['EE'],
                                assume_sorted=False)
            radius = EncE_sol(self.table['Wavelength'])
        else:
            radius = 1.22
        self.debug('radius : {}'.format(radius))

        window_spatial_width = (2.0 * radius * self.description['Fnum_y']['value'] *
                                self.table['Wavelength'] / delta).to('')
        if 'window_spatial_scale' in list(self.description.keys()):
            window_spatial_width *= self.description['window_spatial_scale']['value']
            self.debug('window spatial width scaled by {}'.format(self.description['window_spatial_scale']['value']))

        window_size_px = window_spectral_width * window_spatial_width
        self._add_data_to_built('window_spectral_width', window_spectral_width)
        self._add_data_to_built('window_spatial_width', window_spatial_width)
        self._add_data_to_built('window_size_px', window_size_px)
        self.table['WindowSize'] = window_size_px
        self.debug('window size : {}'.format(window_size_px))

        # PSF gain
        _gain_prf = np.empty(10, dtype=float)
        wl_prf = np.linspace(pixel_wavelength.min(), pixel_wavelength.max(),
                             _gain_prf.size)
        for k, wl in enumerate(wl_prf):
            prf, pixel_prf, extent = binnedPSF(self.description['Fnum_x']['value'],
                                               self.description['Fnum_y']['value'],
                                               wl,
                                               delta)
            _gain_prf[k] = np.max(prf.sum(axis=0) / pixel_prf.sum(axis=0).max())

            if 'WFErms' in self.description.keys():
                self.debug('WFE found')
                Strehl = np.exp(- (2 * np.pi * self.description['WFErms']['value'] / wl) ** 2)
            else:
                Strehl = 1.0
            _gain_prf[k] *= Strehl
        self.debug(_gain_prf)
        gain_prf_data = Signal(wl_prf, _gain_prf)
        self._add_data_to_built('gain_prf_data', gain_prf_data.to_dict())

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

        signal_density = CustomSignal(wl_grid=target.star.sed.wl_grid,
                                      data=(self.payload['optics']['Atel']['value']
                                            * transmission
                                            * qe
                                            * target.star.sed.data
                                            * target.star.sed.wl_grid.to(u.m) /
                                            const.h / const.c).to(1 / u.um / u.s) * u.count,
                                      data_unit=u.count / u.um / u.s)
        self.debug('star signal density: {}'.format(signal_density.data))

        # max signal in pixel
        gain_prf_data = self.built_instr['gain_prf_data']
        gain_prf = interp1d(gain_prf_data['wl_grid']['value'], gain_prf_data['data']['value'],
                            kind='cubic', assume_sorted=False)

        # signal in spectral bin
        window_function = self._window_function(target.star.sed)
        self.debug('window function: {}'.format(window_function))

        flux_density = wave_window * target.star.sed.data
        self.debug('star flux density: {}'.format(flux_density))

        star_flux = np.trapz(flux_density * window_function,
                             x=target.star.sed.wl_grid.to(u.um)).to(u.W / u.m ** 2)
        self.debug('star flux : {}'.format(star_flux))
        out['starFlux'] = star_flux

        star_signal = np.trapz(signal_density.data * window_function,
                               x=target.star.sed.wl_grid).to(u.count / u.s)
        self.debug('star signal : {}'.format(star_signal))
        out['starSignal'] = star_signal
        out['star_signal_inAperture'] = star_signal

        star_signal_inPixel_density = signal_density
        star_signal_inPixel_density.spectral_rebin(self.built_instr['wl_pix_center'])

        star_signal_inPixel = CountsPerSeconds(star_signal_inPixel_density.wl_grid,
                                               (star_signal_inPixel_density.data * self.built_instr['pixel_bandwidth']
                                                * gain_prf(star_signal_inPixel_density.wl_grid)).to(u.count / u.s))
        starSignal_inPixel_max = np.empty(self.table['Wavelength'].size, dtype=float) * star_signal_inPixel.data.unit
        for k, (wld, wlu) in enumerate(zip(self.table['LeftBinEdge'], self.table['RightBinEdge'])):
            idx = np.where(np.logical_and(star_signal_inPixel.wl_grid > wld,
                                          star_signal_inPixel.wl_grid < wlu))[0]
            starSignal_inPixel_max[k] = np.max(star_signal_inPixel.data[idx])
        out['star_MaxSignal_inPixel'] = starSignal_inPixel_max
        self.debug('star signal in pixel MAX : {}'.format(starSignal_inPixel_max))
        return out
