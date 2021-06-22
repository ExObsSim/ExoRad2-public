from astropy.io.misc.hdf5 import read_table_hdf5

from exorad.models.instruments import Photometer, Spectrometer
from exorad.output.hdf5 import load
from .task import Task

instruments = {'photometer': Photometer,
               'spectrometer': Spectrometer}


class BuildInstrument(Task):
    """
    Initialize and build an instrument

    Parameters
    ----------
    type: str
        instrument class
    name: str
        instrument name
    description: dict
        instrument description dictionary
    payload: dict
        main payload. Default is None
    write: bool
        set to True to write the built dict to file. Default is None
    output: str
        output object

    Returns
    -------
    Instrument:
        return the built instrument class

    Raises
    ------
        KeyError
            if the indicated instrument class is not supported

    Examples
    --------
    >>> buildInstrument = BuildInstrument()
    >>> instrument = buildInstrument(type='photometer', name='Phot',
    >>>                              description=payload['channel']['Phot'],
    >>>                              payload=payload, write=False, output=None)
    """

    def __init__(self):
        self.addTaskParam('type', 'instrument type')
        self.addTaskParam('name', 'instrument name')
        self.addTaskParam('description', 'instrument description dictionary')
        self.addTaskParam('payload', 'main payload. Default is None')
        self.addTaskParam('write', 'write processed instrument to output file')
        self.addTaskParam('output', 'output object')

    def execute(self):
        try:
            instrumentClass = instruments[self.get_task_param('type')]
        except KeyError:
            self.error('invalid instrument class')
            raise ValueError
        instrument = instrumentClass(self.get_task_param('name'),
                                     self.get_task_param('description'),
                                     self.get_task_param('payload'))
        instrument.build()
        if self.get_task_param('write'):
            instrument.write(self.get_task_param('output'))
        self.set_output(instrument)


class BuildChannels(Task):
    """
    Initialize and build all the channels in the payload

    Parameters
    ----------
    payload: dict
        main payload. Default is None
    write: bool
        set to True to write the built dict to file. Default is None
    output: str
        output object
    Returns
    -------
    dict:
        return a dict of built Instrument classes

    Examples
    --------
    >>> buildChannels = BuildChannels()
    >>> channels = buildChannels(payload=payload, write=False, output=None)
    """

    def __init__(self):
        self.addTaskParam('payload', 'main payload')
        self.addTaskParam('write', 'write processed instrument to output file')
        self.addTaskParam('output', 'output object')

    def execute(self):
        self.info('building channel')
        channels = {}
        self.debug('detectors found : {}'.format(
            self.get_task_param('payload')['channel'].keys()))

        ch = None
        if self.get_task_param('write'):
            inst = self.get_task_param('output').create_group('payload')
            inst.store_dictionary(self.get_task_param('payload'),
                                  group_name='payload description')
            ch = inst.create_group('channels')

        buildInstrument = BuildInstrument()
        for det in self.get_task_param('payload')['channel'].keys():
            channel_type = \
            self.get_task_param('payload')['channel'][det]['channelClass'][
                'value'].lower()
            channels[det] = buildInstrument(type=channel_type, name=det,
                                            description=
                                            self.get_task_param('payload')[
                                                'channel'][det],
                                            payload=self.get_task_param(
                                                'payload'),
                                            write=False,
                                            output=None)
            if self.get_task_param('write'):
                channels[det].write(ch)
        self.debug('channels : {}'.format(channels))
        self.set_output(channels)


class LoadPayload(Task):
    """
    Loads payload and channels from dict

    Parameters
    ----------
    input: dict
        main dictionary


    Returns
    -------
    dict:
        payload dict
    dict:
        return a dict of built Instrument classes

    Examples
    --------
    >>> loadPayload = LoadPayload()
    >>> channels = loadPayload(input=input)
    """

    def __init__(self):
        self.addTaskParam('input', 'input data')

    def execute(self):
        payload_dir = self.get_task_param('input')['payload']
        payload = load(payload_dir['payload description'])
        channels_dir = payload_dir['channels']
        channels = {}
        for ch in channels_dir.keys():
            ch_dir = channels_dir[ch]
            description = load(ch_dir['description'])
            instrument = instruments[
                description['channelClass']['value'].lower().decode("utf-8")]
            channels[ch] = instrument(name=ch,
                                      description=description,
                                      payload=payload,
                                      )
            table = read_table_hdf5(ch_dir, path=ch)
            built_instr = load(ch_dir['built_instr'])
            channels[ch].load(table, built_instr)
        self.debug('channels loaded: {}'.format(channels))
        self.set_output([payload, channels])


class PreparePayload(Task):
    """
    It loads the payload information and returns a dictionary containing the payload,
    a dictionary with the channels already built,
    and a couple with minimum and maximum wavelength investigated by the payload

    Parameters
    ----------
    payload_file: str
        xml file with payload description
    output: str
        h5 output file

    Returns
    -------

    dict:
        payload dictionary
    dict:
        channels dictionary
    couple:
        minimum and maximum investigated wavelength

    Examples
    --------
    >>> preparePayload = PreparePayload()
    >>> payload, channels, (wl_min, wl_max) = PreparePayload(payload_file=payload, output=output)

    """

    def __init__(self):
        self.addTaskParam('payload_file', 'payload xml file')
        self.addTaskParam('output', 'output file')

    def execute(self):
        import os
        from exorad.tasks import LoadOptions
        from exorad.output.hdf5 import HDF5Output

        loadOptions = LoadOptions()
        buildChannels = BuildChannels()
        loadPayload = LoadPayload()

        payload_file = self.get_task_param('payload_file')
        output = self.get_task_param('output')

        if isinstance(payload_file, str):
            ext = os.path.splitext(payload_file)[1]
        else:
            ext = None

        if (ext == '.xml') or isinstance(payload_file, dict):
            if (ext == '.xml'):
                payload = loadOptions(filename=payload_file)
            if isinstance(payload_file, dict):
                payload = payload_file
            if output is not None:
                with HDF5Output(output) as out:
                    channels = buildChannels(payload=payload, write=True,
                                             output=out)
            else:
                channels = buildChannels(payload=payload, write=False,
                                         output=None)

        elif ext == 'h5':
            payload, channels = loadPayload(input=payload_file)
        else:
            self.error('Unsupported payload format')
            raise IOError('Unsupported payload format')
        wl_min, wl_max = payload['common']['wl_min']['value'], \
                         payload['common']['wl_max']['value']
        self.set_output([payload, channels, (wl_min, wl_max)])


class MergeChannelsOutput(Task):
    """
    Merges the channels output tables

    Parameters
    ----------
    channels: dict

    Returns
    ---------
    Table
    """

    def __init__(self):
        self.addTaskParam('channels', 'dict of channels')

    def execute(self):
        from exorad.utils.util import vstack_tables
        channels = self.get_task_param('channels')
        table_list = []
        for channel in channels.keys():
            table_list.append(channels[channel].table)
        table = vstack_tables(table_list)
        self.set_output(table)


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
        self.info('{} type channel found: {}'.format(self._channel_type,
                                                     self.channel_lst))
        self.set_output(self.channel_lst)

    def __get_channel_list__(self):
        channel_lst = []
        for channel in self._opt['channel'].keys():
            if self._opt['channel'][channel]['channelClass'][
                'value'].lower() == self._channel_type.lower():
                channel_lst.append(channel)
                self.debug(
                    '{} added as {}'.format(channel, self._channel_type))
        return channel_lst
