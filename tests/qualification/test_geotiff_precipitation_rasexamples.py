"""Opt-in executable qualification for direct GeoTIFF precipitation."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from ras_commander import (
    RasCmdr,
    RasExamples,
    RasPlan,
    RasPreprocess,
    RasUnsteady,
    init_ras_project,
)
from ras_commander.hdf import HdfMesh, HdfResultsMesh, HdfResultsPlan


pytestmark = [pytest.mark.integration, pytest.mark.qualification_critical]


def _write_projected_geotiff_series(
    folder: Path,
    mesh_areas,
) -> tuple[list[Path], np.ndarray]:
    """Create asymmetric, deterministic hourly rainfall over the mesh extent."""
    west, south, east, north = (float(value) for value in mesh_areas.total_bounds)
    cell_size = max(east - west, north - south) / 24.0
    width = max(2, int(np.ceil((east - west) / cell_size)))
    height = max(2, int(np.ceil((north - south) / cell_size)))
    transform = from_origin(west, north, cell_size, cell_size)
    row, column = np.mgrid[:height, :width]
    frames = [
        0.5 + 0.5 * (column >= width // 2),
        0.25 + 0.75 * (row >= height // 2),
        0.1 + 0.9 * ((row + column) % 3 == 0),
    ]

    folder.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, values in enumerate(frames, start=1):
        path = folder / f"synthetic_precip_{index:02d}.tif"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=width,
            height=height,
            count=1,
            dtype="float32",
            transform=transform,
            crs=mesh_areas.crs,
            nodata=-9999.0,
        ) as dataset:
            dataset.write(np.asarray(values, dtype=np.float32), 1)
            dataset.update_tags(1, units="mm")
        paths.append(path)
    incremental = np.stack(frames).astype(np.float32)
    cumulative = np.concatenate(
        [np.zeros((1, height, width), dtype=np.float32), np.cumsum(incremental, axis=0)],
        axis=0,
    )
    return paths, cumulative


def _gridded_plan(ras):
    for _, row in ras.plan_df.iterrows():
        unsteady_number = str(row["unsteady_number"]).zfill(2)
        config = RasUnsteady.get_met_precipitation_config(
            unsteady_number, ras_object=ras
        )
        if config.get("enabled") and config.get("mode") == "Gridded":
            return row
    raise RuntimeError("BaldEagle fixture has no gridded-precipitation plan")


def test_geotiff_precipitation_preprocesses_and_computes_on_rasexamples(tmp_path):
    if os.environ.get("RUN_RAS_PRECIP_QUALIFICATION") != "1":
        pytest.skip("set RUN_RAS_PRECIP_QUALIFICATION=1 for native HEC-RAS run")

    previous_zip = RasExamples._zip_file_path
    previous_folders = RasExamples._folder_df
    try:
        RasExamples.get_example_projects("6.6")
        project_path = RasExamples.extract_project(
            "BaldEagleCrkMulti2D",
            output_path=tmp_path,
            suffix="geotiff_precip_qualification",
        )
    finally:
        RasExamples._zip_file_path = previous_zip
        RasExamples._folder_df = previous_folders

    ras = init_ras_project(
        project_path,
        ras_version="6.6",
        load_results_summary=False,
    )
    plan_row = _gridded_plan(ras)
    plan_number = str(plan_row["plan_number"]).zfill(2)
    unsteady_number = str(plan_row["unsteady_number"]).zfill(2)
    geometry_number = str(plan_row["geometry_number"]).zfill(2)
    geometry_hdf = (
        Path(ras.project_folder) / f"{ras.project_name}.g{geometry_number}.hdf"
    )
    mesh_areas = HdfMesh.get_mesh_areas(geometry_hdf)
    source_paths, expected_cumulative = _write_projected_geotiff_series(
        Path(ras.project_folder) / "Precipitation" / "geotiff",
        mesh_areas,
    )

    event_start = datetime(2024, 8, 9, 10)
    event_end = datetime(2024, 8, 9, 16)
    timestamps = [
        datetime(2024, 8, 9, 11),
        datetime(2024, 8, 9, 12),
        datetime(2024, 8, 9, 13),
    ]
    import_result = RasUnsteady.set_gridded_precipitation_geotiff(
        unsteady_number,
        source_paths,
        timestamps=timestamps,
        units="mm",
        value_type="amount",
        first_timestep_hours=1.0,
        interpolation="Bilinear",
        ratio=1.0,
        ras_object=ras,
    )
    assert import_result.cache_path.is_file()
    assert import_result.shape == expected_cumulative.shape
    assert import_result.source_format == "geotiff"
    assert import_result.hec_ras_version == "6.6"
    assert import_result.route_qualification == "qualified_windows_and_wine"

    RasPlan.update_simulation_date(
        plan_number,
        event_start,
        event_end,
        ras_object=ras,
    )
    RasPlan.update_plan_intervals(
        plan_number,
        output_interval="1HOUR",
        instantaneous_interval="1HOUR",
        mapping_interval="1HOUR",
        ras_object=ras,
    )

    preprocess_result = RasPreprocess.preprocess_plan(
        plan_number,
        ras_object=ras,
        max_wait=600,
    )
    assert preprocess_result, preprocess_result.error
    with h5py.File(preprocess_result.tmp_hdf_path, "r") as hdf:
        values = hdf["Event Conditions/Meteorology/Precipitation/Values"][...]
        timestamps_out = hdf[
            "Event Conditions/Meteorology/Precipitation/Timestamp"
        ][...]
    assert values.shape == (
        expected_cumulative.shape[0],
        expected_cumulative.shape[1] * expected_cumulative.shape[2],
    )
    assert timestamps_out.shape == (expected_cumulative.shape[0],)
    expected_solver_values = np.concatenate(
        [
            np.zeros_like(expected_cumulative[:1]),
            np.diff(expected_cumulative, axis=0),
        ],
        axis=0,
    ) / 25.4
    np.testing.assert_allclose(
        values,
        expected_solver_values.reshape(expected_solver_values.shape[0], -1),
        rtol=0.0,
        atol=1e-6,
    )
    assert float(np.nanmax(values)) == pytest.approx(1.0 / 25.4)

    compute_result = RasCmdr.compute_plan(
        plan_number,
        ras_object=ras,
        force_rerun=True,
        verify=True,
        use_optimal_hdf_settings=True,
        hdf_output_variables=[
            "Cell Hydraulic Depth",
            "Cell Precipitation Rate",
            "Cell Cumulative Precipitation Depth",
        ],
    )
    assert compute_result

    plan_hdf = Path(ras.project_folder) / f"{ras.project_name}.p{plan_number}.hdf"
    messages = HdfResultsPlan.get_compute_messages_hdf_only(plan_hdf)
    assert "Processing Precipitation data" in messages
    precip_errors = [
        line
        for line in messages.splitlines()
        if any(term in line.casefold() for term in ("precip", "rain", "raster"))
        and any(term in line.casefold() for term in ("error", "failed", "missing"))
    ]
    assert not precip_errors, precip_errors
    cumulative = HdfResultsMesh.get_mesh_cells_timeseries(
        plan_hdf,
        var="Cell Cumulative Precipitation Depth",
    )
    hydraulic = HdfResultsMesh.get_mesh_cells_timeseries(
        plan_hdf,
        var="Cell Hydraulic Depth",
    )
    assert cumulative and hydraulic
    for dataset in cumulative.values():
        cell_values = dataset["Cell Cumulative Precipitation Depth"].values
        assert float(np.nanmin(cell_values)) >= -1e-6
        assert np.all(np.diff(cell_values, axis=0) >= -1e-6)
        assert 0.01 < float(np.nanmax(cell_values)) <= 0.13
    assert any(
        float(np.nanmax(dataset["Cell Hydraulic Depth"].values)) > 0.0
        for dataset in hydraulic.values()
    )
