import logging
import os
import pathlib
import shutil

import matplotlib.pyplot as plt

import exorad.__version__ as version
import exorad.tasks as tasks
from exorad.cache import GlobalCache
from exorad.log import setLogLevel, addLogFile
from exorad.output.hdf5 import HDF5Output
from exorad.utils.plotter import Plotter

logger = logging.getLogger('exorad')

preparePayload = tasks.PreparePayload()
mergeChannelsOutput = tasks.MergeChannelsOutput()
loadTargetList = tasks.LoadTargetList()
loadSource = tasks.LoadSource()
observeTarget = tasks.ObserveTarget()
observeTargetList = tasks.ObserveTargetlist()


def efficiency_plot(channels, output_dir=None):
    table = mergeChannelsOutput(channels=channels)
    plotter = Plotter(channels=channels, input_table=table)
    plotter.plot_efficiency()
    if output_dir is None:
        plt.show()
    else:
        plotter.save_fig(os.path.join(output_dir, 'efficiency.png'), efficiency=True)
        logger.info('efficiency plot saved in output directory')
    plt.close()


def standard_pipeline(options, target_list, output=None, plot=False, full_contrib=False,
                      n_thread=1, debug=False, log=False):
    from exorad.utils.ascii_art import ascii_art
    logger.info(ascii_art)
    logger.info('code version {}'.format(version))

    gc = GlobalCache()
    gc['n_thread'] = n_thread
    gc['debug'] = debug

    if debug: setLogLevel(logging.DEBUG)
    if isinstance(log, str): addLogFile(fname=log)
    elif log: addLogFile()

    if output is not None:
        out_dir = pathlib.Path(output).parent.absolute()
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
            logger.info('output directory created')
        logger.info('output directory set as {}'.format(out_dir))
        try:
            shutil.copy(options, out_dir)
        except shutil.SameFileError:
            pass
        try:
            shutil.copy(target_list, out_dir)
        except shutil.SameFileError:
            pass
    else:
        out_dir = None

    # step 1 load payload
    payload, channels, (wl_min, wl_max) = preparePayload(payload_file=options,
                                                         output=output)
    if full_contrib:
        from astropy.table import hstack
        for ch in channels:
            channels[ch].table = hstack([channels[ch].table, channels[ch].built_instr['optical_path']['signal_table']])
            channels[ch].table.remove_column('instrument_signal')

    # step 1b plot payload efficiency
    if plot:
        efficiency_plot(channels=channels, output_dir=out_dir)

    # step 2 load targetlist
    targets = loadTargetList(target_list=target_list)

    # step 3 observe targetlist
    targets = observeTargetList(targets=targets.target, payload=payload, channels=channels, wl_range=(wl_min, wl_max),
                                plot=plot, out_dir=out_dir)
    # step 4 save to output
    if output is not None:
        for target in targets:
            with HDF5Output(output, append=True) as out:
                targets[target].write(out)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='ExoRad {}'.format(version))
    parser.add_argument("-p", "--payload", dest='opt', type=str,
                        required=True, help="Input payload description file to pass")
    parser.add_argument("-t", "--targetList", dest='targetList', type=str,
                        required=True, help="Input target list file to pass")
    parser.add_argument("-o", "--output", dest='output', type=str,
                        required=False, default=None, help="Output file")
    parser.add_argument("-c", "--full_contrib", dest='contrib', default=False,
                        required=False, help="produce full contribution output", action='store_true')
    parser.add_argument("-n", "--nThreads", dest='numberOfThreads', default=1, type=int,
                        required=False, help="number of threads for parallel processing")
    parser.add_argument("-d", "--debug", dest='debug', default=False,
                        required=False, help="log output on screen", action='store_true')
    parser.add_argument("-l", "--log", dest='log', default=False,
                        required=False, help="log output on file", action='store_true')
    parser.add_argument("-P", "--plot", dest='plot', default=False,
                        required=False, help="save target plots", action='store_true')

    args = parser.parse_args()

    standard_pipeline(options=args.opt, target_list=args.targetList,
                      output=args.output, plot=args.plot, full_contrib=args.contrib,
                      debug=args.debug, n_thread=args.numberOfThreads, log=args.log)
