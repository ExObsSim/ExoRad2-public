from .targetHandler import UpdateTargetTable
from .task import Task


class PropagateTargetLight(Task):
    """
     Given the target and a channel dict, it propagates the target light over the channels

     Parameters
     ----------
     channels: dict
         main payload. Default is None
     target: Target

     Returns
     -------
     QTable:
         return the output table of propagated signal

     Examples
     --------

     """

    def __init__(self):
        self.addTaskParam('channels', 'payload channels dict')
        self.addTaskParam('target', 'Target class to observe')

    def execute(self):
        self.info('propagating target light')
        from exorad.utils.util import vstack_tables
        target = self.get_task_param('target')
        channels = self.get_task_param('channels')
        self.debug('detectors found : {}'.format(channels.keys()))
        table_list = []
        for ch in self.get_task_param('channels'):
            self.debug('propagating target in {}'.format(ch))
            table_list.append(channels[ch].propagate_target(target))
        table = vstack_tables(table_list)
        updateTargetTable = UpdateTargetTable()
        target = updateTargetTable(target=target, table=table)
        self.set_output(target)


class PropagateForegroundLight(Task):
    """
     Given the target and a channel dict, it propagates the target foreground light over the channels

     Parameters
     ----------
     channels: dict
         main payload. Default is None
     target: Target

     Returns
     -------
     QTable:
         return the output table of propagated signal

     Examples
     --------

     """

    def __init__(self):
        self.addTaskParam('channels', 'payload channels dict')
        self.addTaskParam('target', 'Target class to observe')

    def execute(self):
        self.info('propagating target foreground light')
        from exorad.utils.util import vstack_tables
        target = self.get_task_param('target')
        channels = self.get_task_param('channels')
        self.debug('detectors found : {}'.format(channels.keys()))
        table_list = []
        for ch in self.get_task_param('channels'):
            self.debug('propagating target background in {}'.format(ch))
            table_list.append(channels[ch].propagate_diffuse_foreground(target))
        table = vstack_tables(table_list)
        updateTargetTable = UpdateTargetTable()
        target = updateTargetTable(target=target, table=table)
        self.set_output(target)
