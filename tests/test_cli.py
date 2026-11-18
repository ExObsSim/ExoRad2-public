import os

import matplotlib.pyplot as plt
from click.testing import CliRunner
from test_options import payload_file

from exorad import exorad
from exorad.log import disableLogging, enableLogging

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples"
)
TARGETS = os.path.join(DATA_DIR, "test_target.csv")


class TestStandardPipeline:
    def test_writes_output_and_copies_inputs(self, tmp_path):
        out = tmp_path / "run" / "results.h5"
        disableLogging()
        exorad.standard_pipeline(
            options=payload_file(),
            target_list=TARGETS,
            output=str(out),
        )
        enableLogging()
        assert out.exists()
        # inputs are copied next to the output for reproducibility
        assert (out.parent / "test_target.csv").exists()

    def test_plot_and_full_contrib_and_debug(self, tmp_path):
        out = tmp_path / "results.h5"
        disableLogging()
        exorad.standard_pipeline(
            options=payload_file(),
            target_list=TARGETS,
            output=str(out),
            plot=True,
            full_contrib=True,
            debug=True,
            log=str(tmp_path / "run.log"),
        )
        enableLogging()
        plt.close("all")
        assert out.exists()
        assert (out.parent / "efficiency.png").exists()
        assert (tmp_path / "run.log").exists()

    def test_runs_without_output(self):
        disableLogging()
        exorad.standard_pipeline(options=payload_file(), target_list=TARGETS)
        enableLogging()


class TestMainCli:
    def test_main_entry_point(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EXORAD_NO_VERSION_CHECK", "1")
        out = tmp_path / "cli.h5"
        disableLogging()
        try:
            result = CliRunner().invoke(
                exorad.main,
                ["-p", payload_file(), "-t", TARGETS, "-o", str(out)],
            )
        finally:
            enableLogging()
        assert result.exit_code == 0, result.output
        assert out.exists()

    def test_hyphenated_and_camel_case_aliases(self, monkeypatch):
        seen = {}

        def fake(**kw):
            seen.update(kw)
            return []

        monkeypatch.setenv("EXORAD_NO_VERSION_CHECK", "1")
        monkeypatch.setattr(exorad, "standard_pipeline", fake)
        for flags in (
            ["--target-list", TARGETS, "--n-threads", "3", "--full-contrib"],
            ["--targetList", TARGETS, "--nThreads", "3", "--full_contrib"],
            ["-t", TARGETS, "-n", "3", "-c"],
        ):
            result = CliRunner().invoke(exorad.main, ["-p", payload_file(), *flags])
            assert result.exit_code == 0, result.output
            assert seen["n_thread"] == 3
            assert seen["full_contrib"] is True
            assert seen["target_list"] == TARGETS

    def test_short_flags_map_to_pipeline_arguments(self, monkeypatch, tmp_path):
        seen = {}
        monkeypatch.setenv("EXORAD_NO_VERSION_CHECK", "1")
        monkeypatch.setattr(
            exorad, "standard_pipeline", lambda **kw: seen.update(kw) or []
        )
        out = str(tmp_path / "o.h5")
        result = CliRunner().invoke(
            exorad.main,
            ["-p", payload_file(), "-t", TARGETS, "-o", out, "-d", "-l", "-P"],
        )
        assert result.exit_code == 0, result.output
        assert seen["output"] == out
        assert seen["debug"] is True
        assert seen["log"] is True
        assert seen["plot"] is True
        assert seen["full_contrib"] is False
        assert seen["n_thread"] == 1

    def test_version_flag(self):
        result = CliRunner().invoke(exorad.main, ["--version"])
        assert result.exit_code == 0
        assert f"ExoRad v{exorad.version.__version__}" in result.output

    def test_help_shows_the_version_string_not_the_module(self):
        result = CliRunner().invoke(exorad.main, ["--help"])
        assert result.exit_code == 0
        assert "<module" not in result.output
        assert exorad.version.__version__ in result.output
        for flag in ("--payload", "--target-list", "--output", "--full-contrib"):
            assert flag in result.output

    def test_missing_payload_file_is_rejected(self, tmp_path):
        result = CliRunner().invoke(
            exorad.main,
            ["-p", str(tmp_path / "nope.xml"), "-t", TARGETS],
        )
        assert result.exit_code == 2
        assert "nope.xml" in result.output

    def test_missing_target_list_is_rejected(self, tmp_path):
        result = CliRunner().invoke(
            exorad.main,
            ["-p", payload_file(), "-t", str(tmp_path / "nope.csv")],
        )
        assert result.exit_code == 2

    def test_required_options(self):
        result = CliRunner().invoke(exorad.main, [])
        assert result.exit_code == 2

    def test_version_check_is_invoked(self, monkeypatch):
        calls = []
        monkeypatch.delenv("EXORAD_NO_VERSION_CHECK", raising=False)
        monkeypatch.setattr(exorad, "check_version", lambda: calls.append(1))
        monkeypatch.setattr(exorad, "standard_pipeline", lambda **kw: [])
        result = CliRunner().invoke(exorad.main, ["-p", payload_file(), "-t", TARGETS])
        assert result.exit_code == 0, result.output
        assert calls == [1]

    def test_version_check_is_skipped_with_env_var(self, monkeypatch):
        calls = []

        class Recorder:
            def __init__(self, *args, **kwargs):
                calls.append(1)

        monkeypatch.setenv("EXORAD_NO_VERSION_CHECK", "1")
        monkeypatch.setattr(exorad, "VersionControl", Recorder)
        monkeypatch.setattr(exorad.version, "__version__", "2.3.0")
        monkeypatch.setattr(exorad, "standard_pipeline", lambda **kw: [])
        result = CliRunner().invoke(exorad.main, ["-p", payload_file(), "-t", TARGETS])
        assert result.exit_code == 0, result.output
        assert calls == []

    def test_help_and_version_do_not_check_the_network(self, monkeypatch):
        def boom():
            raise AssertionError("version check ran")

        monkeypatch.setattr(exorad, "check_version", boom)
        for args in (["--help"], ["--version"]):
            assert CliRunner().invoke(exorad.main, args).exit_code == 0

    def test_exit_code_1_and_stderr_when_a_target_was_skipped(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("EXORAD_NO_VERSION_CHECK", "1")
        monkeypatch.setattr(exorad, "standard_pipeline", lambda **kw: ["badB", "x"])
        result = CliRunner().invoke(exorad.main, ["-p", payload_file(), "-t", TARGETS])
        assert result.exit_code == 1
        assert "exorad: 2 target(s) skipped: badB, x" in result.output
