import copy
from abc import abstractmethod

import astropy.constants as const
import astropy.units as u
import numpy as np
from astropy.table import QTable
from scipy.interpolate import interp1d

from exorad.log.logger import Logger
from exorad.models.optics.opticalPath import OpticalPath
from exorad.models.signal import Signal
from exorad.utils.diffuse_light_propagation import prepare, convolve_with_slit, integrate_light
from exorad.models.utils import get_wl_col_name


class Instrument(Logger):
    """
    Abstract Instrument class. Contains the basic function that every instrument needs.

    Parameters
    -----------
    name: str
        instrument name
    description: dict
        instrument description dictionary
    payload: dict
        main payload. Default is None

    Attributes
    ----------
    name: str
        instrument name
    description: dict
        instrument description dictionary
    payload: dict
        main payload. Default is None
    table: QTable
        contain the output grid for the instrument
    built_instr: dict
        contains the instrument parameters needed to propagate the signal

    Methods
    --------
    built()
        it prepare the instrument to propagate the signal
    build_optical_path()
        it builds the instrument optical path
    propagate_target()
        propagates the target light trough the instrument
    propagate_diffuse_foreground()
        propagates the foreground light trough the instrument, starting for zodiacal light
    load(dir)
        it loads the instrument parameters already processed from a file
    write(dir)
        it writes the instrument parameters already processed from a file

    Raises
    -------
    ValueError:
        if you try to build a loaded payload.
    """

    def __init__(self, name, description, payload=None):
        self.set_log_name()
        self.name = name
        self.description = description
        self.payload = payload
        self.table = QTable()
        self.built_instr = dict()
        self.debug('{} initialized'.format(self.name))
        self.loaded = False
        self.opticalPath = None

    def load(self, table, built_instr):
        self.table = table
        self.built_instr = built_instr
        self.loaded = True
        self.info('loaded')

    def write(self, output):
        inst_out = output.create_group(self.name)
        inst_out.write_table(self.name, self.table, )
        inst_out.store_dictionary(self.description, group_name='description')
        inst_out.store_dictionary(self.built_instr, group_name='built_instr')
        self.info('instrument saved')
        return output

    def build(self):
        """
        check if it can build the instrument and populate the output table and dict.
        Then run the builder
        """

        if self.loaded:
            self.error('You cannot build a loaded instrument')
            # to build the instrument we need to be careful about the elements order, especially for optic emission!
            # you cannot load the description and run it again because it's not an ordered dictionary anymore
            raise ValueError('You cannot build a loaded instrument')
        else:
            self.builder()
            self.build_optical_path()

    def build_optical_path(self):

        self.info('building optical path')
        # what wl do I wanna use here?
        wl_grid = np.logspace(np.log10(self.description['detector']['wl_min']['value'].value),
                              np.log10(self.description['detector']['cut_off']['value'].value), 6000) * u.um

        common_optical_path = OpticalPath(wl=wl_grid, description=self.payload)
        channel_optical_path = OpticalPath(wl=wl_grid, description=self.description)
        channel_optical_path.prepend_optical_elements(common_optical_path.optical_element_dict)
        self.opticalPath = channel_optical_path

        transmission_table = self.opticalPath.build_transmission_table()
        optical_path_dict = {'transmission_table': transmission_table}
        # We need to rebin TR to the final one
        self.table['TR'], transmission_data = self._get_transmission(wl_grid, transmission_table['total'])
        self._add_data_to_built('transmission_data', transmission_data.to_dict())

        self.opticalPath.chain()
        if self.opticalPath.slit_width:
            self._add_data_to_built('slit_width', self.opticalPath.slit_width.to(u.um))

        self.table = self.opticalPath.compute_signal(self.table, self.built_instr)
        optical_path_dict['max_signal_per_pixel'] = self.opticalPath.max_signal_per_pixel
        optical_path_dict['signal_table'] = self.opticalPath.signal_table
        optical_path_dict['radiance_table'] = self.opticalPath.radiance_table
        self._add_data_to_built('optical_path', optical_path_dict)

    @abstractmethod
    def builder(self):
        """
        build the instrument and populate the output table and dict
        """
        pass

    @abstractmethod
    def propagate_target(self, target):
        """
        propagate point source
        """
        pass

    def propagate_diffuse_foreground(self, target):
        """
        propagate diffuse foreground sources, starting from zodiacal background
        """
        import copy
        self.debug('diffuse bkg propagation')
        out = QTable()
        total_max_signal, total_signal, wl_table, A, qe, omega_pix, transmission = prepare(self.table,
                                                                                           self.built_instr,
                                                                                           self.description)
        foregrounds = list(target.foreground.keys())
        foregrounds = reversed(foregrounds)
        for i, frg in enumerate(foregrounds):
            self.debug('propagating {}'.format(frg))
            radiance = copy.deepcopy(target.foreground[frg])
            self.debug('{} radiance . {}'.format(frg, radiance.data))

            if hasattr(frg, 'transmission'):
                frg.transmission.spectral_rebin(transmission.wl_grid)
                transmission.data *= frg.transmission.data
                self.debug('added {} transmission'.format(frg))

            transmission.spectral_rebin(radiance.wl_grid)
            radiance.data *= transmission.data

            # for other_el in foregrounds[i+1:]:
            #     if hasattr(target.foreground[other_el], 'transmission'):
            #         self.debug('passing through {}'.format(other_el))
            #         radiance.data *= target.foreground[other_el].transmission
            if 'slit_width' in self.built_instr:
                max_signal_per_pix, signal = convolve_with_slit(self.description, self.built_instr,
                                                                A, self.table, omega_pix, qe, radiance)
            else:
                qe.spectral_rebin(radiance.wl_grid)
                radiance.data *= omega_pix * A * qe.data * (qe.wl_grid / const.c / const.h).to(1. / u.W / u.s) * u.count
                # try:
                #     signal = np.trapz(radiance.data * self._window_function(radiance), x=radiance.wl_grid).to(u.ct / u.s)
                #     signal *= self.built_instr['window_spatial_width']
                # except KeyError:
                max_signal_per_pix, signal = integrate_light(radiance, radiance.wl_grid, self.built_instr)
            total_signal = copy.deepcopy(signal)
            self.debug('sed : {}'.format(total_signal))
            total_max_signal = copy.deepcopy(max_signal_per_pix)

            out['{}_signal'.format(frg)] = total_signal
            out['{}_MaxSignal_inPixel'.format(frg)] = total_max_signal
        return out

    def _bin_signal(self, wl, signal, leftbin, rightbin):

        bsig = [np.mean(signal[np.logical_and(wl >= wlow, wl < whigh)])
                for wlow, whigh in zip(leftbin, rightbin)]
        return u.Quantity(bsig)

    def _get_transmission(self, wl_grid, tr_data=None):

        tr_func = interp1d(wl_grid,
                           tr_data,
                           assume_sorted=False,
                           fill_value=0.0,
                           bounds_error=False)

        transmission_data = Signal(wl_grid, tr_data)
        # self.debug('transmission channel data : {} {}'.format(transmission_data.wl_grid, transmission_data.data))

        transmission = self._bin_signal(self.table['Wavelength'], tr_func(self.table['Wavelength']),
                                        self.table['LeftBinEdge'], self.table['RightBinEdge'])

        if self.payload['optics']['ForceChannelWlEdge']['value']:
            self.debug('force channel wl edge enabled')
            idx = np.logical_or(self.table['Wavelength']
                                < self.description['wl_min']['value'].to(self.table['Wavelength'].unit),
                                self.table['Wavelength']
                                > self.description['wl_max']['value'].to(self.table['Wavelength'].unit))
            transmission[idx] = 0.0
            idx = np.logical_or(transmission_data.wl_grid
                                < self.description['wl_min']['value'].to(self.table['Wavelength'].unit),
                                transmission_data.wl_grid
                                > self.description['wl_max']['value'].to(self.table['Wavelength'].unit))
            transmission_data.data[idx] = 0.0

        self.debug('transmission in channel : {}'.format(transmission))
        return transmission, transmission_data

    def _get_qe(self):
        if 'datafile' in self.description['detector']['qe']:
            self.debug('QE data file found')
            wl_colname = get_wl_col_name(self.description['detector']['qe']['data'])
            qe_data = Signal(self.description['detector']['qe']['data'][wl_colname], \
                             self.description['detector']['qe']['data'][self.name])
        else:
            wl_grid = np.logspace(np.log10(self.description['detector']['wl_min']['value'].to(u.um).value),
                                  np.log10(self.description['detector']['cut_off']['value'].to(u.um).value),
                                  6000) * u.um
            qe_data = Signal(wl_grid,
                             self.description['detector']['qe']['value'] * np.ones(wl_grid.size))

        qe_func = interp1d(qe_data.wl_grid,
                           qe_data.data,
                           assume_sorted=False,
                           fill_value=0.0,
                           bounds_error=False)
        qe = self._bin_signal(self.table['Wavelength'], qe_func(self.table['Wavelength']),
                              self.table['LeftBinEdge'], self.table['RightBinEdge'])
        self.debug('qe in channel : {}'.format(qe))
        return qe, qe_data

    def _get_efficiency(self, wl, target):
        # qe = interp1d(wl, self.built_instr['qe_data']['wl_grid'],
        #               self.built_instr['qe_data']['data'], left=0.0, right=0.0)
        # transmission = interp1d(wl, self.built_instr['transmission_data']['wl_grid'],
        #                         self.built_instr['transmission_data']['data'], left=0.0, right=0.0)
        # wave_window = np.ones(self.table['Wavelength'])
        qe = Signal(
            self.built_instr['qe_data']['wl_grid']['value'] * u.Unit(self.built_instr['qe_data']['wl_grid']['unit']),
            self.built_instr['qe_data']['data']['value'])
        qe.spectral_rebin(wl)

        transmission = Signal(self.built_instr['transmission_data']['wl_grid']['value']
                              * u.Unit(self.built_instr['transmission_data']['wl_grid']['unit']),
                              self.built_instr['transmission_data']['data']['value'])
        transmission.spectral_rebin(wl)

        if hasattr(target, 'skyTransmission'):
            target_transmission = copy.deepcopy(target.skyTransmission)
            self.table['sky TR'], _ = self._get_transmission(target_transmission.wl_grid, target_transmission.data)
            target_transmission.spectral_rebin(wl)
            transmission.data *= target_transmission.data

        wave_window = np.ones(wl.size)
        return qe.data, transmission.data, wave_window

    def _add_data_to_built(self, name, data):
        self.built_instr[name] = data

    def _window_function(self, signal):
        window_function = []
        for wld, wlu in zip(self.table['LeftBinEdge'], self.table['RightBinEdge']):
            mask = np.logical_and(signal.wl_grid >= wld,
                                  signal.wl_grid < wlu).astype(float)
            window_function.append(mask)
        window_function = np.array(window_function)
        self.debug('window function: {}'.format(window_function))
        return window_function
