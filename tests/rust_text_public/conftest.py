"""Shared fixtures for native text public-API qualification.

Environment:

* ``RAS_TEXT_CORPUS`` - folder written by
  ``scripts/benchmarks/rust_text_public/prepare_corpus.py`` (contains
  ``corpus-manifest.json``). Real-corpus tests skip, visibly, without it.
* ``RAS_TEXT_PUBLIC_REPORT`` - optional JSON path for machine-readable results.

Module files are named ``*_test.py`` because the root ``.gitignore`` ignores
nested ``test_*.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

import ras_commander
from ras_commander import fast_text
from ras_commander.geom.GeomCrossSection import GeomCrossSection

REPO = Path(__file__).resolve().parents[2]
REPORT: dict = {"provenance": {}, "results": {}}

#: Python readers that must never run while native mode is required.
PYTHON_READERS = (
    "get_cross_sections",
    "get_station_elevation",
    "get_mannings_n",
    "get_bank_stations",
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture(scope="session")
def native():
    """The imported extension; fails (never skips) when it is unavailable."""
    module = fast_text._require_native()
    pyd = sorted(Path(module.__file__).parent.glob("ras_commander_fast_hdf*.pyd")) or sorted(
        Path(module.__file__).parent.glob("ras_commander_fast_hdf*.so")
    )
    diff = _git("diff", "HEAD").encode()
    REPORT["provenance"].update(
        {
            "ras_commander_file": ras_commander.__file__,
            "native_package": module.__file__,
            "native_binary": str(pyd[0]) if pyd else None,
            "native_binary_sha256": hashlib.sha256(pyd[0].read_bytes()).hexdigest() if pyd else None,
            "text_api_version": module.TEXT_API_VERSION,
            "head": _git("rev-parse", "HEAD").strip(),
            "worktree_diff_sha256": hashlib.sha256(diff).hexdigest(),
            "untracked": _git("ls-files", "--others", "--exclude-standard").split(),
        }
    )
    assert Path(ras_commander.__file__).resolve().is_relative_to(REPO)
    return module


@pytest.fixture
def required_native(native, monkeypatch):
    """Forbid every Python reader and count native calls for the test."""

    def forbidden(name):
        def fail(*args, **kwargs):
            raise AssertionError(f"Python fallback GeomCrossSection.{name} in required-native mode")

        return fail

    for name in PYTHON_READERS:
        monkeypatch.setattr(GeomCrossSection, name, staticmethod(forbidden(name)))
    monkeypatch.setenv("RAS_COMMANDER_FAST_TEXT", "required")
    before = sum(fast_text.NATIVE_CALLS.values())
    yield fast_text.NATIVE_CALLS
    assert sum(fast_text.NATIVE_CALLS.values()) > before, "no native call was made"


@pytest.fixture(scope="session")
def corpus():
    root = os.environ.get("RAS_TEXT_CORPUS")
    if not root:
        pytest.skip("RAS_TEXT_CORPUS is not set: real-corpus coverage is unavailable, not passed")
    root = Path(root)
    manifest = json.loads((root / "corpus-manifest.json").read_text(encoding="utf-8"))
    files = [dict(f, full=root / f["path"]) for f in manifest["files"]]
    assert files, "empty corpus is not a pass"
    REPORT["provenance"]["corpus_archives"] = manifest["archives"]
    return files


def record(section: str, key: str, value) -> None:
    REPORT["results"].setdefault(section, {})[key] = value


def pytest_sessionfinish(session, exitstatus):
    path = os.environ.get("RAS_TEXT_PUBLIC_REPORT")
    if path:
        REPORT["exitstatus"] = int(exitstatus)
        REPORT["native_calls"] = dict(fast_text.NATIVE_CALLS)
        Path(path).write_text(json.dumps(REPORT, indent=1, default=str), encoding="utf-8")
