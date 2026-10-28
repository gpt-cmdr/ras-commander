"""Soils raster equivalence on actual vector/raster files; no native runtime needed."""

from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np
import pandas as pd
import pytest

rasterio = pytest.importorskip("rasterio")
gpd = pytest.importorskip("geopandas")
from rasterio.transform import from_origin
from rasterio.features import rasterize
from rasterio.merge import merge
from shapely.geometry import Polygon, box

import ras_commander._land_classification_helper as helper
import ras_commander._landcover_native as native


@pytest.fixture(params=["shapefile", "gdb"])
def soils(tmp_path, request):
    # Include an overlap, a gap, and a remote polygon to exercise filtering.
    polygons = gpd.GeoDataFrame(
        {"mukey": ["1", "2", "3", "4"], "geometry": [
            box(0, 0, 8, 9), Polygon([(4, 2), (13, 3.1), (11.3, 7), (4, 6.5)],
                    holes=[[(6, 3), (8, 3), (8, 5), (6, 5)]]),
            box(15, 0, 18, 9), box(1000, 1000, 1010, 1010),
        ]}, crs="EPSG:3857",
    )
    table = pd.DataFrame({"mukey": ["1", "2", "3", "4"], "hydgrpdcd": ["A", "B/D", "C", "D"]})
    if request.param == "gdb":
        import pyogrio
        path = tmp_path / "soils.gdb"
        pyogrio.write_dataframe(polygons, path, layer="MUPOLYGON", driver="OpenFileGDB")
        pyogrio.write_dataframe(table, path, layer="muaggatt", driver="OpenFileGDB")
    else:
        path = tmp_path / "soils"
        (path / "spatial").mkdir(parents=True)
        (path / "tabular").mkdir()
        polygons.to_file(path / "spatial/soilmu_a_test.shp")
        table.to_csv(path / "tabular/muaggatt.txt", sep="|", index=False)
    return path


def test_filtered_tiled_soils_equal_full_read_single_raster(tmp_path, monkeypatch, soils):
    full = helper._load_gssurgo_dataframe(soils)
    # Force both column and row tiling on a small real-format fixture.
    monkeypatch.setattr(helper, "_SOILS_MAX_TILE_CELLS", 11)
    paths, rows = helper._rasterize_soils_source(
        soils, 1.0, "EPSG:3857", (0.2, 0.2, 18.2, 8.2), 0.5, tmp_path / "tiles",
    )
    lookup = {name: class_id for class_id, name in rows}
    transform, width, height = helper._bounds_to_grid((-0.3, -0.3, 18.7, 8.7), 1.0)
    reference = rasterize(
        [(geom, lookup[group]) for geom, group in zip(full.geometry, full.soil_group)],
        out_shape=(height, width), transform=transform, fill=0, dtype="int32",
    )
    datasets = [rasterio.open(path) for path in paths]
    try:
        assert len(paths) > 1
        assert all(ds.width * ds.height <= 11 for ds in datasets)
        assert all(ds.nodata is None for ds in datasets)
        assert sum(ds.width * ds.height for ds in datasets) == width * height
        combined, actual_transform = merge(datasets)
        assert actual_transform == transform
        np.testing.assert_array_equal(combined[0], reference)
        assert 0 in combined  # Gaps retain the NoData class.
    finally:
        for ds in datasets:
            ds.close()


def test_bbox_transforms_to_source_crs_and_preserves_whole_polygons(soils):
    from rasterio.warp import transform_bounds

    bounds = transform_bounds("EPSG:3857", "EPSG:4326", 1, 1, 12, 6)
    subset = helper._load_gssurgo_dataframe(soils, bounds=bounds, bounds_crs="EPSG:4326")
    assert list(subset.mukey) == ["1", "2"]
    assert tuple(subset.total_bounds) == (0, 0, 13, 9)


@pytest.mark.parametrize("width,height", [(10_001, 10_001), (100_000_001, 1), (1, 100_000_001)])
def test_large_grid_windows_stay_below_native_prompt(width, height):
    windows = list(helper._soil_tile_windows(width, height))
    assert sum(w.width * w.height for w in windows) == width * height
    assert all(w.width * w.height <= 10_000_000 for w in windows)
    assert len(windows) > 1


@pytest.mark.parametrize("multiple", [False, True])
def test_native_soils_passes_all_tiles_and_same_mapping_to_one_computable(tmp_path, monkeypatch, multiple):
    rasmap = tmp_path / "project.rasmap"
    rasmap.touch()
    paths = [tmp_path / f"tile{i}.tif" for i in range(2 if multiple else 1)]
    for path in paths:
        with rasterio.open(path, "w", driver="GTiff", width=2, height=2,
                           count=1, dtype="uint8", transform=from_origin(0, 2, 1, 1)):
            pass
    calls = []
    mappings = []

    class List(list):
        def Add(self, value):
            self.append(value)

    class Computable:
        def __init__(self, *args):
            calls.append(args)
        def Initialize(self, _display): pass
        def Run(self, _reporter): pass
        def Complete(self): pass
        def Success(self): return True

    layer = SimpleNamespace(
        Classification=object(), Resampler=object(), Save=lambda: None,
        GetIDs=lambda: [0, 1], GetNames=lambda: ["NoData", "A"],
    )
    library = SimpleNamespace(
        LandCoverComputable=Computable,
        LandCoverFile=lambda path, *args: SimpleNamespace(path=path),
        SharedData=SimpleNamespace(SRSProjection=object()),
        LandCoverLayerHelper=SimpleNamespace(DefaultSoils=lambda: None),
        LandCoverLayer=SimpleNamespace(
            TryLoadLayer=lambda *args: (True, layer, None),
            LandCoverType=SimpleNamespace(Soils=1),
        ),
    )
    monkeypatch.setitem(sys.modules, "RasMapperLib", library)
    monkeypatch.setitem(sys.modules, "RasMapperLib.Progress", SimpleNamespace(ConsoleDisplayProgress=lambda: None))
    monkeypatch.setitem(sys.modules, "System", SimpleNamespace(Array=List, Int32=int, Single=float))
    monkeypatch.setitem(sys.modules, "System.Collections.Generic", SimpleNamespace(List=List))
    monkeypatch.setitem(sys.modules, "Utility.Progress", SimpleNamespace(ProgressReporter=SimpleNamespace(**{"None": lambda: None})))
    monkeypatch.setattr(native, "find_hecras_install", lambda _: None)
    monkeypatch.setattr(native, "load_clr", lambda _: None)
    monkeypatch.setattr(native, "_initialize_shared_projection", lambda _: None)
    def mapping(source, rows, **kwargs):
        mappings.append(rows)
        return ["NoData", "A"], [0, 1]
    monkeypatch.setattr(native, "_populate_modern_input_mapping", mapping)
    native.create_soils(
        rasmap_path=rasmap, source_raster_path=paths if multiple else paths[0],
        raster_map_rows=[(0, "NoData"), (1, "A")], cell_size=1,
        output_hdf_path=tmp_path / "Soils.hdf", hecras_version="7.0.1",
    )
    assert len(calls) == 1
    assert [source.path for source in calls[0][3]] == [str(p.resolve()) for p in paths]
    assert len(mappings) == len(paths)
    assert all(mapping == mappings[0] for mapping in mappings)


def test_filtered_extent_without_polygons_keeps_nodata(tmp_path, soils):
    paths, rows = helper._rasterize_soils_source(
        soils, 1.0, "EPSG:3857", (100, 100, 105, 105), 0, tmp_path / "empty",
    )
    assert rows[0] == (0, "NoData")
    with rasterio.open(paths[0]) as ds:
        assert not ds.read(1).any()


def test_fiona_gdb_fallback_filters_polygons(soils, monkeypatch):
    if soils.suffix != ".gdb":
        pytest.skip("FileGDB-specific fallback")
    pytest.importorskip("fiona")
    import builtins
    original = builtins.__import__
    def without_pyogrio(name, *args, **kwargs):
        if name == "pyogrio":
            raise ImportError("exercise Fiona fallback")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", without_pyogrio)
    subset = helper._load_gssurgo_dataframe(
        soils, bounds=(1, 1, 12, 6), bounds_crs="EPSG:3857",
    )
    assert list(subset.mukey) == ["1", "2"]


def test_add_soils_submits_tiles_once_and_cleans_sources(tmp_path, soils, monkeypatch):
    from ras_commander import RasMap

    monkeypatch.setattr(helper, "_SOILS_MAX_TILE_CELLS", 11)
    monkeypatch.setattr(helper, "resolve_project_paths", lambda _: SimpleNamespace(
        project_folder=tmp_path, rasmap_path=tmp_path / "project.rasmap",
    ))
    monkeypatch.setattr(helper, "_get_project_crs", lambda _: "EPSG:3857")
    native_calls = []
    registrations = []
    def create(**kwargs):
        sources = kwargs["source_raster_path"]
        assert len(sources) > 1 and all(path.exists() for path in sources)
        native_calls.append(kwargs)
        kwargs["output_hdf_path"].touch()
    monkeypatch.setattr(native, "create_soils", create)
    monkeypatch.setattr(helper, "upsert_land_classification_layer", lambda *a, **k: registrations.append((a, k)))
    output = RasMap.add_soils_layer(
        tmp_path, soils, 1, restrict_to_extent=(0, 0, 18, 9), hecras_version="7.0.1",
    )
    assert output.exists()
    assert len(native_calls) == len(registrations) == 1
    assert all(not path.exists() for path in native_calls[0]["source_raster_path"])


def test_empty_native_source_list_fails_before_loading_runtime(tmp_path, monkeypatch):
    def unexpected_load(*args):
        raise AssertionError("Runtime must not load with no sources")
    monkeypatch.setattr(native, "find_hecras_install", unexpected_load)
    with pytest.raises(ValueError, match="At least one soils source"):
        native.create_soils(
            rasmap_path=tmp_path / "project.rasmap", source_raster_path=[],
            raster_map_rows=[(0, "NoData")], cell_size=1,
            output_hdf_path=tmp_path / "Soils.hdf", hecras_version="7.0.1",
        )


def test_direct_oversized_soils_raster_fails_before_native_load(tmp_path, monkeypatch):
    source = tmp_path / "oversized.tif"
    # Sparse GTiff exercises the real header without allocating 100M cells.
    with rasterio.open(source, "w", driver="GTiff", width=10_001, height=10_000,
                       count=1, dtype="uint8", nodata=0, tiled=True,
                       sparse_ok=True, transform=from_origin(0, 10_000, 1, 1)):
        pass
    rasmap = tmp_path / "project.rasmap"
    rasmap.write_text("<RASMapper />")
    def unexpected_load(*args):
        raise AssertionError("Oversized input must not reach native modal initialization")
    monkeypatch.setattr(native, "find_hecras_install", unexpected_load)
    output = tmp_path / "soils.hdf"
    with pytest.raises(ValueError, match="100,000,000.*tile or crop"):
        native.create_soils(rasmap_path=rasmap, source_raster_path=source,
            raster_map_rows=[(0, "NoData"), (1, "A")], cell_size=30,
            output_hdf_path=output, hecras_version="7.0.1")
    assert not output.exists()
