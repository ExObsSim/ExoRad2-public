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


def addLogFile(fname="exorad.log"):
    from .logger import root_logger

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler = logging.FileHandler(fname)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
