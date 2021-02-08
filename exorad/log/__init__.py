import logging

from .logger import Logger

last_log = logging.INFO


def setLogLevel(level):
    global last_log
    from .logger import root_logger
    root_logger.handlers[0].setLevel(level)
    #    root_logger.setLevel(level)
    last_log = level


def disableLogging():
    # import logging
    # from .logger import root_logger
    # root_logger.setLevel(logging.ERROR)
    setLogLevel(logging.ERROR)

def enableLogging():
    # global last_log
    # import logging
    # from .logger import root_logger
    # root_logger.setLevel(logging.INFO)
    #
    # # if last_log is None:
    # #     last_log = logging.INFO
    setLogLevel(logging.INFO)


def addLogFile(fname='exorad.log'):
    from .logger import root_logger
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler = logging.FileHandler(fname)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
