"""H17: HDF5 external links and virtual datasets must be refused, never followed.

``group.get(key)`` (what ``exorad.output.hdf5.load`` and a naive tree walk do)
silently opens the file an ``ExternalLink`` points at, so an output file placed
in the work directory could make the server read attributes and values of ANY
file the server process can open. Each test builds the hostile file in
``tmp_path`` OUTSIDE the sandbox, proves with a naive control that the file
really leaks, and then checks that ``inspect_output``, ``explain_output`` and
``plot_output`` refuse it with a ``ValueError`` that names the offending node but
neither the target path nor anything read from it.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest

from exorad.mcp import outputs, tools_output

SECRET_ATTR = "TOPSECRET-ATTR-VALUE"
SECRET_VALUES = np.arange(5, dtype="float64") + 4242.0


@pytest.fixture
def outside_file(tmp_path: Path) -> Path:
    """A file OUTSIDE every sandbox root holding a secret attribute and values."""
    folder = tmp_path / "outside-secret-dir"
    folder.mkdir()
    path = folder / "secret.h5"
    with h5py.File(path, "w") as handle:
        group = handle.create_group("vault")
        group.attrs["secret"] = SECRET_ATTR
        group.create_dataset("values", data=SECRET_VALUES)
        handle.attrs["secret"] = SECRET_ATTR
    return path


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    path = tmp_path / "mcp-work"
    path.mkdir(exist_ok=True)
    return path


def _tool_calls(name: str):
    return {
        "inspect": lambda: tools_output.inspect_output(name),
        "explain": lambda: tools_output.explain_output(name),
        "plot": lambda: tools_output.plot_output(name),
        "plot_eff": lambda: tools_output.plot_output(name, kind="efficiency"),
    }


def _refused(name: str, secret_path: Path) -> None:
    for label, call in _tool_calls(name).items():
        with pytest.raises(ValueError) as caught:
            call()
        text = str(caught.value)
        assert "external" in text.lower() or "virtual" in text.lower(), label
        assert str(secret_path.parent) not in text, label
        assert secret_path.name not in text, label
        assert SECRET_ATTR not in text, label


def test_naive_walk_really_leaks_the_external_link(
    work_dir: Path, outside_file: Path
) -> None:
    """Control: proves the fixture is hostile, i.e. the tests below can fail."""
    link = work_dir / "naive.h5"
    with h5py.File(link, "w") as handle:
        handle["bad"] = h5py.ExternalLink(str(outside_file), "/vault")
    with h5py.File(link, "r") as handle:
        obj = handle.get("bad")  # what a naive BFS does
        assert obj.attrs["secret"] == SECRET_ATTR
        assert np.array_equal(obj["values"][()], SECRET_VALUES)


def test_hdf5_external_link_is_refused_by_inspect_explain_plot(
    work_dir: Path, outside_file: Path
) -> None:
    link = work_dir / "linked.h5"
    with h5py.File(link, "w") as handle:
        handle.create_group("targets")
        handle["targets/evil"] = h5py.ExternalLink(str(outside_file), "/vault")
    _refused("linked.h5", outside_file)
    with pytest.raises(ValueError, match=r"targets/evil"):
        tools_output.inspect_output("linked.h5")


def test_relative_external_link_is_refused(work_dir: Path, outside_file: Path) -> None:
    """A relative link resolves against the linking file's directory."""
    folder = work_dir / "sub"
    folder.mkdir()
    link = folder / "rel.h5"
    relative = Path("..") / ".." / outside_file.parent.name / outside_file.name
    with h5py.File(link, "w") as handle:
        handle["bad"] = h5py.ExternalLink(str(relative), "/vault")
    _refused("sub/rel.h5", outside_file)


def test_external_link_deep_in_the_tree_is_refused(
    work_dir: Path, outside_file: Path
) -> None:
    link = work_dir / "deep.h5"
    with h5py.File(link, "w") as handle:
        deep = handle.create_group("payload/channels/Phot/built_instr")
        deep["PRF"] = h5py.ExternalLink(str(outside_file), "/vault/values")
    _refused("deep.h5", outside_file)
    with pytest.raises(ValueError, match=r"payload/channels/Phot/built_instr/PRF"):
        tools_output.explain_output("deep.h5")


def test_external_link_to_a_missing_file_is_still_refused(work_dir: Path) -> None:
    """A dangling external link is refused too: it could be satisfied later."""
    link = work_dir / "dangling.h5"
    with h5py.File(link, "w") as handle:
        handle["bad"] = h5py.ExternalLink("/nonexistent/where.h5", "/x")
    with pytest.raises(ValueError, match="external"):
        tools_output.inspect_output("dangling.h5")


def test_virtual_dataset_is_refused(work_dir: Path, outside_file: Path) -> None:
    link = work_dir / "virtual.h5"
    layout = h5py.VirtualLayout(shape=(5,), dtype="float64")
    layout[:] = h5py.VirtualSource(str(outside_file), "vault/values", shape=(5,))
    with h5py.File(link, "w") as handle:
        handle.create_virtual_dataset("targets_vds", layout, fillvalue=-1.0)
    with h5py.File(link, "r") as handle:  # control: a naive read leaks the values
        assert np.array_equal(handle["targets_vds"][()], SECRET_VALUES)
    _refused("virtual.h5", outside_file)
    with pytest.raises(ValueError, match="targets_vds"):
        tools_output.inspect_output("virtual.h5")


def test_dataset_with_external_storage_is_refused(
    work_dir: Path, outside_file: Path
) -> None:
    """Raw data kept in another file (``H5Pset_external``) is the same leak."""
    raw = outside_file.parent / "raw.bin"
    raw.write_bytes(SECRET_VALUES.tobytes())
    link = work_dir / "extstore.h5"
    with h5py.File(link, "w") as handle:
        handle.create_dataset(
            "ext", shape=(5,), dtype="float64", external=[(str(raw), 0, 40)]
        )
    with h5py.File(link, "r") as handle:  # control
        assert np.array_equal(handle["ext"][()], SECRET_VALUES)
    for call in _tool_calls("extstore.h5").values():
        with pytest.raises(ValueError, match="external"):
            call()


def test_soft_links_stay_inside_the_file_and_are_not_followed(work_dir: Path) -> None:
    """Soft links (including dangling and cyclic ones) are listed, never followed."""
    path = work_dir / "soft.h5"
    with h5py.File(path, "w") as handle:
        handle.create_group("a").attrs["k"] = 1
        handle["alias"] = h5py.SoftLink("/a")
        handle["dangling"] = h5py.SoftLink("/nope")
        handle["loop"] = h5py.SoftLink("/loop")
    result = tools_output.inspect_output("soft.h5")
    kinds = {item["path"]: item["type"] for item in result["items"]}
    assert kinds["alias"] == "softlink"
    assert kinds["dangling"] == "softlink"
    assert kinds["loop"] == "softlink"
    assert result["total_nodes"] == 4


def test_hard_link_cycle_terminates(work_dir: Path) -> None:
    path = work_dir / "cycle.h5"
    with h5py.File(path, "w") as handle:
        group = handle.create_group("a")
        group["back"] = handle  # hard link to the root group
    result = tools_output.inspect_output("cycle.h5")
    assert result["total_nodes"] <= 3


def test_scan_runs_before_any_attribute_is_read(
    work_dir: Path, outside_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal happens before the walk: no ``attrs`` access on any object."""
    link = work_dir / "order.h5"
    with h5py.File(link, "w") as handle:
        handle.attrs["marker"] = "root"
        handle["bad"] = h5py.ExternalLink(str(outside_file), "/vault")
    opened: list[str] = []
    real = h5py.File.__getitem__

    def spy(self, name):
        opened.append(str(name))
        return real(self, name)

    monkeypatch.setattr(h5py.File, "__getitem__", spy)
    with pytest.raises(ValueError):
        tools_output.inspect_output("order.h5")
    assert "bad" not in opened


def test_scan_function_names_the_node(work_dir: Path, outside_file: Path) -> None:
    link = work_dir / "scan.h5"
    with h5py.File(link, "w") as handle:
        handle["x/y"] = h5py.ExternalLink(str(outside_file), "/vault")
    with pytest.raises(ValueError) as caught:
        outputs.scan_hdf5(link)
    assert "x/y" in str(caught.value)
    assert str(outside_file.parent) not in str(caught.value)
