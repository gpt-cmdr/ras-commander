"""``HdfLandCover.get_landcover_raster_map`` on legacy land-cover layers.

Legacy RAS Mapper land-cover layers (still shipped in the HEC-RAS 7.0 example
projects, e.g. Muncie ``LandCover/*.hdf`` and Weise_2D ``LandCover.hdf``) store
the classes as parallel ``IDs`` / ``Names`` / ``ManningsN`` arrays and no
``Raster Map``/``Variables`` tables. The pixel value of a class is its stored ID.
"""
import json
import os
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import fast_hdf
from ras_commander.hdf.HdfLandCover import HdfLandCover


def _legacy(path, ids, names, n):
    with h5py.File(path, "w") as h:
        h["IDs"] = np.array(ids, dtype="u1")
        h["Names"] = np.array([s.encode() for s in names], dtype="S28")
        h["ManningsN"] = np.array(n, dtype="f4")


def test_legacy_layer_maps_ids_names_and_mannings(tmp_path):
    path = tmp_path / "LandCover.hdf"
    _legacy(path, [0, 11, 21], ["NoData", "Open Water", "Developed, Open Space"], [3.4e38, 0.035, 0.0404])
    df = HdfLandCover.get_landcover_raster_map(path)
    assert df is not None
    assert list(df.columns) == ["pixel_value", "class_name", "mannings_n"]
    assert df["pixel_value"].tolist() == [0, 11, 21]
    assert df["class_name"].tolist() == ["NoData", "Open Water", "Developed, Open Space"]
    expected = np.array([3.4e38, 0.035, 0.0404], dtype="f4").astype(float)
    assert df["mannings_n"].to_numpy().tobytes() == expected.tobytes()


def test_legacy_layer_with_mismatched_arrays_is_refused(tmp_path):
    path = tmp_path / "LandCover.hdf"
    _legacy(path, [0, 11], ["NoData", "Open Water", "Extra"], [1.0, 0.035, 0.1])
    assert HdfLandCover.get_landcover_raster_map(path) is None


def _real_legacy_layers():
    manifest = os.environ.get("RAS_ROUTE2_FIXTURES")
    if not manifest:
        return []
    out = []
    for p in json.loads(Path(manifest).read_text()).get("projects", []):
        lc = p.get("landcover")
        if lc and Path(lc).exists():
            with h5py.File(lc, "r") as h:
                if "Raster Map" not in h and all(k in h for k in ("IDs", "Names", "ManningsN")):
                    out.append(lc)
    return sorted(set(out))


@pytest.mark.parametrize("path", _real_legacy_layers() or [pytest.param(None, marks=pytest.mark.skip(
    reason="Set RAS_ROUTE2_FIXTURES to a manifest whose projects list legacy land-cover layers"))])
def test_real_legacy_layers_match_an_independent_read_in_both_backends(path):
    with h5py.File(path, "r") as h:
        ids, names, n = h["IDs"][()], h["Names"][()], h["ManningsN"][()]
    for backend in ("h5py", "native"):
        with fast_hdf.backend_scope(backend):
            df = HdfLandCover.get_landcover_raster_map(path)
        assert df["pixel_value"].tolist() == [int(i) for i in ids]
        assert df["class_name"].tolist() == [x.decode().strip("\x00 ").strip() for x in names]
        assert df["mannings_n"].to_numpy().tobytes() == n.astype(float).tobytes()
