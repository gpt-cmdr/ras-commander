"""Vectorized native fluvial snapshot inputs equal the per-face / per-cell loops.

``Analysis.from_hdf`` builds the face rings, edge faces and peak keys it hands
to the Rust kernels with NumPy (``_fast_face_rings``, ``_fast_peak_times``).
Disabling both gives the original loops; every snapshot field must be equal,
including the order of appended perimeter points and of the edge-face keys.
Fixtures as in test_public_engine.py (RAS_FLUVIAL_PUBLIC_FIXTURES); a missing
fixture is reported as skipped.
"""
import os
from pathlib import Path

import pytest

from ras_commander.hdf import HdfFluvialNative
from ras_commander.hdf.HdfFluvialNative import Analysis

FIXTURES = Path(os.environ.get("RAS_FLUVIAL_PUBLIC_FIXTURES", "missing"))
FIELDS = ("identities", "keys", "offsets", "neighbors", "points", "rings", "times",
          "present", "wet", "meshes", "valid", "sources", "quarantined_cells",
          "linear_unit_to_m", "peak_round_to")


def _snapshot(path, **kwargs):
    analysis = Analysis.from_hdf(path, wet_policy="all", **kwargs)
    fields = {name: getattr(analysis, name) for name in FIELDS}
    fields["setup"] = {k: v for k, v in analysis.setup.items() if not k.endswith("seconds")}
    edges = analysis.edge_faces
    fields["edge_faces"] = None if edges is None else list(edges.items())
    return fields


@pytest.mark.parametrize("name", ["BaldEagleDamBrk.p18.hdf", "BaldEagleDamBrk.p07.hdf",
                                  "BaldEagleDamBrk.p03.hdf"])
@pytest.mark.parametrize("retain_faces", [False, True])
def test_vectorized_snapshot_equals_the_loops(name, retain_faces, monkeypatch):
    path = FIXTURES / name
    if not path.exists():
        pytest.skip(f"fixture unavailable: {path}")
    kwargs = {"retain_faces": retain_faces, "peak_round_to": "100ms",
              "require_peaks": name != "BaldEagleDamBrk.p03.hdf"}
    fast = _snapshot(path, **kwargs)
    monkeypatch.setattr(HdfFluvialNative, "_fast_face_rings", lambda *args, **kw: None)
    monkeypatch.setattr(HdfFluvialNative, "_fast_peak_times", lambda *args, **kw: None)
    loop = _snapshot(path, **kwargs)
    for field in loop:
        assert fast[field] == loop[field], field
        if field in ("times", "present", "points", "rings"):
            assert [type(v) for v in fast[field]] == [type(v) for v in loop[field]], field
