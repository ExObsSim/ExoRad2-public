import logging
from collections import OrderedDict

import numpy as np
from astropy import units as u

from exorad.models.signal import CustomSignal, Signal

logger = logging.getLogger("exorad.noise")


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
    name = channel["value"]
    max_signal_in_pix = target.table["MaxSignal_inPixel"][
        target.table["chName"] == name
    ]
    out["saturation_time"] = (
        channel["detector"]["well_depth"]["value"] / max_signal_in_pix
    )
    logger.debug("saturation time : {}".format(out["saturation_time"]))
    if "frame_time" in channel["detector"].keys():
        out["frameTime"] = channel["detector"]["frame_time"]["value"] * np.ones(
            out["saturation_time"].size
        )
    else:
        out["frameTime"] = (
            channel["detector"]["f_well_depth"]["value"]
            * np.min(out["saturation_time"])
            * np.ones(out["saturation_time"].size)
        )
    logger.debug("frame time : {}".format(out["frameTime"]))
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
    nRead = np.floor(t_frame * channel["detector"]["freqNDR"]["value"])

    if "multiaccumM" in channel["detector"]:
        m = channel["detector"]["multiaccumM"]["value"]
        logger.debug(f"multiaccum activated: m = {m}")
        tf = 0.0 * u.s
    else:
        m = 1
        tf = 0.0 * u.s

    if nRead < 2:
        nRead = 2.0  # Force to CDS in nRead < 2

    read_gain = 12.0 * (nRead - 1.0) / (nRead**2 + nRead) / m
    shot_gain = (
        6.0
        * (nRead**2 + 1.0)
        / (nRead**2 + nRead)
        / 5.0
        * (1 - 5.0 / 3.0 * (m**2 - 1) / m / (nRead**2 + 1) * tf / (nRead - 1) / t_frame)
    )
    logger.debug(f"read noise gain: {read_gain}")
    logger.debug(f"shot noise gain: {shot_gain}")
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
    name = channel["value"]

    signals = [key for key in table.keys() if "signal" in key]
    for key in signals:
        noise_key = f"{key}_noise"
        out[noise_key] = (
            np.sqrt(
                shot_gain * table[key][table["chName"] == name] * u.count / u.hr
            ).to(u.count / u.s)
            * u.hr**0.5
        )
        logger.debug(f"{noise_key} : {out[noise_key]}")
    return out


def photon_noise_variance(table, out):
    """
    Calculate the sum of photon noise variances from all signal sources.

    Given the target table, this function computes the sum of photon
    variances from all signal contributions.

    Parameters
    ----------
    table : QTable
        Target table containing signal columns to investigate.
    out : QTable
        Output table containing the computed noise columns.

    Returns
    -------
    variance : Quantity
        Sum of photon variances with units of (count/s)^2 * hr.

    Notes
    -----
    The function identifies all columns in the table with 'signal' in their
    name and computes the variance from their corresponding noise columns.
    """
    signals = [key for key in table.keys() if "signal" in key]
    _photon_noise_variance = (
        np.zeros(out["frameTime"].size) * (u.count / u.s) ** 2 * u.hr
    )
    for key in signals:
        noise_key = f"{key}_noise"
        _photon_noise_variance += out[noise_key] * out[noise_key]
    return _photon_noise_variance


def add_custom_noise(custom, wl, out):
    """
    Add custom noise contributions to the output table.

    This function adds user-defined noise sources to the total noise budget.
    Custom noise can be provided either as wavelength-dependent data or as
    constant values.

    Parameters
    ----------
    custom : dict or OrderedDict
        Custom noise specification. Can contain either:
        - 'data' key with wavelength-dependent noise values
        - Multiple entries with constant noise values
    wl : Quantity
        Wavelength grid for rebinning the custom noise data.
    out : QTable
        Output table where custom noise will be added.

    Returns
    -------
    None
        The function modifies the `out` table in place, adding custom noise
        columns and updating the total noise.

    Notes
    -----
    Custom noise values are added in quadrature to the existing total noise.
    Constant noise values should be provided in units of ppm (parts per million)
    and are converted internally.

    Examples
    --------
    >>> custom_noise = {
    ...     "data": {"Wavelength": wl_array, "jitter": noise_array}
    ... }
    >>> add_custom_noise(custom_noise, wl_grid, output_table)
    """

    def _combine(name, contribution):
        out[f"{name}_noise"] = contribution
        logger.debug(f"{name} added as custom noise : {contribution}")
        out["total_noise"] = np.sqrt(
            out["total_noise"] * out["total_noise"] + contribution * contribution
        )

    if "data" in custom:
        col_name = next(col for col in custom["data"].keys() if "Wavelength" not in col)
        custom_noise = Signal(custom["data"]["Wavelength"], custom["data"][col_name])
        custom_noise.spectral_rebin(wl)
        _combine(col_name, custom_noise.data.value * u.hr**0.5)
    elif isinstance(custom, OrderedDict):
        for contrib in custom:
            contribution = (
                custom[contrib]["value"] * 1e-6 * np.ones(wl.size) * u.hr**0.5
            )
            _combine(custom[contrib]["name"]["value"], contribution)
    else:
        contribution = custom["value"] * 1e-6 * np.ones(wl.size) * u.hr**0.5
        _combine(custom["name"]["value"], contribution)
    return out


class Noise(CustomSignal):
    """
    It's a Signal class with data having units of [hr^1/2]
    """

    def __init__(self, wl_grid, data, time_grid=[0] * u.hr):
        super().__init__(wl_grid, data, u.hr**0.5, time_grid)
