"""Installed-wheel native consumer acceptance on real HEC-RAS 5.0.7/6.6/7.0 HDF.

Required-native tests count calls into the installed extension and forbid
Python fallback; Python-reference tests select ``backend='python'`` and assert
zero native calls. Oracles are raw h5py reads, the frozen 89b4ace Python
reference parquet files, and independent format readers (pyarrow, pyogrio,
json, and a spec-level PMTiles/MVT decoder in ``contract.py``).
"""
import datetime as dt
import gc
import json
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np
import pytest

from .contract import (RESULTS, NativeCalls, chunks_touched, decode_mvt, native_package,
                       read_pmtiles, replaced_native, tile_payload)

pytestmark = pytest.mark.usefixtures("receipt")
BENCHMARK = Path(__file__).resolve().parents[2] / "scripts/benchmarks/rust_consumer_contract/benchmark.py"

CASES = {
    # fixture: (mesh names, reference CRS, stored version, physical cells per mesh)
    "BaldEagleDamBrk.p07.hdf": (["BaldEagleCr"], "EPSG:2271", "HEC-RAS 6.6 September 2024", [87039]),
    "BaldEagleDamBrk.p18.hdf": (["BaldEagleCr", "Upper 2D Area"], "EPSG:2271", "HEC-RAS 7.0 April 2026", [3359, 1066]),
    "JUL2020_D100RAS.p04.hdf": (["D601"], "EPSG:6588", "HEC-RAS 5.0.7 March 2019", [340248]),
}
SELECTIONS = [
    lambda t, c: (t // 2, slice(c // 3, c // 3 + 500)),          # one time step, cell window
    lambda t, c: (slice(3, 8), slice(10, 1210, 3)),              # time window, strided cells
    lambda t, c: (-1, slice(None)),                              # negative index, full row
    lambda t, c: (slice(None, None, 50), 7),                     # one cell through time
    lambda t, c: (Ellipsis, slice(c - 5, None)),                 # ellipsis, tail
]


def _bitwise_equal(a, b):
    a, b = np.asarray(a), np.asarray(b)
    if a.dtype != b.dtype or a.shape != b.shape:
        return False
    if a.dtype.kind == "f":
        return np.array_equal(a.view(f"u{a.dtype.itemsize}"), b.view(f"u{b.dtype.itemsize}"))
    return np.array_equal(a, b)


def _wse(h, mesh):
    return h[f"{RESULTS}/2D Flow Areas/{mesh}/Water Surface"]


def _cases(names=None):
    return [(name, mesh) for name, (meshes, *_rest) in CASES.items()
            if names is None or name in names for mesh in meshes]


# ---------------------------------------------------------------------------
# On-demand slices: required native, Python reference, no fallback.


@pytest.mark.parametrize("name,mesh", _cases())
def test_required_native_slices_are_bitwise_h5py(fixture_dir, evidence, name, mesh):
    from ras_commander import fast_hdf
    with h5py.File(fixture_dir / name, "r") as h:
        ds = _wse(h, mesh)
        selections = [make(*ds.shape) for make in SELECTIONS]
        with NativeCalls(["read_numeric", "read_numeric_batch"]) as calls:
            for sel in selections:
                native = fast_hdf.read_dataset(ds, sel, backend="rust")
                assert _bitwise_equal(native, ds[sel]), sel
        assert calls.snapshot() == {"read_numeric": len(selections), "read_numeric_batch": 0}
        capability = native_package().numeric_capability(str(fixture_dir / name), ds.name)
        plan = []
        for sel in selections:
            from ras_commander.fast_hdf import _selection
            slices, _ = _selection(ds.shape, sel)
            plan.append(chunks_touched(ds.shape, capability["chunks"], slices))
    evidence.append({"test": "required_native_slices", "fixture": name, "mesh": mesh,
                     "shape": list(ds.shape), "chunks": capability["chunks"],
                     "native_calls": calls.snapshot(), "chunks_touched_per_selection": plan})


@pytest.mark.parametrize("name,mesh", _cases(["BaldEagleDamBrk.p18.hdf", "BaldEagleDamBrk.p07.hdf"]))
def test_python_reference_makes_no_native_call(fixture_dir, name, mesh):
    from ras_commander import fast_hdf
    with h5py.File(fixture_dir / name, "r") as h:
        ds = _wse(h, mesh)
        with NativeCalls(["read_numeric", "read_numeric_batch"]) as calls:
            for make in SELECTIONS:
                sel = make(*ds.shape)
                assert _bitwise_equal(fast_hdf.read_dataset(ds, sel, backend="python"), ds[sel])
        assert sum(calls.snapshot().values()) == 0


def test_required_native_never_falls_back(fixture_dir, monkeypatch):
    from ras_commander import fast_hdf
    pkg = native_package()

    def refuse(*args, **kwargs):
        raise pkg.UnsupportedError("consumer-contract injected refusal")

    with h5py.File(fixture_dir / "BaldEagleDamBrk.p18.hdf", "r") as h:
        ds = _wse(h, "BaldEagleCr")
        with replaced_native("read_numeric", refuse):
            with pytest.raises(fast_hdf.FastHdfError, match="injected refusal"):
                fast_hdf.read_dataset(ds, (0, slice(0, 10)), backend="rust")
            monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
            with pytest.raises(fast_hdf.FastHdfError):
                fast_hdf.read_dataset(ds, (0, slice(0, 10)))
            # Auto mode documents h5py fallback for UnsupportedError only.
            monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
            assert _bitwise_equal(fast_hdf.read_dataset(ds, (0, slice(0, 10))), ds[0, 0:10])
        with pytest.raises(fast_hdf.FastHdfError):
            fast_hdf.read_dataset(ds, ([0, 2], slice(0, 4)), backend="rust")  # advanced index
        monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
        with NativeCalls(["read_numeric"]) as calls:
            fast_hdf.read_dataset(ds, (1, slice(0, 4)))
        assert calls.snapshot() == {"read_numeric": 1}


def test_call_recorder_preserves_binding_signatures():
    import inspect
    pkg = native_package()
    names = ["read_numeric", "assemble_cells", "temporal_reduce", "export_ipc_file"]
    before = {n: str(inspect.signature(getattr(pkg, n))) for n in names}
    with NativeCalls(names):
        during = {n: str(inspect.signature(getattr(pkg, n))) for n in names}
        assert getattr(pkg, "assemble_cells").__wrapped__ is not None
    assert before == during
    assert "return_diagnostics" in before["assemble_cells"]


def test_small_slice_physical_io_is_bounded(fixture_dir, evidence, tmp_path):
    """Measured process I/O for a small slice versus a whole-dataset read.

    Windows process read_bytes counts bytes requested through ReadFile (cache
    hits included), so it bounds the physical reads the process issued. The
    compressed sizes of the touched storage chunks (h5py chunk index) are the
    independent lower bound; whole-chunk decompression remains explicit.
    """
    name = "BaldEagleDamBrk.p07.hdf"
    results = {}
    for route in ("ondemand_native", "archival_native"):
        out = tmp_path / f"{route}.json"
        subprocess.run([sys.executable, "-I", str(BENCHMARK), "worker", "--route", route,
                        "--fixture", str(fixture_dir / name), "--mesh", "BaldEagleCr",
                        "--requests", "5", "--width", "2000", "--out", str(out)],
                       check=True, cwd=tmp_path)
        results[route] = json.loads(out.read_text())
    small, whole = results["ondemand_native"], results["archival_native"]
    assert small["digest"] == whole["digest"]
    assert small["native_calls"]["read_numeric"] == 5 and small["native_calls"]["read_numeric_batch"] == 0
    assert whole["native_calls"]["read_numeric_batch"] == 1
    assert small["io"]["read_bytes"] < whole["io"]["read_bytes"] / 20
    assert small["chunk_plan"]["compressed_bytes"] <= small["io"]["read_bytes"] + 1
    evidence.append({"test": "small_slice_physical_io", "fixture": name,
                     "ondemand": {k: small[k] for k in ("io", "chunk_plan", "returned_bytes")},
                     "archival": {k: whole[k] for k in ("io", "chunk_plan", "returned_bytes")}})


# ---------------------------------------------------------------------------
# Ownership and lifetime across Python/native.


def test_returned_arrays_own_memory_beyond_file_lifetime(fixture_dir):
    from ras_commander import fast_hdf
    path = fixture_dir / "BaldEagleDamBrk.p18.hdf"
    with h5py.File(path, "r") as h:
        ds = _wse(h, "Upper 2D Area")
        expected = ds[100, 0:600].copy()
        a = fast_hdf.read_dataset(ds, (100, slice(0, 600)), backend="rust")
        b = fast_hdf.read_dataset(ds, (100, slice(0, 600)), backend="rust")
    gc.collect()
    root = a
    while isinstance(root.base, np.ndarray):
        root = root.base
    assert root.flags.owndata or root.base is not None  # owned by NumPy or a native capsule
    assert a.flags.writeable and a.flags.c_contiguous
    assert not np.shares_memory(a, b)
    a[:] = -1.0
    assert _bitwise_equal(b, expected)
    with h5py.File(path, "r") as h:
        again = fast_hdf.read_dataset(_wse(h, "Upper 2D Area"), (100, slice(0, 600)), backend="rust")
    assert _bitwise_equal(again, expected)


def test_assemble_cells_does_not_alias_caller_buffers(fixture_dir):
    from ras_commander import fast_hdf
    pkg = native_package()
    path = fixture_dir / "BaldEagleDamBrk.p18.hdf"
    names = fast_hdf._MESH_ARRAYS
    with h5py.File(path, "r") as h:
        raw = [h[f"Geometry/2D Flow Areas/Upper 2D Area/{n}"][()] for n in names]
    args = [np.ascontiguousarray(v, dtype=np.float64 if i in {0, 3} else np.int64)
            for i, v in enumerate(raw)]
    fresh = [a.copy() for a in args]
    coords, offsets, ids = pkg.assemble_cells(*args)
    for a in args:
        a.fill(0)  # caller reuses/frees its buffers
    gc.collect()
    coords2, offsets2, ids2 = pkg.assemble_cells(*fresh)
    for out, ref in ((coords, coords2), (offsets, offsets2), (ids, ids2)):
        assert _bitwise_equal(out, ref)
        assert not any(np.shares_memory(out, a) for a in args + fresh)
    assert len(ids) == 1066


# ---------------------------------------------------------------------------
# Identity, CRS/units, geometry, and explicit D601 policy.


def _reference(reference_dir, name):
    import geopandas as gpd
    return gpd.read_parquet(reference_dir / f"{name}.parquet")


@pytest.mark.parametrize("name", ["BaldEagleDamBrk.p18.hdf", "BaldEagleDamBrk.p07.hdf"])
def test_composite_identity_geometry_crs_units(fixture_dir, reference_dir, evidence, name):
    import shapely
    from pyproj import CRS
    from ras_commander import fast_hdf
    from ras_commander.hdf.HdfBase import HdfBase
    meshes, crs, version, counts = CASES[name]
    path = fixture_dir / name
    with h5py.File(path, "r") as h:
        assert h.attrs["File Version"].decode() == version
        assert h.attrs["Units System"].decode() == "US Customary"
    assert CRS(HdfBase.get_projection(path)).equals(CRS(crs))
    with NativeCalls(["assemble_cells", "read_numeric_batch"]) as calls:
        native = fast_hdf.mesh_polygons(path, backend="rust", strict=True)
    assert calls.snapshot()["assemble_cells"] == len(meshes)
    with NativeCalls(["assemble_cells", "read_numeric_batch", "read_numeric"]) as py_calls:
        python = fast_hdf.mesh_polygons(path, backend="python", strict=True)
    assert sum(py_calls.snapshot().values()) == 0
    reference = _reference(reference_dir, name)
    for frame in (native, python, reference):
        assert CRS(frame.crs).equals(CRS(crs))
        assert frame.groupby("mesh_name").size().reindex(meshes).tolist() == counts
        assert not frame.duplicated(["mesh_name", "cell_id"]).any()
        assert frame["mesh_name"].notna().all() and frame["cell_id"].notna().all()
    key = ["mesh_name", "cell_id"]
    n = native.sort_values(key).reset_index(drop=True)
    p = python.sort_values(key).reset_index(drop=True)
    r = reference.sort_values(key).reset_index(drop=True)
    assert n[key].equals(p[key]) and n[key].astype({"cell_id": "int64"}).equals(r[key])
    assert shapely.equals(n.geometry.values, p.geometry.values).all()
    # The frozen reference stores HDF cell-center points: an independent check
    # that each polygon (native and legacy) contains its own cell center.
    assert set(r.geometry.geom_type) == {"Point"}
    assert shapely.covers(n.geometry.values, r.geometry.values).all()
    if len(meshes) > 1:
        ids = [set(n.loc[n.mesh_name == m, "cell_id"]) for m in meshes]
        assert ids[0] & ids[1], "expected repeated local cell IDs across meshes"
    evidence.append({"test": "composite_identity", "fixture": name, "rows": len(n),
                     "per_mesh": dict(zip(meshes, counts)), "native_calls": calls.snapshot()})


def test_d601_strict_refuses_and_quarantine_is_explicit(fixture_dir, reference_dir, evidence):
    from ras_commander import fast_hdf
    from ras_commander.hdf.HdfMesh import MeshCellPolygonError
    path = fixture_dir / "JUL2020_D100RAS.p04.hdf"
    with pytest.raises(MeshCellPolygonError, match="317422"):
        fast_hdf.mesh_polygons(path, backend="rust", strict=True)
    with NativeCalls(["assemble_cells"]) as calls:
        quarantined = fast_hdf.mesh_polygons(path, backend="rust", strict=False)
    assert calls.snapshot() == {"assemble_cells": 1}
    omitted = {r["cell_id"] for r in quarantined.attrs["cell_polygon_diagnostics"] if r["status"] == "omitted"}
    assert omitted == {317422, 339176}
    assert len(quarantined) == 340246
    reference = _reference(reference_dir, "JUL2020_D100RAS.p04.hdf")
    assert len(reference) == 340248
    missing = set(reference.cell_id) - set(quarantined.cell_id)
    assert missing == omitted and set(quarantined.cell_id) <= set(reference.cell_id)
    evidence.append({"test": "d601_policy", "strict": "MeshCellPolygonError(317422)",
                     "quarantine_rows": len(quarantined), "omitted": sorted(omitted)})


# ---------------------------------------------------------------------------
# Results consumer: native temporal reduction and timestamps.


@pytest.mark.parametrize("name", list(CASES))
def test_required_native_max_depth_matches_frozen_reference(fixture_dir, reference_dir, evidence,
                                                             monkeypatch, name):
    from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh
    meshes = CASES[name][0]
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    with NativeCalls(["temporal_reduce", "assemble_cells"]) as calls:
        got = HdfResultsMesh.get_mesh_max_depth(fixture_dir / name)
    assert calls.snapshot()["temporal_reduce"] >= len(meshes)
    reference = _reference(reference_dir, name)
    key = ["mesh_name", "cell_id"]
    g = got.sort_values(key).reset_index(drop=True)
    r = reference.sort_values(key).reset_index(drop=True)
    # Max depth is reported at HDF cell centers (no polygon assembly), so all
    # D601 physical cells, including the two with invalid polygons, are present.
    assert set(g.geometry.geom_type) == {"Point"}
    assert len(g) == len(r) == sum(CASES[name][3])
    assert g[key].astype({"cell_id": "int64"}).equals(r[key].astype({"cell_id": "int64"}))
    assert str(g["maximum_depth"].dtype) == "float32"
    assert _bitwise_equal(g["maximum_depth"].to_numpy(), r["maximum_depth"].to_numpy())
    evidence.append({"test": "max_depth_native", "fixture": name, "rows": len(g),
                     "native_calls": calls.snapshot()})


def test_timestamps_epoch_ms_and_year_3000(fixture_dir):
    from ras_commander import fast_results
    from ras_commander.hdf.HdfBase import HdfBase
    stamps = HdfBase.get_unsteady_timestamps(str(fixture_dir / "BaldEagleDamBrk.p07.hdf"))
    assert len(stamps) == 865 and stamps[0] == dt.datetime(1999, 1, 1, 12, 0)
    far = [dt.datetime(2999, 12, 31, 23, 59, 59, 999000), dt.datetime(3000, 1, 1, 0, 0, 0, 1000)]
    peaks = fast_results.peak_times_ms(far, np.array([1, 0, -1], dtype=np.int64))
    expected = [int((t - dt.datetime(1970, 1, 1)).total_seconds() * 1000) for t in far]
    assert peaks[0] == expected[1] and peaks[1] == expected[0] and np.ma.is_masked(peaks[2])
    assert expected[1] == 32503680000001


# ---------------------------------------------------------------------------
# First-tier exports: independent reopen/decode per advertised format.


FAR_MS = 32503680000001  # 3000-01-01T00:00:00.001Z


@pytest.fixture(scope="module")
def export_table(fixture_dir):
    import pyarrow as pa
    import shapely
    from ras_commander import fast_hdf
    from ras_commander.hdf.HdfBase import HdfBase
    path = fixture_dir / "BaldEagleDamBrk.p18.hdf"
    frame = fast_hdf.mesh_polygons(path, backend="rust", strict=True)
    n = len(frame)
    idx = np.arange(n)
    schema = pa.schema([
        pa.field("mesh_name", pa.string(), False), pa.field("cell_id", pa.int64(), False),
        pa.field("geometry", pa.binary(), False), pa.field("label", pa.string()),
        pa.field("flag", pa.bool_()), pa.field("count", pa.int64()),
        pa.field("area_ft2", pa.float64()), pa.field("peak_time", pa.timestamp("ms"))])
    table = pa.table({
        "mesh_name": frame.mesh_name.tolist(), "cell_id": frame.cell_id.to_numpy(np.int64),
        "geometry": shapely.to_wkb(frame.geometry.values, flavor="iso"),
        "label": [None if i % 7 == 0 else f"cell-{i}" for i in idx],
        "flag": [None if i % 5 == 0 else bool(i % 2) for i in idx],
        "count": [None if i % 3 == 0 else int(i) * 1_000_003 for i in idx],
        "area_ft2": [None if i % 11 == 0 else float(a) for i, a in zip(idx, frame.geometry.area)],
        "peak_time": pa.array([None if i % 13 == 0 else (FAR_MS if i % 2 else 915192000000 + int(i))
                               for i in idx], pa.int64()).cast(pa.timestamp("ms")),
    }, schema=schema)
    return table, HdfBase.get_projection(path)


def _decode_ms(values):
    out = []
    for v in values:
        if v is None:
            out.append(None)
        elif isinstance(v, (int, np.integer)):
            out.append(int(v))
        elif isinstance(v, str):
            out.append(int(np.datetime64(v.replace("Z", ""), "ms").astype(np.int64)))
        elif isinstance(v, np.datetime64):
            out.append(int(v.astype("datetime64[ms]").astype(np.int64)))
        elif isinstance(v, dt.datetime):
            if v.tzinfo is not None:  # e.g. GeoPackage returns UTC-aware values
                assert v.utcoffset() == dt.timedelta(0), f"non-UTC timestamp {v!r}"
                v = v.replace(tzinfo=None)
            out.append(int(np.datetime64(v, "ms").astype(np.int64)))
        else:
            raise TypeError(f"undecodable timestamp {v!r}")
    return out


def _reopen(fmt, path):
    """Independent decode to (columns: dict[name -> list], wkb list, crs)."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pyogrio
    if fmt == "arrow":
        table = pa.ipc.open_file(str(path)).read_all()
        crs = json.loads(table.schema.field("geometry").metadata[b"ARROW:extension:metadata"])["crs"]
    elif fmt == "parquet":
        pf = pq.ParquetFile(path)
        table = pf.read()
        geo = json.loads(pf.metadata.metadata[b"geo"])  # GeoParquet file key-value metadata
        assert geo["columns"][geo["primary_column"]]["encoding"] == "WKB"
        crs = geo["columns"][geo["primary_column"]]["crs"]
    elif fmt in {"fgb", "gpkg"}:
        meta, table = pyogrio.read_arrow(path)
        crs = meta["crs"]
        geom = meta.get("geometry_name") or "wkb_geometry"
        table = table.rename_columns(["geometry" if c == geom else c for c in table.column_names])
    else:
        lines = path.read_text(encoding="utf-8")
        if fmt == "geojson":
            doc = json.loads(lines)
            features = doc["features"]
        else:
            features = [json.loads(line) for line in lines.splitlines() if line.strip()]
        import shapely.geometry
        cols = {k: [f["properties"].get(k) for f in features]
                for k in ("mesh_name", "cell_id", "label", "flag", "count", "area_ft2", "peak_time")}
        cols["geometry"] = [shapely.geometry.shape(f["geometry"]).wkb for f in features]
        return cols, "EPSG:4326"
    cols = {name: table.column(name).to_pylist() for name in table.column_names}
    return cols, crs


@pytest.mark.parametrize("fmt", ["arrow", "parquet", "fgb", "gpkg", "geojson", "jsonl"])
def test_export_format_independent_reopen(export_table, tmp_path, evidence, fmt):
    import shapely
    from pyproj import CRS, Transformer
    from ras_commander import fast_hdf
    table, source_crs = export_table
    out = tmp_path / f"cells.{fmt}"
    with NativeCalls(["export_ipc_file", "validate_export_wkb"]) as calls:
        metrics = fast_hdf.export_arrow(out, table, source_crs=source_crs, format=fmt)
    assert calls.snapshot()["export_ipc_file"] == 1
    assert metrics["rows"] == table.num_rows
    cols, crs = _reopen(fmt, out)
    geographic = fmt in {"geojson", "jsonl"}
    assert CRS(crs).equals(CRS(4326 if geographic else source_crs), ignore_axis_order=True)
    assert len(cols["mesh_name"]) == table.num_rows
    want_ids = list(zip(table.column("mesh_name").to_pylist(), table.column("cell_id").to_pylist()))
    got_ids = list(zip(cols["mesh_name"], [int(v) for v in cols["cell_id"]]))
    assert None not in cols["mesh_name"] and None not in cols["cell_id"]
    assert sorted(got_ids) == sorted(want_ids) and len(set(got_ids)) == len(got_ids)
    order_preserved = got_ids == want_ids
    # Indexed FlatGeobuf stores features in packed R-tree order; every other
    # format must keep input order. Rows are aligned by composite identity.
    assert order_preserved or fmt == "fgb"
    position = {key: i for i, key in enumerate(got_ids)}
    perm = [position[key] for key in want_ids]
    cols = {name: [values[i] for i in perm] for name, values in cols.items()}
    source = shapely.from_wkb(table.column("geometry").to_pylist())
    decoded = shapely.from_wkb(cols["geometry"])
    if geographic:
        transformer = Transformer.from_crs(CRS(source_crs), CRS(4326), always_xy=True)
        source = shapely.transform(source, transformer.transform, interleaved=False)
        assert shapely.equals_exact(shapely.normalize(source), shapely.normalize(decoded), 1e-9).all()
    else:
        assert shapely.equals_exact(source, decoded, 0.0).all()
    mismatches = {}
    for name in ("label", "flag", "count", "area_ft2"):
        want = table.column(name).to_pylist()
        got = cols[name]
        if name == "count" and geographic:
            got = [None if v is None else int(v) for v in got]
        if got != want:
            mismatches[name] = sum(a != b for a, b in zip(got, want))
    import pyarrow as pa
    want_ms = table.column("peak_time").cast(pa.int64()).to_pylist()
    got_ms = _decode_ms(cols["peak_time"])
    if got_ms != want_ms:
        bad = [(w, g) for w, g in zip(want_ms, got_ms) if w != g]
        mismatches["peak_time"] = {"count": len(bad), "examples": bad[:3]}
    evidence.append({"test": "export_reopen", "format": fmt, "metrics": metrics,
                     "native_calls": calls.snapshot(), "mismatches": mismatches,
                     "row_order_preserved": order_preserved,
                     "output_bytes": out.stat().st_size})
    assert mismatches == {}


def test_nullable_identity_is_rejected(export_table, tmp_path):
    import pyarrow as pa
    from ras_commander import fast_hdf
    table, source_crs = export_table
    loose = table.cast(pa.schema([f.with_nullable(True) if f.name == "cell_id" else f
                                  for f in table.schema]))
    with pytest.raises(ValueError, match="nonnullable"):
        fast_hdf.export_arrow(tmp_path / "loose.parquet", loose, source_crs=source_crs, format="parquet")
    assert not (tmp_path / "loose.parquet").exists()


def test_float32_attribute_is_rejected_not_converted(export_table, tmp_path):
    import pyarrow as pa
    from ras_commander import fast_hdf
    table, source_crs = export_table
    narrow = table.set_column(table.schema.get_field_index("area_ft2"), pa.field("area_ft2", pa.float32()),
                              table.column("area_ft2").cast(pa.float32()))
    with pytest.raises(ValueError, match="Float32"):
        fast_hdf.export_arrow(tmp_path / "narrow.parquet", narrow, source_crs=source_crs, format="parquet")
    assert not (tmp_path / "narrow.parquet").exists()


def test_pmtiles_bundle_independent_decode(export_table, tmp_path, evidence):
    import pyarrow as pa
    import shapely
    from ras_commander import fast_hdf
    table, source_crs = export_table
    bundle = tmp_path / "bundle"
    with NativeCalls(["export_pmtiles_ipc_file", "validate_export_wkb"]) as calls:
        metrics = fast_hdf.export_arrow_pmtiles(bundle, table, source_crs=source_crs, min_zoom=8,
                                                max_zoom=13, timestamp_ms=True)
    assert calls.snapshot()["export_pmtiles_ipc_file"] == 1
    identities = pa.ipc.open_file(str(bundle / "identities.arrow")).read_all()
    assert not any(f.nullable for f in identities.schema)
    ident = {row["export_id"]: (row["mesh_name"], row["cell_id"]) for row in identities.to_pylist()}
    assert sorted(ident.values()) == sorted(zip(table.column("mesh_name").to_pylist(),
                                                table.column("cell_id").to_pylist()))
    archive = read_pmtiles(bundle / "tiles.pmtiles")
    header = archive["header"]
    assert header["tile_type"] == 1 and (header["min_zoom"], header["max_zoom"]) == (8, 13)
    from .contract import mvt_polygons
    seen, keys, features, tag_mismatch, far_ok = set(), set(), 0, 0, 0
    defects = {}
    expected_far = {key for key, ms in zip(zip(table.column("mesh_name").to_pylist(),
                                               table.column("cell_id").to_pylist()),
                                           table.column("peak_time").cast(pa.int64()).to_pylist())
                    if ms == FAR_MS}
    for (z, x, y) in sorted(archive["tiles"]):
        zoom = defects.setdefault(z, {"features": 0, "invalid": 0, "degenerate_rings": 0, "empty": 0})
        for layer in decode_mvt(tile_payload(archive, (z, x, y))):
            keys.update(layer["keys"])
            for feature in layer["features"]:
                zoom["features"] += 1
                polygons, degenerate = mvt_polygons(feature["geometry"])
                zoom["degenerate_rings"] += degenerate
                if not polygons:
                    zoom["empty"] += 1
                elif not shapely.is_valid(shapely.MultiPolygon(polygons)):
                    zoom["invalid"] += 1
                if z != 13:
                    continue
                features += 1
                seen.add(feature["id"])
                tags = {layer["keys"][k]: layer["values"][v]
                        for k, v in zip(feature["tags"][::2], feature["tags"][1::2])}
                if (tags.get("mesh_name"), tags.get("cell_id")) != ident.get(feature["id"]):
                    tag_mismatch += 1
                if ident.get(feature["id"]) in expected_far and tags.get("peak_time") == FAR_MS:
                    far_ok += 1
    assert seen <= set(ident)
    coverage = len(seen) / len(ident)
    evidence.append({"test": "pmtiles_decode", "metrics": metrics, "header": header,
                     "tiles": len(archive["tiles"]), "z13_features": features,
                     "z13_distinct_ids": len(seen), "identity_rows": len(ident),
                     "validity_by_zoom": defects, "z13_tag_identity_mismatches": tag_mismatch,
                     "z13_year3000_ms_tags": far_ok, "property_keys": sorted(keys),
                     "native_calls": calls.snapshot(),
                     "note": "MVT quantization validity defects are recorded, not waived"})
    assert coverage == 1.0, f"max-zoom tiles cover {coverage:.4f} of exported identities"
    assert tag_mismatch == 0
    assert far_ok > 0, "timestamp_ms=True must carry year-3000 epoch milliseconds"
