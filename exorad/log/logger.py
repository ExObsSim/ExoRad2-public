import logging

__all__ = ['Logger']

root_logger = logging.getLogger('exorad')
root_logger.setLevel(logging.DEBUG)

root_logger.propagate = False

class ExoRadHandler(logging.StreamHandler):

    def __init__(self, stream=None):
        from exorad.utils.mpi import get_rank
        super().__init__(stream=stream)

        self._rank = get_rank()

    def emit(self, record):
        # print(record)
        if self._rank == 0 or record.levelno >= logging.ERROR:
            # msg = '[{}] {}'.format(self._rank,record.msg)
            # record.msg = msg
            return super(ExoRadHandler, self).emit(record)
        else:
            pass


formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
ch = ExoRadHandler()
ch.setFormatter(formatter)
ch.setLevel(logging.INFO)
root_logger.addHandler(ch)


class Logger:
    """
    Standard logging using logger library
    """

    def __init__(self):
        self.set_log_name()

    def set_log_name(self):
        self._log_name = 'exorad.{}'.format(self.__class__.__name__)
        self._logger = logging.getLogger('exorad.{}'.format(self.__class__.__name__))

    def info(self, message, *args, **kwargs):
        """ See :class:`logging.Logger` """
        self._logger.info(message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        """ See :class:`logging.Logger` """
        self._logger.warning(message, *args, **kwargs)

    def debug(self, message, *args, **kwargs):
        """ See :class:`logging.Logger` """
        self._logger.debug(message, *args, **kwargs)

    def error(self, message, *args, **kwargs):
        """ See :class:`logging.Logger` """
        self._logger.error(message, *args, **kwargs)

    def critical(self, message, *args, **kwargs):
        """ See :class:`logging.Logger` """
        self._logger.critical(message, *args, **kwargs)
