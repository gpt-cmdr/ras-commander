"""Opt-in integration smoke tests for land-cover and infiltration HDF readers."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from ras_commander import RasExamples, init_ras_project
from ras_commander.hdf import HdfInfiltration, HdfLandCover

pytestmark = pytest.mark.integration

RUN_ENV = "RAS_COMMANDER_RUN_HDF_LANDCOVER_INTEGRATION"


@pytest.fixture(scope="module")
def extracted_project(tmp_path_factory) -> Path:
    if os.environ.get(RUN_ENV) != "1":
        pytest.skip(
            f"Set {RUN_ENV}=1 to run the real-project land-cover/infiltration smoke tests."
        )

    output_root = tmp_path_factory.mktemp("hdf_landcover_integration")
    return RasExamples.extract_project("BaldEagleCrkMulti2D", output_path=output_root)


@pytest.fixture(scope="module")
def ras_project(extracted_project):
    return init_ras_project(extracted_project, "6.6", load_results_summary=False)


@pytest.fixture(scope="module")
def target_geom_hdf(ras_project) -> Path:
    if ras_project.geom_df.empty:
        pytest.skip("No geometry rows available in extracted example project.")

    hdf_paths = ras_project.geom_df["hdf_path"].dropna().tolist()
    if not hdf_paths:
        pytest.skip("No compiled geometry HDF paths available in extracted example project.")

    return Path(hdf_paths[0])


def test_preprocessed_mannings_n_reads_from_real_geometry_hdf(target_geom_hdf):
    df = HdfLandCover.get_preprocessed_mannings_n(target_geom_hdf)

    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert {"mesh_name", "cell_id", "mannings_n"} <= set(df.columns)
    assert df["mannings_n"].notna().all()


def test_preprocessed_infiltration_reads_from_real_geometry_hdf(target_geom_hdf):
    df = HdfInfiltration.get_preprocessed_infiltration(
        target_geom_hdf,
        variable="Curve Number",
    )

    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert {"mesh_name", "cell_id", "value"} <= set(df.columns)
    assert df["value"].notna().all()
