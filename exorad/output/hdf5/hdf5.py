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
import datetime

import h5py
import hdfdict
from astropy.table import meta

from exorad import __author__
from exorad import __citation__
from exorad import __copyright__
from exorad import __license__
from exorad import __pkg_name__
from exorad import __title__
from exorad import __url__
from exorad import __version__
from exorad.output.hdf5.util import recursively_read_dict_contents
from exorad.output.output import Output
from exorad.output.output import OutputGroup

META_KEY = "__table_column_meta__"


class HDF5OutputGroup(OutputGroup):
    def __init__(self, entry):
        self.set_log_name()
        self._entry = entry

    def write_array(self, array_name, array, metadata=None):
        if isinstance(array, list):
            for idx, a in enumerate(array):
                self.write_array("{}{}".format(array_name, idx), a, metadata)
            return
        ds = self._entry.create_dataset(
            str(array_name), data=array, shape=array.shape, dtype=array.dtype
        )
        if metadata:
            for k, v in metadata.items():
                ds.attrs[k] = v

    def write_table(self, table_name, table, metadata=None):
        table = _encode_mixins(table)
        if any(col.info.dtype.kind == "U" for col in table.itercols()):
            table = table.copy(copy_data=False)
            table.convert_unicode_to_bytestring()

        self._entry.create_dataset(str(table_name), data=table.as_array())
        header_yaml = meta.get_yaml_from_table(table)

        header_encoded = [h.encode("utf-8") for h in header_yaml]
        self._entry.create_dataset(
            str(table_name) + "." + META_KEY, data=header_encoded
        )

        tg = self._entry.create_group("{}_to_group".format(str(table_name)))
        for col in table.keys():
            tg_c = tg.create_group(str(col))
            tg_c.create_dataset("value", data=table[col])
            if table[col].unit != None:
                tg_c.create_dataset("unit", data=str(table[col].unit))

    def write_scalar(self, scalar_name, scalar, metadata=None):
        ds = self._entry.create_dataset(str(scalar_name), data=scalar)
        if metadata:
            for k, v in metadata.items():
                ds.attrs[k] = v

    def write_string(self, string_name, string, metadata=None):
        ds = self._entry.create_dataset(str(string_name), data=string)
        if metadata:
            for k, v in metadata.items():
                ds.attrs[k] = v

    def create_group(self, group_name):
        entry = None
        if self._entry:
            try:
                entry = self._entry.create_group(str(group_name))
            except ValueError:
                entry = self._entry[str(group_name)]
        return HDF5OutputGroup(entry)

    def write_string_array(self, string_name, string_array, metadata=None):
        asciiList = [n.encode("ascii", "ignore") for n in string_array]
        ds = self._entry.create_dataset(
            str(string_name), (len(asciiList), 1), "S64", asciiList
        )

        if metadata:
            for k, v in metadata.items():
                ds.attrs[k] = v

    def write_quantity(self, quantity_name, quantity):
        if quantity_name == "value":
            self._entry.create_dataset(
                "value",
                data=quantity.value,
            )
        else:
            qg_c = self._entry.create_group(str(quantity_name))
            qg_c.create_dataset(
                "value",
                data=quantity.value,
            )
            qg_c.create_dataset("unit", data=str(quantity.unit))
            pass


def _encode_mixins(tbl):
    from astropy.table import serialize
    from astropy.table.table import has_info_class
    from astropy import units as u
    from astropy.utils.data_info import MixinInfo, serialize_context_as

    try:
        import yaml
    except ImportError:
        for col in tbl.itercols():
            if (
                has_info_class(col, MixinInfo)
                and col.__class__ is not u.Quantity
            ):
                raise TypeError(
                    "cannot write type {} column '{}' "
                    "to HDF5 without PyYAML installed.".format(
                        col.__class__.__name__, col.info.name
                    )
                )

    with serialize_context_as("hdf5"):
        encode_tbl = serialize.represent_mixins_as_columns(tbl)

    return encode_tbl


class HDF5Output(Output):
    def __init__(self, filename, append=False):
        super().__init__()
        self.filename = filename
        self._append = append
        self.fd = None

    def open(self):
        self.fd = self._openFile(self.filename)

    def _openFile(self, fname):
        mode = "w"
        if self._append:
            mode = "a"

        attrs = {
            "file_name": fname,
            "file_time": datetime.datetime.now().isoformat(),
            "creator": self.__class__.__name__,
            "HDF5_Version": h5py.version.hdf5_version,
            "h5py_version": h5py.version.version,
            "program_name": str(__title__),
            "package name": str(__pkg_name__),
            "program_version": str(__version__),
            "author": str(__author__),
            "copyright": str(__copyright__),
            "license": str(__license__),
            "url": str(__url__),
            "citation": str(__citation__),
        }

        fd = h5py.File(fname, mode=mode)
        for key in attrs:
            fd.attrs[key] = attrs[key]

        if mode == "w" or "info" not in fd.keys():
            try:
                gd_ = fd["info"]
            except KeyError:
                gd_ = fd.create_group("info")
            gd = HDF5OutputGroup(gd_)
            gd.store_dictionary(attrs, "ExoRad")

        return fd

    def add_info(self, attrs, name=None):
        gd = self.create_group("info")
        gd.store_dictionary(attrs, name)

    def create_group(self, group_name):
        entry = None
        if self.fd:
            try:
                entry = self.fd.create_group(str(group_name))
            except ValueError:
                entry = self.fd[str(group_name)]
        return HDF5OutputGroup(entry)

    def close(self):
        if self.fd:
            self.fd.flush()
            self.fd.close()


def load(input_group):
    """
    Reads and convert an HDF5 group into a dictionary

    Parameters
    ----------
    input_group: HDF5Group
        input dumped group

    Returns
    -------
    dict
    """
    input_group = hdfdict.load(input_group, lazy=False)
    input_group = recursively_read_dict_contents(input_group)
    return input_group
