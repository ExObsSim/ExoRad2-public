import pickle

import astropy.units as u
import pytest
from astropy.table import QTable

from exorad.tasks.loadOptions import LoadOptions, compactString


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_compactstring_handles_none():
    assert compactString(None) is None
    assert compactString("\n  x \n") == "x"


class TestParser:
    def test_types_units_bool_and_config_path(self, tmp_path):
        xml = f"""<root>
            <ConfigPath> {tmp_path!s} </ConfigPath>
            <working_R> 42 </working_R>
            <flag> True </flag>
            <flag2> False </flag2>
            <length unit="m"> 3.5 </length>
            <dimless unit="dimensionless"> 2 </dimless>
            <text> ... </text>
            <path> __ConfigPath__/thing.csv </path>
        </root>"""
        opt = LoadOptions()(filename=_write(tmp_path, "p.xml", xml))
        assert opt["working_R"]["value"] == 42
        assert opt["flag"]["value"] is True
        assert opt["flag2"]["value"] is False
        assert opt["length"]["value"] == 3.5 * u.m
        assert opt["dimless"]["value"] == 2 * u.dimensionless_unscaled
        assert opt["text"]["value"] == "..."
        assert opt["path"]["value"].endswith("/thing.csv")
        assert str(tmp_path) in opt["path"]["value"]

    def test_empty_element_does_not_crash(self, tmp_path):
        xml = f"""<root>
            <ConfigPath> {tmp_path!s} </ConfigPath>
            <sourceSpectrum> phoenix
                <StellarModels></StellarModels>
            </sourceSpectrum>
            <selfclosing/>
        </root>"""
        opt = LoadOptions()(filename=_write(tmp_path, "p.xml", xml))
        assert "value" not in opt["sourceSpectrum"]["StellarModels"]
        assert "value" not in opt["selfclosing"]
        assert opt["sourceSpectrum"]["value"] == "phoenix"

    def test_repeated_tags_become_ordered_dict(self, tmp_path):
        xml = f"""<root>
            <ConfigPath> {tmp_path!s} </ConfigPath>
            <opticalElement> M1 <type>surface</type></opticalElement>
            <opticalElement> M2 <type>surface</type></opticalElement>
        </root>"""
        opt = LoadOptions()(filename=_write(tmp_path, "p.xml", xml))
        assert set(opt["opticalElement"]) == {"M1", "M2"}

    def test_config_path_override(self, tmp_path):
        xml = """<root>
            <ConfigPath> /original </ConfigPath>
            <path> __ConfigPath__/x.csv </path>
        </root>"""
        opt = LoadOptions()(
            filename=_write(tmp_path, "p.xml", xml), config_path="/override"
        )
        assert opt["path"]["value"] == "/override/x.csv"

    def test_wrong_extension_raises(self, tmp_path):
        with pytest.raises(OSError):
            LoadOptions()(filename=_write(tmp_path, "p.txt", "<root/>"))

    def test_missing_file_raises(self):
        with pytest.raises(OSError):
            LoadOptions()(filename="/no/such/payload.xml")


class TestDataFiles:
    def test_datadict_pickle(self, tmp_path):
        pkl = tmp_path / "d.pickle"
        with open(pkl, "wb") as f:
            pickle.dump({"hello": 1}, f)
        xml = f"""<root>
            <ConfigPath> {tmp_path} </ConfigPath>
            <channel> Spec
                <datadict> {pkl} </datadict>
            </channel>
        </root>"""
        opt = LoadOptions()(filename=_write(tmp_path, "p.xml", xml))
        assert opt["channel"]["data"] == {"hello": 1}

    def test_datadict_hdf5(self, tmp_path):
        from exorad.output.hdf5 import HDF5Output

        h5 = tmp_path / "d.h5"
        with HDF5Output(str(h5)) as out:
            g = out.create_group("grp")
            g.write_scalar("x", 5)

        xml = f"""<root>
            <ConfigPath> {tmp_path} </ConfigPath>
            <channel> Spec
                <datadict> {h5} </datadict>
            </channel>
        </root>"""
        opt = LoadOptions()(filename=_write(tmp_path, "p.xml", xml))
        assert "data" in opt["channel"]

    def test_datafile_ecsv(self, tmp_path):
        tab = QTable({"Wavelength": [1, 2] * u.um, "Transmission": [0.9, 0.9]})
        ecsv = tmp_path / "tr.ecsv"
        tab.write(ecsv, format="ascii.ecsv")
        xml = f"""<root>
            <ConfigPath> {tmp_path} </ConfigPath>
            <opticalElement> M1
                <datafile> {ecsv} </datafile>
            </opticalElement>
        </root>"""
        opt = LoadOptions()(filename=_write(tmp_path, "p.xml", xml))
        assert "data" in opt["opticalElement"]

    def test_datafile_bad_datatype_raises(self, tmp_path):
        xml = f"""<root>
            <ConfigPath> {tmp_path} </ConfigPath>
            <opticalElement> M1
                <datatype> weird </datatype>
                <datafile> {tmp_path}/nope.dat </datafile>
            </opticalElement>
        </root>"""
        with pytest.raises(OSError):
            LoadOptions()(filename=_write(tmp_path, "p.xml", xml))

    def test_datafile_with_config_path_placeholder(self, tmp_path):
        tab = QTable({"Wavelength": [1, 2] * u.um, "Transmission": [0.9, 0.9]})
        tab.write(tmp_path / "tr.ecsv", format="ascii.ecsv")
        xml = f"""<root>
            <ConfigPath> {tmp_path} </ConfigPath>
            <opticalElement> M1
                <datafile> __ConfigPath__/tr.ecsv </datafile>
            </opticalElement>
        </root>"""
        opt = LoadOptions()(filename=_write(tmp_path, "p.xml", xml))
        assert "data" in opt["opticalElement"]

    def test_config_dict_replaces_root(self, tmp_path):
        pkl = tmp_path / "cfg.pickle"
        with open(pkl, "wb") as f:
            pickle.dump({"common": {"working_R": 100}}, f)
        xml = f"""<root>
            <ConfigPath> {tmp_path} </ConfigPath>
            <config_dict> {pkl} </config_dict>
        </root>"""
        opt = LoadOptions()(filename=_write(tmp_path, "p.xml", xml))
        assert opt["common"] == {"working_R": 100}
        assert opt["config_dict"].endswith("cfg.pickle")
