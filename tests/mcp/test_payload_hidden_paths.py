"""The static scan sees every place the loader reads (final-review blocker).

``LoadOptions.__parser__`` (exorad/tasks/loadOptions.py) walks EVERY child element,
``<comment>`` subtrees included, turns every XML attribute into a key (a ``value``
attribute becomes the element's value) and opens the files named by any child called
``datafile``, ``datadict`` or ``config_dict`` at any depth. These tests put a hostile
reference in each such place and require that the static scan refuses it, that the
library is never reached, that no pickle runs and that no FIFO is opened.
"""

from __future__ import annotations

import os
import pickle
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from astropy.table import Table
from payload_fixtures import example_tree, make_payload, sandbox_for

from exorad.mcp import comparison, configuration, rules, tools_config

if TYPE_CHECKING:
    from exorad.mcp.sandbox import Sandbox


@pytest.fixture
def box(tmp_path: Path) -> Sandbox:
    return sandbox_for(tmp_path)


@pytest.fixture
def udir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # the same work dir for the env-driven tools and for ``sandbox_for``
    monkeypatch.setenv("EXORAD_MCP_WORK_DIR", str(tmp_path / "work"))
    path = tmp_path / "work" / "user"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def no_loader(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record (and fail on) any call into the library's ``LoadOptions``."""
    calls: list[str] = []

    def boom(*_a: object, **_k: object) -> None:
        calls.append("LoadOptions")
        raise RuntimeError("LoadOptions must not be reached")

    monkeypatch.setattr(rules, "LoadOptions", boom)
    return calls


class _Marker:
    """Unpickling this would create the marker file (it must never happen)."""

    def __init__(self, marker: str) -> None:
        self.marker = marker

    def __reduce__(self):  # type: ignore[no-untyped-def]
        return (open, (self.marker, "w"))


def _evil_pickle(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / "PWNED"
    evil = directory / "evil.pickle"
    evil.write_bytes(pickle.dumps(_Marker(str(marker))))
    return evil, marker


def _inject(payload: Path, fragment: str, encoding: str = "utf-8") -> Path:
    """Insert ``fragment`` before the root's closing tag, re-encoded as asked."""
    text = payload.read_text(encoding="utf-8")
    root_tag = example_tree().tag
    head, _, tail = text.rpartition(f"</{root_tag}>")
    text = head + fragment + f"</{root_tag}>" + tail
    if encoding != "utf-8":
        text = text.replace("utf-8", encoding, 1)
        payload.write_bytes(text.encode(encoding))
    else:
        payload.write_text(text, encoding="utf-8")
    return payload


POSITIONS = {
    "text": "<extra><{t}>{x}</{t}></extra>",
    "attribute": '<extra><{t} value="{x}"/></extra>',
    "comment_child": "<comment><{t}>{x}</{t}></comment>",
    "cdata": "<extra><{t}><![CDATA[{x}]]></{t}></extra>",
    "nested_comment": "<extra><comment><sub><{t}>{x}</{t}></sub></comment></extra>",
    "repeated": "<extra><{t}>{x}</{t}><{t}>{x}</{t}></extra>",
    "comment_at_top_attr": '<comment><{t} value="{x}"/></comment>',
}
TAGS = ("datafile", "datadict", "config_dict")


def _hostile_target(tag: str, tmp_path: Path) -> tuple[str, str, Path]:
    """(path text, expected finding code, marker file)."""
    outside = tmp_path / "outside"
    if tag == "datafile":
        outside.mkdir(exist_ok=True)
        csv = outside / "secret.csv"
        csv.write_text("a,b\n1,2\n", encoding="utf-8")
        return str(csv), "PATH_OUTSIDE_SANDBOX", outside / "PWNED"
    evil, marker = _evil_pickle(outside)
    return str(evil), "PICKLE_REFUSED", marker


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("position", sorted(POSITIONS))
def test_hostile_reference_is_refused_everywhere(
    position: str,
    tag: str,
    encoding: str,
    tmp_path: Path,
    udir: Path,
    box: Sandbox,
    no_loader: list[str],
) -> None:
    target, code, marker = _hostile_target(tag, tmp_path)
    payload = make_payload(udir)
    fragment = POSITIONS[position].format(t=tag, x=target)
    _inject(payload, fragment, encoding)

    findings = rules.static_findings(payload, sandbox=box)
    # an attribute is refused as such (its value is never trusted as a path)
    expected = "ATTRIBUTE_REFUSED" if "attr" in position else code
    assert expected in {f.code for f in rules.errors_of(findings)}, findings

    norm = rules.normalise_payload(payload, sandbox=box, dest_dir=tmp_path / "copy")
    assert norm.path is None

    with pytest.raises(rules.ConfigRuleError):
        rules.load_payload_dict(payload, sandbox=box)
    result = configuration.validate_configuration_file(str(payload), sandbox=box)
    assert result["valid"] is False
    assert not any(f["code"] == "LOADER_FAILED" for f in result["findings"])
    assert no_loader == []
    assert not marker.exists()


def test_comment_pickle_regression_validate_and_compare(
    tmp_path: Path, udir: Path, no_loader: list[str]
) -> None:
    """The reviewer's reproduction: a pickle in a comment ran under --no-exec."""
    evil, marker = _evil_pickle(tmp_path / "outside")
    bad = _inject(
        make_payload(udir, name="bad.xml"),
        f"<comment><datadict>{evil}</datadict></comment>",
    )
    good = make_payload(udir, name="good.xml")
    result = tools_config.validate_config(str(bad))
    assert result["valid"] is False
    assert "PICKLE_REFUSED" in {f["code"] for f in result["findings"]}
    compared = tools_config.compare_configs(str(good), str(bad))
    assert compared["valid"] is False
    assert no_loader == []
    assert not marker.exists()


def test_attribute_value_datafile_does_not_leak_shape(
    tmp_path: Path, udir: Path, no_loader: list[str]
) -> None:
    """The reviewer's reproduction: ``<datafile value=.../>`` revealed an outside file."""
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.csv"
    Table({"hidden_column": [1.0, 2.0], "other": [3.0, 4.0]}).write(
        secret, format="ascii.csv"
    )
    good = make_payload(udir, name="good.xml")
    bad = _inject(
        make_payload(udir, name="bad.xml"),
        f'<extra><datafile value="{secret}"/></extra>',
    )
    result = tools_config.validate_config(str(bad))
    assert result["valid"] is False
    compared = tools_config.compare_configs(str(good), str(bad))
    assert compared["valid"] is False
    assert compared["differences"] == []
    assert "hidden_column" not in repr(compared)
    assert no_loader == []


@pytest.mark.parametrize(
    "fragment",
    [
        '<extra><foo value="/etc/passwd"/></extra>',
        '<extra><foo bar="/etc/passwd"/></extra>',
        '<extra><foo datafile="/etc/passwd"/></extra>',
        '<comment><foo bar="x"/></comment>',
        '<extra><foo unit="m" bar="x"/></extra>',
    ],
)
def test_attributes_other_than_unit_are_refused(
    fragment: str, udir: Path, box: Sandbox, no_loader: list[str]
) -> None:
    payload = _inject(make_payload(udir), fragment)
    findings = rules.static_findings(payload, sandbox=box)
    assert "ATTRIBUTE_REFUSED" in {f.code for f in rules.errors_of(findings)}
    assert no_loader == []


def test_unit_attribute_is_still_accepted(udir: Path, box: Sandbox) -> None:
    payload = make_payload(udir)
    assert 'unit="' in payload.read_text(encoding="utf-8")
    assert not rules.errors_of(rules.static_findings(payload, sandbox=box))


def test_comment_elements_are_not_in_the_normalised_copy(
    udir: Path, box: Sandbox, tmp_path: Path
) -> None:
    """The library gets no comment subtree it could read; the copy still loads."""
    payload = _inject(
        make_payload(udir), "<comment>kept in the original only</comment>"
    )
    norm = rules.normalise_payload(payload, sandbox=box, dest_dir=tmp_path / "copy")
    assert norm.path is not None
    assert "<comment" not in norm.path.read_text(encoding="utf-8")
    rules.load_options(norm.path)


def test_prose_in_comments_is_not_treated_as_a_path(udir: Path, box: Sandbox) -> None:
    payload = _inject(
        make_payload(udir),
        "<comment>see /usr/share/doc or http://example.org and ~/notes</comment>",
    )
    assert not rules.errors_of(rules.static_findings(payload, sandbox=box))


# ---------------------------------------------------------------------- FIFOs
def _fifo(directory: Path, name: str = "pipe.csv") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    os.mkfifo(path)
    return path


def _run_with_timeout(fn, fifo: Path, seconds: float = 10.0):  # type: ignore[no-untyped-def]
    out: list[object] = []

    def target() -> None:
        try:
            out.append(fn())
        except Exception as exc:
            out.append(exc)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    alive = thread.is_alive()
    if alive:  # release a reader blocked in open() so the test process can end
        try:
            fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
            os.close(fd)
        except OSError:
            pass
        thread.join(2)
    assert not alive, "the check blocked on a FIFO"
    return out[0] if out else None


@pytest.mark.parametrize(
    "position", ["text", "attribute", "comment_child", "nested_comment"]
)
@pytest.mark.parametrize("tag", ["datafile", "CustomSed"])
def test_fifo_is_refused_without_blocking(
    position: str, tag: str, tmp_path: Path, udir: Path, box: Sandbox
) -> None:
    fifo = _fifo(udir)
    payload = _inject(make_payload(udir), POSITIONS[position].format(t=tag, x=fifo))

    def check() -> list[str]:
        findings = rules.static_findings(payload, sandbox=box)
        result = configuration.validate_configuration_file(str(payload), sandbox=box)
        assert result["valid"] is False
        # and the next validation is not blocked behind the loader lock
        good = make_payload(udir, name="next.xml")
        assert configuration.validate_configuration_file(str(good), sandbox=box)[
            "valid"
        ]
        return [f.code for f in rules.errors_of(findings)]

    found = _run_with_timeout(check, fifo)
    assert isinstance(found, list), found
    assert "NOT_REGULAR_FILE" in found or "ATTRIBUTE_REFUSED" in found


def test_fifo_in_comment_datafile_is_not_opened(
    tmp_path: Path, udir: Path, box: Sandbox, no_loader: list[str]
) -> None:
    fifo = _fifo(udir)
    payload = _inject(
        make_payload(udir), f"<comment><datafile>{fifo}</datafile></comment>"
    )
    found = _run_with_timeout(
        lambda: [f.code for f in rules.static_findings(payload, sandbox=box)], fifo
    )
    assert found == ["NOT_REGULAR_FILE"]
    assert no_loader == []


# ------------------------------------------------- comparison / deep entry points
@pytest.mark.parametrize("position", ["comment_child", "attribute", "nested_comment"])
def test_compare_scans_both_inputs_before_the_loader(
    position: str, tmp_path: Path, udir: Path, no_loader: list[str]
) -> None:
    target, _code, marker = _hostile_target("datadict", tmp_path)
    good = make_payload(udir, name="good.xml")
    bad = _inject(
        make_payload(udir, name="bad.xml"),
        POSITIONS[position].format(t="datadict", x=target),
    )
    for first, second in ((good, bad), (bad, good), (bad, bad)):
        result = comparison.compare_payloads(
            first, second, sandbox=sandbox_for(tmp_path)
        )
        assert result["valid"] is False
        assert result["errors"]
    assert no_loader == []
    assert not marker.exists()


def test_deep_validation_is_not_reached_on_static_errors(
    tmp_path: Path, udir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, _code, marker = _hostile_target("datadict", tmp_path)
    bad = _inject(
        make_payload(udir), f"<comment><datadict>{target}</datadict></comment>"
    )
    called: list[str] = []
    monkeypatch.setattr(
        configuration, "_deep_build", lambda *a, **k: called.append("deep")
    )
    box = sandbox_for(tmp_path)
    result = configuration.validate_configuration_file(str(bad), deep=True, sandbox=box)
    assert result["valid"] is False
    assert called == []
    assert not marker.exists()


def test_validate_does_not_offer_a_deleted_scratch_copy(
    udir: Path, box: Sandbox
) -> None:
    """``normalised_config`` pointed at a file removed before the client saw it."""
    result = configuration.validate_configuration_file(
        str(make_payload(udir)), sandbox=box
    )
    assert result["valid"] is True
    assert "normalised_config" not in result


# ------------------------------------------------ the scan mirrors the real parser
def test_every_path_the_parser_surfaces_was_inspected(
    udir: Path, box: Sandbox, tmp_path: Path
) -> None:
    """Walk the REAL LoadOptions output: each path-looking string was a scanned reference."""
    payload = make_payload(udir)
    root = rules._read_payload(payload, box)[0]
    assert root is not None
    analysis = rules._analyse(root, payload, box)
    inspected = {str(ref.resolved) for ref in analysis.references if ref.resolved}
    assert len(inspected) >= 4

    norm = rules.normalise_payload(payload, sandbox=box, dest_dir=tmp_path / "copy")
    assert norm.path is not None
    options = rules.load_options(norm.path)

    surfaced: list[tuple[str, str]] = []

    def walk(node: object, trail: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{trail}.{key}" if trail else str(key))
        elif isinstance(node, str) and os.path.isabs(node):
            surfaced.append((trail, node))

    walk(options, "")
    assert surfaced
    for trail, value in surfaced:
        if trail.split(".")[0] == "ConfigPath":
            continue
        if ".StellarModels." in f".{trail}." and analysis.source != "phoenix":
            continue  # a directory only the phoenix source reads (rules._scan_values)
        assert str(Path(value).resolve()) in inspected, (
            f"the parser surfaces a path the static scan never inspected: {trail}={value}"
        )
