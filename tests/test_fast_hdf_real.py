"""Opt-in-capable conformance on existing RasExamples projects, without compute.

Set RAS_FAST_HDF_FIXTURE_ROOT to an extracted example_projects directory. The
repository's example_projects is used when available. Missing fixtures/extension
are explicit skips. RAS_FAST_HDF_LARGE=1 adds the 483 MB computed plan to the scan.
"""
import gzip
import math
import os
from pathlib import Path

import h5py
import numpy as np
import pytest


ROOT = Path(os.environ.get("RAS_FAST_HDF_FIXTURE_ROOT", Path(__file__).resolve().parents[1] / "example_projects"))
BALD = ROOT / "BaldEagleCrkMulti2D_213"
GEOMETRIES = [BALD / f"BaldEagleDamBrk.g{n:02}.hdf" for n in (1, 3, 6, 9, 11)] + [ROOT / "Weise_2D" / "Weise.g08.hdf"]
PLANS = [BALD / "BaldEagleDamBrk.p03.hdf", ROOT / "Muncie_conn_test" / "Muncie.p01.hdf"]
LARGE = ROOT / "BaldEagleCrkMulti2D_fleet_mc_mc_fleet_001" / "BaldEagleDamBrk.p07.hdf"
CORPUS = GEOMETRIES + PLANS + ([LARGE] if os.environ.get("RAS_FAST_HDF_LARGE") == "1" else [])


@pytest.fixture
def native():
    return pytest.importorskip("ras_commander_fast_hdf")


def require_file(path):
    if not path.is_file():
        pytest.skip(f"Real fixture unavailable: {path}")
    return path


def assert_exact(actual, expected):
    assert actual.shape == expected.shape
    assert actual.dtype == expected.dtype
    assert actual.tobytes(order="C") == expected.tobytes(order="C")


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: p.parent.name + "/" + p.name)
def test_all_real_numeric_datasets(native, path, record_property):
    require_file(path)
    names, unsupported = [], []
    with h5py.File(path, "r") as f:
        def visit(name, obj):
            if isinstance(obj, h5py.Dataset):
                (names if obj.dtype.kind in "iuf" and obj.shape is not None else unsupported).append(name)
        f.visititems(visit)
        assert names, "Fixture contains no numeric datasets"
        for name in names:
            expected = np.asarray(f[name][()])
            actual = native.read_numeric(str(path), name, threads=2)
            try:
                assert_exact(actual, expected)
            except AssertionError as exc:
                raise AssertionError(f"Exact dataset mismatch: {path}:{name}") from exc
            if expected.ndim == 2 and all(d > 3 for d in expected.shape):
                slices = [(1, min(d, 12), 2) for d in expected.shape]
                assert_exact(native.read_numeric(str(path), name, selection=slices, threads=2),
                             expected[1:min(expected.shape[0], 12):2, 1:min(expected.shape[1], 12):2])
    record_property("numeric_datasets_exact", len(names))
    record_property("non_numeric_datasets_not_accelerated", len(unsupported))


@pytest.mark.parametrize("path", GEOMETRIES, ids=lambda p: p.parent.name + "/" + p.name)
def test_real_polygons_preserve_topology_vertices_ids(native, path, record_property):
    import shapely
    from ras_commander.hdf import HdfMesh
    require_file(path)
    reference = HdfMesh.get_mesh_cell_polygons(path, backend="python")
    actual = HdfMesh.get_mesh_cell_polygons(path, backend="rust", threads=2)
    assert not reference.empty
    assert actual.columns.tolist() == reference.columns.tolist()
    assert actual.crs == reference.crs
    assert actual[["mesh_name", "cell_id"]].equals(reference[["mesh_name", "cell_id"]])
    assert actual.geom_type.tolist() == reference.geom_type.tolist()
    assert shapely.is_valid(actual.geometry.values).all()
    assert shapely.equals(actual.geometry.values, reference.geometry.values).all()
    np.testing.assert_allclose(actual.area, reference.area, rtol=1e-13, atol=1e-8)
    np.testing.assert_array_equal(actual.total_bounds, reference.total_bounds)
    # Equality alone does not catch removal of collinear perimeter vertices.
    for expected, result in zip(reference.geometry, actual.geometry):
        assert set(map(tuple, shapely.get_coordinates(result))) == set(map(tuple, shapely.get_coordinates(expected)))
    record_property("cells_topologically_equal", len(actual))


@pytest.mark.parametrize("path", PLANS + ([LARGE] if os.environ.get("RAS_FAST_HDF_LARGE") == "1" else []), ids=lambda p: p.parent.name)
@pytest.mark.parametrize("truncate", [False, True])
def test_public_results_exact(native, path, truncate, monkeypatch):
    import xarray as xr
    from ras_commander.hdf import HdfResultsMesh
    require_file(path)
    with h5py.File(path, "r") as f:
        if "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas" not in f:
            pytest.skip(f"Fixture has no computed 2D time series: {path}")
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "0")
    reference = HdfResultsMesh.get_mesh_cells_timeseries(path, var="Water Surface", truncate=truncate)
    if not reference:
        pytest.skip(f"Fixture has no cell time series: {path}")
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    actual = HdfResultsMesh.get_mesh_cells_timeseries(path, var="Water Surface", truncate=truncate)
    assert set(actual) == set(reference)
    for mesh in reference:
        assert reference[mesh].data_vars, f"Empty baseline result for {mesh}"
        xr.testing.assert_identical(actual[mesh], reference[mesh])
        for var in reference[mesh].data_vars:
            assert_exact(actual[mesh][var].values, reference[mesh][var].values)
        monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "0")
        expected_faces = HdfResultsMesh.get_mesh_faces_timeseries(path, mesh, truncate=truncate)
        monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
        actual_faces = HdfResultsMesh.get_mesh_faces_timeseries(path, mesh, truncate=truncate)
        xr.testing.assert_identical(actual_faces, expected_faces)


@pytest.mark.parametrize("method_name", ["get_mesh_max_ws", "get_mesh_max_depth"])
def test_real_summary_output_parity(native, monkeypatch, method_name):
    from geopandas.testing import assert_geodataframe_equal
    from ras_commander.hdf import HdfResultsMesh
    if os.environ.get("RAS_FAST_HDF_LARGE") != "1":
        pytest.skip("Set RAS_FAST_HDF_LARGE=1 for computed-plan summary conformance")
    path = require_file(LARGE)
    method = getattr(HdfResultsMesh, method_name)
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "0")
    reference = method(path)
    if method_name == "get_mesh_max_depth" and reference.empty:
        pytest.skip("Real computed fixture does not contain a Depth dataset")
    assert not reference.empty
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    actual = method(path)
    assert_geodataframe_equal(actual, reference, check_crs=True)


def decode_tiles(path):
    reader_module = pytest.importorskip("pmtiles.reader")
    decoder = pytest.importorskip("mapbox_vector_tile")
    with path.open("rb") as fh:
        reader = reader_module.Reader(reader_module.MmapSource(fh))
        header, metadata = reader.header(), reader.metadata()
    def tiles():
        with path.open("rb") as fh:
            reader = reader_module.Reader(reader_module.MmapSource(fh))
            for address, data in reader_module.all_tiles(reader.get_bytes):
                if data[:2] == b"\x1f\x8b":
                    data = gzip.decompress(data)
                yield address, decoder.decode(data, default_options={"y_coord_down": True})
    return header, metadata, tiles()


def to_tile_pixels(geom, z, x, y, extent):
    import shapely
    def transform(coords):
        lon, lat = coords[:, 0], np.radians(coords[:, 1])
        n = 2 ** z
        return np.column_stack([((lon + 180) / 360 * n - x) * extent,
            ((1 - np.log(np.tan(lat) + 1 / np.cos(lat)) / math.pi) / 2 * n - y) * extent])
    return shapely.transform(geom, transform)


@pytest.mark.parametrize("geom_number,min_zoom,max_zoom", [(11, 6, 12), (1, 10, 15)])
def test_real_pmtiles_ids_properties_coverage_and_validity(native, tmp_path, record_property,
                                                         geom_number, min_zoom, max_zoom):
    import shapely
    from shapely.geometry import shape, box
    from ras_commander import fast_hdf
    from ras_commander.hdf import HdfMesh
    pytest.importorskip("pmtiles.reader")
    pytest.importorskip("mapbox_vector_tile")
    path = require_file(BALD / f"BaldEagleDamBrk.g{geom_number:02}.hdf")
    source = HdfMesh.get_mesh_cell_polygons(path, backend="python").to_crs(4326)
    assert source.mesh_name.nunique() == (2 if geom_number == 11 else 1)
    properties = {}
    for mesh, group in source.groupby("mesh_name"):
        size = int(group.cell_id.max()) + 1
        properties[mesh] = {"test_value": np.arange(size, dtype="f8") * .25}
    output = tmp_path / "mesh.pmtiles"
    fast_hdf.export_mesh_pmtiles(path, output, properties=properties,
        min_zoom=min_zoom, max_zoom=max_zoom, backend="rust", threads=2)
    header, metadata, tiles = decode_tiles(output)
    assert header["min_zoom"] == min_zoom and header["max_zoom"] == max_zoom
    assert {layer["id"] for layer in metadata["vector_layers"]} == {"mesh_cells"}
    lookup = dict(zip(zip(source.mesh_name, source.cell_id), source.geometry))
    footprint = shapely.union_all(source.geometry.values)
    seen = {z: set() for z in range(min_zoom, max_zoom + 1)}
    invalid = []
    tile_count = 0
    for (z, x, y), layers in tiles:
        tile_count += 1
        assert set(layers) == {"mesh_cells"}
        layer = layers["mesh_cells"]
        extent = layer["extent"]
        geometries = []
        for feature in layer["features"]:
            props = feature["properties"]
            key = (props["mesh_name"], props["cell_id"])
            assert key in lookup
            assert props["test_value"] == key[1] * .25
            geom = shape(feature["geometry"])
            if not geom.is_valid:
                invalid.append((z, x, y, key))
            assert not geom.is_empty
            expected = to_tile_pixels(lookup[key], z, x, y, extent)
            assert expected.buffer(2).covers(geom.representative_point())
            geometries.append(geom)
            seen[z].add(key)
        want = to_tile_pixels(footprint, z, x, y, extent).intersection(box(0, 0, extent, extent)).buffer(-2)
        coverage = shapely.union_all(shapely.make_valid(geometries))
        assert want.difference(coverage).area <= max(1, want.area * 1e-6), (z, x, y)
    record_property("invalid_decoded_polygons", len(invalid))
    record_property("decoded_tiles", tile_count)
    for zoom, ids in seen.items():
        record_property(f"unique_source_ids_z{zoom}", len(ids))
    assert tile_count
    assert not invalid, f"Invalid decoded polygons, including low zoom: {invalid[:10]}"
    for zoom, ids in seen.items():
        assert ids == set(lookup), f"Zoom {zoom} dropped source cells"


def test_failed_export_preserves_existing_output(native, tmp_path):
    from ras_commander import fast_hdf
    path = require_file(BALD / "BaldEagleDamBrk.g11.hdf")
    output = tmp_path / "existing.pmtiles"
    output.write_bytes(b"existing archive sentinel")
    with pytest.raises(Exception):
        fast_hdf.export_mesh_pmtiles(path, output, source_crs="not a CRS", backend="rust")
    assert output.read_bytes() == b"existing archive sentinel"
    assert sorted(p.name for p in tmp_path.iterdir()) == [output.name]


def test_real_multilayer_pmtiles(native, tmp_path):
    from shapely.geometry import shape
    from ras_commander import fast_hdf
    from ras_commander.hdf import HdfBase
    pytest.importorskip("pmtiles.reader")
    pytest.importorskip("mapbox_vector_tile")
    path = require_file(BALD / "BaldEagleDamBrk.g11.hdf")
    layers = fast_hdf.packed_meshes(path, backend="rust", threads=2)
    for name, layer in layers.items():
        layer["properties"] = {"cell_id": layer["cell_ids"],
                               "active": np.ones(len(layer["cell_ids"]), dtype=bool)}
    output = tmp_path / "multi.pmtiles"
    fast_hdf.export_pmtiles(output, layers, source_crs=HdfBase.get_projection(path),
                           min_zoom=12, max_zoom=12, backend="rust", threads=2)
    _, metadata, tiles = decode_tiles(output)
    assert {layer["id"] for layer in metadata["vector_layers"]} == set(layers)
    seen = {name: set() for name in layers}
    for _, decoded in tiles:
        for name, layer in decoded.items():
            assert name in layers
            for feature in layer["features"]:
                assert shape(feature["geometry"]).is_valid
                assert feature["properties"]["active"] is True
                seen[name].add(feature["properties"]["cell_id"])
    for name in layers:
        assert seen[name] == set(layers[name]["cell_ids"])
