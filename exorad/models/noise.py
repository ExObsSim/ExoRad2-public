import logging
from collections import OrderedDict

import numpy as np
from astropy import units as u

from exorad.models.signal import Signal, CustomSignal

logger = logging.getLogger('exorad.noise')


def frame_time(target, channel, out):
    """
    Given the channel and channel descriptions, populates the output table with saturation and frame times

    Parameters
    -----------
    channel: dict
        channel description
    target: Target
        Target to investigate
    out: QTable
        output table


    Returns
    --------
    QTable
        output table populated
    """
    name = channel['value']
    max_signal_in_pix = target.table['MaxSignal_inPixel'][target.table['chName'] == name]
    out['saturation_time'] = channel['detector']['well_depth']['value'] / max_signal_in_pix
    logger.debug('saturation time : {}'.format(out['saturation_time']))
    if 'frame_time' in channel['detector'].keys():
        out['frameTime'] = channel['detector']['frame_time']['value'] * np.ones(out['saturation_time'].size)
    else:
        out['frameTime'] = channel['detector']['f_well_depth']['value'] * np.min(out['saturation_time']) \
                           * np.ones(out['saturation_time'].size)
    logger.debug('frame time : {}'.format(out['frameTime']))
    return out


def multiaccum(channel, t_frame):
    """
    Given the channel and time frame, returns the multiaccum estimation for read and shot gain

    Parameters
    -----------
    channel: dict
        channel description
    t_frame: float
        frame time

    Returns
    --------
    float
        read noise gain
    float
        shot noise gain
    """
    nRead = np.floor(t_frame * channel['detector']['freqNDR']['value'])

    if 'multiaccumM' in channel['detector']:
        m = channel['detector']['multiaccumM']['value']
        logger.debug('multiaccum activated: m = {}'.format(m))
        tf = 0. * u.s
    else:
        m = 1
        tf = 0. * u.s

    if nRead < 2:
        nRead = 2.0  # Force to CDS in nRead < 2

    read_gain = 12.0 * (nRead - 1.0) / (nRead ** 2 + nRead) / m
    shot_gain = 6.0 * (nRead ** 2 + 1.0) / (nRead ** 2 + nRead) / 5.0 * \
                (1 - 5. / 3. * (m ** 2 - 1) / m / (nRead ** 2 + 1) * tf / (nRead - 1) / t_frame)
    logger.debug('read noise gain: {}'.format(read_gain))
    logger.debug('shot noise gain: {}'.format(shot_gain))
    return read_gain, shot_gain


def photon_noise(table, channel, shot_gain, out):
    """
    Given the channel and channel descriptions, populates the output table with photon noises

    Parameters
    -----------
    channel: dict
        channel description
    target: Table
        Target table to investigate
    shot_gain: float
        multiaccum factor for photon noise
    out: QTable
        output table

    Returns
    --------
    QTable
        output table populated
    """
    name = channel['value']

    signals = [key for key in table.keys() if 'signal' in key]
    for key in signals:
        noise_key = '{}_noise'.format(key)
        out[noise_key] = np.sqrt(shot_gain * table[key][table['chName'] == name] * u.count / u.hr).to(
            u.count / u.s) * u.hr ** 0.5
        logger.debug('{} : {}'.format(noise_key, out[noise_key]))
    return out

def photon_noise_variance(table, out):
    '''
    """
    Given the target table return the sum of photon variances

    Parameters
    -----------
    target: Table
        Target table to investigate
    out: QTable
        output table

    Returns
    --------
    Array
        sum of photon variances
    """
    '''
    signals = [key for key in table.keys() if 'signal' in key]
    _photon_noise_variance = np.zeros(out['frameTime'].size) * (u.count / u.s) ** 2 * u.hr
    for key in signals:
        noise_key = '{}_noise'.format(key)
        _photon_noise_variance += out[noise_key] * out[noise_key]
    return _photon_noise_variance


def add_custom_noise(custom, wl, out):
    if 'data' in custom:
        col_name = [col for col in custom['data'].keys() if 'Wavelength' not in col]
        custom_noise = Signal(custom['data']['Wavelength'],
                              custom['data'][col_name])
        custom_noise.spectral_rebin(wl)
        out['{}_noise'.format(col_name)] = custom_noise.data
        logger.debug('{} added as custom noise :{}'.format(col_name, custom_noise.data))
        out['total_noise'] = np.sqrt(out['total_noise'] * out['total_noise'] +
                                     custom_noise.data * custom_noise.data)

    if isinstance(custom, OrderedDict):
        for contrib in custom:
            custom_noise = custom[contrib]['value'] * 1e-6 * np.ones(wl.size) * u.hr ** 0.5
            out['{}_noise'.format(custom[contrib]['name']['value'])] = custom_noise
            logger.debug('{} added as custom noise :{}'.format(custom[contrib]['name']['value'],
                                                               custom_noise))
            out['total_noise'] = np.sqrt(out['total_noise'] * out['total_noise'] +
                                         custom_noise * custom_noise)
    else:
        custom_noise = custom['value'] * 1e-6 * np.ones(wl.size) * u.hr ** 0.5
        out['{}_noise'.format(custom['name']['value'])] = custom_noise
        logger.debug('{} added as custom noise :{}'.format(custom['name']['value'],
                                                           custom_noise))
        out['total_noise'] = np.sqrt(out['total_noise'] * out['total_noise'] +
                                     custom_noise * custom_noise)
    return out

class Noise(CustomSignal):
    """
    It's a Signal class with data having units of [hr^1/2]
    """

    def __init__(self, wl_grid, data, time_grid=[0] * u.hr):
        super().__init__(wl_grid, data, u.hr ** 0.5, time_grid)
