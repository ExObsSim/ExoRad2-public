import contextlib
import logging
import os
import pathlib
import shutil

import matplotlib.pyplot as plt

import exorad.__version__ as version
import exorad.tasks as tasks
from exorad.log import addLogFile, setLogLevel
from exorad.output.hdf5 import HDF5Output
from exorad.utils.plotter import Plotter

logger = logging.getLogger("exorad")

preparePayload = tasks.PreparePayload()
mergeChannelsOutput = tasks.MergeChannelsOutput()
loadTargetList = tasks.LoadTargetList()
loadSource = tasks.LoadSource()
observeTarget = tasks.ObserveTarget()
observeTargetList = tasks.ObserveTargetlist()


def efficiency_plot(channels, output_dir=None):
    """
    Generate and display or save the payload efficiency plot.

    This function creates a plot showing the quantum efficiency, transmission,
    and photon conversion efficiency (PCE) of the payload channels.

    Parameters
    ----------
    channels : dict
        Dictionary containing the channel objects with their efficiency data.
    output_dir : str, optional
        Directory path where the plot will be saved as 'efficiency.png'.
        If None, the plot is displayed interactively. Default is None.

    Returns
    -------
    None

    Notes
    -----
    The plot is automatically closed after being displayed or saved to prevent
    memory accumulation in batch processing scenarios.

    Examples
    --------
    >>> efficiency_plot(channels, output_dir="/path/to/output")
    """
    table = mergeChannelsOutput(channels=channels)
    plotter = Plotter(channels=channels, input_table=table)
    plotter.plot_efficiency()
    if output_dir is None:
        plt.show()
    else:
        plotter.save_fig(os.path.join(output_dir, "efficiency.png"), efficiency=True)
        logger.info("efficiency plot saved in output directory")
    plt.close()


def standard_pipeline(
    options,
    target_list,
    output=None,
    plot=False,
    full_contrib=False,
    n_thread=1,
    debug=False,
    log=False,
    replace=True,
):
    """
    Execute the complete ExoRad radiometric analysis pipeline.

    This function orchestrates the full workflow of ExoRad, including:
    1. Loading and preparing the payload configuration
    2. Loading the target list
    3. Propagating light through the optical system
    4. Computing noise sources
    5. Generating output files and diagnostic plots

    Parameters
    ----------
    options : str
        Path to the payload description file (XML or HDF5 format).
    target_list : str
        Path to the target list file containing observation parameters.
    output : str, optional
        Path to the output HDF5 file. If None, no file is written.
        Default is None.
    plot : bool, optional
        If True, generate and save diagnostic plots for each target.
        Default is False.
    full_contrib : bool, optional
        If True, include detailed contribution tables from each optical
        element in the output. Default is False.
    n_thread : int, optional
        Number of threads for parallel target processing. Default is 1.
    debug : bool, optional
        If True, enable debug-level logging. Default is False.
    log : bool or str, optional
        If True, create a log file in the current directory.
        If a string is provided, use it as the log file path.
        If False, logging is only to console. Default is False.
    replace : bool, optional
        If True, replace existing output file if it exists.
        If False, raise an error if output file exists. Default is True.

    Returns
    -------
    None
        Results are written to the output file specified.

    Notes
    -----
    The function copies the input files (options and target_list) to the
    output directory for reproducibility and traceability.

    The pipeline uses multiprocessing when n_thread > 1 to process multiple
    targets in parallel, significantly reducing computation time for large
    target lists.

    Examples
    --------
    Basic usage with single target:

    >>> standard_pipeline(
    ...     options="payload.xml",
    ...     target_list="targets.csv",
    ...     output="results.h5",
    ... )

    Advanced usage with plotting and debug mode:

    >>> standard_pipeline(
    ...     options="payload.xml",
    ...     target_list="targets.csv",
    ...     output="results.h5",
    ...     plot=True,
    ...     debug=True,
    ...     log="pipeline.log",
    ...     n_thread=4,
    ... )

    See Also
    --------
    PreparePayload : Task for loading payload configuration
    LoadTargetList : Task for loading target list
    ObserveTargetlist : Task for processing all targets
    """
    from exorad.utils.ascii_art import ascii_art

    logger.info(ascii_art)
    logger.info(f"code version {version.__version__}")

    if debug:
        setLogLevel(logging.DEBUG)
    if isinstance(log, str):
        addLogFile(fname=log)
    elif log:
        addLogFile()

    if output is not None:
        if replace and os.path.exists(output):
            os.remove(output)

        out_dir = pathlib.Path(output).parent.absolute()
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
            logger.info("output directory created")
        logger.info(f"output directory set as {out_dir}")
        with contextlib.suppress(shutil.SameFileError):
            shutil.copy(options, out_dir)
        with contextlib.suppress(shutil.SameFileError):
            shutil.copy(target_list, out_dir)
    else:
        out_dir = None

    # step 1 load payload
    payload, channels, (wl_min, wl_max) = preparePayload(
        payload_file=options, output=output
    )
    if full_contrib:
        from astropy.table import hstack

        for ch in channels:
            channels[ch].table = hstack(
                [
                    channels[ch].table,
                    channels[ch].built_instr["optical_path"]["signal_table"],
                ]
            )
            channels[ch].table.remove_column("instrument_signal")

    # step 1b plot payload efficiency
    if plot:
        efficiency_plot(channels=channels, output_dir=out_dir)

    # step 2 load targetlist
    targets = loadTargetList(target_list=target_list)

    # step 3 observe targetlist
    targets = observeTargetList(
        targets=targets.target,
        payload=payload,
        channels=channels,
        wl_range=(wl_min, wl_max),
        plot=plot,
        out_dir=out_dir,
        n_thread=n_thread,
        debug=debug,
    )
    # step 4 save to output
    if output is not None:
        for target in targets:
            with HDF5Output(output, append=True) as out:
                targets[target].write(out)


def main():
    """
    Command-line interface entry point for ExoRad.

    This function parses command-line arguments and executes the standard
    ExoRad pipeline. It is the main entry point when ExoRad is run from
    the command line.

    Returns
    -------
    None

    Notes
    -----
    This function is registered as a console script entry point in setup.py.
    It can be invoked directly from the command line after installation:

        $ exorad -p payload.xml -t targets.csv -o output.h5

    For detailed usage information, run:

        $ exorad --help

    Examples
    --------
    Run ExoRad from command line with basic options:

    .. code-block:: bash

        exorad -p payload.xml -t targets.csv -o results.h5

    Run with debugging and plotting enabled:

    .. code-block:: bash

        exorad -p payload.xml -t targets.csv -o results.h5 -d -P -l

    Run with multiple threads:

    .. code-block:: bash

        exorad -p payload.xml -t targets.csv -o results.h5 -n 4
    """
    import argparse

    parser = argparse.ArgumentParser(description=f"ExoRad {version}")
    parser.add_argument(
        "-p",
        "--payload",
        dest="opt",
        type=str,
        required=True,
        help="Input payload description file to pass",
    )
    parser.add_argument(
        "-t",
        "--targetList",
        dest="targetList",
        type=str,
        required=True,
        help="Input target list file to pass",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        type=str,
        required=False,
        default=None,
        help="Output file",
    )
    parser.add_argument(
        "-c",
        "--full_contrib",
        dest="contrib",
        default=False,
        required=False,
        help="produce full contribution output",
        action="store_true",
    )
    parser.add_argument(
        "-n",
        "--nThreads",
        dest="numberOfThreads",
        default=1,
        type=int,
        required=False,
        help="number of threads for parallel processing",
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
    parser.add_argument(
        "-l",
        "--log",
        dest="log",
        default=False,
        required=False,
        help="log output on file",
        action="store_true",
    )
    parser.add_argument(
        "-P",
        "--plot",
        dest="plot",
        default=False,
        required=False,
        help="save target plots",
        action="store_true",
    )

    args = parser.parse_args()

    standard_pipeline(
        options=args.opt,
        target_list=args.targetList,
        output=args.output,
        plot=args.plot,
        full_contrib=args.contrib,
        debug=args.debug,
        n_thread=args.numberOfThreads,
        log=args.log,
    )
