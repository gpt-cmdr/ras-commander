"""Real mesh samples exported as holed and multipart regions, without compute."""
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
import pytest
gpd = pytest.importorskip("geopandas")
import shapely
from shapely.geometry import MultiPolygon, box, shape
from ras_commander import fast_hdf
from ras_commander.hdf import HdfBase, HdfMesh
from .helpers import decode, pack, pixels
from .test_packed_pmtiles import provenance


@pytest.mark.parametrize("filename,version", [("JUL2020_D100RAS.p04.hdf", "5.0.7"),
    ("BaldEagleDamBrk.p03.hdf", "6.6"), ("BaldEagleDamBrk.p18.hdf", "7.0")])
def test_real_regions(tmp_path, filename, version, record_property):
    fixture_root = os.environ.get("RAS_EXPORT_FIXTURE_ROOT")
    if not fixture_root:
        pytest.skip("Set RAS_EXPORT_FIXTURE_ROOT to immutable locally copied qualification HDFs")
    path = Path(fixture_root) / filename
    assert path.is_file(), path
    attrs = HdfBase.get_attrs(path, "/")
    assert f"HEC-RAS {version}" in attrs["File Version"]
    started = time.perf_counter()
    source = HdfMesh.get_mesh_cell_polygons(path, backend="python")
    assert not source.empty and source.crs is not None
    # Bounded valid sample, preserving source vertices; not a whole-model gate.
    sample = source[source.cell_id < 512]
    sample = sample[sample.geometry.is_valid & ~sample.geometry.is_empty].reset_index(drop=True)
    assert len(sample) > 16
    donut = None
    for i, target in enumerate(sample.geometry[:128]):
        neighbors = sample.sindex.query(target, predicate="intersects")
        neighbors = neighbors[neighbors != i]
        candidate = shapely.union_all(sample.geometry.iloc[neighbors].values)
        if (candidate.geom_type == "Polygon" and candidate.is_valid and len(candidate.interiors)
                and candidate.area > 0):
            donut = candidate
            member_ids = sample.iloc[neighbors][["mesh_name", "cell_id"]].values.tolist()
            break
    assert donut is not None, "No source-cell neighbor ring found in bounded sample"
    island = next(g for g in source.geometry.values if g.is_valid and not g.intersects(donut))
    multipart = MultiPolygon([donut, island])
    assert multipart.is_valid
    geoms = [donut, multipart]
    expected = gpd.GeoSeries(geoms, crs=source.crs).to_crs(4326)
    layer = pack(geoms, [2**53 + 1, 2**53 + 2])
    layer["properties"] = {"version": [version, version], "units": ["Foot_US", "Foot_US"],
        "region": ["neighbor_ring", "neighbor_ring_and_remote_cell"],
        "member_count": [len(member_ids), len(member_ids) + 1]}
    output = tmp_path / "regions.pmtiles"
    export_started = time.perf_counter()
    fast_hdf.export_pmtiles(output, {"regions": layer}, source_crs=source.crs,
        min_zoom=17, max_zoom=18, backend="rust", threads=2)
    export_seconds = time.perf_counter() - export_started
    header, metadata, tiles = decode(output)
    assert (header["min_zoom"], header["max_zoom"]) == (17, 18)
    seen = {17: set(), 18: set()}
    invalid = []
    hole_count = 0
    hole_void_observations = 0
    for (z, x, y), layers in tiles.items():
        result = layers["regions"]
        for feature in result["features"]:
            i = list(layer["cell_ids"]).index(feature["id"])
            seen[z].add(feature["id"])
            for key, values in layer["properties"].items():
                assert feature["properties"][key] == values[i]
            actual = shape(feature["geometry"])
            if not actual.is_valid:
                invalid.append([z, x, y, int(feature["id"]), shapely.is_valid_reason(actual)])
            # Upstream quantization may introduce invalid spikes; preserve evidence,
            # and compare a diagnostic valid view only for coverage measurement.
            expected_px = pixels(expected.iloc[i], z, x, y, result["extent"])
            core = box(0, 0, result["extent"], result["extent"])
            diagnostic = shapely.make_valid(actual)
            parts = expected.iloc[i].geoms if expected.iloc[i].geom_type == "MultiPolygon" else [expected.iloc[i]]
            for polygon in parts:
                for ring in polygon.interiors:
                    void = pixels(shapely.Polygon(ring), z, x, y, result["extent"]).intersection(core)
                    void = void.difference(expected_px.boundary.buffer(2))
                    if void.area > 0:
                        hole_void_observations += 1
                        assert void.intersection(diagnostic).area < 1e-5
            diff = expected_px.intersection(core).symmetric_difference(diagnostic.intersection(core))
            assert diff.difference(expected_px.boundary.buffer(2)).area < 1e-4
            if actual.geom_type in ("Polygon", "MultiPolygon"):
                hole_count += sum(len(p.interiors) for p in (actual.geoms if actual.geom_type == "MultiPolygon" else [actual]))
    assert all(ids == set(map(int, layer["cell_ids"])) for ids in seen.values())
    # A hole crossing tile edges becomes open cutouts, so count verified voids
    # rather than requiring each individual clipped tile to contain a full hole.
    assert tiles and hole_void_observations > 0
    frame = gpd.GeoDataFrame(layer["properties"], geometry=geoms, crs=source.crs)
    frame.to_file(tmp_path / "source-regions.gpkg", driver="GPKG")
    freestiler = pytest.importorskip("freestiler")
    reference = tmp_path / "reference.pmtiles"
    freestiler.freestile({"regions": frame}, reference, min_zoom=17, max_zoom=18,
                        simplification=False, quiet=True)
    _, _, reference_tiles = decode(reference)
    assert tiles.keys() == reference_tiles.keys()
    reference_invalid = 0
    for address, layers in tiles.items():
        actual_features = {f["properties"]["region"]: f for f in layers["regions"]["features"]}
        expected_features = {f["properties"]["region"]: f for f in reference_tiles[address]["regions"]["features"]}
        assert actual_features.keys() == expected_features.keys()
        for key, feature in actual_features.items():
            reference_feature = expected_features[key]
            assert feature["properties"] == reference_feature["properties"]
            assert feature["geometry"] == reference_feature["geometry"]
            reference_invalid += not shape(reference_feature["geometry"]).is_valid
    assert reference_invalid == len(invalid)
    report = dict(fixture=filename, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        attrs=attrs, source_crs=str(source.crs), source_cells=len(source), sample_cells=len(sample),
        member_ids=member_ids, region_features=2, rings=len(layer["ring_offsets"])-1,
        tiles=len(tiles), invalid_decoded=invalid, hole_observations=hole_count,
        hole_void_observations=hole_void_observations,
        reference_invalid=reference_invalid, reference_geometry_exact=True,
        export_seconds=export_seconds, total_seconds=time.perf_counter()-started,
        output_bytes=output.stat().st_size)
    (tmp_path / "evidence.json").write_text(json.dumps(report, indent=2, default=str))
    record_property("invalid_decoded", len(invalid))
    record_property("export_seconds", export_seconds)
    record_property("fixture_sha256", report["sha256"])
    # Identity, attributes, holes and coverage above are hard gates. This records
    # freestiler's pre-existing integer validity gap separately from conversion.
    if invalid:
        pytest.xfail(f"Pinned freestiler integer quantization validity gap: {invalid[:2]}")
