import logging
import os
import pathlib
import unittest

import astropy.units as u
import numpy as np
from astropy import constants as cc

from exorad.log import setLogLevel

setLogLevel(logging.DEBUG)


class StarTest(unittest.TestCase):

    phoenix_stellar_model = '/usr/local/project_data/sed/'

    @unittest.skipIf(not os.path.isdir(phoenix_stellar_model),
                     'phoenix dir not found')
    def test_phoenix_star(self):
        from exorad.models.source import Star

        target = {'D': 12.975 * u.pc,
                  'T': 3016 * u.K,
                  'M': 0.15 * u.Msun,
                  'R': 0.218 * u.Rsun}
        g = (cc.G * target['M'].si / (target['R'].si) ** 2).to(u.cm / u.s ** 2)
        logG = np.log10(g.value)

        star1 = Star(self.phoenix_stellar_model,
             target['D'],
             target['T'],
             logG,
             0.0,
             target['R'],
             use_planck_spectrum=False)

    # todo test more phoenix formats
    # def test_phoenix_star_fits(self):
    #     from exorad.models.source import Star
    #
    #     from exorad.models.source import Star
    #     path = pathlib.Path(__file__).parent.absolute()
    #     test_dir = os.path.join(path, 'test_data/fits')
    #
    #     target = {'D': 12.975 * u.pc,
    #               'T': 2300 * u.K,
    #               'M': 0.15 * u.Msun,
    #               'R': 0.218 * u.Rsun}
    #     g = (cc.G * target['M'].si / (target['R'].si) ** 2).to(u.cm / u.s ** 2)
    #     logG = np.log10(g.value)
    #
    #     star1 =Star(test_dir,
    #          target['D'],
    #          target['T'],
    #          logG,
    #          0.0,
    #          target['R'],
    #          use_planck_spectrum=False)
    #
    #
    #     bb = Star('.',
    #          target['D'],
    #          target['T'],
    #          0.0,
    #          0.0,
    #          target['R'],
    #          wl_min=star1.sed.wl_grid.value.min() * u.um,
    #          wl_max=star1.sed.wl_grid.value.max() * u.um,
    #          use_planck_spectrum=True)
    #
    #     import matplotlib.pyplot as plt
    #     plt.plot(star1.sed.wl_grid, star1.sed.data, label='phoenix')
    #     plt.plot(bb.sed.wl_grid, bb.sed.data, label='planck')
    #     plt.yscale('log')
    #     plt.legend()
    #     plt.show()
    #
    # def test_phoenix_star_7format(self):
    #     from exorad.models.source import Star
    #     path = pathlib.Path(__file__).parent.absolute()
    #     test_dir = os.path.join(path, 'test_data')
    #
    #
    #     target = {'D': 12.975 * u.pc,
    #               'T': 800 * u.K,
    #               'M': 0.15 * u.Msun,
    #               'R': 0.218 * u.Rsun}
    #     g = (cc.G * target['M'].si / (target['R'].si) ** 2).to(u.cm / u.s ** 2)
    #     logG = np.log10(g.value)
    #
    #     star1 =Star(test_dir,
    #          target['D'],
    #          target['T'],
    #          logG,
    #          0.0,
    #          target['R'],
    #          use_planck_spectrum=False)
    #
    #     bb = Star('.',
    #          target['D'],
    #          target['T'],
    #          0.0,
    #          0.0,
    #          target['R'],
    #          wl_min=star1.sed.wl_grid.value.min() * u.um,
    #          wl_max=star1.sed.wl_grid.value.max() * u.um,
    #          use_planck_spectrum=True)
    #
    #     import matplotlib.pyplot as plt
    #     plt.plot(star1.sed.wl_grid, star1.sed.data, label='phoenix')
    #     plt.plot(bb.sed.wl_grid, bb.sed.data, label='planck')
    #     # plt.xlim(bb.sed.wl_grid.value.min(), bb.sed.wl_grid.value.max())
    #     plt.yscale('log')
    #     plt.legend()
    #     plt.show()

    def test_BB_star(self):
        from exorad.models.source import Star

        target = {'D': 12.975 * u.pc,
                  'T': 3016 * u.K,
                  'M': 0.15 * u.Msun,
                  'R': 0.218 * u.Rsun}

        Star('.',
             target['D'],
             target['T'],
             0.0,
             0.0,
             target['R'],
             use_planck_spectrum=True)

    def test_GenericSed(self):
        import os
        from inspect import getsourcefile
        from exorad.models.source import CustomSed
        current_folder = os.path.dirname(
            os.path.abspath(getsourcefile(lambda: 0)))
        target = {'D': 12.975 * u.pc,
                  'R': 0.218 * u.Rsun}
        CustomSed(os.path.join(os.path.dirname(current_folder),
                               'examples/customsed.csv'),
                  target['R'],
                  target['D'],
                  )
