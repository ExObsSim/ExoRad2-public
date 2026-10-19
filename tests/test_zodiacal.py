import astropy.units as u
import numpy as np

from exorad.models.foregrounds.zodiacalForeground import ZodiacalFrg

WL = np.logspace(np.log10(0.5), np.log10(5.0), 200) * u.um
COORD = (90.038 * u.deg, -66.554 * u.deg)


class TestZodiacalFrg:
    def test_model_factor(self):
        zodi = ZodiacalFrg(WL, {"zodiacFactor": {"value": 2.5}})
        assert zodi.radiance.data.unit.is_equivalent(u.W / u.m**2 / u.um / u.sr)
        assert np.all(zodi.radiance.data.value > 0)

    def test_zero_factor_scales_to_zero(self):
        zodi = ZodiacalFrg(WL, {"zodiacFactor": {"value": 0.0}})
        assert np.all(zodi.radiance.data.value == 0.0)

    def test_incomplete_description_defaults_to_zero(self):
        zodi = ZodiacalFrg(WL, {})
        assert np.all(zodi.radiance.data.value == 0.0)

    def test_map_fit(self):
        zodi = ZodiacalFrg(WL, {"zodiacalMap": {"value": True}}, coordinates=COORD)
        assert np.all(zodi.radiance.data.value >= 0)

    def test_map_fit_failure_falls_back_to_zero(self, monkeypatch):
        def boom(self, *a, **k):
            raise OSError("no map")

        monkeypatch.setattr(ZodiacalFrg, "zodiacal_fit_direction", boom)
        zodi = ZodiacalFrg(WL, {"zodiacalMap": {"value": True}}, coordinates=COORD)
        # fit failed -> radiance recomputed with no coordinates -> A = 0
        assert np.all(zodi.radiance.data.value == 0.0)

    def test_custom_map_file(self):
        # a custom_map_file that resolves to the bundled map still works
        import os

        from exorad.models.foregrounds import zodiacalForeground

        pkg = os.path.dirname(os.path.dirname(zodiacalForeground.__file__))
        bundled = os.path.join(pkg, "data", "Zodi_map.hdf5")
        zodi = ZodiacalFrg(
            WL,
            {
                "zodiacalMap": {"value": True},
                "custom_map_file": {"value": bundled},
            },
            coordinates=COORD,
        )
        assert np.all(zodi.radiance.data.value >= 0)
