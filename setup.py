"""Build hook: ship the MCP knowledge base, examples and reference configs.

The repository files stay the single source of truth; they are copied into the
*build* directory (``exorad/mcp/_data``) when the wheel is built, never into the
source tree. The copy rules (and the substitution of the reduced-resolution demo
SED in the packaged example payload) live in ``exorad/mcp/assets.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent


def _load_assets():
    """Load ``exorad/mcp/assets.py`` by path (``exorad`` is not importable here)."""
    path = ROOT / "exorad" / "mcp" / "assets.py"
    if not path.is_file():
        raise RuntimeError(
            f"{path} is missing: the source tree is incomplete (see MANIFEST.in)."
        )
    spec = importlib.util.spec_from_file_location("_exorad_mcp_assets", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses needs the module registered
    spec.loader.exec_module(module)
    return module


class BuildPyWithMcpAssets(build_py):
    """``build_py`` that also copies the MCP content into the build tree."""

    def run(self):
        super().run()
        if self.dry_run or getattr(self, "editable_mode", False):
            return
        assets = _load_assets()
        dest = Path(self.build_lib) / "exorad" / "mcp" / assets.DATA_DIRNAME
        copied = assets.collect_assets(ROOT, dest)
        if not any(name.startswith("docs/") for name in copied) or not any(
            name.startswith("examples/") for name in copied
        ):
            raise RuntimeError(
                "MCP assets are incomplete (no docs/ or examples/ found next to "
                "setup.py); the sdist must include them (see MANIFEST.in)."
            )


setup(cmdclass={"build_py": BuildPyWithMcpAssets})
