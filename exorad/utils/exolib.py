import logging
import os

import astropy.units as u
import mpmath
import numpy as np
from astropy.io import fits
from scipy import signal
from scipy.integrate import cumtrapz
from scipy.special import j1
from scipy.stats import binned_statistic

logger = logging.getLogger('exorad.exolib')


def rebin(x, xp, fp):
    ''' Resample a function fp(xp) over the new grid x, rebinning if necessary,
      otherwise interpolates
      Parameters
      ----------
      x	: 	array like
      New coordinates
      fp 	:	array like
      y-coordinates to be resampled
      xp 	:	array like
      x-coordinates at which fp are sampled

      Returns
      -------
      out	: 	array like
      new samples

    '''

    if (x.unit != xp.unit):
        logger.fatal('Units mismatch in rebin {:s}, {:s}'.format(x.unit, xp.unit))
        raise ValueError

    idx = np.where(np.logical_and(xp > 0.9 * x.min(), xp < 1.1 * x.max()))[0]
    xp = xp[idx]
    fp = fp[idx]

    if np.diff(xp).min() < np.diff(x).min():
        # Binning!
        bin_x = 0.5 * (x[1:] + x[:-1])
        x0 = x[0] - (bin_x[0] - x[0]) / 2.0
        x1 = x[-1] + (x[-1] - bin_x[-1]) / 2.0
        bin_x = np.insert(bin_x, [0], x0)
        bin_x = np.append(bin_x, x1)
        new_f = binned_statistic(xp, fp, bins=bin_x, statistic='mean')[0] * fp.unit

        idx = np.where(np.logical_and(xp >= x.min(), xp <= x.max()))[0]

    #    print np.trapz(fp[idx], x=xp[idx])
    #    print np.trapz(new_f, x=x)
    #    asd
    else:
        # Interpolate !
        new_f = np.interp(x, xp, fp, left=0.0, right=0.0)
        #         from scipy.interpolate import interp1d
        #         interpolator = interp1d(xp, fp, kind='cubic', fill_value=0.0, assume_sorted=False, bounds_error=False)
        #         new_f = interpolator(x)

        if not isinstance(new_f, u.Quantity):
            new_f *= fp.unit

    return x, new_f


def rebin_(x, xp, fp):
    ''' Resample a function fp(xp) over the new grid x, rebinning if necessary,
      otherwise interpolates
      Parameters
      ----------
      x	: 	array like
      New coordinates
      fp 	:	array like
      y-coordinates to be resampled
      xp 	:	array like
      x-coordinates at which fp are sampled

      Returns
      -------
      out	: 	array like
      new samples

    '''

    if (x.unit != xp.unit):
        logger.fatal('Units mismatch in rebin {:s}, {:s}'.format(x.unit, xp.unit))
        raise ValueError

    idx = np.where(np.logical_and(xp > 0.9 * x.min(), xp < 1.1 * x.max()))[0]
    xp = xp[idx]
    fp = fp[idx]

    if np.diff(xp).min() < np.diff(x).min():
        # Binning!
        c = cumtrapz(fp.value, x=xp.value) * fp.unit * xp.unit
        xpc = xp[1:]

        delta = np.gradient(x)
        new_c_1 = np.interp(x - 0.5 * delta, xpc, c,
                            left=0.0, right=0.0) * c.unit
        new_c_2 = np.interp(x + 0.5 * delta, xpc, c,
                            left=0.0, right=0.0) * c.unit
        new_f = (new_c_2 - new_c_1) / delta
    else:
        # Interpolate !
        new_f = np.interp(x, xp, fp, left=0.0, right=0.0) * fp.unit

    return x, new_f


def planck(wl, T):
    """ Planck function.

      Parameters
      __________
        wl : 			array
                  wavelength [micron]
        T : 			scalar
                  Temperature [K]
                  Spot temperature [K]
      Returns
      -------
        spectrum:			array
                  The Planck spectrum  [W m^-2 sr^-2 micron^-1]
    """

    a = np.float64(1.191042768e8) * u.um ** 5 * u.W / u.m ** 2 / u.sr / u.um
    b = np.float64(14387.7516) * 1 * u.um * u.K
    try:
        x = b / (wl * T)
        bb = a / wl ** 5 / (np.exp(x) - 1.0)
    except ArithmeticError:
        bb = np.zeros_like(wl)
    return bb


def binnedPSF(F_x, F_y, wl, delta_pix, filename=None, PSFtype='AIRY'):
    if filename:
        with fits.open(os.path.expanduser(filename)) as hdu:
            ima = hdu[0].data
            hdr = hdu[0].header
            # define a kernel representing the detector pixel response
            # and use fractional pixel
            k_x = delta_pix / (F_x * wl * hdr['CDELT2'])
            k_y = delta_pix / (F_y * wl * hdr['CDELT1'])
            xmin = -(hdr['CRPIX2'] - 1) * F_x * wl * hdr['CDELT2']
            xmax = (hdr['NAXIS2'] - (hdr['CRPIX2'] - 1)) * F_x * wl * hdr['CDELT2']
            ymin = -(hdr['CRPIX1'] - 1) * F_y * wl * hdr['CDELT1']
            ymax = (hdr['NAXIS1'] - (hdr['CRPIX1'] - 1)) * F_y * wl * hdr['CDELT1']
            extent = (xmin, xmax, ymin, ymax)
    elif PSFtype == 'AIRY':
        x = np.linspace(-3.0, 3.0, 256)
        xx, yy = np.meshgrid(x, x)
        r = np.pi * np.sqrt(xx ** 2 + yy ** 2) + 1.0e-10

        ima = (2.0 * j1(r) / r) ** 2
        ima *= 0.25 * np.pi * (x[1] - x[0]) ** 2
        # print ima.sum()
        k_x = delta_pix / (F_x * wl * (x[1] - x[0]))
        k_y = delta_pix / (F_y * wl * (x[1] - x[0]))
        # print k_y, k_x
        extent = (-(ima.shape[1] // 2) * F_x * wl * (x[1] - x[0]),
                  (ima.shape[1] // 2) * F_x * wl * (x[1] - x[0]),
                  -(ima.shape[0] // 2) * F_y * wl * (x[1] - x[0]),
                  (ima.shape[0] // 2) * F_y * wl * (x[1] - x[0]))

    fk_x, ik_x = np.modf(k_x)
    fk_y, ik_y = np.modf(k_y)

    kernel = np.ones((int(ik_y) + 2, int(ik_x) + 2)) * fk_x.unit
    kernel[:, 0] *= 0.5 * fk_x
    kernel[:, -1] *= 0.5 * fk_x
    kernel[0, :] *= 0.5 * fk_y
    kernel[-1, :] *= 0.5 * fk_y

    imac = signal.convolve2d(ima, kernel, mode='same')

    return imac, kernel, extent


def OmegaPix(Fnum_x, Fnum_y=None):
    ''' 
    Calculate the solid angle subtended by an elliptical aperture on-axis.
    Algorithm from "John T. Conway. Nuclear Instruments and Methods in 
    Physics Research Section A: Accelerators, Spectrometers, Detectors and
    Associated Equipment, 614(1):17 ? 27, 2010. 
    https://doi.org/10.1016/j.nima.2009.11.075
    Equation n. 56
    
    Parameters
    ----------
    Fnum_x : scalar
             Input F-number along dispersion direction
    Fnum_y : scalar
             Optional, input F-number along cross-dispersion direction
             
    Returns
    -------
     Omega : scalar
             The solid angle subtanded by an elliptical aperture in units u.sr
             
    '''

    if not Fnum_y: Fnum_y = Fnum_x

    if Fnum_x > Fnum_y:
        a = 1.0 / (2 * Fnum_y)
        b = 1.0 / (2 * Fnum_x)
    else:
        a = 1.0 / (2 * Fnum_x)
        b = 1.0 / (2 * Fnum_y)

    h = 1.0

    A = 4.0 * h * b / (a * np.sqrt(h ** 2 + a ** 2))
    k = np.sqrt((a ** 2 - b ** 2) / (h ** 2 + a ** 2))
    alpha = np.sqrt(1 - (b / a) ** 2)

    Omega = 2.0 * np.pi - A * mpmath.ellippi(alpha ** 2, k ** 2)

    return Omega * u.sr


if __name__ == "__main__":
    Omega = OmegaPix(5.0, 5.0)

    sigma = np.arctan(1.0 / 10)
    OmegaCheck = 2.0 * np.pi * (1 - np.cos(sigma))
    print((Omega, OmegaCheck))
