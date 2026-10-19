import os
import sys

import matplotlib.pyplot as plt
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
    def test_main_entry_point(self, tmp_path):
        out = tmp_path / "cli.h5"
        argv = [
            "exorad",
            "-p",
            payload_file(),
            "-t",
            TARGETS,
            "-o",
            str(out),
        ]
        old = sys.argv
        sys.argv = argv
        disableLogging()
        try:
            exorad.main()
        finally:
            sys.argv = old
            enableLogging()
        assert out.exists()
