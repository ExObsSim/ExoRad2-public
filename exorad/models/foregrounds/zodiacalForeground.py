import math

import astropy.units as u
import numpy as np
from astropy.coordinates import BarycentricTrueEcliptic
from astropy.coordinates import SkyCoord
from scipy import interpolate

from exorad.log import Logger
from exorad.models.signal import Radiance
from exorad.utils.exolib import planck


class ZodiacalFrg(Logger):
    """
    Produce the zodiacal radiance.

    Parameters
    ----------
    wl: array
        wavelength grid
    description: dict
        zodiacal foreground description
    coordinates: (float, float)
        pointing coordinates as (ra, dec)

    Attributes
    -----------
    wl: array
        wavelength grid
    description: dict
        zodiacal foreground description dict
    radiance: Radiance
        zodiacal radiance

    Methods
    --------
    model(A,B,C)
        returns the zodiacal Radiance for the zodiacal light model presented in Glasse et al. 2010,
        scaled by coefficients fitted over Kelsall et al. 1998 model
    zodiacal_fit_direction(coord)
        returns the fitted coefficients for the zodiacal model given the target position.
        It's based on Kelsall et al. 1998 model
    """

    def __init__(self, wl, description, coordinates=None):
        super().__init__()
        self.wl = wl
        self.description = description
        self.radiance = self._get_radiance(coordinates)

    def _get_radiance(self, coordinates):
        if coordinates and 'zodicalFrgMap' in self.description:
            self.warning('zodiacal map not tested yet!')
            try:
                A, B, C = self.zodiacal_fit_direction(coordinates)
            except KeyError:
                self.warning('zodiacal fit failed')
                self._get_radiance(coordinates=None)

        elif 'zodiacFactor' in self.description:
            self.debug(' model used for zodiacal foreground')
            A = B = C = self.description['zodiacFactor']['value']
            self.debug('zodiac factor : {}'.format(A))
        else:
            self.warning('zodiacal description uncompleted')
            A = B = C = 0

        return self.model(A, B, C)

    def model(self, A, B, C):
        units = u.W / (u.m ** 2 * u.um * u.sr)
        zodi_emission = (3.5e-14 * B * planck(self.wl, 5500.0 * u.K) +
                         3.58e-8 * C * planck(self.wl, 270.0 * u.K)).to(units)
        return Radiance(self.wl, zodi_emission)

    def zodiacal_fit_direction(self, coord):
        ra = coord[0]
        dec = coord[1]
        eq = SkyCoord(ra=ra, dec=dec, frame='icrs')
        eq = eq.transform_to(BarycentricTrueEcliptic)

        try:
            data = self.description['zodicalFrgMap']['data']
        except KeyError:
            self.warning('zodiacal map not found')
            raise KeyError('zodiacal map not found')

        idx = np.where(data['longitude'] < 0)
        data['longitude'][idx] += 360

        lon = float(math.floor(eq.lon.value))
        lat = float(math.floor(eq.lat.value))

        c1 = np.where(np.logical_and(data['longitude'] == lon,
                                     data['latitude'] == lat))[0][0]
        c2 = np.where(np.logical_and(data['longitude'] == lon + 1,
                                     data['latitude'] == lat))[0][0]
        c3 = np.where(np.logical_and(data['longitude'] == lon,
                                     data['latitude'] == lat + 1))[0][0]
        c4 = np.where(np.logical_and(data['longitude'] == lon + 1,
                                     data['latitude'] == lat + 1))[0][0]

        idx = np.sort([c1, c2, c3, c4])
        fA = interpolate.interp2d(x=data['longitude'][idx], y=data['latitude'][idx], z=data['A'][idx], kind='linear')
        fB = interpolate.interp2d(x=data['longitude'][idx], y=data['latitude'][idx], z=data['B'][idx], kind='linear')
        fC = interpolate.interp2d(x=data['longitude'][idx], y=data['latitude'][idx], z=data['C'][idx], kind='linear')

        A_new = fA(eq.lon, eq.lat)
        B_new = fB(eq.lon, eq.lat)
        C_new = fC(eq.lon, eq.lat)

        return A_new, B_new, C_new
