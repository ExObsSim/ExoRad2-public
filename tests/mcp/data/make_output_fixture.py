"""Regenerate ``tests/mcp/data/radiometric_small.h5.xz`` (a small REAL ExoRad output).

Run from the repository root (no network, a few seconds)::

    EXORAD_NO_VERSION_CHECK=1 python tests/mcp/data/make_output_fixture.py

Recipe
------
1. ``examples/payload_example.xml`` with ``<ConfigPath>`` set to the checkout,
   ``working_R`` 6000 -> 1000, ``CustomSed`` -> ``examples/customsed_demo.csv``
   and the sky-filter table ``modtran_*.csv`` decimated 8:1 (every 8th row);
2. the first line of ``examples/test_target.csv`` (target ``myTest``);
3. ``exorad.standard_pipeline(payload, targets, output=..., n_thread=1)``;
4. a SLIMMING pass (the raw file is 2.4 MB): the 256x256 photometer
   point-response image ``built_instr/PRF`` (0.5 MB, incompressible) is cropped
   to its central 64x64 pixels, the time stamp is frozen and every string that
   contains the checkout path is rewritten to ``/fixture-root`` so that the
   file carries no machine path;
5. the result (1.3 MB, 731 datasets: HDF5 object headers dominate) is stored
   xz-compressed, about 170 kB, which is the committed fixture; tests unpack it
   into a temporary directory.

Everything else (tree, tables, units, attributes) is exactly what the pipeline
wrote, so the tests exercise the real layout.
"""

from __future__ import annotations

import lzma
import os
import sys
import tempfile
from pathlib import Path

import h5py
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
DEST = Path(__file__).resolve().parent / "radiometric_small.h5.xz"
FROZEN_TIME = "2026-01-01T00:00:00.000000"
PLACEHOLDER = "/fixture-root"


def _decimate_ecsv(src: Path, dst: Path, step: int = 8) -> None:
    lines = src.read_text(encoding="utf-8").splitlines()
    header = [i for i, line in enumerate(lines) if line.startswith("#")]
    first_data = header[-1] + 2  # one column-name row follows the comments
    kept = lines[:first_data] + lines[first_data::step]
    dst.write_text("\n".join(kept) + "\n", encoding="utf-8")


def _scrub(value, roots):
    if isinstance(value, bytes):
        text = value.decode("utf-8", "replace")
        for root in roots:
            text = text.replace(root, PLACEHOLDER)
        return text.encode("utf-8")
    if isinstance(value, str):
        for root in roots:
            value = value.replace(root, PLACEHOLDER)
    return value


def slim(src: Path, dst: Path, roots: list[str]) -> None:
    """Copy ``src`` to ``dst`` compressed, with PRF cropped and paths scrubbed."""

    def attrs(source, target) -> None:
        for key, val in source.attrs.items():
            target.attrs[key] = _scrub(val, roots)

    def walk(sg, dg) -> None:
        for key in sg:
            obj = sg[key]
            if isinstance(obj, h5py.Group):
                child = dg.create_group(key, track_order=False)
                attrs(obj, child)
                walk(obj, child)
                continue
            data = obj[()]
            if key == "PRF" and data.ndim == 2:
                cy, cx = (n // 2 for n in data.shape)
                data = data[cy - 32 : cy + 32, cx - 32 : cx + 32]
            if isinstance(data, bytes):
                data = _scrub(data, roots)
            new = dg.create_dataset(key, data=data, track_times=False)
            attrs(obj, new)

    with h5py.File(src, "r") as s, h5py.File(dst, "w", libver="latest") as d:
        attrs(s, d)
        d.attrs["file_time"] = FROZEN_TIME
        d.attrs["file_name"] = "radiometric_small.h5"
        walk(s, d)
        for node in ("info/ExoRad/file_name",):
            if node in d:
                del d[node]
                d[node] = np.bytes_("radiometric_small.h5")
        if "info/ExoRad/file_time" in d:
            del d["info/ExoRad/file_time"]
            d["info/ExoRad/file_time"] = np.bytes_(FROZEN_TIME)


def main(dest: Path = DEST) -> Path:
    os.environ.setdefault("EXORAD_NO_VERSION_CHECK", "1")
    os.environ.setdefault("MPLBACKEND", "Agg")
    import exorad

    with tempfile.TemporaryDirectory(prefix="exorad-fixture-") as tmp:
        work = Path(tmp)
        sky = work / "sky.csv"
        _decimate_ecsv(ROOT / "examples/modtran_38km_sun_180az_55zd_los_45zd.csv", sky)
        text = (ROOT / "examples/payload_example.xml").read_text(encoding="utf-8")
        text = text.replace("<ConfigPath> .", f"<ConfigPath> {ROOT}", 1)
        text = text.replace("<working_R> 6000", "<working_R> 1000", 1)
        text = text.replace(
            "examples/customsed.csv</CustomSed>",
            "examples/customsed_demo.csv</CustomSed>",
        )
        text = text.replace(
            "__ConfigPath__/examples/modtran_38km_sun_180az_55zd_los_45zd.csv", str(sky)
        )
        (work / "payload.xml").write_text(text, encoding="utf-8")
        rows = (ROOT / "examples/test_target.csv").read_text().splitlines()[:2]
        (work / "target.csv").write_text("\n".join(rows) + "\n")
        cwd = os.getcwd()
        os.chdir(work)
        try:
            exorad.standard_pipeline(
                "payload.xml", "target.csv", output="raw/out.h5", n_thread=1
            )
        finally:
            os.chdir(cwd)
        small = work / "radiometric_small.h5"
        slim(work / "raw/out.h5", small, [str(ROOT), str(work), str(work.resolve())])
        dest.write_bytes(lzma.compress(small.read_bytes(), preset=9))
    return dest


if __name__ == "__main__":
    out = main()
    print(f"{out} {out.stat().st_size} bytes", file=sys.stderr)
