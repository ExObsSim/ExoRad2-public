import astropy.units as u
import h5py
import numpy as np
from astropy.table import QTable

from exorad.output.hdf5 import HDF5Output
from exorad.output.hdf5.hdf5 import load


class TestHDF5OutputGroup:
    def test_write_primitives(self, tmp_path):
        path = tmp_path / "o.h5"
        with HDF5Output(str(path)) as out:
            g = out.create_group("g")
            g.write_scalar("s", 3.14, metadata={"note": "pi"})
            g.write_string("name", "hello", metadata={"lang": "en"})
            g.write_array("arr", np.arange(5.0), metadata={"kind": "range"})
            g.write_array("stack", [np.zeros(3), np.ones(3)])
            g.write_string_array("names", ["a", "b", "c"], metadata={"n": 3})
            g.write_quantity("q", 5.0 * u.m)
            sub = g.create_group("sub")
            sub.write_scalar("x", 1)
            # a group that already exists is returned, not recreated
            again = g.create_group("sub")
            assert again is not None

        with h5py.File(path, "r") as fd:
            assert fd["g/s"][()] == 3.14
            assert fd["g/s"].attrs["note"] == "pi"
            assert fd["g/arr"].attrs["kind"] == "range"
            assert fd["g/stack0"].shape == (3,)
            assert fd["g/names"].shape == (3, 1)
            assert fd["g/q/value"][()] == 5.0
            assert fd["g/q/unit"][()].decode() == "m"

    def test_write_table_with_units(self, tmp_path):
        path = tmp_path / "t.h5"
        tab = QTable({"Wavelength": [1.0, 2.0] * u.um, "name": ["x", "y"]})
        tab.meta["title"] = "demo"
        with HDF5Output(str(path)) as out:
            g = out.create_group("g")
            g.write_table("tab", tab, metadata={"m": 1})

        with h5py.File(path, "r") as fd:
            assert "g/tab" in fd
            assert "g/tab_to_group/Wavelength/unit" in fd


class TestHDF5Output:
    def test_metadata_and_info_group(self, tmp_path):
        path = tmp_path / "m.h5"
        with HDF5Output(str(path)) as out:
            out.add_info({"run": "test"}, name="extra")

        with h5py.File(path, "r") as fd:
            assert fd.attrs["program_name"] == "ExoRad2"
            assert "info" in fd
            loaded = load(fd["info"])
            assert isinstance(loaded, dict)

    def test_append_mode_keeps_existing(self, tmp_path):
        path = tmp_path / "a.h5"
        with HDF5Output(str(path)) as out:
            out.create_group("first").write_scalar("x", 1)
        with HDF5Output(str(path), append=True) as out:
            out.create_group("second").write_scalar("y", 2)

        with h5py.File(path, "r") as fd:
            assert "first" in fd
            assert "second" in fd
