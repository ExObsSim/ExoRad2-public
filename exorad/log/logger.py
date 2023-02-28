"""
These parts of the code derives from TauREx3:
    @ARTICLE{2019arXiv191207759A,
           author = {{Al-Refaie}, Ahmed F. and {Changeat}, Quentin and {Waldmann}, Ingo P. and {Tinetti}, Giovanna},
            title = "{TauREx III: A fast, dynamic and extendable framework for retrievals}",
          journal = {arXiv e-prints},
         keywords = {Astrophysics - Instrumentation and Methods for Astrophysics, Astrophysics - Earth and Planetary Astrophysics},
             year = 2019,
            month = dec,
              eid = {arXiv:1912.07759},
            pages = {arXiv:1912.07759},
    archivePrefix = {arXiv},
           eprint = {1912.07759},
     primaryClass = {astro-ph.IM},
           adsurl = {https://ui.adsabs.harvard.edu/abs/2019arXiv191207759A},
          adsnote = {Provided by the SAO/NASA Astrophysics Data System}
    }

BSD 3-Clause License

Copyright (c) 2019, Ahmed F. Al-Refaie, Quentin Changeat, Ingo Waldmann, Giovanna Tinetti
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the names of the copyright holders nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
import logging

__all__ = ["Logger"]

root_logger = logging.getLogger("exorad")
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
            return super().emit(record)
        else:
            pass


formatter = logging.Formatter("%(name)s - %(levelname)s - %(message)s")
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
        self._log_name = "exorad.{}".format(self.__class__.__name__)
        self._logger = logging.getLogger(
            "exorad.{}".format(self.__class__.__name__)
        )

    def info(self, message, *args, **kwargs):
        """See :class:`logging.Logger`"""
        self._logger.info(message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        """See :class:`logging.Logger`"""
        self._logger.warning(message, *args, **kwargs)

    def debug(self, message, *args, **kwargs):
        """See :class:`logging.Logger`"""
        self._logger.debug(message, *args, **kwargs)

    def error(self, message, *args, **kwargs):
        """See :class:`logging.Logger`"""
        self._logger.error(message, *args, **kwargs)

    def critical(self, message, *args, **kwargs):
        """See :class:`logging.Logger`"""
        self._logger.critical(message, *args, **kwargs)
