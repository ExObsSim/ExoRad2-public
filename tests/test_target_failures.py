"""A bad target must not cost the good ones (E0.1) and names must be safe."""

import logging
import os
import pathlib
from copy import deepcopy

import h5py
import pytest
from click.testing import CliRunner
from test_options import payload_file

import exorad.tasks as tasks
from exorad import exorad
from exorad.log import disableLogging, enableLogging
from exorad.tasks import targetHandler

path = pathlib.Path(__file__).parent.absolute()
EXAMPLE_TARGETS = os.path.join(path.parent, "examples", "test_target.csv")

CSV_HEADER = (
    "star name,star M [M_sun],star Teff [K],star R [R_sun],star D [pc],"
    "star magk,star ra [deg],star dec [deg]\n"
)
THREE_TARGETS = (
    CSV_HEADER
    + "goodA,1,5000,1,20,0,90,18\n"
    + "badB,1,5000,1,20,0,90,18\n"
    + "goodC,1.5,6000,1,10,0,331,19\n"
)


def _break(target):
    """Make the observation of ``target`` fail ('target information incomplete')."""
    # the example payload uses a custom SED: only R and D are needed, and a
    # value without a unit -> AttributeError("target information incomplete")
    target.star.D = 20.0
    return target


@pytest.fixture(scope="module")
def prepared():
    """Payload and channels of the example, built once (no output)."""
    payload = tasks.LoadOptions()(filename=payload_file())
    wl = (payload["common"]["wl_min"]["value"], payload["common"]["wl_max"]["value"])
    channels = tasks.BuildChannels()(payload=payload, write=False, output=None)
    return payload, channels, wl


@pytest.fixture
def three_targets(tmp_path):
    csv = tmp_path / "three.csv"
    csv.write_text(THREE_TARGETS)
    return tasks.LoadTargetList()(target_list=str(csv)).target


def _observe(prepared, targets, **kw):
    payload, channels, wl = prepared
    disableLogging()
    try:
        return tasks.ObserveTargetlist()(
            targets=targets,
            payload=payload,
            channels=channels,
            wl_range=wl,
            plot=kw.pop("plot", False),
            out_dir=kw.pop("out_dir", None),
            **kw,
        )
    finally:
        enableLogging()


@pytest.mark.parametrize("n_thread", [1, 2])
def test_good_targets_survive_a_bad_one(prepared, three_targets, n_thread, caplog):
    three_targets[1] = _break(three_targets[1])
    with caplog.at_level(logging.WARNING):
        result = _observe(prepared, three_targets, n_thread=n_thread)
    assert list(result) == ["goodA", "goodC"]
    assert None not in result
    assert all(v is not None for v in result.values())
    assert "badB" in caplog.text


def test_all_targets_bad_raises_a_clear_error(prepared, three_targets):
    targets = [_break(t) for t in three_targets]
    with pytest.raises(RuntimeError, match="no target") as exc:
        _observe(prepared, targets, n_thread=1)
    for name in ("goodA", "badB", "goodC"):
        assert name in str(exc.value)


def test_duplicate_target_names_are_refused(prepared, three_targets):
    three_targets[2].name = three_targets[0].name
    with pytest.raises(ValueError, match="goodA"):
        _observe(prepared, three_targets)


def test_standard_pipeline_writes_every_good_target(tmp_path, monkeypatch):
    csv = tmp_path / "three.csv"
    csv.write_text(THREE_TARGETS)
    original = exorad.loadTargetList

    def with_bad_target(**kwargs):
        targets = original(**kwargs)
        targets.target[1] = _break(targets.target[1])
        return targets

    monkeypatch.setattr(exorad, "loadTargetList", with_bad_target)
    out = tmp_path / "out" / "result.h5"
    out.parent.mkdir()
    out.write_bytes(b"not an hdf5 file")  # replace=True (default) overwrites it
    disableLogging()
    try:
        exorad.standard_pipeline(
            options=payload_file(), target_list=str(csv), output=str(out)
        )
    finally:
        enableLogging()
    with h5py.File(out, "r") as f:
        assert sorted(f["targets"]) == ["goodA", "goodC"]


class _FakeTarget:
    def __init__(self, name):
        self.name = name
        self.table = None


def test_plot_file_name_cannot_escape_output_dir(tmp_path, monkeypatch):
    saved = []

    class FakePlotter:
        def __init__(self, **kwargs):
            pass

        def plot_table(self):
            pass

        def save_fig(self, fname, *args, **kwargs):
            saved.append(fname)

    class FakeObserve:
        def __call__(self, target, **kwargs):
            return target

    from exorad.utils import plotter

    monkeypatch.setattr(plotter, "Plotter", FakePlotter)
    monkeypatch.setattr(tasks, "ObserveTarget", FakeObserve)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    for name in ["../x", "../../etc/y", "a/b", "..", ".hidden"]:
        name_, result = targetHandler.pipeline_to_dict(
            _FakeTarget(name), {}, {}, (0, 1), True, str(out_dir), True
        )
        assert name_ == name
        assert result is not None
    assert len(saved) == 5
    for fname in saved:
        resolved = pathlib.Path(fname).resolve()
        assert resolved.parent == out_dir.resolve(), fname
        assert resolved.suffix == ".png"
    assert not (tmp_path / "x.png").exists()


def test_sanitised_name_keeps_ordinary_names():
    assert targetHandler.safe_file_stem("HD 209458 b") == "HD 209458 b"
    assert targetHandler.safe_file_stem("GJ 1214_b+") == "GJ 1214_b+"
    assert "/" not in targetHandler.safe_file_stem("../x")
    assert not targetHandler.safe_file_stem("../x").startswith(".")
    assert targetHandler.safe_file_stem("..") != ".."


def test_failed_pipeline_to_dict_keeps_the_name(prepared):
    payload, channels, wl = prepared
    target = _break(
        deepcopy(tasks.LoadTargetList()(target_list=EXAMPLE_TARGETS).target[0])
    )
    disableLogging()
    try:
        name, result = targetHandler.pipeline_to_dict(
            target, payload, channels, wl, False, None, False
        )
    finally:
        enableLogging()
    assert name == "myTest"
    assert result is None


# -- exit code of the command line on a partial run ---------------------------
def _patch_bad_second(monkeypatch):
    original = exorad.loadTargetList

    def with_bad_target(**kwargs):
        targets = original(**kwargs)
        targets.target[1] = _break(targets.target[1])
        return targets

    monkeypatch.setattr(exorad, "loadTargetList", with_bad_target)


def test_standard_pipeline_returns_the_skipped_names(tmp_path, monkeypatch):
    csv = tmp_path / "three.csv"
    csv.write_text(THREE_TARGETS)
    _patch_bad_second(monkeypatch)
    disableLogging()
    try:
        skipped = exorad.standard_pipeline(
            options=payload_file(), target_list=str(csv), output=str(tmp_path / "o.h5")
        )
    finally:
        enableLogging()
    assert skipped == ["badB"]


def test_main_exits_nonzero_when_a_target_was_skipped(tmp_path, monkeypatch):
    csv = tmp_path / "three.csv"
    csv.write_text(THREE_TARGETS)
    _patch_bad_second(monkeypatch)
    out = tmp_path / "cli.h5"
    monkeypatch.setenv("EXORAD_NO_VERSION_CHECK", "1")
    disableLogging()
    try:
        result = CliRunner().invoke(
            exorad.main, ["-p", payload_file(), "-t", str(csv), "-o", str(out)]
        )
    finally:
        enableLogging()
    assert result.exit_code == 1
    with h5py.File(out, "r") as f:  # the good targets were written first
        assert sorted(f["targets"]) == ["goodA", "goodC"]
    assert "exorad: 1 target(s) skipped: badB" in result.output


# -- duplicate names are refused before anything is written -------------------
@pytest.mark.parametrize("n_thread", [1, 2])
def test_duplicate_names_leave_no_output_file(tmp_path, n_thread):
    csv = tmp_path / "dup.csv"
    csv.write_text(CSV_HEADER + "same,1,5000,1,20,0,90,18\nsame,1,6000,1,10,0,331,19\n")
    out = tmp_path / "out" / "result.h5"
    disableLogging()
    try:
        with pytest.raises(ValueError, match="same"):
            exorad.standard_pipeline(
                options=payload_file(),
                target_list=str(csv),
                output=str(out),
                n_thread=n_thread,
            )
    finally:
        enableLogging()
    assert not out.exists()
    assert not out.parent.exists()
