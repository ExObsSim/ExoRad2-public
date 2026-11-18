import contextlib
import logging
import os
import pathlib
import shutil
import sys

import click
import matplotlib.pyplot as plt
from rich_click import RichCommand

import exorad.__version__ as version
import exorad.tasks as tasks
from exorad.log import addLogFile, setLogLevel
from exorad.output.hdf5 import HDF5Output
from exorad.tasks.targetHandler import check_unique_target_names
from exorad.utils.plotter import Plotter
from exorad.utils.version_control import VersionControl

logger = logging.getLogger("exorad")

NO_VERSION_CHECK_ENV = "EXORAD_NO_VERSION_CHECK"

preparePayload = tasks.PreparePayload()
mergeChannelsOutput = tasks.MergeChannelsOutput()
loadTargetList = tasks.LoadTargetList()
loadSource = tasks.LoadSource()
observeTarget = tasks.ObserveTarget()
observeTargetList = tasks.ObserveTargetlist()


def check_version():
    """
    Check online whether a newer ExoRad release exists (network access).

    Only tagged builds are checked: development checkouts are always "ahead"
    of the last release. The check is skipped when the environment variable
    ``EXORAD_NO_VERSION_CHECK`` is set to a non-empty value. It is run by the
    command-line entry point :func:`main`, never at ``import exorad``.
    """
    if os.environ.get(NO_VERSION_CHECK_ENV):
        return None
    current = version.__version__
    if "dev" in current or current == "unknown":
        return None
    return VersionControl(current_version=current)


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
        If False, raise a ``FileExistsError`` before any work is done if the
        output file exists. Default is True.

    Returns
    -------
    list of str
        Names of the targets that were skipped because they could not be
        observed (empty when every target succeeded). The good targets are
        written to the output file; a ``RuntimeError`` is raised only when no
        target could be observed. Callers that ignore the return value keep
        the previous behaviour.

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
    if output is not None and not replace and os.path.exists(output):
        # refuse before any work, copy or log file is made
        raise FileExistsError(
            f"output file {output} already exists: pass replace=True to overwrite it"
        )

    from exorad.utils.ascii_art import ascii_art

    logger.info(ascii_art)
    logger.info(f"code version {version.__version__}")

    if debug:
        setLogLevel(logging.DEBUG)
    if isinstance(log, str):
        addLogFile(fname=log)
    elif log:
        addLogFile()

    # load the target list first: duplicated names are refused before any
    # file or directory is created, so a bad list leaves nothing behind
    targets = loadTargetList(target_list=target_list)
    check_unique_target_names(targets.target)

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

    # step 2 targetlist (loaded above)
    # step 3 observe targetlist
    requested = [t.name for t in targets.target]
    observed = observeTargetList(
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
        for target in observed.values():
            if target is None:  # never write a failed target
                continue
            with HDF5Output(output, append=True) as out:
                target.write(out)
    return [name for name in requested if name not in observed]


_MAIN_HELP = f"""ExoRad {version.__version__} -- the generic point source radiometric model.

Run the standard pipeline: read the payload and the target list, propagate the
light through the optics, estimate the signal and noise budgets and write a
self-describing HDF5 file. When some targets cannot be observed the good ones
are still written, the skipped names are printed on stderr and the exit status
is 1.

\b
Examples:
  exorad -p payload.xml -t targets.csv -o results.h5
  exorad -p payload.xml -t targets.csv -o results.h5 -d -l -P
  exorad -p payload.xml -t targets.csv -o results.h5 -n 4
"""


@click.command(cls=RichCommand, help=_MAIN_HELP)
@click.version_option(
    version=version.__version__,
    prog_name="ExoRad",
    message="%(prog)s v%(version)s",
)
@click.option(
    "-p",
    "--payload",
    "options",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Input payload description file (XML).",
)
@click.option(
    "-t",
    "--targetList",
    "--target-list",
    "target_list",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Input target list file (CSV / XLSX / ECSV).",
)
@click.option(
    "-o",
    "--output",
    "output",
    default=None,
    type=click.Path(dir_okay=False),
    help="Output HDF5 file. If omitted, nothing is written to disk.",
)
@click.option(
    "-c",
    "--full-contrib",
    "--full_contrib",
    "full_contrib",
    is_flag=True,
    help="Include the per-optical-element contribution tables in the output.",
)
@click.option(
    "-n",
    "--nThreads",
    "--n-threads",
    "n_thread",
    type=int,
    default=1,
    show_default=True,
    help="Number of threads for parallel target processing.",
)
@click.option(
    "-d",
    "--debug",
    is_flag=True,
    help="Print debug-level logging to the screen.",
)
@click.option(
    "-l",
    "--log",
    is_flag=True,
    help="Also write the log to a file.",
)
@click.option(
    "-P",
    "--plot",
    is_flag=True,
    help="Save the per-target diagnostic plots next to the output.",
)
def main(options, target_list, output, full_contrib, n_thread, debug, log, plot):
    """
    Command-line interface entry point for ExoRad (``exorad`` console script).

    The online version check runs first (opt-out: ``EXORAD_NO_VERSION_CHECK``),
    then the standard pipeline. The process exits with status 1 (after the
    good targets were written) when one or more targets were skipped, and
    with a non-zero status when the run fails; status 0 means every target
    was observed.
    """
    check_version()

    skipped = standard_pipeline(
        options=options,
        target_list=target_list,
        output=output,
        plot=plot,
        full_contrib=full_contrib,
        debug=debug,
        n_thread=n_thread,
        log=log,
    )
    if skipped:
        # a batch script must notice a partial run: the good targets are
        # already written, but the exit status is not 0
        sys.stderr.write(
            f"exorad: {len(skipped)} target(s) skipped: {', '.join(skipped)}\n"
        )
        sys.exit(1)
