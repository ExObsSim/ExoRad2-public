import logging

import astropy.constants as const
import astropy.units as u
import numpy as np
from scipy.interpolate import interp1d

from exorad.models.signal import Signal
from exorad.utils.exolib import OmegaPix

logger = logging.getLogger('exorad.diffuse light')


def prepare(ch_table, ch_built_instr, description):
    logger.info('computing signal')
    wl_table = ch_table['Wavelength']
    logger.debug('wl table : {}'.format(wl_table))
    omega_pix = OmegaPix(description['Fnum_x']['value'].value,
                         description['Fnum_x']['value'].value)
    logger.debug('omega pix : {}'.format(omega_pix))
    A = (description['detector']['delta_pix']['value']
         * description['detector']['delta_pix']['value']).to(u.m ** 2)
    qe = Signal(ch_built_instr['qe_data']['wl_grid']['value'] * u.Unit(ch_built_instr['qe_data']['wl_grid']['unit']),
                ch_built_instr['qe_data']['data']['value'])
    logger.debug('wl qe : {}'.format(qe.wl_grid))

    transmission = Signal(ch_built_instr['transmission_data']['wl_grid']['value'] * \
                          u.Unit(ch_built_instr['transmission_data']['wl_grid']['unit']),
                          ch_built_instr['transmission_data']['data']['value'])

    total_signal = np.zeros(wl_table.size) * u.count / u.s
    total_max_signal = np.zeros(wl_table.size) * u.count / u.s
    return total_max_signal, total_signal, wl_table, A, qe, omega_pix, transmission




def convolve_with_slit(ch_description, ch_built_instr, A, ch_table, omega_pix, qe, radiance):
    slit_width = ch_built_instr['slit_width']
    wl_pix = ch_built_instr['wl_pix_center']
    dwl_pic = ch_built_instr['pixel_bandwidth']
    radiance.spectral_rebin(wl_pix)
    logger.debug('radiance : {}'.format(radiance.data))

    qe_func = interp1d(qe.wl_grid,
                       qe.data,
                       assume_sorted=False,
                       fill_value=0.0,
                       bounds_error=False)
    aomega = omega_pix * A * qe_func(wl_pix) * (wl_pix / const.c / const.h).to(1. / u.W / u.s) * u.count
    logger.debug('AOmega : {}'.format(aomega))
    radiance.data *= aomega
    logger.debug('sed : {}'.format(radiance.data))
    logger.debug('convolving with slit')
    slit_kernel = np.ones(int(slit_width / ch_description['detector']['delta_pix']['value'].to(u.um)))
    signal_tmp = (np.convolve(radiance.data * dwl_pic, slit_kernel, 'same')).to(u.count / u.s)
    logger.debug('signal_tmp: {}'.format(signal_tmp))
    idx = [np.logical_and(wl_pix > wlow, wl_pix <= whigh)
           for wlow, whigh in zip(ch_table['LeftBinEdge'], ch_table['RightBinEdge'])]
    signal = [signal_tmp[idx[k]].sum() for k in range(len(idx))]
    signal = [sig * w for sig, w in zip(signal, np.array(ch_built_instr['window_spatial_width']))]
    logger.debug('signal: {}'.format(signal))
    try:
        max_signal_per_pix = [signal_tmp[idx[k]].max() for k in range(len(idx))]
    except ValueError:
        logger.error('no max value in the array')
        raise
    return max_signal_per_pix, signal


def integrate_light(radiance, wl_qe, ch_built_instr):
    logger.debug('sed : {}'.format(radiance.data))
    signal_tmp = np.trapz(radiance.data, x=wl_qe).to(u.count / u.s)
    # signal_tmp = (np.trapz(radiance.data[~np.isnan(radiance.data)], x=wl_qe[~np.isnan(radiance.data)])).to(
    #     u.count / u.s)
    signal = signal_tmp * np.asarray(ch_built_instr['window_size_px'])
    max_signal_per_pix = signal_tmp * np.ones_like(ch_built_instr['window_size_px'])
    return max_signal_per_pix, signal
