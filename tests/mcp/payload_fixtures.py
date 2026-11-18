"""Shared helpers of the payload/target-list tests (importable: no package).

``make_payload`` writes a user payload next to copies of the small example tables,
the way a client would keep its own project; ``edit`` mutates the parsed XML first.
"""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING

from exorad.mcp.sandbox import Sandbox

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "examples"
TABLES = (
    "QE.csv",
    "Spec-wl_sol.csv",
    "modtran_38km_sun_180az_55zd_los_45zd.csv",
    "customsed_demo.csv",
)


def example_tree(*, demo_sed: bool = True) -> ET.Element:
    """The example payload (``customsed.csv`` swapped for the small demo SED)."""
    text = (EXAMPLES / "payload_example.xml").read_text(encoding="utf-8")
    if demo_sed:
        text = text.replace("customsed.csv", "customsed_demo.csv")
    return ET.fromstring(text)


def write_tree(root: ET.Element, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


def make_payload(
    directory: Path,
    *,
    name: str = "payload.xml",
    edit: Callable[[ET.Element], None] | None = None,
    tables: bool = True,
) -> Path:
    """Write ``directory/name`` with ``ConfigPath = .`` and the tables beside it."""
    root = example_tree()
    if tables:
        (directory / "examples").mkdir(parents=True, exist_ok=True)
        for table in TABLES:
            shutil.copy2(EXAMPLES / table, directory / "examples" / table)
    root.find("ConfigPath").text = "."
    if edit is not None:
        edit(root)
    return write_tree(root, directory / name)


def sandbox_for(tmp_path: Path, **kwargs: object) -> Sandbox:
    """The checkout as content root and ``tmp_path/work`` as work dir."""
    return Sandbox.from_env(
        repo_root=REPO_ROOT,
        work_dir=tmp_path / "work",
        **kwargs,  # type: ignore[arg-type]
    )


def _name(element: ET.Element) -> str:
    return (element.text or "").strip().split("\n")[0].strip()


def find(root: ET.Element, path: str) -> ET.Element:
    """Walk ``a/b/channel[Phot]/c``; ``tag[name]`` picks a repeated tag by its text."""
    node = root
    for part in path.split("/"):
        tag, _, rest = part.partition("[")
        name = rest.rstrip("]") if rest else None
        nxt = next(
            (c for c in node if c.tag == tag and (name is None or _name(c) == name)),
            None,
        )
        assert nxt is not None, f"{part!r} not found under {node.tag}"
        node = nxt
    return node


def remove(root: ET.Element, path: str) -> None:
    node = find(root, path)
    parent = next(p for p in root.iter() if node in list(p))
    parent.remove(node)


def codes(findings: list, severity: str | None = None) -> list[str]:
    return [f.code for f in findings if severity is None or f.severity == severity]
