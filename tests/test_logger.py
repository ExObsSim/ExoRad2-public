import unittest

from exorad.log import Logger


class LoggerTest(Logger):
    def __init__(self):
        super().__init__()
        self.info("info")
        self.debug("debug")
        self.warning("warning")
        self.critical("critical")
        self.error("error")


class LoadOptionsTest(unittest.TestCase):
    LoggerTest()

    def test_logs_messages(self):
        with self.assertLogs("exorad", level="DEBUG") as cm:
            LoggerTest()
            assert "INFO:exorad.LoggerTest:info" in cm.output
            assert "DEBUG:exorad.LoggerTest:debug" in cm.output
            assert "WARNING:exorad.LoggerTest:warning" in cm.output
            assert "CRITICAL:exorad.LoggerTest:critical" in cm.output
            assert "ERROR:exorad.LoggerTest:error" in cm.output

    # def test_log_file(self):
    #     print('starts here')
    #
    #     fname = os.path.join(test_dir, 'exorad.log')
    #     try:
    #         os.remove(fname)
    #     except OSError:
    #         pass
    #     addLogFile(fname)
    #     LoggerTest()
