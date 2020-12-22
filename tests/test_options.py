import logging
import os
import pathlib
import unittest

from exorad.log import setLogLevel
from exorad.tasks import GetChannelList
from exorad.tasks.loadOptions import LoadOptions

path = pathlib.Path(__file__).parent.absolute()
data_dir = os.path.join(path.parent.absolute(), 'examples')
test_dir = os.path.join(path, 'test_data')
setLogLevel(logging.DEBUG)

def payload_file():
    payload_file = os.path.join(data_dir, 'payload_example.xml')
    new_configPath = '    <ConfigPath> {}\n'.format(path.parent.absolute())
    tmp = os.path.join(test_dir,'payload_test.xml')
    with open(tmp, 'w') as new_file:
        with open(payload_file) as old_file:
            for line in old_file:
                if '<ConfigPath>' in line:
                    new_file.write(new_configPath)
                else:
                    new_file.write(line)
    return tmp


class LoadOptionsTest(unittest.TestCase):
    loadOptions = LoadOptions()

    def test_loadFile(self):
        self.loadOptions(filename=payload_file())
        with self.assertRaises(IOError): self.loadOptions(
            filename=os.path.join(test_dir, 'payload_example_missing_data_file.xml'))
        with self.assertRaises(IOError): self.loadOptions(filename=os.path.join(path, 'test_data/payload_example.csv'))
        with self.assertRaises(IOError): self.loadOptions(filename=os.path.join(path, 'test_data/payload_example1.xml'))


class GetChannelListTest(unittest.TestCase):
    options = {'channel': {'Phot': {'channelClass': {'value': 'Photometer'}},
                           'Spec': {'channelClass': {'value': 'Spectrometer'}},
                           'Spec1': {'channelClass': {'value': 'Spectrometer'}}
                           }
               }

    getChannelList = GetChannelList()

    def test_channel_types(self):
        photometer_list = self.getChannelList(options=self.options, channel_type='Photometer')
        self.assertListEqual(photometer_list, ['Phot'])
        photometer_list = self.getChannelList(options=self.options, channel_type='Spectrometer')
        self.assertListEqual(photometer_list, ['Spec', 'Spec1'])
        photometer_list = self.getChannelList(options=self.options, channel_type='Bolometer')
        self.assertListEqual(photometer_list, [])
