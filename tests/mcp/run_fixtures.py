"""Helpers of the pipeline-wrapper tests (importable: no package).

``make_project`` writes a user project into the MCP work directory the way a client
would keep it: a payload with its small tables beside it (demo SED, ``working_R``
reduced) and a target list. Paths are returned relative to the work dir, which is
what a client passes to ``run_pipeline``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from payload_fixtures import find, make_payload

from exorad.mcp.sandbox import Sandbox

if TYPE_CHECKING:
    import xml.etree.ElementTree as ET
    from collections.abc import Callable
    from pathlib import Path

HEADER = "star name,star M [M_sun],star Teff [K],star R [R_sun],star D [pc]"


def work_dir_of(tmp_path: Path) -> Path:
    """The work dir the conftest points ``EXORAD_MCP_WORK_DIR`` at."""
    return tmp_path / "mcp-work"


def target_rows(n_targets: int) -> list[str]:
    return [f"t{i},1,{5000 + 100 * i},1,{20 + i}" for i in range(n_targets)]


def make_project(
    tmp_path: Path,
    *,
    name: str = "proj",
    n_targets: int = 2,
    working_R: int | None = 1000,
    edit: Callable[[ET.Element], None] | None = None,
    rows: list[str] | None = None,
) -> tuple[str, str]:
    """Write ``<work>/<name>/payload.xml`` and ``targets.csv``; return relative paths."""
    directory = work_dir_of(tmp_path) / name

    def apply(root: ET.Element) -> None:
        if working_R is not None:
            find(root, "common/working_R").text = str(working_R)
        if edit is not None:
            edit(root)

    make_payload(directory, edit=apply)
    lines = [HEADER, *(rows if rows is not None else target_rows(n_targets))]
    (directory / "targets.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"{name}/payload.xml", f"{name}/targets.csv"


class FakeJobs:
    """Stands in for ``jobs.JOBS``: records the spec instead of spawning a process."""

    def __init__(self, status: str = "running") -> None:
        self.specs: list[dict] = []
        self.kwargs: list[dict] = []
        self.state = status
        self.raises: BaseException | None = None

    def submit(self, spec: dict, **kwargs: object) -> str:
        if self.raises is not None:
            raise self.raises
        self.specs.append(spec)
        self.kwargs.append(kwargs)
        return f"fake{len(self.specs):04d}"

    def output_clash(self, output: str) -> None:
        return None

    def _status(self, job_id: str) -> dict:
        spec = self.specs[-1]
        return {
            "job_id": job_id,
            "pipeline": spec["pipeline"],
            "status": self.state,
            "output": Sandbox.from_env().display_path(spec["output"]),
            "log_file": "work:logs/x.log",
            "targets_done": 0,
        }

    def wait(self, job_id: str, timeout: float | None) -> dict:
        return self._status(job_id)

    def status(self, job_id: str) -> dict:
        return self._status(job_id)

    def cancel(self, job_id: str) -> dict:
        self.state = "cancelled"
        return self._status(job_id)

    def list_jobs(self) -> list[dict]:
        return [self._status(f"fake{i + 1:04d}") for i in range(len(self.specs))]
