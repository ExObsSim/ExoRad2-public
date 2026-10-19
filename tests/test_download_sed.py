"""Offline tests for the SED download task.

Every test here stubs the network: the grid snapping, the Goettingen URL
builder (including the ``-0.0`` solar-metallicity case that the ExoSim version
gets wrong), the air-to-vacuum conversion, the SVO HTML parsers (fed canned
HTML) and the task orchestration with the backend patched out.
"""

import io
from unittest.mock import patch

import astropy.units as u
import numpy as np
import pytest

from exorad.models.signal import Sed
from exorad.tasks import downloadSed as ds


class TestGridSnapping:
    def test_snap_returns_nearest_grid_point(self):
        grid = np.array([0.0, 10.0, 20.0, 30.0])
        assert ds._snap(12.0, grid) == 10.0
        assert ds._snap(17.0, grid) == 20.0
        assert ds._snap(-5.0, grid) == 0.0


class TestAcesUrl:
    def test_solar_metallicity_uses_minus_zero(self):
        # the bug this port fixes: Goettingen serves Z-0.0 / -0.0, not +0.0
        url, t, g, z = ds._aces_url(5789, 4.4, 0.02)
        assert (t, g, z) == (5800, 4.5, 0.0)
        assert "/Z-0.0/" in url
        assert "lte05800-4.50-0.0.PHOENIX-ACES-AGSS-COND-2011-HiRes.fits" in url

    def test_positive_metallicity(self):
        url, _t, _g, z = ds._aces_url(6000, 4.0, 0.4)
        assert z == 0.5
        assert "/Z+0.5/" in url
        assert "4.00+0.5." in url

    def test_negative_metallicity(self):
        url, _t, _g, z = ds._aces_url(4000, 4.5, -1.2)
        assert z == -1.0
        assert "/Z-1.0/" in url
        assert "4.50-1.0." in url

    def test_feh_str_helper(self):
        assert ds._feh_str(0.0) == "-0.0"
        assert ds._feh_str(0.5) == "+0.5"
        assert ds._feh_str(-0.5) == "-0.5"


class TestAirToVacuum:
    def test_matches_reference_value(self):
        # 5000 AA air -> 5001.39 AA vacuum (Morton/IAU)
        vac = ds.air_to_vacuum_wavelength(np.array([5000.0]))
        assert vac[0] == pytest.approx(5001.39, abs=0.05)

    def test_vacuum_is_longer_than_air(self):
        air = np.array([3000.0, 5000.0, 8000.0])
        vac = ds.air_to_vacuum_wavelength(air)
        assert np.all(vac > air)
        assert np.all((vac - air) / air < 0.001)

    def test_short_wavelengths_are_nan(self):
        out = ds.air_to_vacuum_wavelength(np.array([1000.0, 1999.0]))
        assert np.all(np.isnan(out))


_MODELS_HTML = """
<html><body>
<select name="models">
  <option value="bt-settl">BT-Settl</option>
  <option value="bt-settl-cifist">BT-Settl CIFIST</option>
</select>
<a href="index.php?models=coelho">Coelho</a>
</body></html>
"""

# mirrors the real SVO results table: tabcab headers (some wrapped in <a>),
# tabfld data cells, VOtable + ASCII links in the last cells
_TABLE_HTML = """
<table>
<tr>
  <td class=tabcab>Model</td>
  <td class=tabcab><a href="#"> T<sub>eff</sub></a></td>
  <td class=tabcab><a href="#">Logg</a></td>
  <td class=tabcab><a href="#">Metallicity</a></td>
  <td class=tabcab><a href="#">Alpha</a></td>
  <td class=tabcab>Fetch</td><td class=tabcab>Mark</td>
  <td class=tabcab>Fetch</td><td class=tabcab>Mark</td><td class=tabcab>Plot</td>
</tr>
<tr>
  <td class=tabfld>BT-Settl (CIFIST)</td>
  <td class=tabfld>5000</td><td class=tabfld>4.5</td>
  <td class=tabfld>0</td><td class=tabfld>0</td>
  <td class=tabfld><a href="ssap.php?model=x&fid=1&format=votable">VOtable</a></td>
  <td class=tabfld><input type=checkbox></td>
  <td class=tabfld><a href="ssap.php?model=x&fid=1&format=ascii">ASCII</a></td>
  <td class=tabfld><input type=checkbox></td>
  <td class=tabfld><input type=checkbox></td>
</tr>
<tr>
  <td class=tabfld>BT-Settl (CIFIST)</td>
  <td class=tabfld>6000</td><td class=tabfld>4.0</td>
  <td class=tabfld>-0.5</td><td class=tabfld>0</td>
  <td class=tabfld><a href="ssap.php?model=x&fid=2&format=votable">VOtable</a></td>
  <td class=tabfld><input type=checkbox></td>
  <td class=tabfld><a href="ssap.php?model=x&fid=2&format=ascii">ASCII</a></td>
  <td class=tabfld><input type=checkbox></td>
  <td class=tabfld><input type=checkbox></td>
</tr>
</table>
"""


class TestSVOParsers:
    def test_models_parser_collects_identifiers(self):
        parser = ds._SVOModelsParser()
        parser.feed(_MODELS_HTML)
        assert {"bt-settl", "bt-settl-cifist", "coelho"} <= parser.models

    def test_table_parser_reads_the_grid_and_picks_the_ascii_link(self):
        parser = ds._SVOTableParser()
        parser.feed(_TABLE_HTML)
        rows = parser.models()
        assert len(rows) == 2
        assert rows[0]["teff"] == 5000.0
        assert rows[0]["logg"] == 4.5
        assert rows[1]["feh"] == -0.5
        assert rows[0]["url"].endswith("fid=1&format=ascii")

    def test_table_parser_without_teff_header_returns_empty(self):
        parser = ds._SVOTableParser()
        parser.feed("<table><tr><td class='tabcab'>foo</td></tr></table>")
        assert parser.models() == []


def _resp(html):
    r = io.BytesIO(html.encode())
    r.__enter__ = lambda s: s
    r.__exit__ = lambda *a: False
    return r


class TestSvoNearest:
    def test_picks_the_closest_grid_point(self):
        with (
            patch.object(ds, "_host_is_reachable", return_value=True),
            patch("urllib.request.urlopen", return_value=_resp(_TABLE_HTML)),
        ):
            best = ds._svo_nearest("bt-settl-cifist", 5100, 4.4, 0.1, 0.0)
        assert best["teff"] == 5000.0

    def test_far_metallicity_switches_the_choice(self):
        with (
            patch.object(ds, "_host_is_reachable", return_value=True),
            patch("urllib.request.urlopen", return_value=_resp(_TABLE_HTML)),
        ):
            best = ds._svo_nearest("bt-settl-cifist", 5500, 4.2, -0.5, 0.0)
        assert best["teff"] == 6000.0

    def test_no_candidates_raises_valueerror(self):
        empty = "<table><tr><td class='tabcab'>foo</td></tr></table>"
        with (
            patch.object(ds, "_host_is_reachable", return_value=True),
            patch("urllib.request.urlopen", return_value=_resp(empty)),
            pytest.raises(ValueError, match="no spectra"),
        ):
            ds._svo_nearest("bt-settl", 5000, 4.5, 0.0, 0.0)

    def test_offline_raises_connectionerror(self):
        with (
            patch.object(ds, "_host_is_reachable", return_value=False),
            pytest.raises(ConnectionError, match="no network"),
        ):
            ds._svo_nearest("bt-settl", 5000, 4.5, 0.0, 0.0)


class TestFetchSvoMocked:
    def test_parses_ascii_spectrum_and_builds_a_descriptive_name(self, tmp_path):
        spec = tmp_path / "ssap.php"
        spec.write_text("# header\n3000.0 1.0\n4000.0 2.0\n5000.0 3.0\n")
        best = {
            "url": "https://svo.example/ssap.php?fid=1&format=ascii",
            "teff": 5000.0,
            "logg": 4.5,
            "feh": 0.0,
            "alpha": 0.0,
        }
        with (
            patch.object(ds, "_svo_nearest", return_value=best),
            patch.object(ds, "_host_is_reachable", return_value=True),
            patch.object(ds, "_svo_remote_filename", return_value=None),
            patch.object(ds, "download_file", return_value=str(spec)),
        ):
            wl, flux, meta = ds._fetch_svo("bt-settl-cifist", 5000, 4.5, 0.0, 0.0)
        assert wl.unit == u.AA
        assert flux.unit.is_equivalent("erg / (s cm2 AA)")
        assert len(wl) == 3
        assert meta["model"] == "bt-settl-cifist"
        assert meta["filename"].startswith("bt-settl-cifist_Teff05000")

    def test_unparseable_file_raises(self, tmp_path):
        spec = tmp_path / "empty.txt"
        spec.write_text("# only comments\n#\n")
        best = {
            "url": "https://svo.example/x.spec",
            "teff": 5000.0,
            "logg": 4.5,
            "feh": 0.0,
            "alpha": 0.0,
        }
        with (
            patch.object(ds, "_svo_nearest", return_value=best),
            patch.object(ds, "_host_is_reachable", return_value=True),
            patch.object(ds, "_svo_remote_filename", return_value=None),
            patch.object(ds, "download_file", return_value=str(spec)),
            pytest.raises(ValueError, match="could not parse"),
        ):
            ds._fetch_svo("bt-settl", 5000, 4.5, 0.0, 0.0)


class TestFetchAcesMocked:
    def test_reads_wave_and_flux_fits(self, tmp_path):
        from astropy.io import fits

        wave = tmp_path / "wave.fits"
        flux = tmp_path / "flux.fits"
        fits.PrimaryHDU(np.linspace(3000.0, 30000.0, 50)).writeto(wave)
        fits.PrimaryHDU(np.ones(50) * 1e5).writeto(flux)

        with (
            patch.object(ds, "_host_is_reachable", return_value=True),
            patch.object(ds, "download_file", side_effect=[str(wave), str(flux)]),
        ):
            wl, sed, meta = ds._fetch_aces(5000, 4.5, 0.0)
        assert wl.unit == u.AA
        assert len(wl) == 50
        assert sed.unit.is_equivalent("erg / (s cm2 cm)")
        assert meta["model"] == ds._ACES_MODEL
        assert meta["filename"].startswith("lte05000-4.50-0.0")

    def test_raises_when_offline(self):
        with (
            patch.object(ds, "_host_is_reachable", return_value=False),
            pytest.raises(ConnectionError, match="no network"),
        ):
            ds._fetch_aces(5000, 4.5, 0.0)


class TestSvoRemoteFilename:
    def test_content_disposition_header_wins(self):
        class _Head:
            headers = {
                "Content-Disposition": 'attachment; filename="bt-settl_T5000.spec"'
            }

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def geturl(self):
                return "https://svo.example/ssap.php"

        with patch("urllib.request.urlopen", return_value=_Head()):
            assert (
                ds._svo_remote_filename("https://svo.example/x")
                == "bt-settl_T5000.spec"
            )

    def test_falls_back_to_url_basename(self):
        class _Head:
            headers: dict = {}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def geturl(self):
                return "https://svo.example/spectrum.dat"

        with patch("urllib.request.urlopen", return_value=_Head()):
            assert ds._svo_remote_filename("https://svo.example/x") == "spectrum.dat"

    def test_network_error_returns_none(self):
        with patch("urllib.request.urlopen", side_effect=OSError("boom")):
            assert ds._svo_remote_filename("https://svo.example/x") is None


class TestGetSvoModelsMocked:
    def test_parses_mocked_index_page(self):
        with (
            patch.object(ds, "_host_is_reachable", return_value=True),
            patch("urllib.request.urlopen", return_value=_resp(_MODELS_HTML)),
        ):
            models = ds.get_svo_models()
        assert "bt-settl-cifist" in models
        assert models == sorted(models)

    def test_raises_when_offline(self):
        with (
            patch.object(ds, "_host_is_reachable", return_value=False),
            pytest.raises(ConnectionError, match="no network"),
        ):
            ds.get_svo_models()


class TestHostReachable:
    def test_unreachable_host_is_false(self):
        assert (
            ds._host_is_reachable("https://exorad.invalid.nonexistent.example") is False
        )

    def test_url_without_hostname_is_false(self):
        assert ds._host_is_reachable("not a url") is False


def _fake_spectrum():
    wl = np.linspace(3000.0, 30000.0, 300) * u.AA
    flux = (1e-4 * np.exp(-((wl.value - 12000) ** 2) / 5e7)) * (
        u.erg / u.s / u.cm**2 / u.AA
    )
    return wl, flux, {"teff": 5000.0, "model": "fake", "filename": "fake.spec"}


class TestDownloadSedTask:
    def test_svo_backend_returns_a_scaled_sed(self):
        with patch.object(ds, "_fetch_svo", return_value=_fake_spectrum()):
            sed = ds.DownloadSed()(
                R=1.0 * u.R_sun,
                D=10.0 * u.pc,
                T=5000 * u.K,
                logg=4.5,
                model_name="bt-settl-cifist",
            )
        assert isinstance(sed, Sed)
        assert sed.data.unit == u.W / u.m**2 / u.um
        assert np.all(np.isfinite(sed.wl_grid.value))
        assert np.all(np.diff(sed.wl_grid.value) > 0)
        assert sed.meta["model_name"] == "bt-settl-cifist"

    def test_aces_backend_skips_air_to_vacuum(self):
        wl = np.linspace(3000.0, 30000.0, 50) * u.AA
        flux = np.ones(50) * (u.erg / u.s / u.cm**2 / u.cm)
        with patch.object(
            ds, "_fetch_aces", return_value=(wl, flux, {"model": "aces"})
        ):
            sed = ds.DownloadSed()(
                R=1.0 * u.R_sun,
                D=10.0 * u.pc,
                T=5000 * u.K,
                logg=4.5,
                model_name="phoenix-aces",
            )
        assert isinstance(sed, Sed)
        assert sed.data.unit == u.W / u.m**2 / u.um

    def test_geometric_dilution_scales_as_distance_squared(self):
        with patch.object(ds, "_fetch_svo", return_value=_fake_spectrum()):
            near = ds.DownloadSed()(
                R=1.0 * u.R_sun, D=10.0 * u.pc, T=5000 * u.K, logg=4.5
            )
            far = ds.DownloadSed()(
                R=1.0 * u.R_sun, D=20.0 * u.pc, T=5000 * u.K, logg=4.5
            )
        ratio = float(np.nanmax(far.data) / np.nanmax(near.data))
        assert ratio == pytest.approx(0.25, rel=1e-3)

    def test_missing_parameter_raises_keyerror(self):
        with pytest.raises(KeyError, match="star R missing"):
            ds.DownloadSed()(D=10.0 * u.pc, T=5000 * u.K, logg=4.5)

    def test_temperature_without_units_is_assumed_kelvin(self):
        with patch.object(ds, "_fetch_svo", return_value=_fake_spectrum()):
            sed = ds.DownloadSed()(R=1.0 * u.R_sun, D=10.0 * u.pc, T=5000, logg=4.5)
        assert sed is not None
