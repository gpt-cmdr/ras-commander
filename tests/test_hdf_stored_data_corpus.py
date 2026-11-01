"""Read-only qualification on checksum-pinned public corpus v1.0.1."""

import hashlib
import json
import os
from pathlib import Path

import h5py
import numpy as np
import pytest
import shapely

from ras_commander import HdfBndry, HdfResultsPlan, HdfXsec


@pytest.fixture
def corpus(monkeypatch, request):
    root = os.environ.get("RAS_HDF_DATA_CORPUS")
    if root is None:
        pytest.skip("Set RAS_HDF_DATA_CORPUS to qualify public corpus v1.0.1")
    root = Path(root)
    raw = (root / "manifest.json").read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        == "f3be980317bf514babf4fd2f3a15986898a38a6d90657f869e55c909517f622a"
    )
    entries = {e["id"]: e for e in json.loads(raw)["entries"]}

    def checked(identity):
        entry = entries[identity]
        path = root / entry["path"]
        assert path.stat().st_size == entry["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        return path

    return checked


@pytest.fixture(params=["h5py", "auto"])
def corpus_mode(request, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", request.param)


def test_real_initial_points(corpus, corpus_mode):
    path = corpus("rbfs/DowntownCorpusChris.g12")
    frame = HdfBndry.get_initial_condition_points(path)
    assert len(frame) == 8
    with h5py.File(path) as h:
        expected = h["Geometry/IC Points/Points"][()]
        assert shapely.get_coordinates(frame.geometry).tobytes() == expected.tobytes()
        np.testing.assert_array_equal(
            frame["Cell Index"], h["Geometry/IC Points/Attributes"]["Cell Index"]
        )


def test_real_obstruction_blocks(corpus, corpus_mode):
    path = corpus("hec701r/Baxter.p01")
    frame = HdfXsec.get_blocked_obstructions(path)
    assert len(frame) == 5
    with h5py.File(path) as h:
        expected = h["Geometry/Cross Sections/Obstruction Blocks"][()]
        for field in expected.dtype.names:
            assert frame[field].to_numpy().dtype == expected[field].dtype
            assert frame[field].to_numpy().tobytes() == expected[field].tobytes()


@pytest.mark.parametrize(
    "variable", ["Velocity Total", "Area including Ineffective Total"]
)
def test_real_steady_variables(corpus, corpus_mode, variable):
    path = corpus("hec66/Baxter.p01")
    relative = "Additional Variables/" + variable
    frame = HdfResultsPlan.get_steady_cross_section_results(path, relative)
    with h5py.File(path) as h:
        expected = h[
            "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections/"
            + relative
        ][()]
        assert frame.value.dtype == expected.dtype
        assert frame.value.to_numpy().tobytes() == expected.ravel().tobytes()
        assert (
            frame.profile_index.tolist()
            == np.repeat(np.arange(expected.shape[0]), expected.shape[1]).tolist()
        )
