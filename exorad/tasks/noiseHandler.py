from .task import Task


class EstimateNoiseInChannel(Task):
    """

    Parameters
    ----------
    target: Target
        target to prepare
    channel : dict
        channel to analyse
    payload : dict
        payload description

    Returns
    -------
    Target:
        same target with table attribute updated
    """

    def __init__(self):
        self.addTaskParam('target', 'target to prepare')
        self.addTaskParam('channel', 'channel to analyse')
        self.addTaskParam('payload', 'payload common section')

    def execute(self):
        from exorad.models import noise
        import numpy as np
        import astropy.units as u
        from astropy.table import QTable
        channel = self.get_task_param('channel')
        target = self.get_task_param('target')
        payload = self.get_task_param('payload')

        name = channel['value']
        self.info('estimating noise in {}'.format(name))

        out = QTable()
        out = noise.frame_time(target, channel, out)
        read_gain, shot_gain = noise.multiaccum(channel, out['frameTime'][0])
        self.debug('read gain : {} , shot gain : {}'.format(read_gain, shot_gain))

        out = noise.photon_noise(target.table, channel, shot_gain, out)

        out['darkcurrent_noise'] = np.sqrt(shot_gain * target.table['WindowSize'][target.table['chName'] == name] *
                                           channel['detector']['dark_current']['value'] * u.ct / u.hr).to(
            u.ct / u.s) * u.hr ** 0.5
        self.debug('dark current noise : {}'.format(out['darkcurrent_noise']))
        out['read_noise'] = np.sqrt(
            read_gain * channel['detector']['read_noise']['value'] ** 2 *
            target.table['WindowSize'][target.table['chName'] == name] / out['frameTime'] * 1 / u.hr).to(
            u.ct / u.s) * u.hr ** 0.5
        self.debug('read noise : {}'.format(out['read_noise']))

        if 'NoiseX' in channel:
            NoiseX = channel['NoiseX']['value']
        else:
            NoiseX = 0.0
        self.debug('NoiseX: {}'.format(NoiseX))

        photon_noise_variance = noise.photon_noise_variance(target.table, out)
        signal = target.table['star_signal_inAperture'][target.table['chName'] == name].copy()
        signal[signal == 0.0] = np.nan
        out['total_noise'] = np.sqrt(
                                out['darkcurrent_noise'] ** 2 +
                                (1.0 + NoiseX) *
                                (photon_noise_variance) +
                                out['read_noise'] ** 2
                            ) / signal

        wl = target.table['Wavelength'][target.table['chName'] == name]
        if payload:
            try:
                out = noise.add_custom_noise(payload['common']['customNoise'], wl, out)
            except KeyError:
                self.debug('no custom noise found in common section')
        try:
            out = noise.add_custom_noise(channel['customNoise'], wl, out)
        except KeyError:
            self.debug('no custom noise found in channel section')

        self.debug('total noise : {}'.format(out['total_noise']))

        self.set_output(out)


class EstimateNoise(Task):
    """

    Parameters
    ----------
    target: Target
        target to prepare
    channels : dict
        channel list to analyse

    Returns
    -------
    Target:
        same target with table attribute updated
    """

    def __init__(self):
        self.addTaskParam('target', 'target to prepare')
        self.addTaskParam('channels', 'channel list to analyse')

    def execute(self):
        from exorad.utils.util import vstack_tables
        from exorad.tasks import UpdateTargetTable
        from exorad.tasks import EstimateMaxSignal

        estimateMaxSignal = EstimateMaxSignal()
        estimateNoiseInChannel = EstimateNoiseInChannel()
        updateTargetTable = UpdateTargetTable()

        self.info('computing noise')
        target = self.get_task_param('target')
        channels = self.get_task_param('channels')

        target = estimateMaxSignal(target=target)

        table_list = []
        for ch in self.get_task_param('channels'):
            self.debug('computing noise in {}'.format(ch))
            table_list.append(
                estimateNoiseInChannel(target=target, channel=channels[ch].description, payload=channels[ch].payload))
        table = vstack_tables(table_list)
        new_target = updateTargetTable(target=target, table=table)
        self.set_output(new_target)
