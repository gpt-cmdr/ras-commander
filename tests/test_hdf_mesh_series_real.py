"""Opt-in read-only full-array qualification against a local audit inventory.

Set RAS_F07_REAL_CORPUS to a JSON list of objects with path, mesh, variable,
domain and modes keys. Private fixture paths stay in that external inventory.
"""

import json
import os
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh as Mesh


_inventory = os.environ.get("RAS_F07_REAL_CORPUS")
_cases = json.loads(Path(_inventory).read_text()) if _inventory else []


@pytest.mark.parametrize("case", _cases, ids=lambda case: f"{Path(case['path']).name}/{case['mesh']}/{case['variable']}")
def test_real_series_all_values_match_h5py(case):
    path, mesh, variable = Path(case["path"]), case["mesh"], case["variable"]
    with h5py.File(path, "r") as hdf:
        raw = hdf[Mesh._get_mesh_timeseries_output_path(mesh, variable)]
        for mode in case["modes"]:
            if mode == "stream":
                start = 0
                for result in Mesh.iter_mesh_timeseries(path, mesh, variable, batch_size=8, include_ghost_cells=True):
                    stop = start + result.shape[0]
                    expected = raw[start:stop]
                    assert result.dims == tuple(case["domain"])
                    assert result.dtype == raw.dtype
                    assert result.values.tobytes() == expected.tobytes()
                    start = stop
                assert start == raw.shape[0]
            else:
                result = Mesh.get_mesh_timeseries(
                    path, mesh, variable, truncate=False, include_ghost_cells=True,
                    return_type="view" if mode == "lazy" else "xarray",
                )
                if mode == "lazy":
                    result = result.to_xarray()
                assert result.shape == raw.shape
                assert result.dims == tuple(case["domain"])
                assert result.dtype == raw.dtype
                # Bounded oracle slabs avoid a second full-array allocation.
                for start in range(0, raw.shape[0], 8):
                    assert result.values[start:start + 8].tobytes() == raw[start:start + 8].tobytes()
                if result.ndim == 1:
                    assert set(result.coords) == {"time"}
                del result
        if case["domain"] == ["time", "cell_id"]:
            attrs = hdf["Geometry/2D Flow Areas/Attributes"][:]
            count = next(int(row["Cell Count"]) for row in attrs if row["Name"].decode().strip() == mesh)
            physical = Mesh.get_mesh_timeseries(path, mesh, variable, truncate=False)
            assert physical.shape == (raw.shape[0], count)
            assert not physical.is_ghost_cell.any()
            for start in range(0, raw.shape[0], 8):
                assert physical.values[start:start + 8].tobytes() == raw[start:start + 8, :count].tobytes()
