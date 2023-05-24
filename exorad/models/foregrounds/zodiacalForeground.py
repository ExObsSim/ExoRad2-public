import astropy.units as u

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

    """

    def __init__(self, wl, description, coordinates=None):
        super().__init__()
        self.wl = wl
        self.description = description
        self.radiance = self._get_radiance(coordinates)

    def _get_radiance(self, coordinates):
        fit_coord = (
            self.description["zodiacalMap"]["value"]
            if "zodiacalMap" in self.description
            else False
        )
        map_file = (
            self.description["custom_map_file"]["value"]
            if "custom_map_file" in self.description
            else None
        )
        if fit_coord and coordinates:
            try:
                A = self.zodiacal_fit_direction(coordinates, map_file)
            except (KeyError, OSError):
                self.warning("zodiacal fit failed")
                self._get_radiance(coordinates=None)

        elif "zodiacFactor" in self.description:
            self.debug(" model used for zodiacal foreground")
            A = self.description["zodiacFactor"]["value"]
            self.debug("zodiac factor : {}".format(A))
        else:
            self.warning("zodiacal description uncompleted")
            A = 0

        return self.model(A)

    def model(self, A):
        """
        returns the zodiacal Radiance for the zodiacal light model presented in Glasse et al. 2010,
        scaled by coefficient fitted over Kelsall et al. 1998 model
        """
        units = u.W / (u.m**2 * u.um * u.sr)
        zodi_emission = A * (
            3.5e-14 * planck(self.wl, 5500.0 * u.K)
            + 3.58e-8 * planck(self.wl, 270.0 * u.K)
        ).to(units)
        return Radiance(self.wl, zodi_emission)

    def zodiacal_fit_direction(self, coord, map_file=None):
        """
        returns the fitted coefficient for the zodiacal model given the target position.
        It's based on Kelsall et al. 1998 model
        """
        import os
        from astropy.io.misc.hdf5 import read_table_hdf5
        import numpy as np
        from pathlib import Path

        ra_input = coord[0]
        dec_input = coord[1]

        exorad_path = Path(__file__).parent.parent.parent.absolute()
        zodi_map_file = (
            map_file
            if map_file
            else os.path.join(exorad_path, "data/Zodi_map.hdf5")
        )

        if not os.path.isfile(zodi_map_file):
            dir_path = Path(__file__).parent.absolute()

            i = 0
            while (
                "data"
                not in [d.stem for d in Path(dir_path).iterdir() if d.is_dir()]
                and i < 10
            ):
                dir_path = dir_path.parent
                i += 1
            if i > 10:
                self.error("Zodi map file not found")
                raise OSError("Zodi map file not found")

            data_path = os.path.join(dir_path.absolute().as_posix(), "data")
            zodi_map_file = os.path.join(data_path, "Zodi_map.hdf5")

        self.debug("map data:{}".format(zodi_map_file))

        try:
            zodi_table = read_table_hdf5(zodi_map_file)
            self.debug(zodi_table)
            distance = (zodi_table["ra_icrs"] * u.deg - ra_input) ** 2 + (
                zodi_table["dec_icrs"] * u.deg - dec_input
            ) ** 2
            idx = np.argmin(distance)
            self.debug("selected line {}".format(idx))
            self.debug(zodi_table[idx])
            return zodi_table["zodi_coeff"][idx]

        except OSError:
            self.error("Zodi map file not found")
            raise OSError("Zodi map file not found")
