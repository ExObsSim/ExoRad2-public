import numpy as np
from astropy import constants as cc
from astropy import units as u

from exorad.log.logger import Logger
from exorad.models.source import Star, CustomSed


class Target(Logger, object):
    '''
    Target base class
    '''

    def __init__(self):
        self.set_log_name()
        luminosity = None
        sed = None
        model = None
        table = None
        id = None
        star = None
        planet = None
        name = None

    def calc_logg(self, M, R):
        m = M.si
        r = R.si
        g = cc.G * m / r ** 2
        g = g.to(u.cm / u.s ** 2)

        return np.log10(g.value)

    def update_target(self, obj):
        if isinstance(obj, Star) or isinstance(obj, CustomSed):
            self.star.luminosity = obj.luminosity
            self.star.sed = obj.sed
            self.star.model = obj.model
            self.debug('target updated')
        else:
            self.warning(
                'Object type {:s} not implemented'.format(type(obj)))

    def write(self, output):
        targets_out = output.create_group('targets')
        group_name = str(self.name)
        target_dict = self.to_dict()
        targets_out.store_dictionary(target_dict, group_name=group_name)
        self.info('target {} saved'.format(self.name))
        return output

    def to_dict(self):
        from exorad.utils.util import to_dict
        return to_dict(self)