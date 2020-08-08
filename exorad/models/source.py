import glob
import os
import warnings

import numpy as np
from astropy import units as u
from astropy.io import ascii
from astropy.io import fits

from exorad.log import Logger
from exorad.utils import exolib
from .signal import Sed

warnings.filterwarnings('ignore', category=UserWarning, append=True)


class Star(Logger, object):
    """
      Instantiate a Stellar class using Phenix Stellar Models

      Attributes
      ----------
      lumiosity : 		float
                  Stellar bolometric luminosity computed from Phenix stellar modle. Units [W]
      wl				array
                  wavelength [micron]
      sed 			array
                  Spectral energy density [W m**-2 micron**-1]
      ph_wl			array
                  phoenix wavelength [micron]. Phenix native resolution
      ph_sed 			array
                  phenix spectral energy density [W m**-2 micron**-1]. Phenix native resolution
      ph_filename 		phenix filename
    """

    # def __init__(self, star_sed_path, star_distance, star_temperature, star_logg, star_f_h, star_radius):
    def __init__(self,
                 star_sed_path,
                 starDistance,
                 starTemperature,
                 starLogg,
                 starMetallicity,
                 starRadius,
                 use_planck_spectrum=False,
                 wl_min=0.4 * u.um,
                 wl_max=10.0 * u.um,
                 phoenix_model_filename=None):
        """
        Parameters
        __________
          exocat_star 	: 	object
                    exodata star object
          star_sed_path:    : 	string
                    path to Phoenix stellar spectra

        """
        self.set_log_name()

        if use_planck_spectrum == True:
            self.debug('Planck spectrum used')
            wl = np.linspace(wl_min, wl_max, 10000)
            ph_wl, ph_sed, ph_L = self.__get_star_spectrum(
                wl,
                starDistance.to(u.m),
                starTemperature.to(u.K),
                starRadius.to(u.m))
            ph_file = None
        else:
            if phoenix_model_filename:
                ph_file = os.path.join(star_sed_path, phoenix_model_filename)
                self.debug('phoenix file name : {}'.format(ph_file))
            else:
                ph_file = self.__get_phonix_model_filename(
                    star_sed_path,
                    starTemperature.to(u.K),
                    starLogg,
                    starMetallicity)
                self.debug('phoenix file name : {}'.format(ph_file))

            ph_wl, ph_sed, ph_L = self.__read_phenix_spectrum(
                ph_file,
                starDistance.to(u.m),
                starRadius.to(u.m))

        self.luminosity = ph_L
        self.sed = Sed(wl_grid=ph_wl, data=ph_sed)
        self.filename = ph_file
        self.model = 'Planck' if use_planck_spectrum else os.path.basename(ph_file)

    def __get_phonix_model_filename(self, path, star_temperature,
                                    star_logg, star_f_h):
        sed_name = glob.glob(os.path.join(path, "*.BT-Settl.spec.fits.gz"))

        if len(sed_name) == 0:
            self.error("No stellar SED files found")
            raise OSError("No stellar SED files found")

        sed_T_list = np.array([np.float(os.path.basename(k)[3:8]) for k in sed_name])
        sed_Logg_list = np.array([np.float(os.path.basename(k)[9:12]) for k in sed_name])
        sed_Z_list = np.array([np.float(os.path.basename(k)[13:16]) for k in sed_name])

        idx = np.argmin(np.abs(sed_T_list - np.round(star_temperature.value / 100.0)) +
                        np.abs(sed_Logg_list - star_logg) +
                        np.abs(sed_Z_list - star_f_h))

        ph_file = sed_name[idx]

        return ph_file

    def __read_phenix_spectrum(self, ph_file, star_distance, star_radius):

        """Read a PHENIX Stellar Spectrum.

        Parameters
        __________
          ph_file : 		string
                    full path to models file containing the SED
        Returns
        -------
          wl:			array
                    The Wavelength at which the SED is sampled. Units are [micron]
          sed :			array
                    The SED of the star. Units are [W m**-2 micron**-1]
          L :			scalar
                    The bolometric luminosity of the star. Units are [W]

        """

        ####################### USING PHOENIX BIN_SPECTRA BINARY FILES (h5)

        with fits.open(ph_file) as hdu:
            strUnit = hdu[1].header['TUNIT1']
            wl = hdu[1].data.field('Wavelength') * u.Unit(strUnit)

            strUnit = hdu[1].header['TUNIT2']
            sed = hdu[1].data.field('Flux') * u.Unit(strUnit)

            # remove duplicates
            idx = np.nonzero(np.diff(wl))
            wl = wl[idx]
            sed = sed[idx]

            bolometric_luminosity = (hdu[1].header['PHXLUM'] * u.W).to(u.Lsun)

            hdu.close()

        # Normalise SED to observed SED
        bolometric_flux = np.trapz(sed, x=wl)  # [W m**-2]
        bolometric_luminosity = 4 * np.pi * star_radius ** 2 * bolometric_flux  # [W]
        sed *= (star_radius / star_distance) ** 2  # [W/m^2/mu]

        # When trading two lines below for two above you'll be using the phoenix
        # luminosity, but this invalidates current validation tables against exosim
        # norm = bolometric_luminosity.to(u.W) / (4.0*np.pi*star_distance**2)
        # sed = norm * sed / bolometric_flux

        return wl, sed, bolometric_luminosity.to(u.Lsun)

    def __get_star_spectrum(self, wl, star_distance, star_temperature, star_radius):
        omega_star = np.pi * (star_radius / star_distance) ** 2 * u.sr
        sed = omega_star * exolib.planck(wl, star_temperature)
        bolometric_flux = np.trapz(sed, x=wl)
        bolometric_luminosity = 4.0 * np.pi * star_distance ** 2 * bolometric_flux
        return wl, sed, bolometric_luminosity.to(u.Lsun)


class CustomSed(Logger, object):

    def __init__(self, fname, star_radius, star_distance):
        self.set_log_name()
        ph = ascii.read(fname, format='ecsv')
        ph_wl = ph['Wavelength'].data * ph['Wavelength'].unit
        ph_sed = ph['Sed'].data * ph['Sed'].unit

        bolometric_flux = np.trapz(ph_sed, x=ph_wl)  # [W m**-2]
        bolometric_luminosity = 4 * np.pi * (star_radius.to(u.m)) ** 2 * bolometric_flux  # [W]
        ph_sed *= (star_radius.to(u.m) / star_distance.to(u.m)) ** 2  # [W/m^2/mu]
        self.debug('custom sed used : {}'.format(fname))

        self.sed = Sed(ph_wl, ph_sed)
        self.filename = fname
        self.luminosity = bolometric_luminosity.to(u.Lsun)
        self.model = 'Custom'
