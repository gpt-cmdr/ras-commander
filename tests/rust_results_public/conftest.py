"""Real computed-plan fixtures for the public native result reductions.

``RAS_RESULTS_FIXTURE_ROOT`` names the folder holding the immutable local
copies listed in ``fixture_manifest.json``. Without it the tests skip as
unavailable; ``RAS_RESULTS_REQUIRE_FIXTURES=1`` turns absence into failure.
"""
import hashlib
import json
import os
from pathlib import Path

import pytest

from rust_analysis_conformance.conftest import (  # noqa: F401  (shared fixtures)
    forbid_python,
    native,
    native_calls,
)

MANIFEST = json.loads((Path(__file__).with_name("fixture_manifest.json")).read_text("utf-8"))
_VERIFIED = {}


def fixture_file(entry):
    root = os.environ.get("RAS_RESULTS_FIXTURE_ROOT")
    path = Path(root) / entry["path"] if root else None
    if path is None or not path.is_file():
        message = f"fixture unavailable: {entry['path']}"
        if os.environ.get("RAS_RESULTS_REQUIRE_FIXTURES") == "1":
            pytest.fail(message)
        pytest.skip(message)
    if path not in _VERIFIED:
        _VERIFIED[path] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert _VERIFIED[path] == entry["sha256"], f"fixture changed: {path}"
    return path


def entries(*, unsteady=True):
    return [e for e in MANIFEST["fixtures"] if e["unsteady_2d"] is unsteady]
