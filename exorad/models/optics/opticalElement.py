import numpy as np
from astropy import units as u
from scipy.interpolate import interp1d

from exorad.log import Logger
from exorad.models.utils import get_wl_col_name


class OpticalElement(Logger):
    """
    Handler for an optical element.

    This class represents an optical element within an optical path, managing its
    transmission, emissivity, temperature, and other relevant properties.

    Parameters
    ----------
    description : dict
        Dictionary containing the optical element's description from the payload
        configuration file.
    wl : `astropy.units.Quantity` or array_like
        Wavelength grid where the optical properties of the element are evaluated.
        Should have units of length (e.g., microns).

    Attributes
    ----------
    name : str
        Name of the optical element.
    description : dict
        Original description dictionary of the optical element.
    wl : `astropy.units.Quantity` or array_like
        Wavelength grid.
    transmission : `numpy.ndarray`
        Transmission of the optical element evaluated over the wavelength grid.
    emissivity : `numpy.ndarray`
        Emissivity of the optical element evaluated over the wavelength grid.
    temperature : `astropy.units.Quantity` or None
        Temperature of the optical element in Kelvin. `None` if not specified.
    type : str
        Type of the optical element (e.g., "detector box", "optics box", "surface").
    position : str
        Position of the optical element in the optical path (e.g., "detector",
        "optics box", "path").
    angle : `astropy.units.Quantity` or None
        Solid angle associated with the optical element in steradians. `None` if
        not specified.

    Methods
    -------
    _get_angle()
        Retrieves and processes the solid angle of the optical element.
    _get_position()
        Determines the position of the optical element in the optical path.
    _get_temperature()
        Retrieves and processes the temperature of the optical element.
    _get_transmission()
        Calculates the transmission of the optical element over the wavelength grid.
    _get_emissivity()
        Calculates the emissivity of the optical element over the wavelength grid.
    """

    def __init__(self, description, wl):
        """
        Initialize the OpticalElement instance.

        Parameters
        ----------
        description : dict
            Dictionary containing the optical element's description.
        wl : `astropy.units.Quantity` or array_like
            Wavelength grid with appropriate units.
        """
        super().__init__()
        self.name = description["value"]
        self.debug(f"Initializing OpticalElement: {self.name}")
        self.description = description
        self.wl = wl
        self.type = self.description["type"]["value"]
        self.transmission = self._get_transmission()
        self.emissivity = self._get_emissivity()
        self.temperature = self._get_temperature()
        self.position = self._get_position()
        self.angle = self._get_angle()

    def _get_angle(self):
        """
        Retrieve and process the solid angle of the optical element.

        Returns
        -------
        angle : `astropy.units.Quantity` or None
            Solid angle in steradians if specified; otherwise, `None`.
        """
        if "solid_angle" in self.description:
            angle_value = self.description["solid_angle"]["value"]
            if hasattr(angle_value, "unit"):
                return angle_value.to(u.sr)
            else:
                self.debug("Angle assumed to be in steradians (sr)")
                return angle_value * u.sr
        else:
            # If not specified, return None to use the default value from the instrument
            return None

    def _get_position(self):
        """
        Determine the position of the optical element in the optical path.

        Returns
        -------
        position : str
            Position identifier ("detector", "optics box", or "path").
        """
        if self.type == "detector box":
            return "detector"
        elif self.type == "optics box":
            return "optics box"
        else:
            return "path"

    def _get_temperature(self):
        """
        Retrieve and process the temperature of the optical element.

        Returns
        -------
        temperature : `astropy.units.Quantity` or None
            Temperature in Kelvin if specified; otherwise, `None`.
        """
        if "temperature" in self.description:
            temp_value = self.description["temperature"]["value"]
            if hasattr(temp_value, "unit"):
                return temp_value.to(u.K)
            else:
                self.debug("Temperature assumed to be in Kelvin (K)")
                return temp_value * u.K
        else:
            return None

    def _get_transmission(self):
        """
        Calculate the transmission of the optical element over the wavelength grid.

        The method handles various scenarios:
        - If a transmission data file is provided, it interpolates the transmission
          based on the wavelength grid.
        - If both transmission and reflectivity are provided without a specified
          "use" key, it raises an error.
        - Applies wavelength boundaries (`wl_min` and `wl_max`) if specified.

        Returns
        -------
        transmission : `numpy.ndarray`
            Transmission values corresponding to the wavelength grid.

        Raises
        ------
        KeyError
            If the required transmission or reflectivity column is not found in the
            transmission data file.
        """
        if "data" in self.description:
            self.debug("Transmission data file found")
            # Determine which column to use for transmission
            if "use" in self.description:
                colname = self.description["use"]["value"]
            else:
                try:
                    colname = "Transmission"
                    _ = self.description["data"][colname]
                except KeyError:
                    try:
                        colname = "Reflectivity"
                        _ = self.description["data"][colname]
                    except KeyError:
                        error_msg = f"{colname} column name not found in transmission data file"
                        self.error(error_msg)
                        raise KeyError(error_msg)

            # Get the wavelength column name from the data
            wl_colname = get_wl_col_name(
                self.description["data"], description=self.description
            )
            # Create an interpolation function for transmission
            tr_func = interp1d(
                self.description["data"][wl_colname],
                self.description["data"][colname],
                assume_sorted=False,
                fill_value=0.0,
                bounds_error=False,
            )
            # Evaluate the transmission over the wavelength grid
            transmission = tr_func(self.wl)
        elif "transmission" in self.description and "reflectivity" in self.description:
            if "use" in self.description:
                key = self.description["use"]["value"]
                transmission = np.ones(self.wl.size) * self.description[key]["value"]
            else:
                error_msg = (
                    "Both transmission and reflectivity are included but 'use' is not indicated"
                )
                self.error(error_msg)
                raise KeyError(error_msg)
        elif "transmission" in self.description or "reflectivity" in self.description:
            try:
                transmission = np.ones(self.wl.size) * self.description["transmission"]["value"]
            except KeyError:
                transmission = np.ones(self.wl.size) * self.description["reflectivity"]["value"]
                self.debug(
                    f"Reflectivity keyword found for transmission for {self.name}"
                )
            # Apply wavelength lower bound if specified
            if "wl_min" in self.description:
                wl_min = self.description["wl_min"]["value"].to(self.wl.unit)
                self.debug(f"Transmission lower boundary at {wl_min}")
                idx = np.where(self.wl < wl_min)
                transmission[idx] = 0.0
            # Apply wavelength upper bound if specified
            if "wl_max" in self.description:
                wl_max = self.description["wl_max"]["value"].to(self.wl.unit)
                self.debug(f"Transmission upper boundary at {wl_max}")
                idx = np.where(self.wl > wl_max)
                transmission[idx] = 0.0
        else:
            # Default transmission is 1 (no attenuation)
            transmission = np.ones(self.wl.size)
        self.debug(f"Transmission: {transmission}")
        return transmission

    def _get_emissivity(self):
        """
        Calculate the emissivity of the optical element over the wavelength grid.

        The method handles various scenarios:
        - If an emissivity data file is provided, it interpolates the emissivity
          based on the wavelength grid.
        - If emissivity is specified directly, it applies the constant value.
        - For "detector box" type, emissivity is set to 1.
        - Otherwise, emissivity is set to 0.

        Returns
        -------
        emissivity : `numpy.ndarray`
            Emissivity values corresponding to the wavelength grid.

        Raises
        ------
        KeyError
            If the emissivity column is not found in the emissivity data file.
        """
        if "data" in self.description:
            self.debug("Emissivity data file found")
            # Get the wavelength column name from the data
            wl_colname = get_wl_col_name(
                self.description["data"], description=self.description
            )

            # Determine the emissivity column name
            em_colname = None
            for em_key in ["Emissivity", "emissivity"]:
                if em_key in self.description["data"].keys():
                    em_colname = em_key
                    break
            if em_colname is None:
                error_msg = "Emissivity column not found in transmission data file"
                self.error(error_msg)
                raise KeyError(error_msg)

            # Create an interpolation function for emissivity
            em_func = interp1d(
                self.description["data"][wl_colname],
                self.description["data"][em_colname],
                assume_sorted=False,
                fill_value=0.0,
                bounds_error=False,
            )
            # Evaluate the emissivity over the wavelength grid
            emissivity = em_func(self.wl)
        elif "emissivity" in self.description:
            # Apply a constant emissivity value
            emissivity = np.ones(self.wl.size) * self.description["emissivity"]["value"]
        elif self.type == "detector box":
            # Default emissivity for detector box is 1
            emissivity = np.ones(self.wl.size)
        else:
            # Default emissivity is 0 (non-emissive)
            emissivity = np.zeros(self.wl.size)
        self.debug(f"Emissivity: {emissivity}")
        return emissivity
