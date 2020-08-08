import sys

import astropy.units as u
import numpy as np
from astropy.table import Table, QTable, vstack

def progressbar(it, prefix="", size=60, file=sys.stdout, label=''):
    count = len(it)
    if count > 0:
        def show(j):
            x = int(size * j / count)
            file.write("%s[%s%s] %i/%i %s\r" % (prefix, "#" * x, "." * (size - x), j, count, label))
            file.flush()

        show(0)
        for i, item in enumerate(it):
            yield item
            show(i + 1)
        file.write("\n")
        file.flush()


def to_dict(obj, classkey=None):
    if isinstance(obj, dict):
        data = {}
        for (k, v) in obj.items():
            data[k] = to_dict(v, classkey)
        return data
    elif isinstance(obj, u.Quantity):
        data = {'value': obj.value,
                'unit': str(obj.unit)}
        return data
    elif hasattr(obj, "_ast"):
        return to_dict(obj._ast())
    elif isinstance(obj, QTable):
        data = {'table': obj}
        #
        # commented lines convert table to dict, but table is already converted during the writing process!
        #
        # keys = [k for k in obj.keys()]
        # data_to_dict = {}
        # for k in keys:
        #     if hasattr(obj[k][0], 'unit'):
        #         data_to_dict[k] = {'value': obj[k], 'unit': str(obj[k][0].unit)}
        #     else:
        #         if isinstance(obj[k][0], str):
        #             data_to_dict[k] = {'value': [str(e) for e in obj[k]]}
        #         else:
        #             data_to_dict[k] = {'value': obj[k]}
        return data
    elif isinstance(obj, Table):
        keys = [k for k in obj.keys()]
        data = {}
        for k in keys:
            data[k] = {'value': obj[k]}
        return data

    elif hasattr(obj, "__dict__"):
        data = dict([(key, to_dict(value, classkey))
                     for key, value in obj.__dict__.items()
                     if not callable(value) and not key.startswith('_') and key not in ['name']])
        if classkey is not None and hasattr(obj, "__class__"):
            data[classkey] = obj.__class__.__name__
        return data
    else:
        return obj


def vstack_tables(table_list):
    table = False
    for tab in table_list:
        if not table:
            table = tab
        else:
            col_name1 = [col for col in table.keys() if col not in tab.keys()]
            if col_name1:
                for c in col_name1:
                    tab[c] = np.zeros(len(tab)) * table[c][0]
            col_name2 = [col for col in tab.keys() if col not in table.keys()]
            if col_name2:
                for c in col_name2:
                    table[c] = np.zeros(len(table)) * tab[c][0]
            table = vstack([table, tab], join_type='outer')
    return table


def parse_range(inp, avail_values):
    if inp.strip() == 'all':
        return [x for x in range(avail_values)]
    if inp.strip() == 'none':
        return []
    args = inp.split(',')

    numbers = []

    for a in args:
        start = None
        end = None
        try:
            s = a.split('-')
            start = int(s[0])
            end = int(s[1])
            end += 1
        except IndexError:
            start = int(a)
            end = int(a) + 1
        except ValueError:
            print('Invalid axis format, should be int')
            return None
        for x in range(start, end):
            numbers.append(x)
    return numbers


def chunks(l, n):
    for i in range(0, len(l), n):
        yield l[i:i + n]