import numpy as np
from astropy import units as u
from scipy.interpolate import interp1d
from exorad.models.utils import get_wl_col_name

from exorad.log import Logger


class OpticalElement(Logger):
    """
    Handler for optical element

    Parameters
    -----------
    el: dict
        OpticalElement from the payload description file
    wl: array
        wavelength grid where to evaluate the element optical properties

    Attributes
    ----------
    name: str
        optical element name
    description: dict
        optical element input dict
    wl: array
        wavelength grid
    transmission: array
        optical element transmission estimated over the wl grid
    emissivity: array
        optical element emissivity
    temperature: float
        optical element temperature in K
    type: str
        optical element type
    position: str
        optical element position in the optic path

    """

    def __init__(self, description, wl):
        super().__init__()
        self.name = description['value']
        self.debug(self.name)
        self.description = description
        self.wl = wl
        self.type = self.description['type']['value']
        self.transmission = self._get_transmission()
        self.emissivity = self._get_emissivity()
        self.temperature = self._get_temperature()
        self.position = self._get_position()

    def _get_position(self):
        if self.type == 'detector box':
            return 'detector'
        elif self.type == 'optics box':
            return 'optics box'
        else:
            return 'path'

    def _get_temperature(self):
        if 'temperature' in self.description:
            if hasattr(self.description['temperature']['value'], 'unit'):
                return self.description['temperature']['value'].to(u.K)
            else:
                self.debug('Temperature assumed to be in K')
                return self.description['temperature']['value'] * u.K
        else:
            return None

    def _get_transmission(self):
        """
        it return the transmission for the optical element.
        If a data file is indicated, the user should specify the column name to use.
        Such use allow the use to select if wants to use transmission of reflectivity for dicroics.
        If "use" is not indicated in the description file, the code will look for "Transmission" keyword in column name.
        """
        if 'data' in self.description:
            self.debug('found transmission file')
            if 'use' in self.description:
                colname = self.description['use']['value']
            else:
                try:
                    colname = 'Transmission'
                    _ = self.description['data'][colname]
                except KeyError:
                    try:
                        colname = 'Reflectivity'
                        _ = self.description['data'][colname]
                    except KeyError:
                        self.error('{} column name not found in transmission data file'.format(colname))
                        raise KeyError('{} column name not found in transmission data file'.format(colname))

            wl_colname = get_wl_col_name(self.description['data'], description=self.description)
            tr_func = interp1d(self.description['data'][wl_colname],
                               self.description['data'][colname],
                               assume_sorted=False,
                               fill_value=0.0,
                               bounds_error=False)

            transmission = tr_func(self.wl)
        elif 'transmission' in self.description and 'reflectivity' in self.description:
            if 'use' in self.description:
                key = self.description['use']['value']
                transmission = np.ones(self.wl.size) * self.description[key]['value']
            else:
                self.error('both transmission and reflectivity are included but use is not indicated')
                raise KeyError('both transmission and reflectivity are included but use is not indicated')

        elif 'transmission' in self.description or 'reflectivity' in self.description:
            try:
                transmission = np.ones(self.wl.size) * self.description['transmission']['value']
            except KeyError:
                transmission = np.ones(self.wl.size) * self.description['reflectivity']['value']
                self.debug('reflectivity keyword found for transmission for {}'.format(self.name))
            if 'wl_min' in self.description:
                self.debug('found transmission inferior boundary : {}'.format(self.description['wl_min']['value']))
                idx = np.where(self.wl < self.description['wl_min']['value'].to(self.wl.unit))
                transmission[idx] = 0.0
            if 'wl_max' in self.description:
                self.debug('found transmission superior boundary : {}'.format(self.description['wl_min']['value']))
                idx = np.where(self.wl > self.description['wl_max']['value'].to(self.wl.unit))
                transmission[idx] = 0.0

        else:
            transmission = np.ones(self.wl.size)
        self.debug('transmission : {}'.format(transmission))
        return transmission

    def _get_emissivity(self):
        if 'data' in self.description:
            self.debug('found emissivity file')

            wl_colname = get_wl_col_name(self.description['data'], description=self.description)

            em_colname = None
            for em_key in ['Emissivity', 'emissivity']:
                if em_key in self.description['data'].keys():
                    em_colname= em_key
            if em_colname is None:
                self.error('Emissivity column not found in transmission data file')
                raise KeyError('Emissivity column not found in transmission data file')

            em_func = interp1d(self.description['data'][wl_colname],
                               self.description['data'][em_colname],
                               assume_sorted=False,
                               fill_value=0.0,
                               bounds_error=False)

            emissivity = em_func(self.wl)
        elif 'emissivity' in self.description:
            emissivity = np.ones(self.wl.size) * self.description['emissivity']['value']
        elif self.type == 'detector box':
            emissivity = np.ones(self.wl.size)
        else:
            emissivity = np.zeros(self.wl.size)
        self.debug('emissivity : {}'.format(emissivity))
        return emissivity
