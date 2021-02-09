import os
from copy import deepcopy
from exorad.__version__ import __version__
from exorad.cache import GlobalCache
from exorad.log import disableLogging, enableLogging
from ..models.targetlist import XLXSTargetList, CSVTargetList, QTableTargetList
from .task import Task


class LoadTargetList(Task):
    """
    Loads target list from file

    Parameters
    ----------
    target_list: str
        target list file address. Supported formats are csv and xml


    Returns
    -------
    TargetList:
        return a list of Target class

    Examples
    --------
    >>> loadTargetList = LoadTargetList()
    >>> targets = loadTargetList(target_list='target_list/address')
    """

    def __init__(self):
        self.addTaskParam('target_list', 'target list file name')

    def execute(self):
        target_list_file = self.get_task_param('target_list')
        self.info('target list file : {}'.format(target_list_file))

        target_list_format = {".xlsx": XLXSTargetList,
                              ".csv": CSVTargetList,
                              }

        try:
            ext = os.path.splitext(target_list_file)[1]
            self.debug('target list format : {}'.format(ext))
            target_klass = target_list_format[ext]
        except KeyError:
            self.error('unsupported target list format: {}'.format(ext))
            raise IOError('unsupported target list format: {}'.format(ext))
        except TypeError:
            self.debug('target list is not a file. It is assumed to be QTable')
            target_klass = QTableTargetList

        tt = target_klass(target_list_file)
        self.set_output(tt)


class PrepareTarget(Task):
    """
    Prepares the target output table over the channels to populate with light propagation

    Parameters
    ----------
    target: Target
        target to prepare
    channels : dict
        channel dictionary

    Returns
    -------
    Target:
        same target with table attribute populated
    """

    def __init__(self):
        self.addTaskParam('target', 'target to prepare')
        self.addTaskParam('channels', 'channels dictionary')

    def execute(self):
        from . import MergeChannelsOutput

        target = self.get_task_param('target')
        channels = self.get_task_param('channels')

        mergeChannelsOutput = MergeChannelsOutput()
        table = mergeChannelsOutput(channels=channels)
        table = self.add_metadata(table, target)
        target.table = table
        self.set_output(target)

    def add_metadata(self, table, target):
        table.meta['name'] = target.name
        table.meta['ExoRad version'] = __version__
        return table


class UpdateTargetTable(Task):
    """
    Updated the target output table over the channels to populate with light propagation

    Parameters
    ----------
    target: Target
        target to prepare
    table : QTable
        table to merge in the target table

    Returns
    -------
    Target:
        same target with table attribute updated
    """

    def __init__(self):
        self.addTaskParam('target', 'target to prepare')
        self.addTaskParam('table', 'table to merge in the target table')

    def execute(self):
        from astropy.table import hstack
        self.info('updating target table')
        target = self.get_task_param('target')
        target_table = target.table
        table = self.get_task_param('table')

        repeated_keys = [key for key in target_table.keys() if key in table.keys()]
        if repeated_keys:
            self.debug('the following keys are already in both table and will be replaced : {}'.format(repeated_keys))
            target.table.remove_columns(repeated_keys)
        target.table = hstack([target_table, table])
        target.table.meta.update(table.meta)
        self.set_output(target)


class EstimateMaxSignal(Task):
    """
    Updated the target output table with maximum estimated signal in pix column

    Parameters
    ----------
    target: Target
        target to prepare

    Returns
    -------
    Target:
        same target with table attribute updated
    """

    def __init__(self):
        self.addTaskParam('target', 'target to prepare')

    def execute(self):
        import numpy as np
        import astropy.units as u
        from astropy.table import QTable
        updateTargetTable = UpdateTargetTable()

        self.info('estimating max signal in pixel')
        target = self.get_task_param('target')
        table = target.table
        signals = [key for key in table.keys() if 'Max' in key]
        max_signal = np.zeros(table['Wavelength'].size) * u.count / u.s
        for key in signals:
            max_signal += table[key]
        new_tab = QTable()
        new_tab['MaxSignal_inPixel'] = max_signal
        new_target = updateTargetTable(target=target, table=new_tab)
        self.set_output(new_target)


class ObserveTarget(Task):
    """
    Standard pipeline for target observation. It includes:
    1. PrepareTarget,
    2. EstimateForegrounds,
    3. PropagateForegroundLight
    4. LoadSource
    5. PropagateTargetLight
    6. EstimateNoise

    Parameters
    ----------
    target: Target
        target to prepare
    payload : dict
        payload description
    channels : dict
        channel dictionary
    wl_range: (float, float)
        wavelength range to investigate. (wl_min, wl_max)

    Returns
    -------
    Target:
        same target with table attribute updated
    """

    def __init__(self):
        self.addTaskParam('target', 'target to prepare')
        self.addTaskParam('payload', 'payload description')
        self.addTaskParam('channels', 'channel dictionary')
        self.addTaskParam('wl_range', 'wavelength range to investigate. (wl_min, wl_max)')

    def execute(self):
        target = self.get_task_param('target')
        payload = self.get_task_param('payload')
        channels = self.get_task_param('channels')
        wl_min, wl_max = self.get_task_param('wl_range')

        from . import PrepareTarget, PropagateTargetLight, \
            EstimateForegrounds, PropagateForegroundLight, EstimateNoise, LoadSource
        prepareTarget = PrepareTarget()
        propagateTargetLight = PropagateTargetLight()
        loadSource = LoadSource()
        estimateForegrounds = EstimateForegrounds()
        propagateForegroundLight = PropagateForegroundLight()
        estimateNoise = EstimateNoise()

        target = prepareTarget(target=target, channels=channels)

        if 'foreground' in payload['common']:
            target = estimateForegrounds(foregrounds=payload['common']['foreground'],
                                         target=target,
                                         wl_range=(wl_min, wl_max))
        target = propagateForegroundLight(channels=channels, target=target)

        target, sed = loadSource(target=target,
                                 source=payload['common']['sourceSpectrum'],
                                 wl_range=(wl_min, wl_max))
        target = propagateTargetLight(channels=channels, target=target)

        target = estimateNoise(target=target, channels=channels)

        self.set_output(target)


class ObserveTargetlist(Task):
    """
    Standard pipeline to observe a full targetlist. It allows parallelization:

    Parameters
    ----------
    targets: Target
        targets to prepare
    payload : dict
        payload description
    channels : dict
        channel dictionary
    wl_range: (float, float)
        wavelength range to investigate. (wl_min, wl_max)
    plot: bool
        allow to save plots
    out_dir: str
        indicate the directory where to save plots

    Returns
    -------
    dict:
        targets dict
    """

    def __init__(self):
        self.addTaskParam('targets', 'targets to prepare')
        self.addTaskParam('payload', 'payload description')
        self.addTaskParam('channels', 'channel dictionary')
        self.addTaskParam('wl_range', 'wavelength range to investigate. (wl_min, wl_max)')
        self.addTaskParam('plot', 'allow to save plots')
        self.addTaskParam('out_dir', 'indicate the directory where to save plots')

    def execute(self):
        from exorad.utils.util import chunks
        import multiprocessing as mp
        try:
            mp.set_start_method('fork')
        except RuntimeError:
            pass

        targets = self.get_task_param('targets')

        manager = mp.Manager()
        outputDict = manager.dict()
        for tt in chunks(targets, GlobalCache()['n_thread']):
            job = [mp.Process(target=self.pipeline_to_dict, args=(target, outputDict)) for target in tt]
            for j in job:
                j.start()
            for j in job:
                j.join()
        self.set_output(outputDict)

    def pipeline_to_dict(self,  target, outputDict):
        from . import ObserveTarget
        from exorad.utils.plotter import Plotter
        import matplotlib.pyplot as plt
        import matplotlib
        matplotlib.use('Agg')

        payload = self.get_task_param('payload')
        channels = self.get_task_param('channels')
        wl_range = self.get_task_param('wl_range')
        plot = self.get_task_param('plot')
        out_dir = self.get_task_param('out_dir')
        observeTarget = ObserveTarget()

        self.info('observing {}'.format(target.name))
        if not GlobalCache()['debug']: disableLogging()
        try:
            target = observeTarget(target=target, payload=payload, channels=channels, wl_range=wl_range)
            enableLogging()
            outputDict[target.name] = deepcopy(target)

            if plot:
                plotter = Plotter(input_table=target.table)
                plotter.plot_table()
                plotter.save_fig(os.path.join(out_dir, '{}.png'.format(target.name)))
                plt.close()

        except:
            enableLogging()
            self.warning('target {} skipped. Please check for previous error messages'.format(target.name))
