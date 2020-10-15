import copy
from collections import OrderedDict

import astropy.constants as const
import astropy.units as u
import numpy as np
from astropy.table import QTable, hstack

from exorad.log import Logger
from exorad.models.optics.opticalElement import OpticalElement
from exorad.models.signal import Radiance
from exorad.utils.diffuse_light_propagation import integrate_light, prepare, convolve_with_slit
from exorad.utils.exolib import planck


def surface_radiance(wl, T, emissivity):
    """
        Spectral radiance from optics [power per unit surface, solid angle and bandwidth]

        Parameters
        __________
        wl : array_like
            wavelength array in unit of length
        T : scalar
            temperature of optical elements in [K]
        emissivity: array_like
            emissivity of optical surfaces

        Returns
        -------
        I : ndarray
            Spectral radiance. `I` will have the same shape of array `wl`

        """
    wl_ = wl.to(u.micron) if hasattr(wl, 'unit') else wl
    T_ = T.to(u.K) if hasattr(T, 'unit') else T
    try:
        I = planck(wl_, T_).to(u.W / (u.m ** 2 * u.micron * u.sr))
    except AttributeError:
        I = np.zeros_like(wl_) * u.W / u.m ** 2 / u.sr / u.micron
    radiance = Radiance(wl_grid=wl, data=emissivity * I)

    return radiance


class InstRadiance(Radiance):
    """
    Handler for instrument radiance

    Attributes
    ----------
    position: str
        tells the position of the optical element in the optical path. Default is 'path'
    """
    position = 'path'
    slit = None


class OpticalPath(Logger):
    """
    Handler for a instrument diffuse light

    Parameters
    -----------
    description: dict
        optic description
    wl: array
        quantity array for wavelength grid

    Attributes
    ----------
    optical_element_dict_: dict
        dictionary of OpticalElement classes
    radiance_dict: dict
        dictionary of InstrRadiance classes
    radiance_table: QTable
        table of optical elements radiance
    transmission_table: QTable
        table of optical elements transmissions
    signal_table: QTable
        table of optical elements signals
    max_signal_per_pixel: QTable
        table of optical elements max signal per pixel
    slit_width: Quantity
        slit width measurement, if a slit is in the optical path. Default is None

    Methods
    -------
    prepend_optical_elements(optical_element_dict):
        updates the class optical_element_dict putting the input dictionary at the top of the existing one.
    chain():
        it concatenates the optical elements, producing the radiance_table and radiance_dictionary
    build_transmission_table():
        produces the transmission table for the optical path
    compute_signal( ch_table, ch_built_instr):
        produce the telescope self emission signal for the channel and return the channel table updated

    Examples
    -------
        >>> telescope = OpticalPath(wl=self.wl_grid, description=options)
        >>> spec = OpticalPath(wl=wl_grid, description=options['channel']['Spec'])
        >>> spec.prepend_optical_elements(telescope.optical_element_dict)
        >>> spec.build_transmission_table()
        >>> spec = spec.chain()
    """

    def __init__(self, description, wl):
        super().__init__()
        self.description = description
        self.opt = description['optics']
        self.radiance_dict = OrderedDict()
        self.radiance_table = QTable()
        self.signal_table = QTable()
        self.max_signal_per_pixel = QTable()
        self.wl = self._wl_grid_refinement(wl)
        self.optical_element_dict = self._prepare_elements()
        self.transmission_table = QTable()
        self.slit_width = None

    def build_transmission_table(self):
        self.info('building transmission table')
        self.transmission_table['Wavelength'] = self.wl
        total_transmission = np.ones(self.wl.size)
        for el in self.optical_element_dict:
            self.transmission_table[el] = self.optical_element_dict[el].transmission
            total_transmission *= self.optical_element_dict[el].transmission
        self.transmission_table['total'] = copy.deepcopy(total_transmission)
        self.debug('transmission table : {}'.format(self.transmission_table))
        return self.transmission_table

    def _wl_grid_refinement(self, wl):
        """
        if the input wavelength list include only one element, it produce a wl_grid from the minimum wl
        investigated by the detector and the cut off
        """
        if len(wl) == 1:
            wl_min = self.description['detector']['wl_min']['value'].to(u.um)
            cut_off = self.description['detector']['cut_off']['value'].to(u.um)
            out_wl = np.logspace(np.log10(wl_min.value), np.log10(cut_off.value), 6000) * u.um
            self.debug('wl grid of a single value found. Instead we use : {}'.format(out_wl))
        else:
            out_wl = wl
            self.debug('selected wl grid : {}'.format(wl))
        return out_wl

    def prepend_optical_elements(self, optical_element_dict):
        self.optical_element_dict = OrderedDict(list(optical_element_dict.items()) +
                                                list(self.optical_element_dict.items()))

    def _prepare_elements(self):
        wl = self.wl
        out = OrderedDict()
        try:
            opt_el = self.opt['opticalElement']
        except KeyError:
            opt_el = {'value': 'noElement', 'type': {'value': 'surface'}}
        if isinstance(opt_el, OrderedDict):
            for el in opt_el:
                self.debug('preparing {}'.format(el))
                out[el] = OpticalElement(opt_el[el], wl)
        else:
            out[opt_el['value']] = OpticalElement(opt_el, wl)
        return out

    def chain(self):
        wl = self.wl
        self.radiance_table['Wavelength'] = wl
        opt_el = self.optical_element_dict
        opt_list = list(opt_el.keys())
        self.debug('optics list : {}'.format(opt_list))
        for i, k in enumerate(opt_list):
            el = opt_el[k]
            self.debug('propagating {}'.format(el.name))
            out_radiance = InstRadiance(wl_grid=wl, data=np.zeros(wl.size))
            out_radiance.position = el.position
            if el.temperature is not None:
                out_radiance.data = surface_radiance(el.wl, el.temperature, el.emissivity).data
            else:
                self.debug('skipped because of missing temperature')
                continue
            for other_el in opt_list[i + 1:]:
                self.debug('passing through {}'.format(other_el))
                out_radiance.data *= opt_el[other_el].transmission
                if opt_el[other_el].type == 'slit':
                    out_radiance.slit = True
                    self.slit_width = opt_el[other_el].description['width']['value']
            # try:
            #     if opt_el[opt_list[i + 1]].type == 'detector box':
            #         out_radiance.position = 'optics box'
            # except IndexError:
            #     out_radiance.position = 'detector'
            self.radiance_dict[el.name] = copy.deepcopy(out_radiance)
            self.radiance_table[el.name] = copy.deepcopy(out_radiance.data)
            self.debug('final radiance : {}'.format(out_radiance.data))
        return self.radiance_dict

    def compute_signal(self, ch_table, ch_built_instr):
        total_max_signal, total_signal, wl_table, A, qe, omega_pix, _ = prepare(ch_table, ch_built_instr,
                                                                                self.description)
        for item in self.radiance_dict:
            rad = copy.deepcopy(self.radiance_dict[item])
            qe.spectral_rebin(rad.wl_grid)
            self.debug('computing signal for {}'.format(item))
            if rad.slit and 'slit_width' in ch_built_instr:
                max_signal_per_pix, signal = convolve_with_slit(self.description, ch_built_instr,
                                                                A, ch_table, omega_pix, qe, rad,
                                                                )
            else:
                self.debug('no slit found')
                if rad.position == 'detector':
                    self.debug('this is the detector box')
                    rad.data *= A * np.pi * u.sr * qe.data * (qe.wl_grid / const.c / const.h).to(
                        1. / u.W / u.s) * u.count
                elif rad.position == 'optics box':
                    self.debug('this is the optics box')
                    rad.data *= A * (np.pi * u.sr - omega_pix) * qe.data \
                                * (qe.wl_grid / const.c / const.h).to(1. / u.W / u.s) * u.count
                else:
                    rad.data *= omega_pix * A * qe.data * (qe.wl_grid / const.c / const.h).to(1. / u.W / u.s) * u.count
                max_signal_per_pix, signal = integrate_light(rad, rad.wl_grid, ch_built_instr)

            self.signal_table['{} signal'.format(item)] = signal
            self.max_signal_per_pixel[item] = max_signal_per_pix

            self.debug('signal : {}'.format(self.signal_table['{} signal'.format(item)]))
            total_signal += self.signal_table['{} signal'.format(item)]
            total_max_signal += self.max_signal_per_pixel[item]
        out = QTable()
        out['instrument_signal'] = total_signal
        out['instrument_MaxSignal_inPixel'] = total_max_signal

        return hstack([ch_table, out['instrument_signal', 'instrument_MaxSignal_inPixel']])
