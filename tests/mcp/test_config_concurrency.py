"""Validation runs in worker threads: the loader's global state must not mix (H14)."""

from __future__ import annotations

import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

import pytest
from payload_fixtures import find, make_payload

from exorad.mcp import configuration, rules, tools_config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def projects(tmp_path: Path) -> list[Path]:
    """Four payloads in the work dir, each with its own working_R."""
    files = []
    for index, working_r in enumerate((1000, 2000, 3000, 4000)):
        directory = tmp_path / "mcp-work" / f"p{index}"
        directory.mkdir(parents=True)
        files.append(
            make_payload(
                directory,
                edit=lambda r, v=working_r: setattr(
                    find(r, "common/working_R"), "text", str(v)
                ),
            )
        )
    return files


class SlowLoader:
    """Writes the process-global working_R, waits, then reads it back (like a slow parse)."""

    seen: list[tuple[int, int]]

    def __call__(self, filename: str) -> dict[str, Any]:
        from exorad.utils.passVal import PassVal

        own = int(ET.parse(filename).getroot().find("common/working_R").text)
        PassVal.working_R = own
        time.sleep(0.05)  # let another thread run between the write and the read
        type(self).seen.append((own, PassVal.working_R))
        return {"common": {"working_R": {"value": own}}}


def test_concurrent_loads_do_not_mix_state(
    monkeypatch: pytest.MonkeyPatch, projects: list[Path]
) -> None:
    """Deterministic: a slow loader interleaves without CONFIG_LOAD_LOCK."""
    from exorad.utils.passVal import PassVal

    SlowLoader.seen = []
    monkeypatch.setattr(rules, "LoadOptions", SlowLoader)
    before = PassVal.working_R
    barrier = threading.Barrier(len(projects))

    def run(path: Path) -> dict[str, Any]:
        barrier.wait()
        return configuration.validate_configuration_file(str(path))

    with ThreadPoolExecutor(len(projects)) as pool:
        results = list(pool.map(run, projects))
    assert all(r["valid"] for r in results), results
    assert len(SlowLoader.seen) == len(projects)
    assert all(own == seen for own, seen in SlowLoader.seen), SlowLoader.seen
    assert PassVal.working_R == before  # and nothing leaks out of the lock


def test_compare_and_validate_share_the_lock(
    monkeypatch: pytest.MonkeyPatch, projects: list[Path]
) -> None:
    SlowLoader.seen = []
    monkeypatch.setattr(rules, "LoadOptions", SlowLoader)
    barrier = threading.Barrier(4)

    def compare(pair: tuple[Path, Path]) -> Any:
        barrier.wait()
        return tools_config.compare_configs(str(pair[0]), str(pair[1]))

    def validate(path: Path) -> Any:
        barrier.wait()
        return tools_config.validate_config(str(path))

    with ThreadPoolExecutor(4) as pool:
        futures = [
            pool.submit(compare, (projects[0], projects[1])),
            pool.submit(compare, (projects[2], projects[3])),
            pool.submit(validate, projects[0]),
            pool.submit(validate, projects[3]),
        ]
        [f.result() for f in futures]
    assert len(SlowLoader.seen) == 6
    assert all(own == seen for own, seen in SlowLoader.seen), SlowLoader.seen


def test_concurrent_validation_of_real_payloads(projects: list[Path]) -> None:
    def run(path: Path) -> Any:
        result = tools_config.validate_config(str(path))
        return result["valid"], result["summary"]["working_R"]

    serial = {p: run(p) for p in projects}
    with ThreadPoolExecutor(8) as pool:
        futures = {i: pool.submit(run, projects[i % 4]) for i in range(8)}
    for i, future in futures.items():
        assert future.result() == serial[projects[i % 4]]
    assert [serial[p][1] for p in projects] == [1000, 2000, 3000, 4000]
