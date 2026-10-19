import io

import astropy.units as u
from astropy.table import QTable, Table

from exorad.utils.util import parse_range, progressbar, to_dict, vstack_tables


class TestProgressbar:
    def test_yields_all_items_and_draws(self):
        buf = io.StringIO()
        items = list(progressbar([1, 2, 3], prefix="p", size=10, file=buf, label="x"))
        assert items == [1, 2, 3]
        assert "3/3" in buf.getvalue()

    def test_empty_iterable_is_a_noop(self):
        buf = io.StringIO()
        assert list(progressbar([], file=buf)) == []
        assert buf.getvalue() == ""


class TestToDict:
    def test_nested_dict_and_quantity(self):
        out = to_dict({"a": 1 * u.m, "b": {"c": 2}})
        assert out["a"] == {"value": 1.0, "unit": "m"}
        assert out["b"] == {"c": 2}

    def test_qtable_is_wrapped(self):
        tab = QTable({"x": [1, 2] * u.m})
        assert to_dict(tab) == {"table": tab}

    def test_plain_table_becomes_value_dict(self):
        tab = Table({"x": [1, 2], "y": [3, 4]})
        out = to_dict(tab)
        assert set(out) == {"x", "y"}
        assert list(out["x"]["value"]) == [1, 2]

    def test_object_with_dict_and_classkey(self):
        class Thing:
            def __init__(self):
                self.public = 3
                self._private = 4
                self.name = "skip me"

        out = to_dict(Thing(), classkey="__class__")
        assert out["public"] == 3
        assert "_private" not in out
        assert "name" not in out
        assert out["__class__"] == "Thing"

    def test_passthrough_for_scalars(self):
        assert to_dict(42) == 42


class TestVstackTables:
    def test_missing_columns_are_zero_filled(self):
        t1 = Table({"w": [1, 2] * u.um, "a": [10, 20] * u.ct})
        t2 = Table({"w": [3, 4] * u.um, "b": [30, 40] * u.ct})
        out = vstack_tables([t1, t2])
        assert len(out) == 4
        assert set(out.colnames) == {"w", "a", "b"}
        assert out["a"][2] == 0 * u.ct
        assert out["b"][0] == 0 * u.ct

    def test_empty_list_returns_none(self):
        assert vstack_tables([]) is None


class TestParseRange:
    def test_all(self):
        assert parse_range("all", 5) == [0, 1, 2, 3, 4]

    def test_none(self):
        assert parse_range("none", 5) == []

    def test_single_values_and_ranges(self):
        assert parse_range("0,2-4", 10) == [0, 2, 3, 4]

    def test_invalid_returns_none(self):
        assert parse_range("a-b", 10) is None
