import contextlib
import logging
import os
import pathlib
import unittest

import pytest

from exorad.log import setLogLevel
from exorad.tasks import GetChannelList
from exorad.tasks.loadOptions import LoadOptions

path = pathlib.Path(__file__).parent.absolute()
data_dir = os.path.join(path.parent.absolute(), "examples")
test_dir = os.path.join(path, "test_data")
setLogLevel(logging.DEBUG)


def payload_file(
    source=path.parent.absolute(), destination=test_dir, name="payload_test.xml"
):
    payload_file_ = os.path.join(data_dir, "payload_example.xml")
    new_configPath = f"    <ConfigPath> {source}\n"
    tmp = os.path.join(destination, name)
    with contextlib.suppress(OSError):
        os.remove(tmp)
    with open(tmp, "w+") as new_file, open(payload_file_) as old_file:
        for line in old_file:
            if "<ConfigPath>" in line:
                new_file.write(new_configPath)
            else:
                new_file.write(line)
    return tmp


class LoadOptionsTest(unittest.TestCase):
    loadOptions = LoadOptions()

    def test_loadFile(self):
        self.loadOptions(filename=payload_file())
        with pytest.raises(IOError):
            self.loadOptions(
                filename=os.path.join(test_dir, "payload_example_missing_data_file.xml")
            )
        with pytest.raises(IOError):
            self.loadOptions(
                filename=os.path.join(path, "test_data/payload_example.csv")
            )
        with pytest.raises(IOError):
            self.loadOptions(
                filename=os.path.join(path, "test_data/payload_example1.xml")
            )

        self.loadOptions(
            filename=os.path.join(test_dir, "payload_example_missing_config.xml"),
            config_path=str(path.parent.absolute()),
        )

    def test_loadpickle(self):
        if not os.path.exists(os.path.join(test_dir, "spec.pickle")):
            options = self.loadOptions(filename=payload_file())
            import pickle

            with open(os.path.join(test_dir, "spec.pickle"), "wb") as filehandler:
                pickle.dump(options["channel"]["Spec"], filehandler)
        self.loadOptions(filename=payload_file(name="payload_test_pickle_spec.xml"))


class GetChannelListTest(unittest.TestCase):
    options = {
        "channel": {
            "Phot": {"channelClass": {"value": "Photometer"}},
            "Spec": {"channelClass": {"value": "Spectrometer"}},
            "Spec1": {"channelClass": {"value": "Spectrometer"}},
        }
    }

    getChannelList = GetChannelList()

    def test_channel_types(self):
        photometer_list = self.getChannelList(
            options=self.options, channel_type="Photometer"
        )
        assert photometer_list == ["Phot"]
        photometer_list = self.getChannelList(
            options=self.options, channel_type="Spectrometer"
        )
        assert photometer_list == ["Spec", "Spec1"]
        photometer_list = self.getChannelList(
            options=self.options, channel_type="Bolometer"
        )
        assert photometer_list == []
