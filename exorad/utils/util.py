from __future__ import annotations

import logging
import sys
from typing import IO, TYPE_CHECKING, Any

import astropy.units as u
import numpy as np
from astropy.table import QTable, Table, vstack

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

logger = logging.getLogger("exorad.util")


def progressbar(
    it: Sequence[Any],
    prefix: str = "",
    size: int = 60,
    file: IO[str] = sys.stdout,
    label: str = "",
) -> Iterator[Any]:
    count = len(it)
    if count > 0:

        def show(j: int) -> None:
            x = int(size * j / count)
            file.write(f"{prefix}[{'#' * x}{'.' * (size - x)}] {j}/{count} {label}\r")
            file.flush()

        show(0)
        for i, item in enumerate(it):
            yield item
            show(i + 1)
        file.write("\n")
        file.flush()


def to_dict(obj: Any, classkey: str | None = None) -> Any:
    if isinstance(obj, dict):
        data = {}
        for k, v in obj.items():
            data[k] = to_dict(v, classkey)
        return data
    if isinstance(obj, u.Quantity):
        return {"value": obj.value, "unit": str(obj.unit)}
    if hasattr(obj, "_ast"):
        return to_dict(obj._ast())
    if isinstance(obj, QTable):
        return {"table": obj}
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
    if isinstance(obj, Table):
        keys = list(obj.keys())
        data = {}
        for k in keys:
            data[k] = {"value": obj[k]}
        return data

    if hasattr(obj, "__dict__"):
        data = {
            key: to_dict(value, classkey)
            for key, value in obj.__dict__.items()
            if not callable(value) and not key.startswith("_") and key != "name"
        }
        if classkey is not None and hasattr(obj, "__class__"):
            data[classkey] = obj.__class__.__name__
        return data
    return obj


def vstack_tables(table_list: Sequence[Table]) -> Table | None:
    table: Table | None = None
    for tab in table_list:
        if table is None:
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
            table = vstack([table, tab], join_type="outer")
    return table


def parse_range(inp: str, avail_values: int) -> list[int] | None:
    if inp.strip() == "all":
        return list(range(avail_values))
    if inp.strip() == "none":
        return []
    args = inp.split(",")

    numbers: list[int] = []

    for a in args:
        try:
            s = a.split("-")
            start = int(s[0])
            end = int(s[1])
            end += 1
        except IndexError:
            start = int(a)
            end = int(a) + 1
        except ValueError:
            logger.warning("Invalid axis format, should be int")
            return None
        numbers.extend(range(start, end))
    return numbers
