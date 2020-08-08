from scipy.interpolate import interp1d

from exorad.log import Logger
from exorad.models.signal import Radiance


class SkyFilter(Radiance):
    """
    Handler for sky filter

    Attributes
    ----------
    transmission: array
        contains the transmission information sampled at the radiance wl grid
    """
    transmission = None


class SkyForeground(Logger):

    def __init__(self, wl, description):
        super().__init__()
        self.wl = wl
        self.name = description['value']
        self.description = description
        self.skyFilter = self._get_radiance()

    def _get_radiance(self):
        radiance_data = self.description['radiance']['data']
        self.debug('radiance data found')

        colname = radiance_data.colnames[-1]

        em_func = interp1d(radiance_data['Wavelength'].to(self.wl.unit),
                           radiance_data[colname],
                           assume_sorted=False,
                           fill_value=0.0,
                           bounds_error=False)
        skyFilter = SkyFilter(self.wl, em_func(self.wl) * radiance_data[colname].unit)
        self.debug('radiance : {}'.format(skyFilter.data))

        transmission_data = self.description['transmission']['data']
        self.debug('transmission data found')

        colname = transmission_data.colnames[-1]

        tr_func = interp1d(transmission_data['Wavelength'].to(self.wl.unit),
                           transmission_data[colname],
                           assume_sorted=False,
                           fill_value=0.0,
                           bounds_error=False)
        skyFilter.transmission = tr_func(self.wl)
        self.debug('transmission : {}'.format(skyFilter.transmission))

        return skyFilter
