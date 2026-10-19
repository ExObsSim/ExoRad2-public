import logging
import os
import pathlib
import unittest

import matplotlib.pyplot as plt
import pytest
from test_options import payload_file

from exorad import tasks
from exorad.log import disableLogging, enableLogging
from exorad.utils.plotter import Plotter

path = pathlib.Path(__file__).parent.absolute()
data_dir = os.path.join(path.parent.absolute(), "examples")


class PlotterTest(unittest.TestCase):
    loadOptions = tasks.LoadOptions()
    buildChannels = tasks.BuildChannels()
    loadTargetList = tasks.LoadTargetList()
    mergeChannelsOutput = tasks.MergeChannelsOutput()
    observeTargetList = tasks.ObserveTargetlist()

    disableLogging()
    payload = loadOptions(filename=payload_file())
    wl_min, wl_max = (
        payload["common"]["wl_min"]["value"],
        payload["common"]["wl_max"]["value"],
    )
    channels = buildChannels(payload=payload, write=False, output=None)
    table = mergeChannelsOutput(channels=channels)

    targets = loadTargetList(target_list=os.path.join(data_dir, "test_target.csv"))
    targets = observeTargetList(
        targets=targets.target,
        payload=payload,
        channels=channels,
        wl_range=(wl_min, wl_max),
        plot=False,
        out_dir=None,
    )
    enableLogging()

    def tearDown(self):
        plt.close("all")

    def test_plot_bands(self):
        plotter = Plotter(input_table=self.table)
        _fig, ax = plt.subplots()
        out = plotter.plot_bands(ax, channel_edges=True)
        assert out is ax
        assert len(ax.get_xticks()) > 0

    def test_plot_bands_no_edges(self):
        plotter = Plotter(input_table=self.table)
        _fig, ax = plt.subplots()
        plotter.plot_bands(ax, scale="linear", channel_edges=False)

    def test_plot_efficiency_with_channels(self):
        plotter = Plotter(channels=self.channels, input_table=self.table)
        fig = plotter.plot_efficiency()
        assert fig is not None
        assert plotter.fig_efficiency is fig

    def test_plot_efficiency_without_channels_returns_none(self):
        plotter = Plotter(input_table=self.table)
        assert plotter.plot_efficiency() is None

    def test_plot_table(self):
        for name in self.targets:
            plotter = Plotter(input_table=self.targets[name].table)
            fig, (ax1, ax2) = plotter.plot_table()
            assert fig is not None
            assert ax1 is not None
            assert ax2 is not None
            assert plotter.fig is fig

    def test_save_fig_table_and_efficiency(self, tmp_path=None):
        import tempfile

        tmpdir = tempfile.mkdtemp()
        name = next(iter(self.targets))
        plotter = Plotter(channels=self.channels, input_table=self.targets[name].table)
        plotter.plot_table()
        plotter.plot_efficiency()

        table_png = os.path.join(tmpdir, "table.png")
        eff_png = os.path.join(tmpdir, "eff.png")
        plotter.save_fig(table_png)
        plotter.save_fig(eff_png, efficiency=True)
        assert os.path.exists(table_png)
        assert os.path.exists(eff_png)

    def test_save_fig_without_a_figure_logs_error(self):
        plotter = Plotter(input_table=self.table)
        # no plot produced yet -> AttributeError is caught and logged
        plotter.save_fig("nope.png")


class PlotterMainTest(unittest.TestCase):
    def test_main_writes_png_per_target(self):
        import sys
        import tempfile

        from exorad.exorad import standard_pipeline
        from exorad.utils import plotter

        tmpdir = tempfile.mkdtemp()
        h5_path = os.path.join(tmpdir, "out.h5")
        disableLogging()
        standard_pipeline(
            options=payload_file(),
            target_list=os.path.join(data_dir, "test_target.csv"),
            output=h5_path,
        )
        enableLogging()

        out_dir = os.path.join(tmpdir, "plots")
        old = sys.argv
        sys.argv = ["exorad-plot", "-i", h5_path, "-o", out_dir]
        try:
            plotter.main()
        finally:
            sys.argv = old
            plt.close("all")

        pngs = [f for f in os.listdir(out_dir) if f.endswith(".png")]
        assert len(pngs) >= 1

    def test_main_rejects_both_target_selectors(self):
        import sys
        import tempfile

        from exorad.exorad import standard_pipeline
        from exorad.utils import plotter

        tmpdir = tempfile.mkdtemp()
        h5_path = os.path.join(tmpdir, "out.h5")
        disableLogging()
        standard_pipeline(
            options=payload_file(),
            target_list=os.path.join(data_dir, "test_target.csv"),
            output=h5_path,
        )
        enableLogging()

        old = sys.argv
        sys.argv = [
            "exorad-plot",
            "-i",
            h5_path,
            "-o",
            os.path.join(tmpdir, "plots"),
            "-n",
            "0",
            "-t",
            "myTest",
        ]
        try:
            with pytest.raises(ValueError):
                plotter.main()
        finally:
            sys.argv = old


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    unittest.main()
