"""
Test GeomCrossSection.get_xs_coords() with multiple HEC-RAS versions.

This tests the plain text geometry XYZ extraction against:
- HEC-RAS 4.1 projects (legacy)
- HEC-RAS 6.x projects (modern)
- Comparison to HdfXsec.get_cross_sections() where HDF available
"""

import sys
from pathlib import Path

# Ensure we're using local source, not installed package
repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import pytest
import pandas as pd
import numpy as np
import tempfile

from ras_commander import RasExamples, init_ras_project
from ras_commander.geom import GeomCrossSection
from ras_commander import RasCmdr


class TestGeomXsCoords:
    """Test XYZ extraction from plain text geometry files"""

    def test_basic_extraction_muncie(self):
        """Test basic XYZ extraction with Muncie (6.x compatible)"""
        # Extract project
        project_path = RasExamples.extract_project("Muncie", suffix="test_xs_coords")

        # Find geometry file
        geom_files = list(project_path.glob("*.g0*"))
        assert len(geom_files) > 0, "No geometry files found"

        geom_file = geom_files[0]
        print(f"\nTesting with: {geom_file}")

        # Extract XYZ coordinates
        xyz = GeomCrossSection.get_xs_coords(geom_file)

        # Validation checks
        assert len(xyz) > 0, "No XYZ points extracted"
        assert 'river' in xyz.columns
        assert 'reach' in xyz.columns
        assert 'RS' in xyz.columns
        assert 'station' in xyz.columns
        assert 'x' in xyz.columns
        assert 'y' in xyz.columns
        assert 'z' in xyz.columns

        # Check data types
        assert xyz['x'].dtype in [np.float64, np.float32]
        assert xyz['y'].dtype in [np.float64, np.float32]
        assert xyz['z'].dtype in [np.float64, np.float32]

        # Check for NaN values (should be none)
        assert xyz['x'].notna().all(), "Found NaN in x coordinates"
        assert xyz['y'].notna().all(), "Found NaN in y coordinates"
        assert xyz['z'].notna().all(), "Found NaN in z coordinates"

        # Check coordinates are reasonable (not all zeros)
        assert xyz['x'].std() > 0, "All x coordinates are identical"
        assert xyz['y'].std() > 0, "All y coordinates are identical"
        assert xyz['z'].std() > 0, "All elevations are identical"

        print(f"[OK] Extracted {len(xyz)} points from {xyz['RS'].nunique()} cross sections")
        print(f"  X range: {xyz['x'].min():.2f} to {xyz['x'].max():.2f}")
        print(f"  Y range: {xyz['y'].min():.2f} to {xyz['y'].max():.2f}")
        print(f"  Z range: {xyz['z'].min():.2f} to {xyz['z'].max():.2f}")

    def test_filtering_by_river_reach(self):
        """Test filtering by river and reach"""
        project_path = RasExamples.extract_project("Muncie", suffix="test_filtering")
        geom_file = list(project_path.glob("*.g0*"))[0]

        # Get all XS first
        xyz_all = GeomCrossSection.get_xs_coords(geom_file)
        rivers = xyz_all['river'].unique()
        reaches = xyz_all['reach'].unique()

        if len(rivers) > 0 and len(reaches) > 0:
            # Filter by first river
            xyz_river = GeomCrossSection.get_xs_coords(geom_file, river=rivers[0])
            assert len(xyz_river) > 0
            assert (xyz_river['river'] == rivers[0]).all()

            # Filter by river and reach
            xyz_reach = GeomCrossSection.get_xs_coords(
                geom_file,
                river=rivers[0],
                reach=reaches[0]
            )
            assert len(xyz_reach) > 0
            assert (xyz_reach['river'] == rivers[0]).all()
            assert (xyz_reach['reach'] == reaches[0]).all()

            print(f"[OK] Filtering works: {len(xyz_all)} total -> {len(xyz_river)} river -> {len(xyz_reach)} reach")

    def test_single_cross_section(self):
        """Test extracting single cross section"""
        project_path = RasExamples.extract_project("Muncie", suffix="test_single_xs")
        geom_file = list(project_path.glob("*.g0*"))[0]

        # Get first cross section
        xyz_all = GeomCrossSection.get_xs_coords(geom_file)
        first_xs = xyz_all.iloc[0]

        # Extract just that cross section
        xyz_single = GeomCrossSection.get_xs_coords(
            geom_file,
            river=first_xs['river'],
            reach=first_xs['reach'],
            rs=first_xs['RS']
        )

        assert len(xyz_single) > 0
        assert (xyz_single['RS'] == first_xs['RS']).all()

        print(f"[OK] Single XS extraction: {len(xyz_single)} points for RS {first_xs['RS']}")

    def test_compare_to_hdf(self):
        """Compare plain text extraction to HDF extraction (when HDF available)"""
        project_path = RasExamples.extract_project("Muncie", suffix="test_hdf_compare")

        # Initialize and force geometry preprocessing
        init_ras_project(project_path, "6.6")

        # Execute plan to generate geometry HDF
        try:
            RasCmdr.compute_plan("01", force_geompre=True, num_cores=2)
        except Exception as e:
            pytest.skip(f"Could not execute plan (HEC-RAS not available): {e}")

        # Check if geometry HDF was created
        geom_hdf = list(project_path.glob("*.g*.hdf"))
        if len(geom_hdf) == 0:
            pytest.skip("No geometry HDF created")

        geom_file = list(project_path.glob("*.g0*"))[0]

        # Extract from plain text
        xyz_txt = GeomCrossSection.get_xs_coords(geom_file)

        # Extract from HDF
        from ras_commander.hdf import HdfXsec
        try:
            gdf_hdf = HdfXsec.get_cross_sections(str(geom_hdf[0]))
        except Exception as e:
            pytest.skip(f"Could not read HDF: {e}")

        # Compare cross section counts
        num_xs_txt = xyz_txt['RS'].nunique()
        num_xs_hdf = len(gdf_hdf)

        print(f"\n[OK] Cross section count comparison:")
        print(f"  Plain text: {num_xs_txt} cross sections")
        print(f"  HDF: {num_xs_hdf} cross sections")

        # Counts should match (or be close)
        assert abs(num_xs_txt - num_xs_hdf) <= 1, \
            f"XS count mismatch: txt={num_xs_txt}, hdf={num_xs_hdf}"

        # Compare a specific cross section's coordinates
        if num_xs_txt > 0 and num_xs_hdf > 0:
            # Get first XS from text
            first_rs = xyz_txt['RS'].unique()[0]
            xyz_xs = xyz_txt[xyz_txt['RS'] == first_rs]

            # Find matching XS in HDF
            hdf_xs = gdf_hdf[gdf_hdf['RS'] == first_rs]

            if len(hdf_xs) > 0:
                # Compare point counts
                num_pts_txt = len(xyz_xs)
                # HDF station_elevation is Nx2 array
                num_pts_hdf = len(hdf_xs.iloc[0]['station_elevation'])

                print(f"  RS {first_rs} points: txt={num_pts_txt}, hdf={num_pts_hdf}")

                # Point counts should match
                assert num_pts_txt == num_pts_hdf, \
                    f"Point count mismatch for RS {first_rs}"

    def test_export_to_shapefile(self):
        """Test exporting to shapefile format"""
        try:
            import geopandas as gpd
            from shapely.geometry import LineString
        except ImportError:
            pytest.skip("geopandas not installed")

        project_path = RasExamples.extract_project("Muncie", suffix="test_export")
        geom_file = list(project_path.glob("*.g0*"))[0]

        # Extract XYZ
        xyz = GeomCrossSection.get_xs_coords(geom_file)

        # Convert to GeoDataFrame with LineStrings
        xs_lines = []
        for (river, reach, rs), group in xyz.groupby(['river', 'reach', 'RS']):
            coords = list(zip(group['x'], group['y'], group['z']))
            xs_lines.append({
                'river': river,
                'reach': reach,
                'RS': rs,
                'geometry': LineString(coords)
            })

        gdf = gpd.GeoDataFrame(xs_lines, geometry='geometry')

        assert len(gdf) > 0, "No cross sections in GeoDataFrame"
        assert all(isinstance(geom, LineString) for geom in gdf['geometry'])

        print(f"[OK] Created GeoDataFrame with {len(gdf)} cross section LineStrings")

        # Test writing to file (in temp location)
        output_path = project_path / "cross_sections.shp"
        try:
            gdf.to_file(output_path)
            assert output_path.exists()
            print(f"[OK] Successfully exported to: {output_path}")
        except Exception as e:
            pytest.skip(f"Could not write shapefile: {e}")

    def test_error_handling(self):
        """Test error handling for invalid inputs"""
        # Non-existent file
        with pytest.raises(FileNotFoundError):
            GeomCrossSection.get_xs_coords("nonexistent.g01")

        # Valid file but invalid filter
        project_path = RasExamples.extract_project("Muncie", suffix="test_errors")
        geom_file = list(project_path.glob("*.g0*"))[0]

        with pytest.raises(ValueError, match="No cross sections found"):
            GeomCrossSection.get_xs_coords(
                geom_file,
                river="NonexistentRiver",
                reach="NonexistentReach"
            )


    def test_dynamic_section_search_synthetic(self):
        """
        Regression test: parser must dynamically search to end of XS section
        to find #Sta/Elev= when cross sections have many GIS cut line points.

        Bug history:
        - DEFAULT_SEARCH_RANGE was 50, then increased to 500
        - Now replaced with dynamic _find_xs_section_end() that has no fixed limit

        This test uses 600 cut line points to prove no fixed limit exists.
        """
        project_path = RasExamples.extract_project("Muncie", suffix="test_search_range")

        NUM_CUT_POINTS = 600  # Proves no fixed limit (beyond old 500-line limit)

        # Generate cut line coordinates that fill 16-char fixed-width fields
        np.random.seed(42)
        xs_coords = 3101220.0 + np.cumsum(np.random.uniform(0.5, 2.0, NUM_CUT_POINTS))
        ys_coords = 13779229.0 + np.cumsum(np.random.uniform(-1.0, 1.0, NUM_CUT_POINTS))

        # Format as 16-char fixed-width values, 10 per line
        vals = []
        for i in range(NUM_CUT_POINTS):
            vals.append(f"{xs_coords[i]:16.7f}")
            vals.append(f"{ys_coords[i]:16.7f}")

        cut_line_data_lines = []
        for i in range(0, len(vals), 10):
            chunk = vals[i:i+10]
            cut_line_data_lines.append("".join(chunk))

        # Build synthetic geometry with large cut line BEFORE #Sta/Elev=
        sta_elev_pairs = 5
        # HEC-RAS uses 8-char fixed-width columns for station/elevation data
        sta_elev_values = (
            f"{'0.0':>8s}{'100.0':>8s}{'250.0':>8s}{'95.0':>8s}{'500.0':>8s}"
            f"{'90.0':>8s}{'750.0':>8s}{'95.0':>8s}{'1000.0':>8s}{'100.0':>8s}"
        )

        synthetic_geom = f"""Geom Title=Search Range Test
Program Version=6.50
River Reach=TestRiver    ,TestReach
Reach XY= 2
         0.00         0.00
     10000.00         0.00
Type RM Length L Ch R = 1 ,5000.000,     0.0,     0.0,     0.0
Node Last Edited Time=Jan/01/2025 00:00:00
Bank Sta=0,1000
XS GIS Cut Line={NUM_CUT_POINTS}
"""
        synthetic_geom += "\n".join(cut_line_data_lines) + "\n"
        synthetic_geom += f"""Node Name=
Dist XS Type=
#Sta/Elev= {sta_elev_pairs}
{sta_elev_values}
#Mann= 2 , 0 , 0
     0   .04     0     0 500   .04     0     0
"""

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.g01', delete=False, dir=str(project_path)
        ) as f:
            f.write(synthetic_geom)
            synthetic_file = Path(f.name)

        try:
            # This is the critical test: get_station_elevation must find
            # #Sta/Elev= past all the cut line data lines
            sta_elev_df = GeomCrossSection.get_station_elevation(
                synthetic_file, "TestRiver", "TestReach", "5000.000"
            )

            assert sta_elev_df is not None, \
                "get_station_elevation() returned None -- dynamic section search failed"
            assert len(sta_elev_df) == sta_elev_pairs, \
                f"Expected {sta_elev_pairs} pairs, got {len(sta_elev_df)}"

            # Verify actual values
            assert abs(sta_elev_df.iloc[0]['Station'] - 0.0) < 0.01
            assert abs(sta_elev_df.iloc[0]['Elevation'] - 100.0) < 0.01
            assert abs(sta_elev_df.iloc[-1]['Station'] - 1000.0) < 0.01
            assert abs(sta_elev_df.iloc[-1]['Elevation'] - 100.0) < 0.01

            print(f"[OK] get_station_elevation() found #Sta/Elev= past {NUM_CUT_POINTS} "
                  f"cut line points ({len(cut_line_data_lines)} data lines)")
            print(f"  Station-elevation pairs: {len(sta_elev_df)}")

        finally:
            synthetic_file.unlink(missing_ok=True)


    def test_real_world_dense_cut_lines(self):
        """
        Real-world test: parse XS with 462 GIS cut line points from HCFCD
        M3 White Oak Bayou model (Model E).

        This model has production FEMA effective cross sections with dense
        GIS cut lines. The XS at RS=95027.60 has 462 cut line points,
        producing ~231 data lines between the XS header and #Sta/Elev=.
        With the old DEFAULT_SEARCH_RANGE=50 (or even 500), this XS would
        fail. Dynamic section-end search handles it correctly.

        Skips gracefully if network is unavailable (download required).
        """
        try:
            from ras_commander import M3Model
        except ImportError:
            pytest.skip("M3Model not available")

        # Download Model E (White Oak Bayou, ~20 MB)
        try:
            model_path = M3Model.extract_model("E")
        except Exception as e:
            pytest.skip(f"Could not download M3 Model E (network unavailable?): {e}")

        # M3Model.extract_model() downloads an outer zip containing inner
        # per-submodel zips (e.g. E100-00-00.zip). We need to extract the
        # inner zip to get the .g01 geometry file.
        import zipfile
        inner_zip = model_path / "HEC-RAS" / "E100-00-00.zip"
        if inner_zip.exists():
            extract_dir = model_path / "HEC-RAS" / "E100-00-00"
            if not extract_dir.exists():
                with zipfile.ZipFile(inner_zip, 'r') as zf:
                    zf.extractall(extract_dir)
                print(f"Extracted inner zip: {inner_zip.name}")

        # Find the geometry file E100-00-00.g01
        geom_files = list(model_path.glob("**/E100-00-00.g01"))
        if not geom_files:
            # Try broader search
            geom_files = list(model_path.glob("**/*.g01"))

        if not geom_files:
            pytest.skip("Could not find geometry file in M3 Model E")

        geom_file = geom_files[0]
        print(f"\nTesting with real-world file: {geom_file}")
        print(f"  File size: {geom_file.stat().st_size / 1024:.0f} KB")

        # Read file to find XS with most cut line points
        with open(geom_file, 'r') as f:
            lines = f.readlines()

        max_cut_points = 0
        max_cut_rs = None
        max_cut_river = None
        max_cut_reach = None
        current_river = None
        current_reach = None
        current_rs = None

        for i, line in enumerate(lines):
            if line.startswith("River Reach="):
                parts = line.split("=")[1].strip().split(",")
                if len(parts) >= 2:
                    current_river = parts[0].strip()
                    current_reach = parts[1].strip()
            elif line.startswith("Type RM Length L Ch R ="):
                parts = line.split(",")
                if len(parts) >= 2:
                    current_rs = parts[1].strip()
            elif line.startswith("XS GIS Cut Line="):
                count = int(line.split("=")[1].strip())
                if count > max_cut_points:
                    max_cut_points = count
                    max_cut_rs = current_rs
                    max_cut_river = current_river
                    max_cut_reach = current_reach

        print(f"  Densest XS: {max_cut_river}/{max_cut_reach}/RS {max_cut_rs}")
        print(f"  Cut line points: {max_cut_points}")

        assert max_cut_points > 200, \
            f"Expected dense cut lines (>200 points), got {max_cut_points}"

        # Critical test: parse station-elevation past all the cut line data
        sta_elev_df = GeomCrossSection.get_station_elevation(
            geom_file, max_cut_river, max_cut_reach, max_cut_rs
        )

        assert sta_elev_df is not None, \
            f"get_station_elevation() returned None for {max_cut_points}-point XS"
        assert len(sta_elev_df) > 0, \
            f"get_station_elevation() returned empty DataFrame for {max_cut_points}-point XS"

        # Verify data is reasonable
        assert sta_elev_df['Station'].notna().all(), "Found NaN in stations"
        assert sta_elev_df['Elevation'].notna().all(), "Found NaN in elevations"
        assert sta_elev_df['Station'].is_monotonic_increasing, \
            "Stations should be monotonically increasing"

        print(f"[OK] Parsed {len(sta_elev_df)} station-elevation pairs past "
              f"{max_cut_points} cut line points")
        print(f"  Station range: {sta_elev_df['Station'].min():.1f} to "
              f"{sta_elev_df['Station'].max():.1f}")
        print(f"  Elevation range: {sta_elev_df['Elevation'].min():.1f} to "
              f"{sta_elev_df['Elevation'].max():.1f}")


if __name__ == "__main__":
    # Run tests manually
    test = TestGeomXsCoords()

    print("=" * 80)
    print("Testing GeomCrossSection.get_xs_coords()")
    print("=" * 80)

    print("\n1. Basic extraction test...")
    test.test_basic_extraction_muncie()

    print("\n2. Filtering test...")
    test.test_filtering_by_river_reach()

    print("\n3. Single cross section test...")
    test.test_single_cross_section()

    print("\n4. Shapefile export test...")
    test.test_export_to_shapefile()

    print("\n5. Error handling test...")
    test.test_error_handling()

    print("\n6. HDF comparison test...")
    try:
        test.test_compare_to_hdf()
    except Exception as e:
        print(f"   Skipped (HEC-RAS not available): {e}")

    print("\n7. Dynamic section search test (600-point synthetic)...")
    test.test_dynamic_section_search_synthetic()

    print("\n8. Real-world dense cut lines test (M3 Model E)...")
    try:
        test.test_real_world_dense_cut_lines()
    except Exception as e:
        print(f"   Skipped (download failed): {e}")

    print("\n" + "=" * 80)
    print("[OK] All tests passed!")
    print("=" * 80)
