import logging
import subprocess
from importlib import import_module

import geopandas as gpd
from shapely.geometry import box


usgs_module = import_module("ras_commander.terrain.Usgs3depAws")
Usgs3depAws = usgs_module.Usgs3depAws


def _messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == usgs_module.logger.name and record.levelno == level
    ]


def _text(caplog, level):
    return "\n".join(_messages(caplog, level))


def test_download_tile_index_is_debug_only_with_paths(monkeypatch, tmp_path, caplog):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"fake-gpkg"

    def fake_get(url, stream=False):
        assert url == Usgs3depAws.METADATA_URLS[1]
        assert stream is True
        return FakeResponse()

    def fake_read_file(path):
        assert path == tmp_path / "FESM_1m.gpkg"
        return gpd.GeoDataFrame(
            {"proj_name": ["PA_Example_2020_A20"]},
            geometry=[box(-77.1, 40.6, -77.0, 40.7)],
            crs="EPSG:4326",
        )

    monkeypatch.setattr(usgs_module.requests, "get", fake_get)
    monkeypatch.setattr(usgs_module.gpd, "read_file", fake_read_file)
    caplog.set_level(logging.DEBUG, logger=usgs_module.logger.name)

    result = Usgs3depAws.download_tile_index(1, cache_folder=tmp_path)

    assert len(result) == 1
    info_text = _text(caplog, logging.INFO)
    debug_text = _text(caplog, logging.DEBUG)

    assert "Downloading 1m USGS 3DEP tile index" not in info_text
    assert "USGS 3DEP tile index loaded: 1 tiles (1m)" not in info_text
    assert "https://" not in info_text
    assert str(tmp_path) not in info_text
    assert "Downloading 1m USGS 3DEP tile index" in debug_text
    assert "USGS 3DEP tile index loaded: 1 tiles (1m)" in debug_text
    assert Usgs3depAws.METADATA_URLS[1] in debug_text
    assert str(tmp_path / "FESM_1m.gpkg") in debug_text


def test_list_projects_logs_summary_and_projects_at_debug(monkeypatch, caplog):
    projects = gpd.GeoDataFrame(
        {
            "proj_name": [
                "PA_Example_2020_A20",
                "PA_Older_2018_B18",
            ],
        },
        geometry=[
            box(-77.1, 40.6, -77.0, 40.7),
            box(-77.1, 40.6, -77.0, 40.7),
        ],
        crs="EPSG:4326",
    )

    monkeypatch.setattr(
        Usgs3depAws,
        "find_tiles_for_bbox",
        staticmethod(
            lambda bbox,
            resolution,
            cache_folder=None,
            buffer_distance=0.0: projects.copy()
        ),
    )
    caplog.set_level(logging.DEBUG, logger=usgs_module.logger.name)

    result = Usgs3depAws.list_projects_for_bbox((-77.1, 40.6, -77.0, 40.7), 1)

    assert len(result) == 2
    info_text = _text(caplog, logging.INFO)
    debug_text = _text(caplog, logging.DEBUG)

    assert "USGS 3DEP projects listed: 2 project(s) intersect bbox" not in info_text
    assert "PA_Example_2020_A20" not in info_text
    assert "PA_Older_2018_B18" not in info_text
    assert "USGS 3DEP projects listed: 2 project(s) intersect bbox" in debug_text
    assert "PA_Example_2020_A20" in debug_text
    assert "PA_Older_2018_B18" in debug_text


def test_download_single_tile_success_is_debug_only(monkeypatch, tmp_path, caplog):
    tile_path = tmp_path / "USGS_1M_10_x37y351_PA_Example_2020_A20.tif"
    tile_bytes = b"tile"
    tile_path.write_bytes(tile_bytes)

    monkeypatch.setattr(
        Usgs3depAws,
        "_get_remote_file_size",
        staticmethod(lambda url: len(tile_bytes)),
    )
    caplog.set_level(logging.DEBUG, logger=usgs_module.logger.name)

    result = Usgs3depAws._download_single_tile(
        "https://example.com/USGS_1M_10_x37y351_PA_Example_2020_A20.tif",
        tmp_path,
        overwrite_dest=False,
    )

    assert result == tile_path
    assert _messages(caplog, logging.INFO) == []
    debug_text = _text(caplog, logging.DEBUG)
    assert "Using cached USGS 3DEP tile" in debug_text
    assert str(tile_path) in debug_text


def test_download_tiles_info_omits_paths_and_debug_keeps_mechanics(monkeypatch, tmp_path, caplog):
    projects = gpd.GeoDataFrame(
        {
            "proj_name": [
                "PA_Example_2020_A20",
                "PA_Older_2018_B18",
            ],
        },
        geometry=[
            box(-77.1, 40.6, -77.0, 40.7),
            box(-77.1, 40.6, -77.0, 40.7),
        ],
        crs="EPSG:4326",
    )
    tile_urls = [
        "https://example.com/USGS_1M_10_x37y351_PA_Example_2020_A20.tif",
        "https://example.com/USGS_1M_10_x38y351_PA_Example_2020_A20.tif",
    ]

    monkeypatch.setattr(
        Usgs3depAws,
        "find_tiles_for_bbox",
        staticmethod(lambda bbox, resolution, cache_folder=None: projects.copy()),
    )
    monkeypatch.setattr(
        Usgs3depAws,
        "_get_project_tile_urls",
        staticmethod(lambda project_name: tile_urls),
    )
    monkeypatch.setattr(
        Usgs3depAws,
        "_parse_tile_bounds_from_filename",
        staticmethod(lambda filename: (-77.1, 40.6, -77.0, 40.7)),
    )
    monkeypatch.setattr(
        Usgs3depAws,
        "_download_single_tile",
        staticmethod(lambda tile_url, output_folder, overwrite_dest: output_folder / tile_url.rsplit("/", 1)[-1]),
    )
    caplog.set_level(logging.DEBUG, logger=usgs_module.logger.name)

    result = Usgs3depAws.download_tiles(
        bbox=(-77.1, 40.6, -77.0, 40.7),
        resolution=1,
        output_folder=tmp_path,
        max_workers=1,
    )

    assert len(result) == 2
    info_text = _text(caplog, logging.INFO)
    debug_text = _text(caplog, logging.DEBUG)

    assert "USGS 3DEP project selected: PA_Example_2020_A20" not in info_text
    assert "USGS 3DEP intersecting tiles: 2" not in info_text
    assert "USGS 3DEP tile download complete: 2 tile(s) available" in info_text
    assert "https://" not in info_text
    assert str(tmp_path) not in info_text
    assert "USGS_1M_10_x37y351_PA_Example_2020_A20.tif" not in info_text
    assert "USGS 3DEP project selected: PA_Example_2020_A20" in debug_text
    assert "USGS 3DEP intersecting tiles: 2" in debug_text
    assert "Downloading USGS 3DEP tiles sequentially" in debug_text
    assert "Skipped older USGS 3DEP project: PA_Older_2018_B18" in debug_text


def test_download_tiles_single_project_logs_selection_once(monkeypatch, tmp_path, caplog):
    projects = gpd.GeoDataFrame(
        {"proj_name": ["PA_Example_2020_A20"]},
        geometry=[box(-77.1, 40.6, -77.0, 40.7)],
        crs="EPSG:4326",
    )

    monkeypatch.setattr(
        Usgs3depAws,
        "find_tiles_for_bbox",
        staticmethod(lambda bbox, resolution, cache_folder=None: projects.copy()),
    )
    monkeypatch.setattr(
        Usgs3depAws,
        "_get_project_tile_urls",
        staticmethod(lambda project_name: []),
    )
    caplog.set_level(logging.DEBUG, logger=usgs_module.logger.name)

    result = Usgs3depAws.download_tiles(
        bbox=(-77.1, 40.6, -77.0, 40.7),
        resolution=1,
        output_folder=tmp_path,
        max_workers=1,
    )

    assert result == []
    selection_messages = [
        message
        for message in _messages(caplog, logging.DEBUG)
        if message.startswith("USGS 3DEP project selected:")
    ]
    assert selection_messages == [
        "USGS 3DEP project selected: PA_Example_2020_A20 (year 2020)"
    ]


def test_create_vrt_info_uses_filename_and_debug_keeps_full_paths(monkeypatch, tmp_path, caplog):
    tile_a = tmp_path / "tile_a.tif"
    tile_b = tmp_path / "tile_b.tif"
    tile_a.write_text("a", encoding="utf-8")
    tile_b.write_text("b", encoding="utf-8")

    output_vrt = tmp_path / "terrain.vrt"
    gdalbuildvrt = tmp_path / "gdalbuildvrt.exe"
    gdalbuildvrt.write_text("", encoding="utf-8")
    input_list_path = tmp_path / "gdalbuildvrt-input.txt"

    def fake_run(cmd, capture_output, text, timeout):
        output_vrt.write_text("<VRTDataset />", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def fake_write_input_file_list(tile_paths, output_dir):
        input_list_path.write_text(
            "".join(f"{tile_path}\n" for tile_path in tile_paths),
            encoding="utf-8",
        )
        return input_list_path

    monkeypatch.setattr(
        Usgs3depAws,
        "_find_gdalbuildvrt_path",
        staticmethod(lambda hecras_version=None: gdalbuildvrt),
    )
    monkeypatch.setattr(
        Usgs3depAws,
        "_write_gdal_input_file_list",
        staticmethod(fake_write_input_file_list),
    )
    monkeypatch.setattr(usgs_module.subprocess, "run", fake_run)
    caplog.set_level(logging.DEBUG, logger=usgs_module.logger.name)

    result = Usgs3depAws.create_vrt([tile_a, tile_b], output_vrt)

    assert result == output_vrt
    info_text = _text(caplog, logging.INFO)
    debug_text = _text(caplog, logging.DEBUG)

    assert "Creating VRT mosaic from 2 tile(s)" not in info_text
    assert "VRT mosaic created: terrain.vrt" in info_text
    assert str(output_vrt) not in info_text
    assert str(gdalbuildvrt) not in info_text
    assert "Creating VRT mosaic from 2 tile(s)" in debug_text
    assert str(output_vrt) in debug_text
    assert str(gdalbuildvrt) in debug_text
    assert str(input_list_path) in debug_text
