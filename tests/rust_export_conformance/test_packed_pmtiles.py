"""Actual freestiler exports decoded via independent PMTiles/MVT readers."""
from pathlib import Path

import numpy as np
import pytest
gpd = pytest.importorskip("geopandas")
import shapely
from shapely.geometry import MultiPolygon, Polygon, box, shape

from ras_commander import fast_hdf
import ras_commander
native = pytest.importorskip("ras_commander_fast_hdf")
from .helpers import decode, pack, pixels


@pytest.fixture(autouse=True)
def provenance():
    root = Path(__file__).resolve().parents[2]
    assert Path.cwd().resolve() == root
    assert Path(ras_commander.__file__).resolve().is_relative_to(root / "ras_commander")
    assert Path(native.__file__).resolve().is_relative_to(root / ".venv")


def cases():
    # Same winding deliberately: roles come from offsets, not orientation.
    donut = Polygon(box(-80, 30, -70, 40).exterior.coords,
                    [box(-78, 32, -72, 38).exterior.coords])
    island = box(-76, 34, -74, 36)
    return [donut, MultiPolygon([donut, island, box(-68, 32, -66, 34)])]


@pytest.mark.parametrize("zoom", [0, 6, 10])
@pytest.mark.parametrize("reverse", [False, True])
def test_holes_islands_multipart_identity_properties_and_quantization(tmp_path, zoom, reverse):
    geoms = cases()
    if reverse:
        geoms = [shapely.reverse(g) for g in geoms]
    ids = [2**53 + 17, np.iinfo(np.int64).max]
    layer = pack(geoms, ids)
    layer["properties"] = {"region": ["donut", "islands"], "depth_ft": [2.5, 3.25],
        "wet": [True, False], "local_id": [7, 7], "mesh": ["a", "b"],
        "exact_int": [2**53 + 1, -(2**53 + 1)], "mixed": [7, "unknown"],
        "nodata": [None, float("nan")]}
    output = tmp_path / "packed.pmtiles"
    fast_hdf.export_pmtiles(output, {"regions": layer}, min_zoom=zoom, max_zoom=zoom,
                           backend="rust", threads=2)
    header, metadata, tiles = decode(output)
    assert (header["min_zoom"], header["max_zoom"]) == (zoom, zoom)
    info, = metadata["vector_layers"]
    assert info["id"] == "regions" and info["minzoom"] == zoom and info["maxzoom"] == zoom
    assert info["fields"] == {"region": "String", "depth_ft": "Number", "wet": "Boolean",
                              "local_id": "Number", "mesh": "String", "exact_int": "Number",
                              "nodata": "String"}
    seen = set()
    decoded_shapes = []
    for (z, x, y), layers in tiles.items():
        assert z == zoom
        result = layers["regions"]
        for feature in result["features"]:
            i = ids.index(feature["id"])
            seen.add(feature["id"])
            props = feature["properties"]
            for key, values in layer["properties"].items():
                if key != "nodata":
                    assert props[key] == values[i]
            assert "nodata" not in props  # MVT has no null scalar.
            actual = shape(feature["geometry"])
            assert not actual.is_empty and actual.is_valid
            expected = pixels(geoms[i], z, x, y, result["extent"])
            # Compare only core tile: freestiler deliberately includes a 5% buffer.
            core = box(0, 0, result["extent"], result["extent"])
            difference = expected.intersection(core).symmetric_difference(actual.intersection(core))
            assert difference.difference(expected.boundary.buffer(2)).area < 1e-5
            decoded_shapes.append(actual)
    assert seen == set(ids)
    if zoom == 0:
        assert sum(len(p.interiors) for g in decoded_shapes
                   for p in (g.geoms if g.geom_type == "MultiPolygon" else [g])) == 2
        assert any(g.geom_type == "MultiPolygon" and len(g.geoms) == 3 for g in decoded_shapes)


def test_legacy_equivalent_nested_and_thread_counts(tmp_path):
    source = [box(-77, 40, -76.9, 40.1), box(-76.8, 40, -76.7, 40.1)]
    nested = pack(source, [42, 43])
    legacy = {key: value for key, value in nested.items()
              if key not in ("ring_offsets", "polygon_offsets", "feature_offsets")}
    legacy["offsets"] = nested["ring_offsets"]
    results = []
    for index, (layer, threads) in enumerate([(legacy, 1), (nested, 1), (nested, 4)]):
        path = tmp_path / f"{index}.pmtiles"
        fast_hdf.export_pmtiles(path, {"cells": layer}, min_zoom=6, max_zoom=9,
                               backend="rust", threads=threads)
        header, metadata, tiles = decode(path)
        assert {z for z, _, _ in tiles} == set(range(6, 10))
        results.append((header, metadata, tiles))
    assert results[0] == results[1] == results[2]


@pytest.mark.parametrize("key,values", [
    ("ring_offsets", []), ("ring_offsets", [0, -1, 10]),
    ("ring_offsets", [0, 5, 5, 10]), ("ring_offsets", [0, 11, 10]),
    ("polygon_offsets", [0, 3]), ("polygon_offsets", [0, 0, 2]),
    ("feature_offsets", [0, 2]), ("feature_offsets", [1, 2]),
    ("feature_offsets", [0, 0, 2]), ("feature_offsets", [0, 1, 3]),
])
@pytest.mark.parametrize("entry", ["native", "public"])
def test_bad_nested_offsets_reject_before_write(tmp_path, key, values, entry):
    layer = pack([box(1, 1, 2, 2), box(3, 3, 4, 4)])
    layer[key] = np.array(values, dtype="i8")
    output = tmp_path / "sentinel.pmtiles"
    output.write_bytes(b"preserved")
    with pytest.raises(ValueError):
        if entry == "native":
            native.write_pmtiles([dict(name="cells", **layer)], str(output), 0, 0, threads=1)
        else:
            fast_hdf.export_pmtiles(output, {"cells": layer}, min_zoom=0, max_zoom=0, backend="rust")
    assert output.read_bytes() == b"preserved"
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("change", ["partial", "mixed", "unclosed", "duplicate", "negative", "nonfinite", "nonscalar", "uint64"])
def test_invalid_geometry_identity_properties(tmp_path, change):
    layer = pack(cases(), [17, 18])
    if change == "partial": del layer["polygon_offsets"]
    elif change == "mixed": layer["offsets"] = layer["ring_offsets"]
    elif change == "unclosed": layer["coordinates"][0, 0] += 0.01
    elif change == "duplicate": layer["cell_ids"][:] = 17
    elif change == "negative": layer["cell_ids"][0] = -1
    elif change == "nonfinite": layer["coordinates"][0, 0] = np.nan
    elif change == "nonscalar": layer["properties"] = {"nested": [[1], [2]]}
    elif change == "uint64": layer["properties"] = {"large": [2**64 - 1, 1]}
    output = tmp_path / "existing.pmtiles"
    output.write_bytes(b"preserved")
    with pytest.raises((ValueError, TypeError, OverflowError, fast_hdf.FastHdfError)):
        fast_hdf.export_pmtiles(output, {"cells": layer}, min_zoom=0, max_zoom=0, backend="rust")
    assert output.read_bytes() == b"preserved"


def test_projected_feet_crs_matches_wgs84_and_rejects_unknown(tmp_path):
    source = gpd.GeoSeries(cases(), crs=4326)
    projected = source.to_crs(2271)  # Pennsylvania North, US survey feet.
    outputs = []
    for index, (geoms, crs) in enumerate([(source, 4326), (projected, 2271)]):
        path = tmp_path / f"{index}.pmtiles"
        fast_hdf.export_pmtiles(path, {"regions": pack(list(geoms))}, source_crs=crs,
                               min_zoom=6, max_zoom=6, backend="rust")
        header, metadata, tiles = decode(path)
        outputs.append(tiles)
        assert abs(header["min_lon_e7"] / 1e7 - -80) < 1e-5
        assert abs(header["max_lat_e7"] / 1e7 - 40) < 1e-5
    assert outputs[0] == outputs[1]
    with pytest.raises(ValueError, match="CRS"):
        fast_hdf.export_pmtiles(tmp_path / "unknown.pmtiles", {"x": pack(cases())},
                               source_crs=None, backend="rust")


def test_reference_ras2cng_freestiler_route(tmp_path):
    freestiler = pytest.importorskip("freestiler")
    geoms = cases()
    reference = tmp_path / "reference.pmtiles"
    freestiler.freestile({"regions": gpd.GeoDataFrame({"key": [0, 1]}, geometry=geoms, crs=4326)},
                        reference, min_zoom=0, max_zoom=2, simplification=False, quiet=True)
    layer = pack(geoms)
    layer["properties"] = {"key": [0, 1]}
    output = tmp_path / "native.pmtiles"
    fast_hdf.export_pmtiles(output, {"regions": layer}, min_zoom=0, max_zoom=2, backend="rust")
    _, _, want = decode(reference)
    _, _, got = decode(output)
    assert want.keys() == got.keys()
    for address, layers in got.items():
        actual = {f["properties"]["key"]: f for f in layers["regions"]["features"]}
        expected = {f["properties"]["key"]: f for f in want[address]["regions"]["features"]}
        assert actual.keys() == expected.keys()
        for key in actual:
            assert shape(actual[key]["geometry"]).equals(shape(expected[key]["geometry"]))
            assert actual[key]["properties"] == expected[key]["properties"]


@pytest.mark.parametrize("empty", [False, True])
def test_empty_layer_handling(tmp_path, empty):
    layers = {"empty": pack([])}
    if not empty:
        layers["regions"] = pack(cases())
        path = tmp_path / "nonempty.pmtiles"
        fast_hdf.export_pmtiles(path, layers, min_zoom=0, max_zoom=0, backend="rust")
        assert set(decode(path)[2][(0, 0, 0)]) == {"regions"}
    else:
        with pytest.raises(ValueError, match="non-empty"):
            fast_hdf.export_pmtiles(tmp_path / "empty.pmtiles", layers, backend="rust")
