import copy
from collections import OrderedDict

import astropy.constants as const
import astropy.units as u
import numpy as np
from astropy.table import hstack
from astropy.table import QTable

from exorad.log import Logger
from exorad.models.optics.opticalElement import OpticalElement
from exorad.models.signal import Radiance
from exorad.utils.diffuse_light_propagation import convolve_with_slit
from exorad.utils.diffuse_light_propagation import integrate_light
from exorad.utils.diffuse_light_propagation import prepare
from exorad.utils.exolib import planck
from exorad.utils.passVal import PassVal


def surface_radiance(wl, T, emissivity):
    """
    Calculate the spectral radiance from optics.

    The spectral radiance is defined as power per unit surface area,
    per unit solid angle, and per unit bandwidth.

    Parameters
    ----------
    wl : array_like
        Wavelength array with units of length.
    T : scalar
        Temperature of optical elements in Kelvin.
    emissivity : array_like
        Emissivity of optical surfaces.

    Returns
    -------
    radiance : Radiance
        Spectral radiance. It will have the same shape as the input `wl`.
    """
    # Ensure wavelength is in microns
    wl_ = wl.to(u.micron) if hasattr(wl, "unit") else wl
    # Ensure temperature is in Kelvin
    T_ = T.to(u.K) if hasattr(T, "unit") else T
    try:
        # Calculate spectral radiance using Planck's law
        I = planck(wl_, T_).to(u.W / (u.m**2 * u.micron * u.sr))
    except AttributeError:
        # If Planck function fails, use zeros
        I = np.zeros_like(wl_) * u.W / u.m**2 / u.sr / u.micron
    # Create Radiance object with emissivity applied
    radiance = Radiance(wl_grid=wl, data=emissivity * I)
    return radiance


class InstRadiance(Radiance):
    """
    Handler for instrument radiance.

    Attributes
    ----------
    position : str
        Position of the optical element in the optical path.
        Default is 'path'.
    slit : None or bool
        Indicates if a slit is present in the optical path.
    """

    position = "path"
    slit = None


class OpticalPath(Logger):
    """
    Handler for instrument diffuse light.

    Parameters
    ----------
    description : dict
        Optic description.
    wl : array_like
        Wavelength grid as a quantity array.

    Attributes
    ----------
    optical_element_dict : dict
        Dictionary of `OpticalElement` instances.
    radiance_dict : dict
        Dictionary of `InstRadiance` instances.
    radiance_table : QTable
        Table of optical elements radiance.
    transmission_table : QTable
        Table of optical elements transmissions.
    signal_table : QTable
        Table of optical elements signals.
    max_signal_per_pixel : QTable
        Table of optical elements max signal per pixel.
    slit_width : Quantity or None
        Slit width measurement, if a slit is in the optical path. Default is None.

    Methods
    -------
    prepend_optical_elements(optical_element_dict)
        Updates the class `optical_element_dict` by putting the input dictionary
        at the top of the existing one.
    chain()
        Concatenates the optical elements, producing the `radiance_table` and `radiance_dict`.
    build_transmission_table()
        Produces the transmission table for the optical path.
    compute_signal(ch_table, ch_built_instr)
        Produces the telescope self-emission signal for the channel and returns
        the updated channel table.

    Examples
    --------
    >>> telescope = OpticalPath(wl=wl_grid, description=options)
    >>> spec = OpticalPath(wl=wl_grid, description=options['channel']['Spec'])
    >>> spec.prepend_optical_elements(telescope.optical_element_dict)
    >>> spec.build_transmission_table()
    >>> spec.chain()
    """

    def __init__(self, description, wl):
        """
        Initialize the OpticalPath instance.

        Parameters
        ----------
        description : dict
            Optic description.
        wl : array_like
            Wavelength grid as a quantity array.
        """
        super().__init__()
        self.description = description
        self.opt = description["optics"]  # Optical elements description
        self.radiance_dict = OrderedDict()
        self.radiance_table = QTable()
        self.signal_table = QTable()
        self.max_signal_per_pixel = QTable()
        # Refine the wavelength grid if necessary
        self.wl = self._wl_grid_refinement(wl)
        # Prepare optical elements
        self.optical_element_dict = self._prepare_elements()
        self.transmission_table = QTable()
        self.slit_width = None

    def build_transmission_table(self):
        """
        Build the transmission table for the optical path.

        Returns
        -------
        transmission_table : QTable
            Table containing the transmission of each optical element and the total transmission.
        """
        self.info("Building transmission table")
        self.transmission_table["Wavelength"] = self.wl
        total_transmission = np.ones(self.wl.size)
        for el in self.optical_element_dict:
            # Add the transmission of each optical element to the table
            self.transmission_table[el] = self.optical_element_dict[el].transmission
            # Multiply to get the total transmission
            total_transmission *= self.optical_element_dict[el].transmission
        # Add total transmission to the table
        self.transmission_table["total"] = copy.deepcopy(total_transmission)
        self.debug(f"Transmission table : {self.transmission_table}")
        return self.transmission_table

    def _wl_grid_refinement(self, wl):
        """
        Refine the wavelength grid if it contains only one element.

        If the input wavelength list contains only one element, it produces a wavelength grid
        from the minimum wavelength investigated by the detector and the cutoff.

        Parameters
        ----------
        wl : array_like
            Wavelength grid.

        Returns
        -------
        out_wl : array_like
            Refined wavelength grid.
        """
        if len(wl) == 1:
            # If only one wavelength, create a logarithmic grid
            wl_min = self.description["detector"]["wl_min"]["value"].to(u.um)
            cut_off = self.description["detector"]["cut_off"]["value"].to(u.um)
            out_wl = (
                np.logspace(
                    np.log10(wl_min.value),
                    np.log10(cut_off.value),
                    PassVal.working_R,
                )
                * u.um
            )
            self.debug(f"Single wavelength found. Using grid: {out_wl}")
        else:
            out_wl = wl
            self.debug(f"Selected wavelength grid: {wl}")
        return out_wl

    def prepend_optical_elements(self, optical_element_dict):
        """
        Update the optical_element_dict by prepending the input dictionary.

        Parameters
        ----------
        optical_element_dict : dict
            Dictionary of optical elements to prepend.
        """
        # Prepend the new optical elements to the existing ones
        self.optical_element_dict = OrderedDict(
            list(optical_element_dict.items()) + list(self.optical_element_dict.items())
        )

    def _prepare_elements(self):
        """
        Prepare the optical elements.

        Returns
        -------
        out : OrderedDict
            Dictionary of `OpticalElement` instances.
        """
        wl = self.wl
        out = OrderedDict()
        try:
            opt_el = self.opt["opticalElement"]
        except KeyError:
            # If no optical elements defined, create a default one
            opt_el = {"value": "noElement", "type": {"value": "surface"}}
        if isinstance(opt_el, OrderedDict):
            for el in opt_el:
                self.debug(f"Preparing {el}")
                out[el] = OpticalElement(opt_el[el], wl)
        else:
            out[opt_el["value"]] = OpticalElement(opt_el, wl)
        return out

    def chain(self):
        """
        Concatenate the optical elements, producing the radiance_table and radiance_dict.

        Returns
        -------
        radiance_dict : OrderedDict
            Dictionary of `InstRadiance` instances for each optical element.
        """
        wl = self.wl
        self.radiance_table["Wavelength"] = wl
        opt_el = self.optical_element_dict
        opt_list = list(opt_el.keys())
        self.debug(f"Optics list: {opt_list}")
        for i, k in enumerate(opt_list):
            el = opt_el[k]
            self.debug(f"Propagating {el.name}")
            out_radiance = InstRadiance(wl_grid=wl, data=np.zeros(wl.size))
            out_radiance.position = el.position
            if el.temperature is not None:
                # Calculate the surface radiance
                out_radiance.data = surface_radiance(
                    el.wl, el.temperature, el.emissivity
                ).data
            else:
                self.debug("Skipped due to missing temperature")
                continue
            for other_el in opt_list[i + 1 :]:
                self.debug(f"Passing through {other_el}")
                # Apply the transmission of subsequent optical elements
                out_radiance.data *= opt_el[other_el].transmission
                if opt_el[other_el].type == "slit":
                    out_radiance.slit = True
                    self.slit_width = opt_el[other_el].description["width"]["value"]
            # Store the radiance data
            self.radiance_dict[el.name] = copy.deepcopy(out_radiance)
            self.radiance_table[el.name] = copy.deepcopy(out_radiance.data)
            self.debug(f"Final radiance: {out_radiance.data}")
        return self.radiance_dict

    def compute_signal(self, ch_table, ch_built_instr):
        """
        Compute the telescope self-emission signal for the channel.

        Parameters
        ----------
        ch_table : QTable
            Channel table.
        ch_built_instr : dict
            Built instrument parameters for the channel.

        Returns
        -------
        updated_table : QTable
            Updated channel table with instrument signals.
        """
        (
            total_max_signal,
            total_signal,
            wl_table,
            A,
            qe,
            omega_pix,
            _,
        ) = prepare(ch_table, ch_built_instr, self.description)
        for item in self.radiance_dict:
            self.debug(f"Computing signal for {item}")
            rad = copy.deepcopy(self.radiance_dict[item])
            # Rebin the quantum efficiency to match the radiance wavelength grid
            qe.spectral_rebin(rad.wl_grid)
            if rad.slit and "slit_width" in ch_built_instr:
                # If there is a slit, convolve the signal with the slit function
                max_signal_per_pix, signal = convolve_with_slit(
                    self.description,
                    ch_built_instr,
                    A,
                    ch_table,
                    omega_pix,
                    qe,
                    rad,
                )
            else:
                self.debug("No slit found")
                # Calculate the photon rate per unit area
                rad.data *= (
                    A
                    * qe.data
                    * (qe.wl_grid / const.c / const.h).to(1.0 / u.W / u.s)
                    * u.count
                )
                if hasattr(rad, "angle") and rad.angle is not None:
                    self.debug("Angle found")
                    rad.data *= rad.angle
                else:
                    if rad.position == "detector":
                        self.debug("This is the detector box")
                        rad.data *= np.pi * u.sr
                    elif rad.position == "optics box":
                        self.debug("This is the optics box")
                        rad.data *= np.pi * u.sr - omega_pix
                    else:
                        self.debug("This is the optical path")
                        rad.data *= omega_pix
                # Integrate the radiance over wavelength
                max_signal_per_pix, signal = integrate_light(
                    rad, rad.wl_grid, ch_built_instr
                )
            # Store the signals
            self.signal_table[f"{item} signal"] = signal
            self.max_signal_per_pixel[item] = max_signal_per_pix
            self.debug(f"Signal: {self.signal_table[f'{item} signal']}")
            total_signal += self.signal_table[f"{item} signal"]
            total_max_signal += self.max_signal_per_pixel[item]
        out = QTable()
        out["instrument_signal"] = total_signal
        out["instrument_MaxSignal_inPixel"] = total_max_signal

        return hstack(
            [ch_table, out["instrument_signal", "instrument_MaxSignal_inPixel"]]
        )
