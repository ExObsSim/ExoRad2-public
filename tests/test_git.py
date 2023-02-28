import logging
import unittest

from exorad.log import setLogLevel
from exorad.utils.version_control import VersionControl
from exorad.utils.version_control import VersionError

setLogLevel(logging.DEBUG)


class VersionControlTest(unittest.TestCase):

    def test_updated(self):
        VersionControl()

    def test_to_update(self):
        VersionControl(current_version='2.0.0')

    def test_error(self):
        with self.assertRaises(VersionError) as context:
            ver = VersionControl(current_version='2.0.0', force=True)
            if not ver.status_code:
                raise VersionError
