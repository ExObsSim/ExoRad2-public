import datetime

import h5py
import hdfdict
from astropy.table import meta

from exorad.__version__ import __version__
from exorad.output.hdf5.util import recursively_read_dict_contents
from exorad.output.output import Output, OutputGroup

META_KEY = '__table_column_meta__'


class HDF5OutputGroup(OutputGroup):

    def __init__(self, entry):
        self.set_log_name()
        self._entry = entry

    def write_array(self, array_name, array, metadata=None):
        if isinstance(array, list):
            for idx, a in enumerate(array):
                self.write_array('{}{}'.format(array_name, idx), a, metadata)
            return
        ds = self._entry.create_dataset(str(array_name), data=array, shape=array.shape, dtype=array.dtype)
        if metadata:
            for k, v in metadata.items():
                ds.attrs[k] = v

    def write_table(self, table_name, table, metadata=None):
        table = _encode_mixins(table)
        if any(col.info.dtype.kind == 'U' for col in table.itercols()):
            table = table.copy(copy_data=False)
            table.convert_unicode_to_bytestring()

        self._entry.create_dataset(str(table_name), data=table.as_array())
        header_yaml = meta.get_yaml_from_table(table)

        header_encoded = [h.encode('utf-8') for h in header_yaml]
        self._entry.create_dataset(str(table_name) + '.' + META_KEY,
                                   data=header_encoded)

        tg = self._entry.create_group('{}_to_group'.format(str(table_name)))
        for col in table.keys():
            tg_c = tg.create_group(str(col))
            tg_c.create_dataset('value', data=table[col])
            if (table[col].unit != None):
                tg_c.create_dataset('unit', data=str(table[col].unit))

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
            str(string_name), (len(asciiList), 1), 'S64', asciiList)

        if metadata:
            for k, v in metadata.items():
                ds.attrs[k] = v

    def write_quantity(self, quantity_name, quantity):
        if quantity_name == 'value':
            self._entry.create_dataset('value', data=quantity.value,)
        else:
            qg_c = self._entry.create_group(str(quantity_name))
            qg_c.create_dataset('value', data=quantity.value,)
            qg_c.create_dataset('unit', data=str(quantity.unit))
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
            if (has_info_class(col, MixinInfo) and
                    col.__class__ is not u.Quantity):
                raise TypeError("cannot write type {} column '{}' "
                                "to HDF5 without PyYAML installed."
                                .format(col.__class__.__name__, col.info.name))

    with serialize_context_as('hdf5'):
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

        mode = 'w'
        if self._append:
            mode = 'a'

        fd = h5py.File(fname, mode=mode)
        fd.attrs['file_name'] = fname
        fd.attrs['file_time'] = datetime.datetime.now().isoformat()
        fd.attrs['creator'] = self.__class__.__name__
        fd.attrs['HDF5_Version'] = h5py.version.hdf5_version
        fd.attrs['h5py_version'] = h5py.version.version
        fd.attrs['program_name'] = 'ExoRad'
        fd.attrs['program_version'] = __version__
        return fd

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
