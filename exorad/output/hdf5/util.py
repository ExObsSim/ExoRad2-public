import astropy.units as u
import numpy as np
from astropy.table import Table, QTable, meta, serialize

from exorad.models.signal import Signal, Sed

signal = {'W / (m2 um)': Sed}


def recursively_read_dict_contents(input):
    """
    Will recursive read a dictionary, initializing quantities and table from a dictionary read from an hdf5 file.

    Parameters
    ----------
    input : dict
        dictionary read from hdf5

    Returns
    --------
    dict
        Dictionary we want to use

    """
    new_keys = [k for k in input.keys()]
    # if all(elem in new_keys for elem in ['wl_grid', 'data', 'time_grid']):
    #     wl = input['wl_grid']['value'] * u.Unit(input['wl_grid']['unit'])
    #     data = input['data']['value'] * u.Unit(input['data']['unit'])
    #     time = input['time_grid']['value'] * u.Unit(input['time_grid']['unit'])
    #     input = signal[str(input['data']['unit'])](wl, data, time)
    if all(elem in new_keys for elem in ['value', 'unit']):
        input['value'] = input['value'] * u.Unit(input['unit'])
    if any('.__table_column_meta__' in elem for elem in new_keys):
        table_keys = [elem for elem in new_keys if '.__table_column_meta__' in elem]
        table_keys = (elem.split('.')[0] for elem in table_keys)
        for k in table_keys:
            table = Table(np.array(input[k]))
            header = meta.get_header_from_yaml(h.decode('utf-8') for h in input['{}.__table_column_meta__'.format(k)])
            header_cols = dict((x['name'], x) for x in header['datatype'])
            for col in table.columns.values():
                for attr in ('description', 'format', 'unit', 'meta'):
                    if attr in header_cols[col.name]:
                        setattr(col, attr, header_cols[col.name][attr])
            table = serialize._construct_mixins_from_columns(table)
            try:
                header['meta'].pop('__serialized_columns__')
                table.meta = header['meta']
            except KeyError:
                pass
            input[k] = table
    for key in new_keys:
        if isinstance(input[key], dict):
            input[key] = recursively_read_dict_contents(input[key])
    return input


def recursively_save_dict_contents_to_output(output, dic):
    """
    Will recursive write a dictionary into output.

    Parameters
    ----------
    output :
        Group (or root) in output file to write to

    dic : :obj:`dict`
        Dictionary we want to write

    """

    for key, item in dic.items():

        try:
            store_thing(output, key, item)
        except TypeError:
            raise ValueError('Cannot write %s type' % type(item))


def store_thing(output, key, item):
    if isinstance(item, (float, int, np.int64, np.float64,)):
        output.write_scalar(key, item)
    elif isinstance(item, (np.ndarray,)):
        output.write_array(key, item)
    elif isinstance(item, (str,)):
        output.write_string(key, item)
    elif isinstance(item, (Table, QTable)):
        output.write_table(key, item)
    elif isinstance(item, Signal):
        group = output.create_group(key)
        recursively_save_dict_contents_to_output(group, item.to_dict())
    elif isinstance(item, (list, tuple,)):
        if isinstance(item, tuple):
            item = list(item)
        if True in [isinstance(x, str) for x in item]:
            output.write_string_array(key, item)
        else:
            try:
                output.write_array(key, np.array(item))

            except TypeError:
                for idx, val in enumerate(item):
                    new_key = '{}{}'.format(key, idx)
                    store_thing(output, new_key, val)

    elif isinstance(item, dict):
        group = output.create_group(key)
        recursively_save_dict_contents_to_output(group, item)
    else:
        raise TypeError
