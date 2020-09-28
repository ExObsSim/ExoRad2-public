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
        skyFilter_data = self.description['data']

        em_func = interp1d(skyFilter_data['Wavelength'].to(self.wl.unit),
                           skyFilter_data['Radiance'],
                           assume_sorted=False,
                           fill_value=0.0,
                           bounds_error=False)
        skyFilter = SkyFilter(self.wl, em_func(self.wl) * skyFilter_data['Radiance'].unit)
        self.debug('radiance : {}'.format(skyFilter.data))

        tr_func = interp1d(skyFilter_data['Wavelength'].to(self.wl.unit),
                           skyFilter_data['Transmission'],
                           assume_sorted=False,
                           fill_value=1.0,
                           bounds_error=False)
        skyFilter.transmission = tr_func(self.wl)
        self.debug('transmission : {}'.format(skyFilter.transmission))

        return skyFilter
