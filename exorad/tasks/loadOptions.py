import os
import xml.etree.ElementTree as ET
from collections import OrderedDict

from astropy import units as u
from astropy.io.ascii.core import InconsistentTableError
from astropy.io import ascii

from .task import Task

compactString = lambda string: string.replace('\n', '').strip()


class LoadOptions(Task):
    """
    Reads the xml file with payload description and return an object with attributes related to the input data

    Parameters
    ----------
    filename: string
        input xml file location
    config_path: string (optional)
        on-run setting for ConfigPat. Default is None.

    Returns
    -------
    dict:
        parsed xml input file

    Raises
    ------
        IOError
            if the indicated file is not found or the format is not supported

    Examples
    --------
    >>> loadOptions = LoadOptions()
    >>> options = loadOptions(filename = 'path/to/file.xml')
    """

    def __init__(self):
        self.addTaskParam('filename', 'input option file name')
        self.addTaskParam('config_path', 'on-run setting for ConfigPath', None)

    def execute(self):
        self._filename = self.get_task_param('filename')
        self._config_path = self.get_task_param('config_path')
        self.__check_format__()
        root = self.__get_root__()
        self._dict = self.__parser__(root)
        # self.debug('loaded options: {}'.format(self._dict))
        self.set_output(self._dict)

    configPath = None

    def __check_format__(self):
        if not self._filename.endswith('.xml'):
            self.error('wrong input format')
            raise IOError

    def __get_root__(self):
        try:
            self.debug('input option file found %s' % self._filename)
            return ET.parse(self._filename).getroot()
        except IOError:
            self.error('No input option file found')
            raise IOError

    def __parser__(self, root):
        root_dict = {}

        for ch in root:

            retval = self.__parser__(ch)
            # parse all attributes
            for key in list(ch.attrib.keys()):
                retval[key] = ch.attrib[key]

            value = compactString(ch.text)
            if (value is not None) and (value != ''):
                try:
                    value = int(value)
                except ValueError:
                    if value.replace('.', ''):
                        try:
                            value = float(value)
                        except ValueError:
                            pass
                if 'unit' in retval:
                    unitName = retval['unit']
                    if unitName == 'dimensionless': unitName = ''
                    value = value * u.Unit(unitName)
                if value == 'True':
                    value = bool(True)
                if value == 'False':
                    value = bool(False)
                if isinstance(value, str):
                    if '__ConfigPath__' in value:
                        value = value.replace('__ConfigPath__', self.configPath)
                if ch.tag == "ConfigPath":
                    self.configPath = value

                if self._config_path:
                    self.configPath = self._config_path

                # if isinstance(value, str):
                #     retval = value
                # else:
                retval['value'] = value

            if ch.tag in root_dict:
                # if an other instance of same tag exists, transform into a dict
                attr = root_dict[ch.tag]
                if isinstance(attr, OrderedDict):
                    attr[value] = retval
                else:
                    if not isinstance(attr, str):
                        dtmp = OrderedDict([(attr['value'], attr), (value, retval)])
                        root_dict[ch.tag] = dtmp
            else:
                # othewise, set new attr
                root_dict[ch.tag] = retval

        if 'datafile' in root_dict:
            try:
                datatype_attr = root_dict['datatype']
                datatype = datatype_attr['value']
            except:
                datatype = 'ecsv'

            attrValue = root_dict['datafile']
            datafile = attrValue
            datafile = datafile['value'].replace('__ConfigPath__', self.configPath)
            try:
                data = self.__read_datatable__(datafile, datatype)
                root_dict['data'] = data
            except IOError:
                self.error("Cannot read input file")
                raise IOError

        if 'datadict' in root_dict:
            attrValue = root_dict['datadict']
            datafile = attrValue
            datafile = datafile['value'].replace('__ConfigPath__', self.configPath)
            try:
                data = self.__read_datadict__(datafile)
                root_dict['data'] = data
            except IOError:
                self.error("Cannot read input file")
                raise IOError
        if 'config_dict' in root_dict:
            attrValue = root_dict['config_dict']
            datafile = attrValue
            datafile = datafile['value'].replace('__ConfigPath__', self.configPath)
            try:
                data = self.__read_datadict__(datafile)
                root_dict = data
                root_dict['config_dict'] = datafile
                self.debug('Configuration dictionary found in {}'.format(datafile))
            except IOError:
                self.error("Cannot read input file")
                raise IOError

        return root_dict

    def getopt(self):
        return self.__obj__

    def __read_datatable__(self, datafile, datatype):
        if datatype == 'ecsv':
            try:
                data = ascii.read(os.path.expanduser(datafile),
                                  format='ecsv')
            except InconsistentTableError:
                data = ascii.read(os.path.expanduser(datafile),
                                  format='csv')
            return data

        else:
            self.error('inconsistent table')
            raise IOError

    def __read_datadict__(self, datadict):
        ext = os.path.splitext(datadict)[1]
        if ext in ['.h5', '.hdf5']:
            from exorad.output.hdf5 import load
            data = load(datadict)
            return data
        elif ext == '.pickle':
            import pickle
            f = open(datadict, 'rb')
            data = pickle.load(f)
            f.close()
            return data
        else:
            self.error('inconsistent table')
            raise IOError

