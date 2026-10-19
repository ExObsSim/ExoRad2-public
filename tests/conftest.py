"""Shared pytest configuration and fixtures.

Force a non-interactive matplotlib backend so the test suite never opens
figure windows (some code paths call ``plt.show()`` when plotting is enabled).
"""

import gzip

import matplotlib
import numpy as np
import pytest
from astropy.io import fits

matplotlib.use("Agg")


@pytest.fixture
def phoenix_dir(tmp_path):
    """A directory with one synthetic BT-Settl spectrum in the .spec.fits.gz format.

    The filename encodes ``lte<T/100>-<logg>-<Z>`` so ``Star`` can pick it by
    temperature; the payload is a plain decreasing spectrum.
    """
    wl = np.linspace(0.2, 50.0, 3000)
    flux = 1e6 * wl**-1

    hdu = fits.BinTableHDU.from_columns(
        [
            fits.Column(name="Wavelength", array=wl, format="D"),
            fits.Column(name="Flux", array=flux, format="D"),
        ]
    )
    hdu.header["TUNIT1"] = "um"
    hdu.header["TUNIT2"] = "W / (m2 um)"
    hdu.header["PHXLUM"] = 3.8e26

    raw = tmp_path / "lte030-4.5-0.0.BT-Settl.spec.fits"
    fits.HDUList([fits.PrimaryHDU(), hdu]).writeto(raw)

    gz = tmp_path / "lte030-4.5-0.0.BT-Settl.spec.fits.gz"
    with open(raw, "rb") as fin, gzip.open(gz, "wb") as fout:
        fout.write(fin.read())
    raw.unlink()
    return str(tmp_path)


@pytest.fixture
def paos_h5(tmp_path):
    """A synthetic PAOS PSF file: one group per wavelength, each holding an
    image sub-group with amplitude / dx / dy / extent / fratio."""
    import h5py

    path = tmp_path / "paos.h5"
    yy, xx = np.mgrid[-32:32, -32:32]
    with h5py.File(path, "w") as fd:
        for wl in (0.5, 1.0, 2.0):
            amp = np.exp(-(xx**2 + yy**2) / (2 * (6 * wl) ** 2))
            g = fd.create_group(f"{wl}/0")
            g["amplitude"] = amp
            g["dx"] = 6.0
            g["dy"] = 6.0
            g["extent"] = np.array([-96.0, 96.0, -96.0, 96.0])
            g["fratio"] = 5.0
    return str(path)
