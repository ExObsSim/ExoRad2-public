import glob
import logging
import os

import astropy.units as u
import mpmath
import numpy as np
import photutils
from astropy.io import fits
from scipy import signal
from scipy.integrate import cumtrapz
from scipy.interpolate import interp1d
from scipy.special import j1
from scipy.stats import binned_statistic

logger = logging.getLogger("exorad.exolib")


def rebin(x, xp, fp):
    """Resample a function fp(xp) over the new grid x, rebinning if necessary,
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

    """

    if x.unit != xp.unit:
        logger.fatal(
            "Units mismatch in rebin {:s}, {:s}".format(x.unit, xp.unit)
        )
        raise ValueError

    idx = np.where(np.logical_and(xp > 0.9 * x.min(), xp < 1.1 * x.max()))[0]
    xp = xp[idx]
    fp = fp[idx]

    if not hasattr(fp, "unit"):
        logger.debug("No units found for fp. Forced to None")
        fp *= u.Unit()
    funits = fp.unit

    # remove NaNs
    id = np.where(np.isnan(xp))[0]
    if id.size > 0:
        logger.debug("Nans found in input x array: removing it")
        xp = np.delete(xp, id)
        fp = np.delete(fp, id)

    id = np.where(np.isnan(x))[0]
    if id.size > 0:
        logger.debug("Nans found in new x array: removing it")
        x = np.delete(x, id)

    # remove duplicates
    while np.diff(xp).min() == 0:
        logger.debug("duplicate found in input x array: removing it")
        id = np.argmin(np.diff(xp))
        xp = np.delete(xp, id)
        fp = np.delete(fp, id)

    while np.diff(x).min() == 0:
        logger.debug("duplicate found in new x array: removing it")
        id = np.argmin(np.diff(x))
        x = np.delete(x, id)

    if np.diff(xp).max() < np.diff(x).min():
        # Binning!
        logger.debug("binning")
        bin_x = 0.5 * (x[1:] + x[:-1])
        x0 = x[0] - (bin_x[0] - x[0]) / 2.0
        x1 = x[-1] + (x[-1] - bin_x[-1]) / 2.0
        bin_x = np.insert(bin_x, [0], x0)
        bin_x = np.append(bin_x, x1)
        new_f = (
            binned_statistic(xp, fp, bins=bin_x, statistic="mean")[0] * funits
        )

    #    idx = np.where(np.logical_and(xp >= x.min(), xp <= x.max()))[0]
    #    print np.trapz(fp[idx], x=xp[idx])
    #    print np.trapz(new_f, x=x)
    #    asd
    else:
        logger.debug("interpolating")

        # Interpolate !
        # new_f = np.interp(x, xp, fp, left=0.0, right=0.0)
        #         from scipy.interpolate import interp1d
        #         interpolator = interp1d(xp, fp, kind='cubic', fill_value=0.0, assume_sorted=False, bounds_error=False)
        #         new_f = interpolator(x)
        func = interp1d(
            xp,
            fp,
            fill_value=0.0,
            assume_sorted=False,
            bounds_error=False,
            kind="linear",
        )
        new_f = func(x)

        if not hasattr(new_f, "unit"):
            logger.debug("output units force to inputs fp")
            new_f *= funits

    return x, new_f


def rebin_(x, xp, fp):
    """Resample a function fp(xp) over the new grid x, rebinning if necessary,
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

    """

    if x.unit != xp.unit:
        logger.fatal(
            "Units mismatch in rebin {:s}, {:s}".format(x.unit, xp.unit)
        )
        raise ValueError

    idx = np.where(np.logical_and(xp > 0.9 * x.min(), xp < 1.1 * x.max()))[0]
    xp = xp[idx]
    fp = fp[idx]

    if np.diff(xp).max() < np.diff(x).min():
        # Binning!
        c = cumtrapz(fp.value, x=xp.value) * fp.unit * xp.unit
        xpc = xp[1:]

        delta = np.gradient(x)
        new_c_1 = (
            np.interp(x - 0.5 * delta, xpc, c, left=0.0, right=0.0) * c.unit
        )
        new_c_2 = (
            np.interp(x + 0.5 * delta, xpc, c, left=0.0, right=0.0) * c.unit
        )
        new_f = (new_c_2 - new_c_1) / delta
    else:
        # Interpolate !
        new_f = np.interp(x, xp, fp, left=0.0, right=0.0) * fp.unit

    return x, new_f


def planck(wl, T):
    """Planck function.

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
                The Planck spectrum  [W m^-2 sr^-1 micron^-1]
    """

    a = np.float64(1.191042768e8) * u.um**5 * u.W / u.m**2 / u.sr / u.um
    b = np.float64(14387.7516) * 1 * u.um * u.K
    try:
        x = b / (wl * T)
        bb = a / wl**5 / (np.exp(x) - 1.0)
    except ArithmeticError:
        bb = np.zeros_like(wl)
    return bb


def load_standard_psf(F_x, F_y, wl, delta_pix, hdr):
    k_x = delta_pix / (F_x * wl * hdr["CDELT2"])
    k_y = delta_pix / (F_y * wl * hdr["CDELT1"])
    xmin = -(hdr["CRPIX2"] - 1) * F_x * wl * hdr["CDELT2"]
    xmax = (hdr["NAXIS2"] - (hdr["CRPIX2"] - 1)) * F_x * wl * hdr["CDELT2"]
    ymin = -(hdr["CRPIX1"] - 1) * F_y * wl * hdr["CDELT1"]
    ymax = (hdr["NAXIS1"] - (hdr["CRPIX1"] - 1)) * F_y * wl * hdr["CDELT1"]
    extent = (xmin, xmax, ymin, ymax)
    return k_x, k_y, extent


def binnedPSF(
    F_x,
    F_y,
    wl,
    delta_pix,
    filename=None,
    format=None,
    PSFtype="AIRY",
    plot=False,
):
    if filename and os.path.exists(filename):
        if filename[-5:] == ".fits":
            with fits.open(os.path.expanduser(filename)) as hdu:
                ima = hdu[0].data
                hdr = hdu[0].header
                # define a kernel representing the detector pixel response
                # and use fractional pixel
                k_x, k_y, extent = load_standard_psf(
                    F_x, F_y, wl, delta_pix, hdr
                )
        elif os.path.isdir(filename):
            filenames = np.sort(glob.glob(filename + "*.fits"))
            psf_wl = []
            for file in filenames:
                with fits.open(os.path.expanduser(file)) as hdu:
                    psf_wl.append(hdu[0].header["WAVELEN"])
            idx = (np.abs(np.asarray(psf_wl) - wl.value)).argmin()
            with fits.open(os.path.expanduser(filenames[idx])) as hdu:
                ima = hdu[0].data
                hdr = hdu[0].header
                k_x, k_y, extent = load_standard_psf(
                    F_x, F_y, wl, delta_pix, hdr
                )
    else:
        x = np.linspace(-4.0, 4.0, 256)
        xx, yy = np.meshgrid(x, x)
        r = np.pi * np.sqrt(xx**2 + yy**2) + 1.0e-10

        ima = (2.0 * j1(r) / r) ** 2
        ima *= 0.25 * np.pi * (x[1] - x[0]) ** 2
        # print ima.sum()
        k_x = delta_pix / (F_x * wl * (x[1] - x[0]))
        k_y = delta_pix / (F_y * wl * (x[1] - x[0]))
        # print k_y, k_x
        extent = (
            -(ima.shape[1] // 2) * F_x * wl * (x[1] - x[0]),
            (ima.shape[1] // 2) * F_x * wl * (x[1] - x[0]),
            -(ima.shape[0] // 2) * F_y * wl * (x[1] - x[0]),
            (ima.shape[0] // 2) * F_y * wl * (x[1] - x[0]),
        )
        # normalise
        ima /= ima.sum()

    fk_x, ik_x = np.modf(k_x)
    fk_y, ik_y = np.modf(k_y)

    kernel = np.ones((int(ik_y) + 2, int(ik_x) + 2)) * fk_x.unit
    kernel[:, 0] *= 0.5 * fk_x
    kernel[:, -1] *= 0.5 * fk_x
    kernel[0, :] *= 0.5 * fk_y
    kernel[-1, :] *= 0.5 * fk_y

    imac = signal.convolve2d(ima, kernel, mode="same")

    if plot:
        plot_imac(imac, extent)

    return imac, kernel, extent


def load_pixel_psf_size(delta_pix, hdr):
    xmin = [-hdr["NAXIS2"] / 2.0 * delta_pix.value] * u.micron
    xmax = [hdr["NAXIS2"] / 2.0 * delta_pix.value] * u.micron
    ymin = [-hdr["NAXIS1"] / 2.0 * delta_pix.value] * u.micron
    ymax = [hdr["NAXIS1"] / 2.0 * delta_pix.value] * u.micron
    extent = (xmin, xmax, ymin, ymax)
    return extent


def pixel_based_psf(wl, delta_pix, filename):
    if filename[-5:] == ".fits":
        with fits.open(os.path.expanduser(filename)) as hdu:
            ima = hdu[0].data
            hdr = hdu[0].header
            extent = load_pixel_psf_size(delta_pix, hdr)

    elif os.path.isdir(filename):
        filenames = np.sort(glob.glob(filename + "*.fits"))
        psf_wl = []
        for file in filenames:
            with fits.open(os.path.expanduser(file)) as hdu:
                psf_wl.append(hdu[0].header["WAVELEN"])
        idx = (np.abs(np.asarray(psf_wl) - wl.value)).argmin()
        with fits.open(os.path.expanduser(filenames[idx])) as hdu:
            ima = hdu[0].data
            hdr = hdu[0].header
            extent = load_pixel_psf_size(delta_pix, hdr)

    return ima, np.array([1.0]), extent


def load_paos_psf(wl_group):
    from exorad.output.hdf5 import load

    scale = 1.0e6
    group = load(input_group=wl_group)

    img_key = list(group.keys())[-1]
    group = group[img_key]

    ima = group["amplitude"] ** 2
    dx = group["dx"] * u.micron * scale
    dy = group["dy"] * u.micron * scale
    extent = group["extent"] * u.micron * scale
    fratio = group["fratio"]

    return ima, dx, dy, extent, fratio


def interpolate_paos_psf(fd, wl):
    wavelengths = np.asarray(
        [key for key in list(fd.keys()) if key != "info"]
    ).astype(np.float64)
    wavelengths.sort()

    if len(wavelengths) == 1:
        logger.error("Can't interpolate, PAOS file has only one wavelength")
        raise ValueError(
            "Can't interpolate, PAOS file has only one wavelength"
        )

    idx0 = np.argmin(np.abs(wavelengths - wl))

    if np.min(wavelengths) <= wl <= np.max(wavelengths):
        idx1 = idx0 - 1 if wavelengths[idx0] - wl > 0 else idx0 + 1
    else:
        logger.warning(
            "Wavelength is outside interpolation region, extrapolating..."
        )
        idx1 = idx0 + 1 if wavelengths[idx0] - wl > 0 else idx0 - 1

    wl0, wl1 = wavelengths[idx0], wavelengths[idx1]

    ima0, dx0, dy0, extent0, fratio0 = load_paos_psf(wl_group=fd[f"{wl0}"])

    ima1, dx1, dy1, extent1, fratio1 = load_paos_psf(wl_group=fd[f"{wl1}"])

    dx0, dy0, extent0 = dx0.value, dy0.value, extent0.value
    dx1, dy1, extent1 = dx1.value, dy1.value, extent1.value

    ima = interp1d(
        x=[wl0, wl1],
        y=[ima0, ima1],
        kind="linear",
        fill_value="extrapolate",
        axis=0,
    )(wl)
    dx = interp1d(
        x=[wl0, wl1], y=[dx0, dx1], kind="linear", fill_value="extrapolate"
    )(wl)
    dy = interp1d(
        x=[wl0, wl1], y=[dy0, dy1], kind="linear", fill_value="extrapolate"
    )(wl)
    extent = interp1d(
        x=[wl0, wl1],
        y=[extent0, extent1],
        kind="linear",
        fill_value="extrapolate",
        axis=0,
    )(wl)
    fratio = interp1d(
        x=[wl0, wl1],
        y=[fratio0, fratio1],
        kind="linear",
        fill_value="extrapolate",
    )(wl)

    return ima, dx * u.micron, dy * u.micron, extent * u.micron, fratio


def paosPSF(wl, delta_pix, filename="", plot=False):
    import h5py
    from scipy import signal

    logger.debug("loading PAOS psf")

    assert wl.unit == u.micron, print("Wavelength unit should be micron. ")

    try:
        with h5py.File(os.path.expanduser(filename), mode="r") as fd:
            wavelength = wl.value[0]
            if str(wavelength) in list(fd.keys()):
                ima, dx, dy, extent, fratio = load_paos_psf(
                    wl_group=fd[f"{wavelength}"]
                )
            else:
                ima, dx, dy, extent, fratio = interpolate_paos_psf(
                    fd, wavelength
                )

    except OSError as e:
        logger.error("Error loading PAOS psf file. ")
        raise FileNotFoundError(e.errno)

    k_x = delta_pix / dx
    k_y = delta_pix / dy

    fk_x, ik_x = np.modf(k_x)
    fk_y, ik_y = np.modf(k_y)

    kernel = np.ones((int(ik_y) + 2, int(ik_x) + 2)) * fk_x.unit

    kernel[:, 0] *= 0.5 * fk_x
    kernel[:, -1] *= 0.5 * fk_x
    kernel[0, :] *= 0.5 * fk_y
    kernel[-1, :] *= 0.5 * fk_y

    imac = signal.convolve2d(ima, kernel, mode="same")

    if plot:
        plot_imac(imac, extent)

    return imac, kernel, extent


def plot_imac(imac, extent, xlim=None, ylim=None):
    import matplotlib.pyplot as plt
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    extent = np.asarray([ext.value for ext in extent]).ravel()

    fig, ax = plt.subplots(1, 1, figsize=(8, 6))

    im = ax.imshow(imac, cmap=plt.get_cmap("viridis"), origin="lower")
    extent = np.asarray(extent).astype(np.float64)
    im.set_extent(extent=extent)

    if (xlim, ylim) != (None, None):
        plt.xlim(*xlim)
        plt.ylim(*ylim)

    plt.grid(True)

    cax = make_axes_locatable(ax).append_axes("right", size="5%", pad=0.05)
    plt.colorbar(im, cax=cax, orientation="vertical")

    plt.show()

    return 0


def wl_encircled_energy(filename, eec, format, Fnum_x, Fnum_y, delta_pix):
    filenames = np.sort(glob.glob(filename + "*.fits"))
    psf_wl, enc = [], []
    for file in filenames:
        with fits.open(os.path.expanduser(file)) as hdu:
            psf_wl.append(hdu[0].header["WAVELEN"])
        if format == "pixel_based":
            ima, _, _ = pixel_based_psf(
                hdu[0].header["WAVELEN"], delta_pix, file
            )
            enc += [find_aperture_radius(ima, eec, 1, 1, 1)]
        else:
            ima, _, _ = binnedPSF(
                Fnum_x, Fnum_y, hdu[0].header["WAVELEN"], delta_pix
            )
            enc += [
                find_aperture_radius(
                    ima, eec, Fnum_x, Fnum_y, hdu[0].header["WAVELEN"]
                )
            ]
    return psf_wl, enc


def find_aperture_radius(ima, eec, Fnum_x, Fnum_y, wavelength):
    """
    It finds the aperture radius for a given PSF such that the desired Encircled Energy is contained.

    Parameters
    ----------
    ima:
        psf image in micron scale
    eec:
        desired encircled energy
    Fnum_x:
        f number in the spectral direction
    Fnum_y:
        f number in the spatial direction
    wavelength:
        wavelength of the sampled psf

    Returns
    ---------
    float
    """
    last_enc, i = 0, 0
    rs, enc = [], []
    while last_enc < (eec + 0.02):
        i += 1
        rs += [i]
        enc += [encircled_energy(i, ima, Fnum_x, Fnum_y, wavelength)]
        last_enc = enc[-1]
    inter = interp1d(enc, rs)
    r = inter(eec)
    return r


def encircled_energy(r, ima, Fnum_x, Fnum_y, wavelength):
    r_pix_x = r * Fnum_x * wavelength
    r_pix_y = r * Fnum_y * wavelength
    aper = photutils.aperture.EllipticalAperture(
        (ima.shape[1] // 2, ima.shape[0] // 2),
        b=float(r_pix_y.value),
        a=float(r_pix_x.value),
    )
    phot_ = photutils.aperture.aperture_photometry(ima, aper)
    phot = phot_["aperture_sum"].data[0]

    return phot / ima.sum()


def OmegaPix(Fnum_x, Fnum_y=None):
    """
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

    """

    if not Fnum_y:
        Fnum_y = Fnum_x

    if Fnum_x > Fnum_y:
        a = 1.0 / (2 * Fnum_y)
        b = 1.0 / (2 * Fnum_x)
    else:
        a = 1.0 / (2 * Fnum_x)
        b = 1.0 / (2 * Fnum_y)

    h = 1.0

    A = 4.0 * h * b / (a * np.sqrt(h**2 + a**2))
    k = np.sqrt((a**2 - b**2) / (h**2 + a**2))
    alpha = np.sqrt(1 - (b / a) ** 2)

    Omega = 2.0 * np.pi - A * mpmath.ellippi(alpha**2, k**2)

    return Omega * u.sr


if __name__ == "__main__":
    Omega = OmegaPix(5.0, 5.0)

    sigma = np.arctan(1.0 / 10)
    OmegaCheck = 2.0 * np.pi * (1 - np.cos(sigma))
    print((Omega, OmegaCheck))
