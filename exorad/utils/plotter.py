import logging
import os

import astropy.units as u
import h5py
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from astropy.io.misc.hdf5 import read_table_hdf5

from exorad.log import Logger
from exorad.log import setLogLevel

mpl_logger = logging.getLogger("matplotlib")
mpl_logger.setLevel(logging.WARNING)
cmap = matplotlib.cm.get_cmap("Set1")
matplotlib.rcParams.update({'font.size': 18})


class Plotter(Logger):
    """
    Plotter class. It offers a fast and easy way to produce diagnostic plots on the produced data.

    Parameters
    -----------
    input_table: Qtable
        table where to grab data and wl grid to plot.
    channels: dict
        dictionary describing the channels in the payload. Default is None
    """

    def __init__(self, input_table, channels=None, payload=None):
        self.set_log_name()
        self.inputTable = input_table
        self.channels = channels
        self.payload = payload
        self.fig = None
        self.fig_efficiency = None

    def plot_bands(self, ax, scale="log", channel_edges=True):
        """
        It plots the channels bands behind the indicated axes.

        Parameters
        -----------
        ax: matplotlib.axes
            axes where to plot the bands

        Returns
        --------
        matplotlib.axes.axes

        Note
        ----
        The Class input_table input parameter is required for this method to work.
        """
        channels = set(self.inputTable["chName"])
        cmap_bands = matplotlib.cm.get_cmap("tab10")
        norm = matplotlib.colors.Normalize(vmin=0.0, vmax=len(channels))
        tick_list = []

        for k, channelName in enumerate(channels):
            wl_min = min(
                self.inputTable["LeftBinEdge"][
                    np.where(self.inputTable["chName"] == channelName)
                ]
            )
            if hasattr(wl_min, "unit"):
                wl_min = wl_min.value
            wl_max = max(
                self.inputTable["RightBinEdge"][
                    np.where(self.inputTable["chName"] == channelName)
                ]
            )
            if hasattr(wl_max, "unit"):
                wl_max = wl_max.value
            ax.axvspan(
                wl_min,
                wl_max,
                alpha=0.1,
                zorder=0,
                color=cmap_bands(
                    norm(k),
                ),
            )
            tick_list.append(wl_min)
        tick_list.append(wl_max)
        ax.set_xscale(scale)
        if channel_edges:
            ax.set_xticks(tick_list)
            ax.get_xaxis().set_major_formatter(
                matplotlib.ticker.ScalarFormatter()
            )

        return ax

    def plot_efficiency(self, scale="log", channel_edges=False):
        """
        It produces a figure with payload efficiency over wavelength.
        The quantities reported are quantum efficiency, transmission and the photon conversion efficiency (pce)
        computed as the product of the quantum efficiency and transmission.

        Returns
        --------
        matplotlib.pyplot.figure

        Note
        ----
        The Class channels input parameter is required for this method to work.
        """
        if self.channels:
            from matplotlib.lines import Line2D
            from exorad.models.signal import Signal

            keys = ["transmission", "qe"]

            norm = matplotlib.colors.Normalize(
                vmin=0.0, vmax=len(self.channels)*len(keys)
            )

            fig, ax = plt.subplots(1, 1, figsize=(10, 8))
            # fig.suptitle("Payload photon conversion efficiency")

            lines, labels = [], []
            i = 0
            if self.channels:
                for ch in self.channels:
                    pce = None
                    for key in keys:
                        data = self.channels[ch].built_instr[
                            "{}_data".format(key)
                        ]
                        sig = Signal(
                            wl_grid=data["wl_grid"]["value"]
                            * u.Unit(data["wl_grid"]["unit"]),
                            data=data["data"]["value"],
                        )
                        ax.plot(
                            sig.wl_grid,
                            sig.data,
                            color=cmap(
                                norm(i),
                            ),
                            zorder=10,
                            lw=2
                        )
                        lines.append(
                            Line2D(
                                [0],
                                [0],
                                color=cmap(
                                    norm(i),
                                ),
                                lw=3,
                            )
                        )
                        labels.append('{} {}'.format(key, ch))
                        i+=1

                        if not pce:
                            pce = sig
                        else:
                            sig.spectral_rebin(pce.wl_grid)
                            pce.data *= sig.data
                    ax.plot(
                        pce.wl_grid,
                        pce.data,
                        lw=2,
                        zorder=10,
                        c='k'
                    )

                lines.append(
                    Line2D(
                        [0],
                        [0],
                        lw=3,
                        c='k'

                    )
                )
                labels.append("pce")
            else:
                pce = self.inputTable["TR"] * self.inputTable["QE"]
                self.inputTable["pce"] = pce
                keys = ["TR", "QE", "pce"]
                self.debug("efficiency keys : {}".format(keys))
                for e in keys:
                    ax.plot(
                        self.inputTable["Wavelength"],
                        self.inputTable[e],
                        label=e,
                        zorder=10,
                    )
                    # ax.plot(self.inputTable['Wavelength'], self.inputTable[e], c='None')
            ax.grid(zorder=0)
            ax = self.plot_bands(ax, scale, channel_edges)
            ax.legend(
                handles=lines, labels=labels,
                prop={"size": 14},
                loc="upper left",
                ncol=3,
                bbox_to_anchor=(0.1, -0.12),
                labelspacing=1.2,
                handlelength=1,
            )
            ax.set_title("Photon conversion efficiency")
            ax.set_xlabel(r"Wavelength [$\mu m$]")
            ax.set_ylabel("Efficiency")
            # ax.set_xscale('log')
            plt.tight_layout()
            plt.subplots_adjust(top=0.9, bottom=0.22, hspace=0.7)

            self.fig_efficiency = fig
            return fig

        else:
            self.error(
                "channels parameter is required for this method to work"
            )

    def plot_noise(self, ax, ylim=None, scale="log", channel_edges=False):
        """
        It plots the noise components found in the input table in the indicated axes.

        Parameters
        -----------
        ax: matplotlib.axes
            axes where to plot the noises
        ylim: float
            if present, it sets the axes y bottom lim. Default is None.

        Returns
        --------
        matplotlib.axes.axes

        Note
        ----
        The Class input_table input parameter is required for this method to work.
        """
        noise_keys = [
            x for x in self.inputTable.keys() if "noise" in x or "custom" in x
        ]
        self.debug("noise keys : {}".format(noise_keys))
        for k, n in enumerate(noise_keys):
            if n == "total_noise":
                ax.plot(
                    self.inputTable["Wavelength"],
                    self.inputTable[n],
                    zorder=9,
                    lw=3,
                    c="k",
                    marker=".",
                    markersize=5,
                    label="total_noise",
                    alpha=0.8,
                )  # , c='None')
            else:
                if self.inputTable[n].unit == u.hr**0.5:
                    noise = self.inputTable[n]
                else:
                    self.debug(
                        "{} rescaled by starSignal_inAperture".format(n)
                    )
                    noise = (
                        self.inputTable[n]
                        / self.inputTable["star_signal_inAperture"]
                    )
                # ax.scatter(self.inputTable['Wavelength'], noise, label=n, zorder=10, s=5, color=palette[k])
                ax.plot(
                    self.inputTable["Wavelength"],
                    noise,
                    zorder=9,
                    lw=2,
                    alpha=0.5,
                    marker=".",
                    label=n,
                )  # color=palette[k])  # c='None')

        if not ylim:
            ax.set_ylim(5e-7)
        else:
            ax.set_ylim(ylim)
        #        ax.grid(zorder=0, which='both')
        locmaj = matplotlib.ticker.LogLocator(base=10, numticks=12)
        ax.yaxis.set_major_locator(locmaj)
        locmin = matplotlib.ticker.LogLocator(
            base=10.0, subs=(0.2, 0.4, 0.6, 0.8), numticks=12
        )
        ax.yaxis.set_minor_locator(locmin)
        ax.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
        ax.grid(axis="y", which="minor", alpha=0.3)
        ax.grid(axis="y", which="major", alpha=0.5)
        #        ax.legend(bbox_to_anchor=(1, 1))
        ax.legend(
            prop={"size": 14},
            loc="upper left",
            ncol=3,
            bbox_to_anchor=(0.01, -0.25),
            labelspacing=1.2,
            handlelength=1,
        )
        ax.set_title("Noise Budget")
        ax.set_xlabel(r"Wavelength [$\mu m$]")
        ax.set_ylabel(r"Relative noise [$\sqrt{t_{int} \, / \, {hr}}$]")
        ax.set_yscale("log")
        # ax.set_xscale('log')
        ax = self.plot_bands(ax, scale, channel_edges)
        return ax

    def plot_signal(self, ax, ylim=None, scale="log", channel_edges=True):
        """
        It plots the signal components found in the input table in the indicated axes.

        Parameters
        -----------
        ax: matplotlib.axes
            axes where to plot the signals
        ylim: float
            if present, it sets the axes y bottom lim. Default is None.

        Returns
        --------
        matplotlib.axes.axes

        Note
        ----
        The Class input_table input parameter is required for this method to work.
        """

        keys = [
            x
            for x in self.inputTable.keys()
            if "signal" in x and "noise" not in x
        ]
        self.debug("signal keys : {}".format(keys))
        for k, s in enumerate(keys):
            # ax.scatter(self.inputTable['Wavelength'], self.inputTable[s], label=s, zorder=10, s=5, color=palette[k])
            ax.plot(
                self.inputTable["Wavelength"],
                self.inputTable[s],
                zorder=9,
                lw=2,
                alpha=0.5,
                marker=".",
                label=s,
            )
            # color=palette[k])  # , c='None')

        if not ylim:
            ax.set_ylim(1e-1, 5e6)
        else:
            ax.set_ylim(ylim)
        #        ax.grid(zorder=0, which='both')
        locmaj = matplotlib.ticker.LogLocator(base=10, numticks=12)
        ax.yaxis.set_major_locator(locmaj)
        locmin = matplotlib.ticker.LogLocator(
            base=10.0, subs=(0.2, 0.4, 0.6, 0.8), numticks=12
        )
        ax.yaxis.set_minor_locator(locmin)
        ax.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
        ax.grid(axis="y", which="minor", alpha=0.3)
        ax.grid(axis="y", which="major", alpha=0.5)
        #        ax.legend(bbox_to_anchor=(1, 1))
        ax.legend(
            prop={"size": 14},
            loc="upper left",
            ncol=3,
            bbox_to_anchor=(0.05, -0.25),
            labelspacing=1.2,
            handlelength=1,
        )
        ax.set_title("Signals")
        ax.set_xlabel(r"Wavelength [$\mu m$]")
        ax.set_ylabel("$counts/s$")
        ax.set_yscale("log")
        # ax.set_xscale('log')
        ax = self.plot_bands(ax, scale, channel_edges)

        return ax

    def plot_table(
        self, sig_ylim=None, noise_ylim=None, scale="log", channel_edges=False
    ):
        """
        It produces a figure with signal and noise for the input table.

        Returns
        --------
        matplotlib.pyplot.figure
        (matplotlib.axes.axes, matplotlib.axes.axes)

        Note
        ----
        The Class input_table input parameter is required for this method to work.
        """
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 10))
        # fig.suptitle(self.inputTable.meta["name"])
        ax1 = self.plot_signal(
            ax1, ylim=sig_ylim, scale=scale, channel_edges=channel_edges
        )
        ax2 = self.plot_noise(
            ax2, ylim=noise_ylim, scale=scale, channel_edges=channel_edges
        )
        plt.tight_layout()
        plt.subplots_adjust(top=0.95, bottom=0.25, hspace=0.8)
        self.fig = fig
        return fig, (ax1, ax2)

    def save_fig(self, name, efficiency=False):
        """
        It saves the produced figure.

        Parameters
        --------
        name: str
            figure name
        efficiency: bool
            if True it wll save the efficiency plot instead of the table plot. Default is False.
        """
        try:
            if efficiency:
                self.fig_efficiency.savefig("{}".format(name))
            else:
                self.fig.savefig("{}".format(name))

            self.info("plot saved in {}".format(name))
        except AttributeError:
            self.error(
                "the indicated figure is not available. Check if you have produced it."
            )


def main():
    import argparse
    from exorad.__version__ import __version__
    from exorad.utils.util import parse_range

    parser = argparse.ArgumentParser(
        description="ExoRad {}".format(__version__)
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input",
        type=str,
        required=True,
        help="Input h5 file to pass",
    )
    parser.add_argument(
        "-o",
        "--out",
        dest="out",
        type=str,
        default="None",
        required=True,
        help="Output directory",
    )
    parser.add_argument(
        "-n",
        "--target-number",
        dest="target_number",
        type=str,
        default="all",
        required=False,
        help="A list or range of targets to run",
    )
    parser.add_argument(
        "-t",
        "--target-name",
        dest="target_name",
        type=str,
        default="None",
        required=False,
        help="name of the target to plot",
    )
    parser.add_argument(
        "-d",
        "--debug",
        dest="debug",
        default=False,
        required=False,
        help="log output on screen",
        action="store_true",
    )

    args = parser.parse_args()

    logger = logging.getLogger("exorad")
    from exorad.utils.ascii_art import ascii_plot

    logger.info(ascii_plot)
    logger.info("code version {}".format(__version__))

    if args.debug:
        setLogLevel(logging.DEBUG)

    if not os.path.exists(args.out):
        os.makedirs(args.out)
        logger.info("output directory created")

    logger.info("reading {}".format(args.input))
    file = h5py.File(args.input)

    if args.target_number != "all" and args.target_name != "None":
        logger.error("you cannot use both target number and target name")
        raise ValueError

    targets_dir = file["targets"]
    targets_to_run_id = parse_range(
        args.target_number, len(targets_dir.keys())
    )
    targets_to_run = [list(targets_dir.keys())[n] for n in targets_to_run_id]

    if args.target_name != "None":
        targets_to_run = [
            target for target in targets_to_run if target == args.target_name
        ]

    for target in targets_to_run:
        target_dir = targets_dir[target]
        table_dir = target_dir["table"]
        table = read_table_hdf5(table_dir, path="table")

        plotter = Plotter(input_table=table)
        plotter.plot_table()
        plotter.save_fig(os.path.join(args.out, "{}.png".format(target)))
        plt.close()
