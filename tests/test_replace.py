"""``replace=False`` must refuse an existing output early and clearly (E0.2)."""

import pytest

from exorad import exorad


class _StopError(Exception):
    """Raised by the stub that replaces the payload step."""


@pytest.fixture
def stub_payload(monkeypatch):
    def stop(**kwargs):
        raise _StopError

    monkeypatch.setattr(exorad, "preparePayload", stop)


@pytest.fixture
def inputs(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    payload = src / "payload.xml"
    payload.write_text("<root/>")
    targets = src / "targets.csv"
    targets.write_text("star name\n")
    return str(payload), str(targets)


def test_replace_false_existing_output_raises_before_any_work(
    tmp_path, inputs, stub_payload
):
    options, targets = inputs
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    out = out_dir / "result.h5"
    out.write_bytes(b"precious")
    with pytest.raises(FileExistsError) as exc:
        exorad.standard_pipeline(
            options=options, target_list=targets, output=str(out), replace=False
        )
    message = str(exc.value)
    assert str(out) in message
    assert "replace" in message
    # nothing was done: file untouched, no input copy, payload step not reached
    assert out.read_bytes() == b"precious"
    assert sorted(p.name for p in out_dir.iterdir()) == ["result.h5"]


def test_replace_false_new_output_proceeds(tmp_path, inputs, stub_payload):
    options, targets = inputs
    out = tmp_path / "new" / "result.h5"
    with pytest.raises(_StopError):
        exorad.standard_pipeline(
            options=options, target_list=targets, output=str(out), replace=False
        )
    assert (out.parent / "payload.xml").exists()


def test_replace_true_removes_existing_output(tmp_path, inputs, stub_payload):
    options, targets = inputs
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    out = out_dir / "result.h5"
    out.write_bytes(b"old")
    with pytest.raises(_StopError):
        exorad.standard_pipeline(
            options=options, target_list=targets, output=str(out), replace=True
        )
    assert not out.exists()
    assert (out_dir / "payload.xml").exists()
    assert (out_dir / "targets.csv").exists()
