from collections import OrderedDict

import astropy.units as u
import numpy as np

from exorad.models.foregrounds.skyForegrounds import SkyForeground
from exorad.models.foregrounds.zodiacalForeground import ZodiacalFrg
from .task import Task


class EstimateZodi(Task):
    """
    It estimate the zodiacal radiance in the target direction for a specific wl range

    Parameters
    -----------
    zodi: dict
        zodiacal foreground description
    target: Target
        target class
    wl_range: (float, float)
        wavelength range to investigate. (wl_min, wl_max)

    Returns
    -------
    Target:
        updated target class
    """

    def __init__(self):
        self.addTaskParam('zodi', 'zodiacal foreground description')
        self.addTaskParam('target', 'target class')
        self.addTaskParam('wl_range', 'wavelength range to investigate')

    def execute(self):
        self.info('estimating zodiacal foreground')
        zodi_dict = self.get_task_param('zodi')
        target = self.get_task_param('target')
        wl_min, wl_max = self.get_task_param('wl_range')

        wl = np.logspace(np.log10((wl_min.to(u.um)).value),
                         np.log10((wl_max.to(u.um)).value), 6000) * u.um
        zodi = ZodiacalFrg(wl=wl, description=zodi_dict)

        if not hasattr(target, 'foreground'):
            setattr(target, 'foreground', OrderedDict())
        target.foreground['zodi'] = zodi.radiance
        self.set_output(target)


class EstimateForeground(Task):
    """
    It estimate the foreground radiance in the target direction for a specific wl range

    Parameters
    -----------
    foreground: dict
        foreground description
    target: Target
        target class
    wl_range: (float, float)
        wavelength range to investigate. (wl_min, wl_max)

    Returns
    -------
    Target:
        updated target class
    """

    def __init__(self):
        self.addTaskParam('foreground', 'foreground description')
        self.addTaskParam('target', 'target class')
        self.addTaskParam('wl_range', 'wavelength range to investigate')

    def execute(self):
        self.info('estimating custom foreground')
        foreground_dict = self.get_task_param('foreground')
        target = self.get_task_param('target')
        wl_min, wl_max = self.get_task_param('wl_range')

        wl = np.logspace(np.log10((wl_min.to(u.um)).value),
                         np.log10((wl_max.to(u.um)).value), 6000) * u.um
        foreground_name = foreground_dict['value']
        foreground = SkyForeground(wl, foreground_dict)
        if not hasattr(target, 'foreground'):
            setattr(target, 'foreground', OrderedDict())
        target.foreground[foreground_name] = foreground.skyFilter
        if not hasattr(target, 'skyTransmission'):
            from exorad.models.signal import Signal
            setattr(target, 'skyTransmission', Signal(wl, foreground.skyFilter.transmission))
        else:
            target.skyTransmission.data *= foreground.skyFilter.transmission
        self.set_output(target)


class EstimateForegrounds(Task):
    """
    It estimate the foreground radiance in the target direction for a specific wl range

    Parameters
    -----------
    foregrounds: dict
        foregrounds description
    target: Target
        target class
    wl_range: (float, float)
        wavelength range to investigate. (wl_min, wl_max)

    Returns
    -------
    Target:
        updated target class
    """

    def __init__(self):
        self.addTaskParam('foregrounds', 'foregrounds description')
        self.addTaskParam('target', 'target class')
        self.addTaskParam('wl_range', 'wavelength range to investigate')

    def execute(self):
        self.info('estimating foregrounds')
        target = self.get_task_param('target')
        foregrounds = self.get_task_param('foregrounds')
        wl_min, wl_max = self.get_task_param('wl_range')

        estimateZodi = EstimateZodi()
        estimateForeground = EstimateForeground()

        if isinstance(foregrounds, OrderedDict):
            for foreground in foregrounds:
                if foreground == 'zodiacal':
                    target = estimateZodi(zodi=foregrounds['zodiacal'],
                                          target=target,
                                          wl_range=(wl_min, wl_max))
                else:
                    target = estimateForeground(foreground=foregrounds[foreground],
                                                target=target,
                                                wl_range=(wl_min, wl_max))
        else:
            if foregrounds['value'] == 'zodiacal':
                target = estimateZodi(zodi=foregrounds,
                                      target=target,
                                      wl_range=(wl_min, wl_max))
            else:
                target = estimateForeground(foreground=foregrounds,
                                            target=target,
                                            wl_range=(wl_min, wl_max))
        self.set_output(target)
