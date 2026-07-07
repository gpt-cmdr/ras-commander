from __future__ import annotations

import logging
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import HdfStorageArea


LOGGER_NAME = "ras_commander.hdf.HdfStorageArea"


def _hdf_storage_records(caplog):
    return [record for record in caplog.records if record.name == LOGGER_NAME]


def _write_empty_geometry_hdf(
    path: Path,
    *,
    units_system: str | None = None,
    si_units: str | None = None,
) -> Path:
    with h5py.File(path, "w") as hdf:
        if units_system is not None:
            hdf.attrs["Units System"] = units_system
        geom = hdf.create_group("Geometry")
        if si_units is not None:
            geom.attrs["SI Units"] = si_units
    return path


def _write_storage_area_hdf(path: Path, *, terrain_filename: str | None = None) -> Path:
    with h5py.File(path, "w") as hdf:
        geom = hdf.create_group("Geometry")
        if terrain_filename is not None:
            geom.attrs["Terrain Filename"] = terrain_filename

        storage = geom.create_group("Storage Areas")
        attrs_dtype = np.dtype([("Name", "S16"), ("Mode", "S24")])
        storage.create_dataset(
            "Attributes",
            data=np.array([(b"SA-1", b"Elev Vol RC")], dtype=attrs_dtype),
        )
    return path


def _patch_stage_storage_dependencies(
    monkeypatch,
    terrain_path: Path,
    *,
    polygon_area: float,
    raw_volume: float,
    min_elevation: float = 100.0,
):
    class _Polygon:
        pass

    _Polygon.area = polygon_area

    monkeypatch.setattr(
        HdfStorageArea,
        "_get_perimeter_polygon",
        staticmethod(lambda *args, **kwargs: _Polygon()),
    )
    monkeypatch.setattr(
        HdfStorageArea,
        "get_terrain_path_from_geom_hdf",
        staticmethod(lambda *args, **kwargs: terrain_path),
    )
    monkeypatch.setattr(
        HdfStorageArea,
        "_extract_terrain_stats_in_polygon",
        staticmethod(
            lambda *args, **kwargs: {
                "min_interior": min_elevation,
                "max_interior": min_elevation,
                "mean_interior": min_elevation,
                "min_perimeter": min_elevation,
                "max_perimeter": min_elevation,
                "valid_cell_count": 1,
                "cell_area": 1.0,
            }
        ),
    )
    monkeypatch.setattr(
        HdfStorageArea,
        "_compute_volume_below_elevation_from_terrain",
        staticmethod(lambda *args, **kwargs: raw_volume),
    )


def _compute_single_stage_storage(hdf_path: Path):
    return HdfStorageArea.compute_stage_storage_curve(
        hdf_path,
        "SA-1",
        elevation_interval=5.0,
        min_elevation=100.0,
        max_elevation=100.0,
    )


def test_optional_storage_metadata_absence_quiet_by_default(tmp_path, caplog):
    hdf_path = _write_empty_geometry_hdf(tmp_path / "empty.g01.hdf")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        assert HdfStorageArea.get_storage_area_names(hdf_path) == []
        assert HdfStorageArea.get_storage_area_properties(hdf_path, "SA-1") == {}

    assert _hdf_storage_records(caplog) == []


def test_optional_storage_metadata_absence_has_debug_context(tmp_path, caplog):
    hdf_path = _write_empty_geometry_hdf(tmp_path / "empty.g01.hdf")

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        assert HdfStorageArea.get_storage_area_names(hdf_path) == []

    messages = [record.getMessage() for record in _hdf_storage_records(caplog)]
    assert any(
        "Storage areas group 'Geometry/Storage Areas' not found" in message
        for message in messages
    )
    assert any("empty.g01.hdf" in message for message in messages)


def test_missing_volume_elevation_curve_logs_preprocessor_guidance(tmp_path, caplog):
    hdf_path = _write_storage_area_hdf(tmp_path / "storage.g01.hdf")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        curve = HdfStorageArea.get_volume_elevation_curve(hdf_path, "SA-1")

    assert curve.empty
    records = _hdf_storage_records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert records[0].levelno == logging.ERROR
    assert "storage area 'SA-1'" in message
    assert "storage.g01.hdf" in message
    assert "created by the HEC-RAS geometry preprocessor" in message
    assert "run the geometry preprocessor first" in message
    assert "Geometry/Storage Areas/Volume Elevation Info" in message
    assert "Geometry/Storage Areas/Volume Elevation Values" in message
    assert str(tmp_path) not in message


def test_missing_terrain_reference_is_debug_only(tmp_path, caplog):
    hdf_path = _write_storage_area_hdf(
        tmp_path / "storage.g01.hdf",
        terrain_filename="Terrain/MissingTerrain.hdf",
    )

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        assert HdfStorageArea.get_terrain_path_from_geom_hdf(hdf_path) is None

    assert _hdf_storage_records(caplog) == []

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        assert HdfStorageArea.get_terrain_path_from_geom_hdf(hdf_path) is None

    messages = [record.getMessage() for record in _hdf_storage_records(caplog)]
    assert any(
        "Terrain referenced by storage.g01.hdf was not found" in message
        for message in messages
    )
    assert any("MissingTerrain" in message for message in messages)
    assert any("Checked candidate path(s)" in message for message in messages)


def test_compute_stage_storage_curve_uses_private_volume_helper(monkeypatch, tmp_path):
    hdf_path = _write_empty_geometry_hdf(tmp_path / "storage.g01.hdf")
    terrain_path = tmp_path / "terrain.vrt"
    terrain_path.touch()

    class _Polygon:
        area = 43560.0

    def _public_helper_should_not_be_called(*args, **kwargs):
        raise AssertionError("compute_stage_storage_curve should use the private helper")

    monkeypatch.setattr(
        HdfStorageArea,
        "_get_perimeter_polygon",
        staticmethod(lambda *args, **kwargs: _Polygon()),
    )
    monkeypatch.setattr(
        HdfStorageArea,
        "get_terrain_path_from_geom_hdf",
        staticmethod(lambda *args, **kwargs: terrain_path),
    )
    monkeypatch.setattr(
        HdfStorageArea,
        "_extract_terrain_stats_in_polygon",
        staticmethod(
            lambda *args, **kwargs: {
                "min_interior": 100.0,
                "max_interior": 110.0,
                "mean_interior": 105.0,
                "min_perimeter": 100.0,
                "max_perimeter": 110.0,
                "valid_cell_count": 2,
                "cell_area": 1.0,
            }
        ),
    )
    monkeypatch.setattr(
        HdfStorageArea,
        "compute_volume_below_elevation",
        staticmethod(_public_helper_should_not_be_called),
    )
    monkeypatch.setattr(
        HdfStorageArea,
        "_compute_volume_below_elevation_from_terrain",
        staticmethod(lambda *args, **kwargs: 123.0),
    )

    curve, metadata = HdfStorageArea.compute_stage_storage_curve(
        hdf_path,
        "SA-1",
        elevation_interval=5.0,
        min_elevation=100.0,
        max_elevation=110.0,
    )

    assert curve["storage"].tolist() == [123.0, 123.0, 123.0]
    assert metadata["num_elevation_points"] == 3
    assert metadata["storage_units"] == "cubic project units"


def test_compute_stage_storage_curve_converts_us_customary_storage_units(
    monkeypatch,
    tmp_path,
):
    hdf_path = _write_empty_geometry_hdf(
        tmp_path / "storage.g01.hdf",
        units_system="US Customary",
    )
    terrain_path = tmp_path / "terrain.vrt"
    terrain_path.touch()
    _patch_stage_storage_dependencies(
        monkeypatch,
        terrain_path,
        polygon_area=43560.0,
        raw_volume=43560.0,
    )

    curve, metadata = _compute_single_stage_storage(hdf_path)
    assert curve["storage"].tolist() == [1.0]
    assert metadata["units_system"] == "US Customary"
    assert metadata["storage_units"] == "acre-ft"
    assert metadata["raw_storage_units"] == "cubic ft"
    assert metadata["storage_conversion_factor"] == pytest.approx(1.0 / 43560.0)
    assert metadata["storage_area_area_units"] == "sq ft"
    assert metadata["storage_area_acres"] == 1.0


def test_compute_stage_storage_curve_keeps_metric_storage_units(
    monkeypatch,
    tmp_path,
):
    hdf_path = _write_empty_geometry_hdf(
        tmp_path / "storage.g01.hdf",
        si_units="True",
    )
    terrain_path = tmp_path / "terrain.vrt"
    terrain_path.touch()
    _patch_stage_storage_dependencies(
        monkeypatch,
        terrain_path,
        polygon_area=4046.8564224,
        raw_volume=250.0,
    )

    curve, metadata = _compute_single_stage_storage(hdf_path)
    assert curve["storage"].tolist() == [250.0]
    assert metadata["units_system"] == "SI"
    assert metadata["storage_units"] == "m^3"
    assert metadata["raw_storage_units"] == "m^3"
    assert metadata["storage_conversion_factor"] == 1.0
    assert metadata["storage_area_area_units"] == "m^2"
    assert metadata["storage_area_acres"] == pytest.approx(1.0)


def test_compute_stage_storage_curve_uses_geometry_si_units_precedence(
    monkeypatch,
    tmp_path,
):
    hdf_path = _write_empty_geometry_hdf(
        tmp_path / "storage.g01.hdf",
        units_system="US Customary",
        si_units="True",
    )
    terrain_path = tmp_path / "terrain.vrt"
    terrain_path.touch()
    _patch_stage_storage_dependencies(
        monkeypatch,
        terrain_path,
        polygon_area=4046.8564224,
        raw_volume=43560.0,
    )

    curve, metadata = _compute_single_stage_storage(hdf_path)
    assert curve["storage"].tolist() == [43560.0]
    assert metadata["units_system"] == "SI"
    assert metadata["storage_units"] == "m^3"


def test_compute_stage_storage_curve_uses_root_metric_when_si_flag_absent(
    monkeypatch,
    tmp_path,
):
    hdf_path = _write_empty_geometry_hdf(
        tmp_path / "storage.g01.hdf",
        units_system="Metric",
    )
    terrain_path = tmp_path / "terrain.vrt"
    terrain_path.touch()
    _patch_stage_storage_dependencies(
        monkeypatch,
        terrain_path,
        polygon_area=4046.8564224,
        raw_volume=250.0,
    )

    curve, metadata = _compute_single_stage_storage(hdf_path)
    assert curve["storage"].tolist() == [250.0]
    assert metadata["units_system"] == "SI"
    assert metadata["storage_units"] == "m^3"


def test_compute_stage_storage_curve_keeps_unknown_project_area_units(
    monkeypatch,
    tmp_path,
):
    hdf_path = _write_empty_geometry_hdf(tmp_path / "storage.g01.hdf")
    terrain_path = tmp_path / "terrain.vrt"
    terrain_path.touch()
    _patch_stage_storage_dependencies(
        monkeypatch,
        terrain_path,
        polygon_area=12345.0,
        raw_volume=678.0,
    )

    curve, metadata = _compute_single_stage_storage(hdf_path)
    assert curve["storage"].tolist() == [678.0]
    assert metadata["units_system"] == "unknown"
    assert metadata["storage_units"] == "cubic project units"
    assert metadata["storage_area_area_units"] == "square project units"
    assert metadata["storage_area_acres"] is None


def test_compute_stage_storage_curve_unexpected_failure_debug_only(monkeypatch, tmp_path, caplog):
    hdf_path = _write_empty_geometry_hdf(tmp_path / "storage.g01.hdf")
    terrain_path = tmp_path / "terrain.vrt"
    terrain_path.touch()

    class _Polygon:
        area = 43560.0

    monkeypatch.setattr(
        HdfStorageArea,
        "_get_perimeter_polygon",
        staticmethod(lambda *args, **kwargs: _Polygon()),
    )
    monkeypatch.setattr(
        HdfStorageArea,
        "get_terrain_path_from_geom_hdf",
        staticmethod(lambda *args, **kwargs: terrain_path),
    )
    monkeypatch.setattr(
        HdfStorageArea,
        "_extract_terrain_stats_in_polygon",
        staticmethod(
            lambda *args, **kwargs: {
                "min_interior": 100.0,
                "max_interior": 110.0,
                "mean_interior": 105.0,
                "min_perimeter": 100.0,
                "max_perimeter": 110.0,
                "valid_cell_count": 2,
                "cell_area": 1.0,
            }
        ),
    )
    monkeypatch.setattr(
        HdfStorageArea,
        "_compute_volume_below_elevation_from_terrain",
        staticmethod(
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
        ),
    )

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(IOError, match="storage area 'SA-1' in storage.g01.hdf"):
            HdfStorageArea.compute_stage_storage_curve(
                hdf_path,
                "SA-1",
                elevation_interval=5.0,
                min_elevation=100.0,
                max_elevation=110.0,
            )

    assert _hdf_storage_records(caplog) == []
