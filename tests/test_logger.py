import unittest

from exorad.log import Logger


class LoggerTest(Logger):
    def __init__(self):
        super().__init__()
        self.info('info')
        self.debug('debug')
        self.warning('warning')
        self.critical('critical')
        self.error('error')


class LoadOptionsTest(unittest.TestCase):
    LoggerTest()

    def test_logs_messages(self):
        with self.assertLogs('exorad', level='DEBUG') as cm:
            LoggerTest()
            self.assertIn(
                "INFO:exorad.LoggerTest:info",
                cm.output)
            self.assertIn(
                "DEBUG:exorad.LoggerTest:debug",
                cm.output)
            self.assertIn(
                "WARNING:exorad.LoggerTest:warning",
                cm.output)
            self.assertIn(
                "CRITICAL:exorad.LoggerTest:critical",
                cm.output)
            self.assertIn(
                "ERROR:exorad.LoggerTest:error",
                cm.output)

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
