"""Smoke test: write a 2D flow area perimeter, then run HEC-RAS geometry preprocessor.

Round-trips the BaldEagleCrkMulti2D g11 perimeters through set_2d_flow_area_perimeter()
and verifies HEC-RAS can preprocess the result via compute_plan(force_geompre=True).
"""

import pytest
from pathlib import Path

from ras_commander import init_ras_project, RasCmdr
from ras_commander.RasExamples import RasExamples
from ras_commander.geom.GeomStorage import GeomStorage


@pytest.fixture(scope="module")
def bald_eagle_project():
    """Extract BaldEagleCrkMulti2D to a temp folder for modification."""
    project_path = RasExamples.extract_project(
        "BaldEagleCrkMulti2D", suffix="geom_preprocess_smoke"
    )
    return project_path


class TestGeomPreprocessSmoke:

    def test_roundtrip_perimeter_then_preprocess(self, bald_eagle_project):
        """Write perimeter via API, then verify HEC-RAS preprocesses successfully."""
        project_path = bald_eagle_project
        geom_file = project_path / "BaldEagleDamBrk.g11"
        assert geom_file.exists(), f"g11 not found at {geom_file}"

        # --- Step 1: Read existing perimeters ---
        gdf = GeomStorage.get_storage_area_polygons(geom_file, exclude_2d=False)
        areas_2d = gdf[gdf["is_2d"]]
        assert len(areas_2d) == 2, f"Expected 2 flow areas in g11, got {len(areas_2d)}"

        # --- Step 2: Round-trip each perimeter through the writer ---
        for _, row in areas_2d.iterrows():
            name = row["Name"]
            polygon = row.geometry
            GeomStorage.set_2d_flow_area_perimeter(
                geom_file,
                flow_area_name=name,
                geometry=polygon,
                create_backup=True,
            )

        # --- Step 3: Verify written file is still parseable ---
        gdf_after = GeomStorage.get_storage_area_polygons(geom_file, exclude_2d=False)
        areas_2d_after = gdf_after[gdf_after["is_2d"]]
        assert len(areas_2d_after) == 2, "Lost a 2D flow area during round-trip"

        for _, row in areas_2d_after.iterrows():
            orig = areas_2d[areas_2d["Name"] == row["Name"]].iloc[0]
            orig_coords = list(orig.geometry.exterior.coords)
            new_coords = list(row.geometry.exterior.coords)
            assert len(new_coords) == len(orig_coords), (
                f"{row['Name']}: vertex count changed "
                f"({len(orig_coords)} -> {len(new_coords)})"
            )

        # --- Step 4: Delete any stale geometry HDF so preprocessing is forced ---
        for hdf in project_path.glob("*.g11.hdf"):
            hdf.unlink()
        for c_file in project_path.glob("*.c18"):
            c_file.unlink()

        # --- Step 5: Initialize project and run geometry preprocessor ---
        init_ras_project(project_path, "6.6")

        try:
            result = RasCmdr.compute_plan(
                "18",
                force_geompre=True,
                num_cores=2,
            )
        except Exception as e:
            pytest.skip(f"HEC-RAS execution unavailable: {e}")

        # --- Step 6: Verify geometry HDF was created ---
        geom_hdfs = list(project_path.glob("*.g11.hdf"))
        assert len(geom_hdfs) > 0, (
            "Geometry HDF not created — HEC-RAS could not preprocess the written file"
        )

        assert result, (
            f"compute_plan returned failure — geometry preprocessing or simulation failed"
        )

        print(f"[OK] HEC-RAS successfully preprocessed round-tripped g11 geometry")
        print(f"     Geometry HDF: {geom_hdfs[0].name} ({geom_hdfs[0].stat().st_size:,} bytes)")
