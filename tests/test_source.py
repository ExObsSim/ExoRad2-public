import astropy.units as u
import numpy as np
import pytest

from exorad.models.source import CustomSed, Star

TARGET = {
    "D": 12.975 * u.pc,
    "T": 3016 * u.K,
    "M": 0.15 * u.Msun,
    "R": 0.218 * u.Rsun,
}


class TestPlanckStar:
    def test_builds_blackbody_sed(self):
        star = Star(
            ".",
            TARGET["D"],
            TARGET["T"],
            0.0,
            0.0,
            TARGET["R"],
            use_planck_spectrum=True,
        )
        assert star.model == "Planck"
        assert star.sed.data.unit.is_equivalent(u.W / u.m**2 / u.um)
        assert star.luminosity.unit.is_equivalent(u.Lsun)
        assert star.sed.wl_grid.min() >= 0.2 * u.um


class TestPhoenixStar:
    def test_reads_bt_settl_spectrum(self, phoenix_dir):
        g = 10**4.5
        star = Star(
            phoenix_dir,
            TARGET["D"],
            TARGET["T"],
            np.log10(g),
            0.0,
            TARGET["R"],
            use_planck_spectrum=False,
        )
        assert "BT-Settl" in star.model
        assert star.sed.data.unit.is_equivalent(u.W / u.m**2 / u.um)
        assert star.filename.endswith(".spec.fits.gz")

    def test_explicit_model_filename(self, phoenix_dir):
        star = Star(
            phoenix_dir,
            TARGET["D"],
            TARGET["T"],
            4.5,
            0.0,
            TARGET["R"],
            use_planck_spectrum=False,
            phoenix_model_filename="lte030-4.5-0.0.BT-Settl.spec.fits.gz",
        )
        assert star.sed is not None

    def test_temperature_outside_grid_raises(self, phoenix_dir):
        with pytest.raises(ValueError):
            Star(
                phoenix_dir,
                TARGET["D"],
                9000 * u.K,
                4.5,
                0.0,
                TARGET["R"],
                use_planck_spectrum=False,
            )

    def test_missing_sed_files_raises(self, tmp_path):
        with pytest.raises(OSError):
            Star(
                str(tmp_path),
                TARGET["D"],
                TARGET["T"],
                4.5,
                0.0,
                TARGET["R"],
                use_planck_spectrum=False,
            )


class TestCustomSed:
    def test_reads_ecsv(self, tmp_path):
        path = tmp_path / "sed.ecsv"
        path.write_text(
            "# %ECSV 1.0\n"
            "# ---\n"
            "# datatype:\n"
            "# - {name: Wavelength, unit: um, datatype: float64}\n"
            "# - {name: Sed, unit: W / (m2 um), datatype: float64}\n"
            "Wavelength Sed\n"
            "1.0 10.0\n"
            "2.0 8.0\n"
            "3.0 6.0\n"
        )
        sed = CustomSed(str(path), TARGET["R"], TARGET["D"])
        assert sed.model == "Custom"
        assert sed.luminosity.unit.is_equivalent(u.Lsun)
        assert sed.sed.data.unit.is_equivalent(u.W / u.m**2 / u.um)
