import json
from pathlib import Path

import pytest

from .contract import env_path, load_receipt, sha256

FIXTURES = {
    # name: (expected SHA256, stored version) from fixture-readiness.json
    "JUL2020_D100RAS.p04.hdf": ("37d91b9f957f78067cb0a8ae5db7cf3355f9c5d7172cb40e7931c35be78b9683",
                                "HEC-RAS 5.0.7 March 2019"),
    "BaldEagleDamBrk.p03.hdf": ("98bfbeea11d31f9586b2e21b1f292974a93b97742c86eb370c3d78be1e9efa9f",
                                "HEC-RAS 6.6 September 2024"),
    "BaldEagleDamBrk.p07.hdf": ("07cad3930a679891f87bbface1ab749b82fd7d7eae6aaac3b5ff041c44280984",
                                "HEC-RAS 6.6 September 2024"),
    "BaldEagleDamBrk.p18.hdf": ("1d0063a84fd131ac95ffaa2b3f6647f2ef51c7f38f23c43e8ae6c698bfc95f0b",
                                "HEC-RAS 7.0 April 2026"),
}
RECEIPT_LOG = []


@pytest.fixture(scope="session")
def receipt():
    data = load_receipt()
    if data is None:
        pytest.skip("RAS_CONSUMER_ACCEPTANCE_RECEIPT not set: installed-wheel acceptance not requested")
    return data


@pytest.fixture(scope="session")
def fixture_dir():
    folder = env_path("RAS_CONSUMER_FIXTURES")
    if folder is None:
        pytest.skip("RAS_CONSUMER_FIXTURES not set")
    before = {}
    for name, (expected, _version) in FIXTURES.items():
        path = folder / name
        if not path.is_file():
            pytest.fail(f"fixture missing (unavailable, not an empty pass): {path}")
        before[name] = sha256(path)
        assert before[name] == expected, f"fixture hash mismatch before tests: {name}"
    yield folder
    after = {name: sha256(folder / name) for name in FIXTURES}
    RECEIPT_LOG.append({"fixture_dir": str(folder), "sha256_before": before, "sha256_after": after})
    out = env_path("RAS_CONSUMER_EVIDENCE")
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "fixture-session-hashes.json").write_text(json.dumps(RECEIPT_LOG, indent=2))
    assert after == before, "a test modified an immutable fixture"


@pytest.fixture(scope="session")
def reference_dir():
    folder = env_path("RAS_CONSUMER_REFERENCE_DEPTH")
    if folder is None:
        pytest.skip("RAS_CONSUMER_REFERENCE_DEPTH not set")
    return folder


@pytest.fixture(scope="session")
def evidence():
    """Append machine-readable observations (native call counts, metrics)."""
    folder = env_path("RAS_CONSUMER_EVIDENCE")
    records = []
    yield records
    if folder is not None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "native-consumer-observations.json").write_text(
            json.dumps(records, indent=2, default=str))


def fixture_path(folder: Path, name: str) -> Path:
    return folder / name
