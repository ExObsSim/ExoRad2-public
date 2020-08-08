from exorad.tasks.task import Task


class GetChannelList(Task):
    """
    Returns a list of the channels of the specific type that are contained in the instrument options file

    Parameters
    ----------
    options: object
        payload description
    channel_type: string
        type of channel to find

    Returns
    -------
    list:
        list of strings with channel names

    Examples
    --------
    >>> from exorad.tasks.loadOptions import LoadOptions
    >>> loadOptions = LoadOptions()
    >>> options = loadOptions(filename = 'path/to/file.xml')
    >>> getDetectorList = GetChannelList()
    >>> photometers_list = getDetectorList(options = options, channel_type = 'Photometer')
    >>> spectrometers_list = getDetectorList(options = options, channel_type = 'Spectrometer')
    """

    def __init__(self):
        self.addTaskParam('options', 'instrument description class')
        self.addTaskParam('channel_type', 'desired channel type')

    def execute(self):
        self._opt = self.get_task_param('options')
        self._channel_type = self.get_task_param('channel_type')
        self.channel_lst = self.__get_channel_list__()
        self.info('{} type channel found: {}'.format(self._channel_type, self.channel_lst))
        self.set_output(self.channel_lst)

    def __get_channel_list__(self):
        channel_lst = []
        for channel in self._opt['channel'].keys():
            if self._opt['channel'][channel]['channelClass']['value'].lower() == self._channel_type.lower():
                channel_lst.append(channel)
                self.debug('{} added as {}'.format(channel, self._channel_type))
        return channel_lst
