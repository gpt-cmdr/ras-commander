from pathlib import Path
import logging

import h5py
import pytest
from pyproj import CRS

from ras_commander import HdfBase, RasPrj


def _epsg_wkt(epsg: int) -> str:
    return CRS.from_epsg(epsg).to_wkt()


def _write_hdf(path: Path, epsg: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as hdf:
        if epsg is not None:
            hdf.attrs["Projection"] = _epsg_wkt(epsg)


def _write_raster(path: Path, epsg: int) -> None:
    rasterio = pytest.importorskip("rasterio")
    import numpy as np
    from rasterio.transform import from_origin

    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "height": 2,
        "width": 2,
        "count": 1,
        "dtype": "float32",
        "crs": f"EPSG:{epsg}",
        "transform": from_origin(0.0, 2.0, 1.0, 1.0),
    }

    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.array([[1.0, 2.0], [3.0, 4.0]], dtype="float32"), 1)


def _write_rasmap(
    path: Path,
    projection_relative_path: str | None = None,
    terrain_relative_paths: list[str] | None = None,
) -> None:
    terrain_relative_paths = terrain_relative_paths or []
    projection_xml = ""
    if projection_relative_path is not None:
        projection_xml = (
            f'  <RASProjectionFilename Filename="{projection_relative_path}" />\n'
        )

    terrain_xml = "\n".join(
        f'    <Layer Name="Terrain" Filename="{terrain_path}" />'
        for terrain_path in terrain_relative_paths
    )

    if terrain_xml:
        terrain_xml = f"  <Terrains>\n{terrain_xml}\n  </Terrains>\n"

    path.write_text(
        (
            "<RASMapper>\n"
            f"{projection_xml}"
            f"{terrain_xml}"
            "</RASMapper>\n"
        ),
        encoding="utf-8",
    )


def _write_project_files(
    project_dir: Path,
    *,
    project_name: str = "TestModel",
    include_geom_entry: bool = True,
) -> str:
    project_dir.mkdir(parents=True, exist_ok=True)

    prj_lines = ["Proj Title=Test Model", "Plan File=p01"]
    if include_geom_entry:
        prj_lines.append("Geom File=g01")

    (project_dir / f"{project_name}.prj").write_text(
        "\n".join(prj_lines) + "\n",
        encoding="utf-8",
    )
    (project_dir / f"{project_name}.p01").write_text(
        (
            "Plan Title=Base Plan\n"
            "Program Version=6.6\n"
            "Geom File=g01\n"
            "Flow File=u01\n"
        ),
        encoding="utf-8",
    )
    (project_dir / f"{project_name}.g01").write_text(
        "Geom Title=Base Geometry\n",
        encoding="utf-8",
    )

    return project_name


def _init_project(project_dir: Path) -> RasPrj:
    project = RasPrj()
    project.initialize(
        project_dir,
        "Ras.exe",
        suppress_logging=True,
        load_results_summary=False,
    )
    return project


def test_project_crs_prefers_geometry_hdf_over_plan_hdf(tmp_path):
    project_name = _write_project_files(tmp_path, include_geom_entry=True)
    _write_hdf(tmp_path / f"{project_name}.g01.hdf", epsg=2278)
    _write_hdf(tmp_path / f"{project_name}.p01.hdf", epsg=26915)

    project = _init_project(tmp_path)

    assert project.project_crs == "EPSG:2278"
    assert project.project_crs_source == "geom_hdf"


def test_project_crs_falls_back_to_plan_hdf(tmp_path):
    project_name = _write_project_files(tmp_path)
    _write_hdf(tmp_path / f"{project_name}.p01.hdf", epsg=26915)

    project = _init_project(tmp_path)

    assert project.project_crs == "EPSG:26915"
    assert project.project_crs_source == "plan_hdf"


def test_project_crs_warning_uses_folder_name_and_debug_keeps_path(tmp_path, caplog):
    _write_project_files(tmp_path)

    caplog.set_level(logging.DEBUG, logger="ras_commander.RasPrj")
    project = _init_project(tmp_path)

    assert project.project_crs is None
    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "ras_commander.RasPrj"
        and record.levelno == logging.WARNING
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "ras_commander.RasPrj"
        and record.levelno == logging.DEBUG
    ]

    assert warning_messages == [
        f"Could not resolve project CRS for {tmp_path.name}"
    ]
    assert str(tmp_path.parent) not in warning_messages[0]
    assert any(str(tmp_path) in message for message in debug_messages)


def test_project_crs_falls_back_to_rasmap_projection_path(tmp_path):
    project_name = _write_project_files(tmp_path)
    projection_path = tmp_path / "Projection" / "project.prj"
    projection_path.parent.mkdir(parents=True, exist_ok=True)
    projection_path.write_text(_epsg_wkt(2277), encoding="utf-8")
    _write_rasmap(
        tmp_path / f"{project_name}.rasmap",
        projection_relative_path="Projection/project.prj",
    )

    project = _init_project(tmp_path)

    assert project.project_crs == "EPSG:2277"
    assert project.project_crs_source == "rasmap_projection_path"


def test_project_crs_falls_back_to_terrain_hdf(tmp_path):
    project_name = _write_project_files(tmp_path)
    terrain_hdf_path = tmp_path / "Terrain" / "terrain.hdf"
    _write_hdf(terrain_hdf_path, epsg=2264)
    _write_rasmap(
        tmp_path / f"{project_name}.rasmap",
        terrain_relative_paths=["Terrain/terrain.hdf"],
    )

    project = _init_project(tmp_path)

    assert project.project_crs == "EPSG:2264"
    assert project.project_crs_source == "terrain_hdf"


def test_project_crs_falls_back_to_terrain_raster(tmp_path):
    project_name = _write_project_files(tmp_path)
    terrain_hdf_path = tmp_path / "Terrain" / "terrain.hdf"
    _write_hdf(terrain_hdf_path, epsg=None)
    _write_raster(tmp_path / "Terrain" / "terrain.tif", epsg=2276)
    _write_rasmap(
        tmp_path / f"{project_name}.rasmap",
        terrain_relative_paths=["Terrain/terrain.hdf"],
    )

    project = _init_project(tmp_path)

    assert project.project_crs == "EPSG:2276"
    assert project.project_crs_source == "terrain_raster"


def test_reinitialize_resets_project_crs_state(tmp_path):
    first_project_dir = tmp_path / "first"
    first_project_name = _write_project_files(
        first_project_dir,
        include_geom_entry=True,
    )
    _write_hdf(first_project_dir / f"{first_project_name}.g01.hdf", epsg=2278)

    project = _init_project(first_project_dir)

    assert project.project_crs == "EPSG:2278"
    assert project.project_crs_source == "geom_hdf"

    second_project_dir = tmp_path / "second"
    _write_project_files(second_project_dir)

    project.initialize(
        second_project_dir,
        "Ras.exe",
        suppress_logging=True,
        load_results_summary=False,
    )

    assert project.project_crs is None
    assert project.project_crs_source is None


def test_hdfbase_projection_still_uses_rasmap_projection_file(tmp_path):
    project_name = _write_project_files(tmp_path)
    plan_hdf_path = tmp_path / f"{project_name}.p01.hdf"
    _write_hdf(plan_hdf_path, epsg=None)

    projection_path = tmp_path / "Projection" / "fallback.prj"
    projection_path.parent.mkdir(parents=True, exist_ok=True)
    projection_path.write_text(_epsg_wkt(6347), encoding="utf-8")
    _write_rasmap(
        tmp_path / f"{project_name}.rasmap",
        projection_relative_path="Projection/fallback.prj",
    )

    assert HdfBase.get_projection(plan_hdf_path) == "EPSG:6347"


def test_hdfbase_missing_projection_warns_once_without_critical(tmp_path, caplog):
    project_name = _write_project_files(tmp_path)
    plan_hdf_path = tmp_path / f"{project_name}.p01.hdf"
    _write_hdf(plan_hdf_path, epsg=None)

    caplog.set_level(logging.WARNING, logger="ras_commander.hdf.HdfBase")

    assert HdfBase.get_projection(plan_hdf_path) is None
    assert HdfBase.get_projection(plan_hdf_path) is None

    warnings = [
        record
        for record in caplog.records
        if record.name == "ras_commander.hdf.HdfBase"
        and record.levelno == logging.WARNING
    ]
    criticals = [
        record
        for record in caplog.records
        if record.name == "ras_commander.hdf.HdfBase"
        and record.levelno >= logging.CRITICAL
    ]

    assert len(warnings) == 1
    assert "Projection not found for TestModel.p01.hdf" in warnings[0].getMessage()
    assert str(plan_hdf_path) not in warnings[0].getMessage()
    assert criticals == []


def test_hdfbase_missing_projection_debug_includes_diagnostics(tmp_path, caplog):
    project_name = _write_project_files(tmp_path)
    plan_hdf_path = tmp_path / f"{project_name}.p01.hdf"
    _write_hdf(plan_hdf_path, epsg=None)

    caplog.set_level(logging.DEBUG, logger="ras_commander.hdf.HdfBase")

    assert HdfBase.get_projection(plan_hdf_path) is None

    assert "No valid projection found. Checked:" in caplog.text
    assert str(plan_hdf_path) in caplog.text
    assert "To fix this:" in caplog.text


def test_hdfbase_malformed_rasmap_projection_probe_is_not_error(tmp_path, caplog):
    project_name = _write_project_files(tmp_path)
    plan_hdf_path = tmp_path / f"{project_name}.p01.hdf"
    _write_hdf(plan_hdf_path, epsg=None)
    (tmp_path / f"{project_name}.rasmap").write_text("<RASMapper>\n", encoding="utf-8")

    caplog.set_level(logging.WARNING, logger="ras_commander.hdf.HdfBase")

    assert HdfBase.get_projection(plan_hdf_path) is None

    errors = [
        record
        for record in caplog.records
        if record.name == "ras_commander.hdf.HdfBase"
        and record.levelno >= logging.ERROR
    ]
    assert errors == []
