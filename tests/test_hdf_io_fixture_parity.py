"""Exact-equality parity of public HDF outputs with the sized chunk cache and handle reuse on/off.

Real-fixture gate: set ``RAS_H5PY_CACHE_FIXTURES`` to a directory holding the
five qualification plan HDFs (fixture-manifest-portable.json of the
successor-perf py-perf-1 packet). Each fixture's SHA-256 is verified before use.
Without the variable every test here is skipped with that reason.

Modes compared against ``off`` (h5py default cache, no reuse):
  * ``cache``  - explicit sized chunk cache, no reuse
  * ``reuse``  - sized chunk cache plus cached read-only handles
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import hdf_io

FIXTURE_ENV = "RAS_H5PY_CACHE_FIXTURES"
FIXTURES = {
    "BaldEagleDamBrk.p07.hdf": "07cad3930a679891f87bbface1ab749b82fd7d7eae6aaac3b5ff041c44280984",
    "BaldEagleDamBrk.p18.hdf": "1d0063a84fd131ac95ffaa2b3f6647f2ef51c7f38f23c43e8ae6c698bfc95f0b",
    "JUL2020_D100RAS.p04.hdf": "37d91b9f957f78067cb0a8ae5db7cf3355f9c5d7172cb40e7931c35be78b9683",
    "AustinOyster.p01.hdf": "c9eff69c9c477ea293dcc69aea16fe88da8adf24da388c1e7249fec954da90f8",
    "1101001306.p01.hdf": "5106807376e0f69db9aa9714c1d50753c1682f6c678ce8049889b5cdd117f85f",
}
BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas"
MODES = {
    "off": dict(chunk_cache_bytes=0, handle_cache=False),
    "cache": dict(chunk_cache_bytes=64 * 1024 * 1024, handle_cache=False),
    "reuse": dict(chunk_cache_bytes=None, handle_cache=True),
}
_verified: dict = {}


def _fixture_path(name: str) -> Path:
    root = os.environ.get(FIXTURE_ENV)
    if not root:
        pytest.skip(f"set {FIXTURE_ENV} to the qualification fixture directory to run real-fixture parity")
    path = Path(root) / name
    if not path.is_file():
        pytest.skip(f"fixture {name} not present in {root}")
    if name not in _verified:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 24), b""):
                digest.update(block)
        _verified[name] = digest.hexdigest()
    assert _verified[name] == FIXTURES[name], f"{name} does not match the manifest hash"
    return path


def _layout(path: Path):
    with h5py.File(path, "r") as hdf:
        meshes = [m for m in hdf[BASE] if isinstance(hdf[BASE][m], h5py.Group) and "Water Surface" in hdf[BASE][m]]
        mesh = meshes[0]
        nt = hdf[f"{BASE}/{mesh}/Water Surface"].shape[0]
        attrs = hdf["Geometry/2D Flow Areas/Attributes"][()]
        names = [n.decode().strip() if isinstance(n, bytes) else str(n).strip() for n in attrs["Name"]]
        nphys = int(attrs["Cell Count"][names.index(mesh)])
        has_faces = "Face Velocity" in hdf[f"{BASE}/{mesh}"]
    return mesh, nt, nphys, has_faces


def _in_mode(mode, fn):
    hdf_io.close_hdf_handles()
    hdf_io.configure_hdf_reads(**MODES[mode])
    try:
        return fn()
    finally:
        hdf_io.configure_hdf_reads(chunk_cache_bytes=None, handle_cache=None)
        hdf_io.close_hdf_handles()


def _same_bits(a, b):
    a = np.asarray(a)
    b = np.asarray(b)
    assert a.dtype == b.dtype and a.shape == b.shape
    if a.dtype == object:
        assert a.tolist() == b.tolist()
    else:
        assert np.array_equal(
            np.ascontiguousarray(a).view(np.uint8), np.ascontiguousarray(b).view(np.uint8)
        )


def _assert_frame_identical(left, right):
    assert type(left) is type(right)
    geometry = getattr(left, "_geometry_column_name", None) if hasattr(left, "geom_type") else None
    if geometry is not None and geometry in left.columns:
        assert str(left.crs) == str(right.crs)
        assert [g.wkb if g is not None else None for g in left[geometry]] == [
            g.wkb if g is not None else None for g in right[geometry]
        ]
        left = pd.DataFrame(left.drop(columns=geometry))
        right = pd.DataFrame(right.drop(columns=geometry))
    pd.testing.assert_frame_equal(left, right, check_exact=True)
    for column in left.columns:
        if pd.api.types.is_float_dtype(left[column]):
            _same_bits(left[column].to_numpy(), right[column].to_numpy())
    assert repr(sorted(left.attrs.items())) == repr(sorted(right.attrs.items()))


def _assert_dataarray_identical(left, right):
    import xarray as xr

    xr.testing.assert_identical(left, right)
    _same_bits(left.values, right.values)


def _outcome(fn):
    try:
        return ("value", fn())
    except Exception as exc:  # a fixture-level error must be identical in every mode
        return ("error", type(exc), str(exc))


def _compare(name, fn, compare):
    path = _fixture_path(name)
    results = {mode: _in_mode(mode, lambda: _outcome(lambda: fn(path))) for mode in MODES}
    for mode in ("cache", "reuse"):
        if results["off"][0] == "error" or results[mode][0] == "error":
            assert results[mode] == results["off"]
        else:
            compare(results["off"][1], results[mode][1])


def _frames(left, right):
    _assert_frame_identical(left, right)


def _dataarrays(left, right):
    assert len(left) == len(right)
    for a, b in zip(left, right):
        _assert_dataarray_identical(a, b)


names = pytest.mark.parametrize("name", list(FIXTURES))


@names
def test_mesh_max_ws(name):
    from ras_commander import HdfResultsMesh

    _compare(name, lambda p: HdfResultsMesh.get_mesh_max_ws(p), _frames)


@names
def test_mesh_max_ws_with_ghost_cells(name):
    from ras_commander import HdfResultsMesh

    _compare(name, lambda p: HdfResultsMesh.get_mesh_max_ws(p, include_ghost_cells=True), _frames)


@names
@pytest.mark.parametrize("variable", ["Water Surface", "Face Velocity"])
def test_per_timestep_reads(name, variable):
    from ras_commander import HdfResultsMesh

    mesh, nt, _, has_faces = _layout(_fixture_path(name))
    if variable == "Face Velocity" and not has_faces:
        pytest.skip(f"{name} has no Face Velocity output")
    steps = sorted({int(round(i * (nt - 1) / 23)) for i in range(24)})

    def read(path):
        return [
            HdfResultsMesh.get_mesh_timeseries(path, mesh, variable, truncate=False, time_selection=t)
            for t in steps
        ]

    _compare(name, read, _dataarrays)


@names
def test_single_cell_all_time_reads(name):
    from ras_commander import HdfResultsMesh

    mesh, _, nphys, _ = _layout(_fixture_path(name))

    def read(path):
        return [
            HdfResultsMesh.get_mesh_timeseries(path, mesh, "Water Surface", spatial_selection=c)
            for c in (1000 % nphys, nphys // 2, nphys - 2)
        ]

    _compare(name, read, _dataarrays)


@names
def test_view_strided_block(name):
    from ras_commander import HdfResultsMesh

    mesh, nt, nphys, _ = _layout(_fixture_path(name))

    def read(path):
        view = HdfResultsMesh.get_mesh_timeseries(
            path, mesh, "Water Surface", return_type="view",
            time_selection=slice(0, min(nt, 24)), spatial_selection=slice(0, nphys, 7),
        )
        return view.to_numpy()

    _compare(name, read, _same_bits)


@names
def test_boundary_condition_series(name):
    import xarray as xr
    from ras_commander import HdfResultsMesh

    def compare(left, right):
        xr.testing.assert_identical(left, right)
        for var in left.data_vars:
            _same_bits(left[var].values, right[var].values)

    _compare(name, lambda p: HdfResultsMesh.get_boundary_conditions_timeseries(p), compare)


@names
def test_timestamps_and_start_time(name):
    from ras_commander import HdfBase

    def read(path):
        return (
            np.asarray(HdfBase.get_unsteady_timestamps(path)),
            HdfBase.get_simulation_start_time(path),
        )

    def compare(left, right):
        _same_bits(left[0], right[0])
        assert left[1] == right[1]

    _compare(name, read, compare)


@names
@pytest.mark.parametrize(
    "method",
    ["get_mesh_areas", "get_mesh_cell_points", "get_mesh_cell_faces", "bc_lines", "get_mesh_perimeter_faces"],
)
def test_geometry_readers(name, method):
    from ras_commander import HdfBndry, HdfMesh

    mesh, _, _, _ = _layout(_fixture_path(name))
    readers = {
        "get_mesh_areas": lambda p: HdfMesh.get_mesh_areas(p),
        "get_mesh_cell_points": lambda p: HdfMesh.get_mesh_cell_points(p),
        "get_mesh_cell_faces": lambda p: HdfMesh.get_mesh_cell_faces(p),
        "bc_lines": lambda p: HdfBndry.get_bc_lines(p),
        "get_mesh_perimeter_faces": lambda p: HdfMesh.get_mesh_perimeter_faces(p, mesh),
    }
    _compare(name, readers[method], _frames)
