"""The online version check must run only from the CLI, never at import (E0.3)."""

import json
import os
import subprocess
import sys
import textwrap

import pytest
from click.testing import CliRunner
from test_options import payload_file

from exorad import exorad
from exorad.utils.version_control import VersionControl

PAYLOAD = payload_file()
TARGETS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "examples",
    "test_target.csv",
)

# Runs in a fresh interpreter: a RELEASE version is forced (a dev version skips
# the check, which would make the test vacuous), every socket entry point
# records and raises, then ``exorad`` is imported.
_CHILD = textwrap.dedent(
    """
    import importlib.abc
    import importlib.machinery
    import json
    import socket
    import sys

    calls = []

    def _record(name):
        def _raiser(*args, **kwargs):
            calls.append(name)
            raise OSError(f"network blocked by test: {name}")

        return _raiser

    socket.socket.connect = _record("socket.connect")
    socket.create_connection = _record("socket.create_connection")
    socket.getaddrinfo = _record("socket.getaddrinfo")

    class _Loader(importlib.abc.Loader):
        def create_module(self, spec):
            return None

        def exec_module(self, module):
            module.__version__ = "2.3.0"

    class _Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path, target=None):
            if fullname == "exorad.__version__":
                return importlib.machinery.ModuleSpec(fullname, _Loader())
            return None

    sys.meta_path.insert(0, _Finder())

    import exorad

    print(json.dumps({"version": exorad.__version__.__version__, "calls": calls}))
    """
)


def _run_child(extra_env=None):
    env = {k: v for k, v in os.environ.items() if k != "EXORAD_NO_VERSION_CHECK"}
    env.update(extra_env or {})
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_import_exorad_makes_no_network_call_release_version():
    result = _run_child()
    # non-vacuous: the child really saw a release version
    assert result["version"] == "2.3.0"
    assert result["calls"] == []


class _Recorder:
    calls = 0

    def __init__(self, *args, **kwargs):
        type(self).calls += 1


@pytest.fixture
def recorder(monkeypatch):
    _Recorder.calls = 0
    monkeypatch.setattr(exorad, "VersionControl", _Recorder)
    monkeypatch.delenv("EXORAD_NO_VERSION_CHECK", raising=False)
    monkeypatch.setattr(exorad.version, "__version__", "2.3.0")
    return _Recorder


def test_check_version_runs_for_release(recorder):
    exorad.check_version()
    assert recorder.calls == 1


def test_check_version_skipped_for_dev_version(recorder, monkeypatch):
    monkeypatch.setattr(exorad.version, "__version__", "2.3.0.dev0")
    exorad.check_version()
    assert recorder.calls == 0


def test_check_version_honours_env_variable(recorder, monkeypatch):
    monkeypatch.setenv("EXORAD_NO_VERSION_CHECK", "1")
    exorad.check_version()
    assert recorder.calls == 0


def test_cli_main_runs_the_check(recorder, monkeypatch):
    monkeypatch.setattr(exorad, "standard_pipeline", lambda **kw: [])
    result = CliRunner().invoke(exorad.main, ["-p", PAYLOAD, "-t", TARGETS])
    assert result.exit_code == 0, result.output
    assert recorder.calls == 1


def test_version_control_itself_honours_env_variable(monkeypatch):
    monkeypatch.setenv("EXORAD_NO_VERSION_CHECK", "1")

    def _boom(*args, **kwargs):
        raise AssertionError("network contacted")

    monkeypatch.setattr(VersionControl, "_check_internet", _boom)
    VersionControl()


def test_cli_main_skips_the_check_with_env(recorder, monkeypatch):
    monkeypatch.setenv("EXORAD_NO_VERSION_CHECK", "1")
    monkeypatch.setattr(exorad, "standard_pipeline", lambda **kw: [])
    result = CliRunner().invoke(exorad.main, ["-p", PAYLOAD, "-t", TARGETS])
    assert result.exit_code == 0, result.output
    assert recorder.calls == 0


def _plot_args(tmp_path):
    # an existing (but not HDF5) input: click accepts it, h5py then fails, so
    # the version check has demonstrably run first
    bad = tmp_path / "not_hdf5.h5"
    bad.write_text("x")
    return ["-i", str(bad), "-o", str(tmp_path / "plots")]


def test_plot_cli_main_runs_the_check(recorder, tmp_path):
    from exorad.utils import plotter

    result = CliRunner().invoke(plotter.main, _plot_args(tmp_path))
    assert isinstance(result.exception, OSError)
    assert recorder.calls == 1


def test_plot_cli_main_skips_the_check_with_env(recorder, monkeypatch, tmp_path):
    from exorad.utils import plotter

    monkeypatch.setenv("EXORAD_NO_VERSION_CHECK", "1")
    result = CliRunner().invoke(plotter.main, _plot_args(tmp_path))
    assert isinstance(result.exception, OSError)
    assert recorder.calls == 0
