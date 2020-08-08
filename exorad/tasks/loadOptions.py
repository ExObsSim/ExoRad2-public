import os
import xml.etree.ElementTree as ET
from collections import OrderedDict

import numpy as np
from astropy import units as u
from astropy.io.ascii.core import InconsistentTableError
from astropy.table import Table

from .task import Task

compactString = lambda string: string.replace('\n', '').strip()


class LoadOptions(Task):
    """
    Reads the xml file with payload description and return an object with attributes related to the input data

    Parameters
    ----------
    filename: string
        input xml file location

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

    def execute(self):
        self._filename = self.get_task_param('filename')
        self.__check_format__()
        root = self.__get_root__()
        self._dict = self.__parser__(root)
        # self.debug('loaded options: {}'.format(self._dict))
        self.set_output(self._dict)

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
        return root_dict

    def getopt(self):
        return self.__obj__

    def __read_datatable__(self, datafile, datatype):
        if datatype == 'ecsv':
            try:
                data = Table.read(os.path.expanduser(datafile),
                                  format='ascii.ecsv')
            except InconsistentTableError:
                data = Table.read(os.path.expanduser(datafile),
                                  format='ascii.csv')
            return data


        elif datatype == 'modtran':
            if 'transmission' in datafile:
                rawdata = np.loadtxt(os.path.expanduser(datafile))
                data = Table()
                data['Frequency'] = rawdata[:, 0] / u.cm
                data['Wavelength'] = data['Frequency'].to(u.micron, equivalencies=u.spectral())
                data['Transmission'] = rawdata[:, 1]
            if 'emission' in datafile:
                rawdata = np.loadtxt(os.path.expanduser(datafile))
                data = Table()
                data['Frequency'] = rawdata[:, 0] / u.cm
                data['Wavelength'] = data['Frequency'].to(u.micron, equivalencies=u.spectral())
                data['Emission per frequency'] = rawdata[:, 1] * u.W / u.sr / u.cm ** 2 / u.cm
                data['Emission'] = data['Emission per frequency'].to(
                    u.W / u.sr / u.micron / u.m ** 2, equivalencies=u.spectral())
            return data
        else:
            self.error('inconsistent table')
