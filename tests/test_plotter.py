import logging
import os
import pathlib
import unittest

import matplotlib.pyplot as plt
from conf import skip_plot
from test_options import payload_file

from exorad import tasks
from exorad.log import disableLogging
from exorad.log import enableLogging
from exorad.log import setLogLevel
from exorad.utils.plotter import Plotter

path = pathlib.Path(__file__).parent.absolute()
data_dir = os.path.join(path.parent.absolute(), 'examples')


class PlotterTest(unittest.TestCase):
    loadOptions = tasks.LoadOptions()
    buildChannels = tasks.BuildChannels()
    buildInstrument = tasks.BuildInstrument()
    loadPayload = tasks.LoadPayload()
    loadTargetList = tasks.LoadTargetList()
    loadSource = tasks.loadSource.LoadSource()
    mergeChannelsOutput = tasks.MergeChannelsOutput()
    observeTargetList = tasks.ObserveTargetlist()

    disableLogging()
    payload = loadOptions(filename=payload_file())
    wl_min, wl_max = payload['common']['wl_min']['value'], \
                     payload['common']['wl_max']['value']
    channels = buildChannels(payload=payload, write=False, output=None)
    table = mergeChannelsOutput(channels=channels)

    targets = loadTargetList(
        target_list=os.path.join(data_dir, 'test_target.csv'))
    targets = observeTargetList(targets=targets.target, payload=payload,
                                channels=channels, wl_range=(wl_min, wl_max),
                                plot=False, out_dir=None)
    enableLogging()

    @unittest.skipIf(skip_plot, "This test only produces plots")
    def test_efficiency(self):
        setLogLevel(logging.DEBUG)

        plotter = Plotter(channels=self.channels, input_table=self.table)
        plotter.plot_efficiency()
        plt.show()

    @unittest.skipIf(skip_plot, "This test only produces plots")
    def test_efficiency_catcher(self):
        setLogLevel(logging.DEBUG)

        plotter = Plotter(input_table=self.table)
        plotter.plot_efficiency()
        plotter.save_fig('test.png', efficiency=True)

    @unittest.skipIf(skip_plot, "This test only produces plots")
    def test_table(self):
        setLogLevel(logging.DEBUG)
        for target in self.targets:
            plotter = Plotter(input_table=self.targets[target].table)
            plotter.plot_table()
            plt.show()
