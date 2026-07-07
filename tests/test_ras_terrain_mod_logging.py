import logging
import sys
from importlib import import_module
from types import SimpleNamespace

import numpy as np
import pandas as pd


terrain_mod_module = import_module("ras_commander.terrain.RasTerrainMod")
RasTerrainMod = terrain_mod_module.RasTerrainMod


def _messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == terrain_mod_module.logger.name and record.levelno == level
    ]


def _text(caplog, level):
    return "\n".join(_messages(caplog, level))


def test_setup_gdal_bridge_info_uses_version_and_debug_keeps_path(monkeypatch, tmp_path, caplog):
    ras_path = tmp_path / "HEC-RAS" / "6.6"
    ras_path.mkdir(parents=True)
    (ras_path / "RasMapperLib.dll").write_text("", encoding="utf-8")

    configured = []

    monkeypatch.setattr(
        RasTerrainMod,
        "_find_hecras_path",
        staticmethod(lambda: ras_path),
    )
    monkeypatch.setattr(
        terrain_mod_module,
        "configure_hecras_gdal_runtime",
        lambda path: configured.append(("runtime", path)),
    )
    monkeypatch.setattr(
        terrain_mod_module,
        "configure_rasmapper_gdal_bridge",
        lambda path, python_dir=None: configured.append(("bridge", path, python_dir)),
    )
    caplog.set_level(logging.DEBUG, logger=terrain_mod_module.logger.name)

    assert RasTerrainMod.setup_gdal_bridge("6.6") is True

    info_text = _text(caplog, logging.INFO)
    debug_text = _text(caplog, logging.DEBUG)

    assert configured == [
        ("runtime", ras_path),
        ("bridge", ras_path, None),
    ]
    assert "Configured HEC-RAS GDAL runtime for HEC-RAS 6.6" in info_text
    assert str(tmp_path) not in info_text
    assert str(ras_path / "GDAL") in debug_text


def test_ensure_initialized_info_is_concise_and_debug_keeps_dll_path(monkeypatch, tmp_path, caplog):
    ras_path = tmp_path / "HEC-RAS" / "7.0"
    ras_path.mkdir(parents=True)
    dll_path = ras_path / "RasMapperLib.dll"
    dll_path.write_text("", encoding="utf-8")
    references = []

    fake_clr = SimpleNamespace(AddReference=lambda path: references.append(path))

    monkeypatch.setattr(RasTerrainMod, "_initialized", False)
    monkeypatch.setattr(RasTerrainMod, "_ras_path", None)
    monkeypatch.setattr(terrain_mod_module.platform, "system", lambda: "Windows")
    monkeypatch.setitem(sys.modules, "clr", fake_clr)
    monkeypatch.setattr(
        RasTerrainMod,
        "_find_hecras_path",
        staticmethod(lambda: ras_path),
    )
    monkeypatch.setattr(
        terrain_mod_module,
        "configure_rasmapper_gdal_bridge",
        lambda path: None,
    )
    caplog.set_level(logging.DEBUG, logger=terrain_mod_module.logger.name)

    RasTerrainMod._ensure_initialized()

    info_text = _text(caplog, logging.INFO)
    debug_text = _text(caplog, logging.DEBUG)

    assert references == [str(dll_path)]
    assert RasTerrainMod._initialized is True
    assert "RasMapperLib.dll loaded" in info_text
    assert str(tmp_path) not in info_text
    assert str(dll_path) in debug_text


def test_compute_modified_terrain_raster_info_uses_filename_and_debug_keeps_path(
    monkeypatch,
    tmp_path,
    caplog,
):
    terrain_tif = tmp_path / "Terrain.tif"
    terrain_tif.write_text("fake raster", encoding="utf-8")
    output_tif = tmp_path / "ModifiedTerrain.tif"
    rasmap = tmp_path / "Project.rasmap"
    geom_hdf = tmp_path / "Project.g01.hdf"
    rasmap.write_text("<RASMapper />", encoding="utf-8")
    geom_hdf.write_text("fake hdf", encoding="utf-8")

    class FakeReadRaster:
        height = 2
        width = 3
        transform = SimpleNamespace(c=100.0, a=10.0, f=200.0, e=-10.0)
        crs = "EPSG:2276"
        nodata = -9999.0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, band):
            return np.zeros((self.height, self.width), dtype=np.float32)

    class FakeWriteRaster:
        def __init__(self):
            self.writes = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            output_tif.write_text("written", encoding="utf-8")
            return False

        def write(self, array, band):
            self.writes.append((array.copy(), band))

    def fake_open(path, mode="r", **kwargs):
        if mode == "w":
            return FakeWriteRaster()
        assert path == terrain_tif
        return FakeReadRaster()

    def fake_profile(*args, **kwargs):
        return pd.DataFrame(
            {
                "station": [0.0, 20.0],
                "elevation": [1.0, 3.0],
            }
        )

    monkeypatch.setitem(sys.modules, "rasterio", SimpleNamespace(open=fake_open))
    monkeypatch.setattr(
        RasTerrainMod,
        "get_terrain_profile",
        staticmethod(fake_profile),
    )
    caplog.set_level(logging.DEBUG, logger=terrain_mod_module.logger.name)

    result = RasTerrainMod.compute_modified_terrain_raster(
        rasmap_path=rasmap,
        geom_hdf_path=geom_hdf,
        terrain_tif_path=terrain_tif,
        output_tif_path=output_tif,
    )

    info_text = _text(caplog, logging.INFO)
    debug_text = _text(caplog, logging.DEBUG)

    assert result.shape == (2, 3)
    assert output_tif.exists()
    assert "Modified terrain raster: 2/2 rows updated" in info_text
    assert "Modified terrain raster written: ModifiedTerrain.tif" in info_text
    assert str(tmp_path) not in info_text
    assert str(output_tif) in debug_text
