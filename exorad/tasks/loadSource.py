import numpy as np
from astropy import units as u

from exorad.models.source import Star, CustomSed
from exorad.tasks.task import Task


class LoadSource(Task):
    """
    Updates target with its source and return the source Sed

    Parameters
    ----------
    target: Target Class
        target class
    source: dict
        source spectrum description
    wl_range: couple
        wavelength range to investigate: (wl_min, wl_max)


    Returns
    -------
        Target:
            Target class with star.sed updated
        Sed:
            source Sed

    Examples
    --------
    >>> loadSource = LoadSource()
    >>> target, source = loadSource(target= target, source={'sourceSpectrum': {'value':'Planck'}})

    Raises
    ------
    AttributeError:
        if some target information are missing
    """

    def __init__(self):
        self.addTaskParam('target', 'target class object')
        self.addTaskParam('source', 'source spectrum description')
        self.addTaskParam('wl_range', 'wavelength range to investigate')

    def execute(self):
        target = self.get_task_param('target')
        source = self.get_task_param('source')

        if isinstance(source, str):
            source = {'value': source}
            self.warning('source should be dict, not string.')

        # check if star information are complete
        for attr in ['D', 'Teff', 'M', 'R']:
            if not hasattr(target.star.__getattribute__(attr), 'value'):
                self.error('target information incomplete')
                raise AttributeError('target information incomplete')

        self.debug('source spectrum : {}'.format(source['value'].lower()))
        if source['value'].lower() == 'planck':
            self.debug('Plack sed selected')
            star = Star('.',
                        target.star.D,
                        target.star.Teff,
                        target.star.calc_logg(target.star.M, target.star.R),
                        0.0,
                        target.star.R,
                        use_planck_spectrum=True)

        elif source['value'].lower() == 'phoenix':
            star = Star(source['StellarModels']['value'],
                        target.star.D,
                        target.star.Teff,
                        target.star.calc_logg(target.star.M, target.star.R),
                        0.0,
                        target.star.R,
                        use_planck_spectrum=False)
            self.debug('stellar sed used {}'.format(star.filename))
        elif source['value'].lower() == 'custom':
            star = CustomSed(source['CustomSed']['value'],
                             target.star.R,
                             target.star.D)
            self.debug('custom sed used {}'.format(source['CustomSed']['value']))
        else:
            star = Star('.',
                        target.star.D,
                        target.star.Teff,
                        target.star.calc_logg(target.star.M, target.star.R),
                        0.0,
                        target.star.R,
                        use_planck_spectrum=True)
            self.info('invalid source spectrum description. Planck spectrum is used')

        wl_min, wl_max = self.get_task_param('wl_range')
        if wl_min > wl_max: wl_min, wl_max = wl_max, wl_min
        if not hasattr(wl_min, 'unit'):
            self.debug('wavelength unit not found: micron assumed')
            wl_min *= u.um
            wl_max *= u.um

        wl_grid = np.logspace(np.log10(wl_min.value),
                              np.log10(wl_max.value), 6000) * \
                  wl_max.unit
        star.sed.spectral_rebin(wl_grid)

        target.update_target(star)
        if hasattr(target, 'table'):
            target.table = self._add_star_metadata(target.star, target.table)
        self.set_output([target, star.sed])

    def _add_star_metadata(self, star, table):
        metadata = {}

        metadata['starName'] = star.name
        metadata['starM'] = star.M
        metadata['starTeff'] = star.Teff
        metadata['starR'] = star.R
        metadata['starDistance'] = star.D
        metadata['starL'] = star.luminosity
        metadata['starModel'] = star.model
        if hasattr(star, 'magk'):
            metadata['starMagK'] = star.magk

        table.meta.update(metadata)
        return table
