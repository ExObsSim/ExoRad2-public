"""Scientific numbers must not change with the E0 library fixes.

The reference ``test_data/example_tables_digest.json`` was generated from the
unchanged ``release/2.3`` code (before E0.1-E0.3). The test reruns the example
payload and target list and compares every numeric dataset/column written to the
HDF5 output (the ``info`` group, which holds timestamps, is ignored).

Bit-for-bit hashes depend on the platform and on the numpy build, so the default
comparison is a per-dataset numeric summary (shape, dtype kind, sum, min, max and
five fixed sample points at 12 significant digits) checked with ``rtol=1e-9``;
integers, booleans and strings are exact. Set ``EXORAD_BITWISE_REFERENCE=1`` to
also compare the old SHA-256 digests: that is only meaningful on the platform
that generated them (recorded in the file; skipped elsewhere).

Regenerate the reference ONLY for an intended scientific change, from the
changed code, with ``python tests/test_science_invariance.py --regenerate``.
"""

import hashlib
import json
import os
import platform
import sys

import h5py
import numpy as np
import pytest
from test_options import payload_file

from exorad import exorad
from exorad.log import disableLogging, enableLogging

HERE = os.path.dirname(os.path.abspath(__file__))
TARGETS = os.path.join(os.path.dirname(HERE), "examples", "test_target.csv")
REFERENCE = os.path.join(HERE, "test_data", "example_tables_digest.json")
BITWISE_ENV = "EXORAD_BITWISE_REFERENCE"
RTOL = 1e-9
SAMPLE_FRACTIONS = (0.0, 0.25, 0.5, 0.75, 1.0)


def _sha(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()[:16]


def _datasets(path):
    """Yield ``(name, ndarray)`` for every numeric/string dataset or column."""
    items = []
    with h5py.File(path, "r") as f:

        def visit(name, obj):
            if name.startswith("info") or not isinstance(obj, h5py.Dataset):
                return
            a = obj[()]
            if not isinstance(a, np.ndarray):
                return
            if a.dtype.kind in "fiucbSU":
                items.append((name, a))
            elif a.dtype.names:
                for n in a.dtype.names:
                    col = np.ascontiguousarray(a[n])
                    if col.dtype.kind in "fiucbSU":
                        items.append((f"{name}[{n}]", col))

        f.visititems(visit)
    return items


def digest_h5(path):
    """SHA-256 digest of the raw bytes of every numeric dataset/column."""
    return {n: _sha(a) for n, a in _datasets(path) if a.dtype.kind in "fiucb"}


def _g12(value):
    """A float at 12 significant digits (JSON-safe: non-finite -> text)."""
    value = float(value)
    return value if np.isfinite(value) else str(value)


# Short keys keep the reference small: s shape, k kind, n non-finite count,
# x fixed sample points, S sum, A sum of |x|, m min, M max, v string values,
# h SHA-256 digest (added in the reference file only).
def _summary(a):
    kind = a.dtype.kind
    if kind in "SU":
        text = [x.decode() if isinstance(x, bytes) else str(x) for x in a.ravel()]
        return {"s": list(a.shape), "k": "S", "v": text[:50]}
    if kind == "c":
        a = np.concatenate([a.real.ravel(), a.imag.ravel()])
        kind = "f"
    flat = np.ascontiguousarray(a).ravel()
    # up to five elements: every value is a sample point, no aggregate needed
    short = flat.size <= len(SAMPLE_FRACTIONS)
    index = (
        list(range(flat.size))
        if short
        else sorted(
            {min(int(f * (flat.size - 1)), flat.size - 1) for f in SAMPLE_FRACTIONS}
        )
    )
    if flat.size == 0:
        return {"s": list(a.shape), "k": kind}
    if kind in "iub":
        ints = flat.astype(np.int64)
        out = {"s": list(a.shape), "k": "i", "x": [int(ints[i]) for i in index]}
        if not short:
            out.update(S=int(ints.sum()), m=int(ints.min()), M=int(ints.max()))
        return out
    finite = flat[np.isfinite(flat)].astype(np.float64)
    out = {
        "s": list(a.shape),
        "k": "f",
        "n": int(flat.size - finite.size),
        "x": [_g12(f"{flat[i]:.12g}") for i in index],
    }
    if finite.size and not short:
        out.update(
            S=_g12(f"{finite.sum():.12g}"),
            A=_g12(f"{np.abs(finite).sum():.12g}"),
            m=_g12(f"{finite.min():.12g}"),
            M=_g12(f"{finite.max():.12g}"),
        )
    return out


def summarise_h5(path):
    """Numeric summary of every dataset/column (see the module docstring)."""
    return {n: _summary(a) for n, a in _datasets(path)}


def _same_number(got, ref, scale):
    got, ref = float(got), float(ref)
    if np.isnan(ref) or np.isnan(got):
        return bool(np.isnan(ref) and np.isnan(got))
    if np.isinf(ref) or np.isinf(got):
        return got == ref
    return bool(np.isclose(got, ref, rtol=RTOL, atol=1e-12 * scale))


def compare_summaries(got, ref):
    """Names of the datasets whose summary differs (empty list: identical)."""
    differing = sorted(set(got) ^ set(ref))
    for name in sorted(set(got) & set(ref)):
        g, r = got[name], ref[name]
        if g.get("s") != r.get("s") or g.get("k") != r.get("k"):
            differing.append(name)
        elif g["k"] in "iS":  # integers and strings are exact
            if g != r:
                differing.append(name)
        elif g.get("n") != r.get("n") or ("S" in g) != ("S" in r):
            differing.append(name)
        else:
            finite = [abs(float(v)) for v in r["x"] if np.isfinite(float(v))]
            scale = max([float(r.get("A", 0.0)), *finite])
            pairs = list(zip(g["x"], r["x"], strict=True))
            pairs.extend((g[key], r[key]) for key in ("S", "m", "M") if key in r)
            if not all(_same_number(a, b, scale) for a, b in pairs):
                differing.append(name)
    return differing


def environment():
    return {
        "machine": platform.machine(),
        "platform": sys.platform,
        "numpy": np.__version__,
        "python": platform.python_version(),
    }


@pytest.fixture(scope="module")
def example_output(tmp_path_factory):
    out = tmp_path_factory.mktemp("science") / "result.h5"
    disableLogging()
    try:
        exorad.standard_pipeline(
            options=payload_file(), target_list=TARGETS, output=str(out)
        )
    finally:
        enableLogging()
    return out


@pytest.fixture(scope="module")
def reference():
    """``summaries`` (compared with a tolerance) and ``digests`` (bitwise)."""
    with open(REFERENCE) as fp:
        data = json.load(fp)
    entries = data["datasets"]
    return {
        "environment": data["environment"],
        "summaries": {
            n: {k: v for k, v in e.items() if k != "h"} for n, e in entries.items()
        },
        "digests": {n: e["h"] for n, e in entries.items() if "h" in e},
    }


def test_example_tables_match_the_reference(example_output, reference):
    ref = reference["summaries"]
    assert len(ref) > 100
    differing = compare_summaries(summarise_h5(str(example_output)), ref)
    assert not differing, differing[:10]


def test_example_tables_bit_identical_on_the_reference_platform(
    example_output, reference
):
    if not os.environ.get(BITWISE_ENV):
        pytest.skip(f"opt-in strict mode: set {BITWISE_ENV}=1")
    recorded = reference["environment"]
    here = environment()
    if any(recorded[k] != here[k] for k in ("machine", "platform", "numpy")):
        pytest.skip(f"bitwise reference was generated on {recorded}, this is {here}")
    got = digest_h5(str(example_output))
    ref = reference["digests"]
    assert got.keys() == ref.keys()
    differing = sorted(k for k in ref if got[k] != ref[k])
    assert not differing, differing[:10]


def test_a_changed_number_is_detected(example_output, reference, tmp_path):
    """Mutation check: one perturbed value must fail, a rounding-level one must not."""
    copy = tmp_path / "mutant.h5"
    copy.write_bytes(example_output.read_bytes())
    ref = reference["summaries"]
    name = next(
        n
        for n in digest_h5(str(copy))
        if n.startswith("targets/") and "[" not in n and ref[n]["k"] == "f"
    )
    with h5py.File(copy, "r+") as f:
        data = f[name]
        values = data[()]
        i = values.size // 2
        original = values.flat[i]
        values.flat[i] = original * (1 + 1e-13) + 1e-300  # below the tolerance
        data[...] = values
    assert compare_summaries(summarise_h5(str(copy)), ref) == []
    with h5py.File(copy, "r+") as f:
        data = f[name]
        values = data[()]
        values.flat[i] = original * 1.001 + 1e-3  # a real change
        data[...] = values
    assert compare_summaries(summarise_h5(str(copy)), ref) == [name]


def test_summary_comparison_catches_shape_and_integer_changes():
    base = _summary(np.arange(10.0))
    assert compare_summaries({"a": base}, {"a": base}) == []
    assert compare_summaries({"a": _summary(np.arange(11.0))}, {"a": base}) == ["a"]
    ints = _summary(np.arange(5))
    assert compare_summaries({"a": _summary(np.arange(5) + 1)}, {"a": ints}) == ["a"]
    names = _summary(np.array([b"Phot", b"Spec"]))
    assert compare_summaries(
        {"a": _summary(np.array([b"Phot", b"Spex"]))}, {"a": names}
    )


def _regenerate():  # pragma: no cover - manual tool
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "result.h5")
        disableLogging()
        exorad.standard_pipeline(
            options=payload_file(), target_list=TARGETS, output=out
        )
        enableLogging()
        digests = digest_h5(out)
        data = {
            "_note": (
                "Per-dataset numeric summaries (shape, kind, sum, min, max, five "
                "fixed samples at 12 significant digits) and SHA-256 digests (first "
                "16 hex chars) of every numeric dataset or column under payload/ and "
                "targets/ of the HDF5 written by standard_pipeline("
                "examples/payload_example.xml, examples/test_target.csv, "
                "n_thread=1). Generated from the unchanged release/2.3 science code "
                "(E0 changed no number). The summaries are compared with rtol=1e-9; "
                "the digests only with EXORAD_BITWISE_REFERENCE=1 on the platform "
                "in 'environment'. Regenerate only for an intended scientific change."
            ),
            "environment": environment(),
            "datasets": {
                n: {**e, **({"h": digests[n]} if n in digests else {})}
                for n, e in summarise_h5(out).items()
            },
        }
    with open(REFERENCE, "w") as fp:
        json.dump(data, fp, sort_keys=True, separators=(",", ":"))
        fp.write("\n")


if __name__ == "__main__":  # pragma: no cover
    if "--regenerate" in sys.argv:
        _regenerate()
