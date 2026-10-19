from __future__ import annotations

from typing import TYPE_CHECKING, Any

import astropy.units as u
import matplotlib.pyplot as plt
import numpy as np

from exorad.log.logger import Logger
from exorad.utils.exolib import rebin

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure


class Signal(Logger):
    """
    Signal class is the main class for every wavelength and time dependent object.
    By default it assume wavelength in um, data dimensionless and time in hours.

    Parameters
    ----------
    wl_grid: quantity
        wavelength grid. Must have a single axes
    data: array
        data table. Can have 2 axes
    time_grid: quantity (optional)
        time grid. Must have a single axes

    Attributes
    ----------
    wl_grid: quantity(um)
        wavelength grid. Must have a single axes
    data: quantity(dimensionless)
        data table. Can have 2 axes
    time_grid: quantity(hr)
        time grid. Must have a single axes
    time_dependent: bool
        it tells if the signal is time dependent (True) or not (False)

    Examples
    ---------
    >>> import numpy as np
    >>> wl = np.linspace(0.1, 1, 10) * u.um
    >>> data = np.random.random_sample((10, 10))
    >>> time = np.linspace(1, 5, 10) * u.hr
    >>> signal = Signal(wl_grid=wl, data=data, time_grid=time)
    """

    wl_grid: u.Quantity
    data: u.Quantity
    time_grid: u.Quantity

    def __init__(
        self, wl_grid: u.Quantity, data: Any, time_grid: u.Quantity = [0] * u.hr
    ) -> None:
        """
        class constructor

        Parameters
        ----------
        wl_grid: quantity
            wavelength grid. Must have a single axes
        data: array
            data table. Can have 2 axes
        time_grid: quantity (optional)
            time grid. Must have a single axes
        """

        self.set_log_name()
        self.wl_grid = self.check_quantities(wl_grid, "um")
        self.data = self.check_quantities(data, "")
        self.time_grid = self.check_quantities(time_grid, "hr")
        self.check_sizes()

    @property
    def time_dependent(self) -> bool:
        """
        It tells if the Signal is time dependent
        Returns
        -------
        bool:
            True if Signal is time dependent.

        """
        if all(self.time_grid == [0] * u.hr):
            return False
        #            return True
        raise NotImplementedError

    def check_quantities(self, quantity: Any, units: str | u.UnitBase) -> u.Quantity:
        """
        It assures that the input data has the desired units, if not it converts the data.
        If the data are dimensionless it assumes that are reported with the correct units.

        Parameters
        ----------
        quantity: quantity
        units: units or string

        Returns
        -------
        quantity

        Raises
        ------
        UnitConversionError
            if it cannot convert the original units into the desired ones

        """
        if isinstance(quantity, u.Quantity):
            if quantity.unit != units:
                try:
                    data_converted = quantity.to(u.Unit(units))
                    self.debug(f"input data: {quantity}")
                    self.debug(f"converted {quantity.unit} to {units}")
                    self.debug(f"converted data: {data_converted}")
                    return data_converted
                except u.UnitConversionError:
                    self.error(f"Impossible to convert {quantity.unit} to {units}")
                    raise

            else:
                return quantity
        else:
            # if units == '':
            #     self.debug('assumed dimensionless quantity as input'.format(units))
            # else:
            #     self.debug('assumed {} as input units'.format(units))
            return np.array(quantity) * u.Unit(units)

    def check_sizes(self) -> None:
        """
        Assures that the class attributes (wl_grid, data and time_grid) have the correct dimensions

        Raises
        -------
        ValueError
            if there is a dimension mismatch
        """
        if self.wl_grid.ndim > 1:
            self.error("wavelength grid cannot have multiple axes")
            raise ValueError
        if self.time_grid.ndim > 1:
            self.error("time grid cannot have multiple axes")
            raise ValueError
        if self.data.ndim > 2:
            self.error("data cannot have more than 2 axes")
            raise ValueError
        if self.data.shape[0] != self.wl_grid.shape[0]:
            self.error("dimension mismatch between wavelength grid and data")
            raise ValueError
        if (self.time_grid.shape[0] > 1 or self.data.ndim > 1) and (
            self.data.shape[1] - self.time_grid.shape[0] != 0
        ):
            self.error("dimension mismatch between time grid and data")
            raise ValueError

    def spectral_rebin(self, new_wl_grid: u.Quantity) -> None:
        """
        rebins the signal to the new wavelength grid
        """
        self.data = rebin(new_wl_grid, self.wl_grid, self.data)[1]
        idx = np.where(np.isnan(self.data))
        self.data[idx] = 0.0
        self.wl_grid = new_wl_grid

    def temporal_rebin(self, new_time_grid: u.Quantity) -> None:
        """
        rebins the signal to the new time grid
        """
        raise NotImplementedError

    def to_dict(self) -> dict:
        """
        Converts the Signal class into standard python dict.
        """
        from exorad.utils.util import to_dict

        return to_dict(self)

    def plot(
        self,
        fig: Figure | None = None,
        ax: Axes | None = None,
        yscale: str | None = None,
        xscale: str | None = None,
        label: str | None = None,
    ) -> tuple[Figure, Axes]:
        """
        plots the signal and return figure and axis or add the plot to an existing figure and axis
        """
        if fig is None or ax is None:
            fig, ax = plt.subplots(1, 1)
            ax.set_xlabel(rf"Wavelength [${self.wl_grid.unit}$]")
            ax.set_ylabel(rf"${self.data.unit}$")
        ax.plot(self.wl_grid, self.data, label=label)

        if yscale is not None:
            ax.set_yscale(yscale)
        if xscale is not None:
            ax.set_xscale(xscale)
        return fig, ax


class CustomSignal(Signal):
    """
    It's a Signal class with data having units custom units
    """

    def __init__(
        self,
        wl_grid: u.Quantity,
        data: Any,
        data_unit: str | u.UnitBase,
        time_grid: u.Quantity = [0] * u.hr,
    ) -> None:
        self.set_log_name()
        self.wl_grid = self.check_quantities(wl_grid, "um")
        self.data = self.check_quantities(data, data_unit)
        self.time_grid = self.check_quantities(time_grid, "hr")
        self.check_sizes()


class Sed(CustomSignal):
    """
    It's a Signal class with data having units of [W m^-2 mu^-1]
    """

    def __init__(
        self, wl_grid: u.Quantity, data: Any, time_grid: u.Quantity = [0] * u.hr
    ) -> None:
        super().__init__(wl_grid, data, u.W / u.m**2 / u.um, time_grid)


class Radiance(CustomSignal):
    """
    It's a Signal class with data having units of [W m^-2 mu^-1 sr^-1]
    """

    def __init__(
        self, wl_grid: u.Quantity, data: Any, time_grid: u.Quantity = [0] * u.hr
    ) -> None:
        super().__init__(wl_grid, data, u.W / u.m**2 / u.um / u.sr, time_grid)


class CountsPerSeconds(CustomSignal):
    """
    It's a Signal class with data having units of [ct/s]
    """

    def __init__(
        self, wl_grid: u.Quantity, data: Any, time_grid: u.Quantity = [0] * u.hr
    ) -> None:
        super().__init__(wl_grid, data, "ct/s", time_grid)
