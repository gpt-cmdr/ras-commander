"""
Integration tests for RasUnsteady.set_precipitation_hyetograph().

Tests verify that:
1. Hyetograph DataFrame format validation works
2. Fixed-width formatting is correct
3. Interval detection works correctly
4. Existing unsteady files are updated properly
5. Integration with StormGenerator works

Test with real HEC-RAS example projects following TDD approach.
"""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
import shutil
import tempfile


class _InitializedRas:
    def check_initialized(self):
        return None


class TestSetPrecipitationHyetograph:
    """Test RasUnsteady.set_precipitation_hyetograph() method."""

    @pytest.fixture
    def sample_hyetograph_1hr(self):
        """Create sample 24-hour hyetograph with 1-hour intervals."""
        hours = np.arange(1.0, 25.0, 1.0)  # 1, 2, 3, ..., 24
        incremental = np.array([
            0.10, 0.10, 0.10, 0.25, 0.25, 0.25, 0.25, 0.50, 0.75, 1.00,
            1.50, 2.00, 2.50, 2.00, 1.50, 1.00, 0.75, 0.50, 0.25, 0.25,
            0.25, 0.25, 0.10, 0.10
        ])
        cumulative = np.cumsum(incremental)

        return pd.DataFrame({
            'hour': hours,
            'incremental_depth': incremental,
            'cumulative_depth': cumulative
        })

    @pytest.fixture
    def sample_hyetograph_30min(self):
        """Create sample 6-hour hyetograph with 30-minute intervals."""
        hours = np.arange(0.5, 6.5, 0.5)  # 0.5, 1.0, 1.5, ..., 6.0
        incremental = np.array([
            0.05, 0.10, 0.15, 0.25, 0.50, 1.00, 0.50, 0.25, 0.15, 0.10,
            0.05, 0.05
        ])
        cumulative = np.cumsum(incremental)

        return pd.DataFrame({
            'hour': hours,
            'incremental_depth': incremental,
            'cumulative_depth': cumulative
        })

    @pytest.fixture
    def temp_unsteady_file(self, tmp_path):
        """Create a temporary unsteady file with Precipitation Hydrograph section."""
        content = """Flow Title=Test Rain Storm
Program Version=6.60
Use Restart= 0
Boundary Location=                ,                ,        ,        ,                ,TestArea        ,                ,                                ,
Interval=1HOUR
Precipitation Hydrograph= 21
      .1      .1      .1     .25     .25     .25     .25       0       0       0
       0       0       0       0       0       0       0       0       0       0
       0
DSS Path=
Use DSS=False
"""
        file_path = tmp_path / "test.u01"
        file_path.write_text(content)
        return file_path

    def test_validates_dataframe_columns(self, temp_unsteady_file):
        """Test that missing columns raise ValueError."""
        from ras_commander import RasUnsteady

        # Missing 'hour' column
        df_missing_hour = pd.DataFrame({
            'incremental_depth': [0.1, 0.2],
            'cumulative_depth': [0.1, 0.3]
        })

        with pytest.raises(ValueError, match="missing required columns"):
            RasUnsteady.set_precipitation_hyetograph(
                temp_unsteady_file, df_missing_hour
            )

        # Missing 'incremental_depth' column
        df_missing_incr = pd.DataFrame({
            'hour': [1.0, 2.0],
            'cumulative_depth': [0.1, 0.3]
        })

        with pytest.raises(ValueError, match="missing required columns"):
            RasUnsteady.set_precipitation_hyetograph(
                temp_unsteady_file, df_missing_incr
            )

    def test_validates_minimum_rows(self, temp_unsteady_file):
        """Test that single-row DataFrame raises ValueError."""
        from ras_commander import RasUnsteady

        df_single_row = pd.DataFrame({
            'hour': [1.0],
            'incremental_depth': [0.5],
            'cumulative_depth': [0.5]
        })

        with pytest.raises(ValueError, match="at least 2 rows"):
            RasUnsteady.set_precipitation_hyetograph(
                temp_unsteady_file, df_single_row
            )

    def test_detects_1hour_interval(self, temp_unsteady_file, sample_hyetograph_1hr):
        """Test that 1-hour interval is correctly detected and set."""
        from ras_commander import RasUnsteady

        RasUnsteady.set_precipitation_hyetograph(
            temp_unsteady_file, sample_hyetograph_1hr
        )

        content = temp_unsteady_file.read_text()
        assert "Interval=1HOUR" in content

    def test_detects_30min_interval(self, temp_unsteady_file, sample_hyetograph_30min):
        """Test that 30-minute interval is correctly detected and set."""
        from ras_commander import RasUnsteady

        RasUnsteady.set_precipitation_hyetograph(
            temp_unsteady_file, sample_hyetograph_30min
        )

        content = temp_unsteady_file.read_text()
        assert "Interval=30MIN" in content

    def test_updates_precipitation_count(self, temp_unsteady_file, sample_hyetograph_1hr):
        """Test that precipitation count is updated correctly."""
        from ras_commander import RasUnsteady

        RasUnsteady.set_precipitation_hyetograph(
            temp_unsteady_file, sample_hyetograph_1hr
        )

        content = temp_unsteady_file.read_text()
        # 24 time steps
        assert "Precipitation Hydrograph= 24" in content

    def test_writes_exact_sequential_depth_fields(self, temp_unsteady_file, sample_hyetograph_1hr):
        """Write one incremental-depth field per interval, with ten fields per row."""
        from ras_commander import RasUnsteady

        RasUnsteady.set_precipitation_hyetograph(
            temp_unsteady_file, sample_hyetograph_1hr
        )

        content = temp_unsteady_file.read_text()
        lines = content.split('\n')

        # Find the data lines after Precipitation Hydrograph header
        data_started = False
        data_lines = []
        for line in lines:
            if 'Precipitation Hydrograph=' in line:
                data_started = True
                continue
            if data_started:
                if line.strip() and not line.startswith('DSS'):
                    # Stop at non-data lines
                    if '=' in line:
                        break
                    data_lines.append(line)
                else:
                    if '=' in line:
                        break

        field_rows = [
            [float(line[i:i + 8]) for i in range(0, len(line), 8)]
            for line in data_lines
        ]
        written_depths = [value for row in field_rows for value in row]

        assert [len(row) for row in field_rows] == [10, 10, 4]
        assert len(written_depths) == 24
        assert written_depths == pytest.approx(
            sample_hyetograph_1hr["incremental_depth"].tolist()
        )

    def test_writer_round_trip_preserves_count_and_depth(
        self, temp_unsteady_file, sample_hyetograph_1hr
    ):
        """Read writer output through the public table reader without losing depth."""
        from ras_commander import RasUnsteady

        RasUnsteady.set_precipitation_hyetograph(
            temp_unsteady_file, sample_hyetograph_1hr
        )
        tables = RasUnsteady.extract_tables(
            temp_unsteady_file,
            ras_object=_InitializedRas(),
        )

        values = tables["Precipitation Hydrograph="]["Value"].tolist()
        assert len(values) == 24
        assert values == pytest.approx(
            sample_hyetograph_1hr["incremental_depth"].tolist()
        )
        assert sum(values) == pytest.approx(
            sample_hyetograph_1hr["incremental_depth"].sum()
        )

    def test_preserves_other_content(self, temp_unsteady_file, sample_hyetograph_1hr):
        """Test that other file content is preserved."""
        from ras_commander import RasUnsteady

        RasUnsteady.set_precipitation_hyetograph(
            temp_unsteady_file, sample_hyetograph_1hr
        )

        content = temp_unsteady_file.read_text()

        # Verify other content preserved
        assert "Flow Title=Test Rain Storm" in content
        assert "Program Version=6.60" in content
        assert "Boundary Location=" in content
        assert "Use DSS=False" in content

    def test_file_not_found_raises(self):
        """Test that FileNotFoundError is raised for non-existent file."""
        from ras_commander import RasUnsteady

        df = pd.DataFrame({
            'hour': [1.0, 2.0],
            'incremental_depth': [0.1, 0.2],
            'cumulative_depth': [0.1, 0.3]
        })

        with pytest.raises(FileNotFoundError):
            RasUnsteady.set_precipitation_hyetograph(
                "/nonexistent/path/test.u01", df
            )

    def test_no_precipitation_section_raises(self, tmp_path):
        """Test that ValueError is raised when no Precipitation Hydrograph section exists."""
        from ras_commander import RasUnsteady

        # Create file without Precipitation Hydrograph section
        content = """Flow Title=Test Flow
Program Version=6.60
Boundary Location=River,Reach,Station
Flow Hydrograph= 3
     100     200     300
"""
        file_path = tmp_path / "no_precip.u01"
        file_path.write_text(content)

        df = pd.DataFrame({
            'hour': [1.0, 2.0],
            'incremental_depth': [0.1, 0.2],
            'cumulative_depth': [0.1, 0.3]
        })

        with pytest.raises(ValueError, match="No 'Precipitation Hydrograph=' section found"):
            RasUnsteady.set_precipitation_hyetograph(file_path, df)


class TestIntervalDetection:
    """Test interval detection from DataFrame."""

    @pytest.fixture
    def temp_unsteady_file(self, tmp_path):
        """Create a temporary unsteady file."""
        content = """Flow Title=Test Rain
Program Version=6.60
Boundary Location=                ,                ,        ,        ,                ,Area1           ,                ,                                ,
Interval=1HOUR
Precipitation Hydrograph= 3
      .1      .2      .3
DSS Path=
Use DSS=False
"""
        file_path = tmp_path / "test.u01"
        file_path.write_text(content)
        return file_path

    @pytest.mark.parametrize("hours,expected_interval", [
        (np.arange(1.0, 5.0, 1.0), "1HOUR"),        # 1 hour
        (np.arange(0.5, 3.0, 0.5), "30MIN"),        # 30 minutes
        (np.arange(0.25, 2.0, 0.25), "15MIN"),      # 15 minutes
        (np.arange(1/12, 1.0, 1/12), "5MIN"),       # 5 minutes (0.0833 hours)
        (np.arange(2.0, 50.0, 2.0), "2HOUR"),       # 2 hours
        (np.arange(6.0, 50.0, 6.0), "6HOUR"),       # 6 hours
    ])
    def test_interval_detection(self, temp_unsteady_file, hours, expected_interval):
        """Test various interval detections."""
        from ras_commander import RasUnsteady

        df = pd.DataFrame({
            'hour': hours,
            'incremental_depth': np.ones(len(hours)) * 0.1,
            'cumulative_depth': np.cumsum(np.ones(len(hours)) * 0.1)
        })

        RasUnsteady.set_precipitation_hyetograph(temp_unsteady_file, df)

        content = temp_unsteady_file.read_text()
        assert f"Interval={expected_interval}" in content, \
            f"Expected Interval={expected_interval}, but not found in file"


class TestStormGeneratorIntegration:
    """Test integration with StormGenerator."""

    @pytest.fixture
    def temp_unsteady_file(self, tmp_path):
        """Create a temporary unsteady file."""
        content = """Flow Title=Design Storm Test
Program Version=6.60
Boundary Location=                ,                ,        ,        ,                ,Watershed       ,                ,                                ,
Interval=1HOUR
Precipitation Hydrograph= 5
     0.1     0.2     0.3     0.2     0.1
DSS Path=
Use DSS=False
"""
        file_path = tmp_path / "storm.u01"
        file_path.write_text(content)
        return file_path

    def test_storm_generator_dataframe_format(self, temp_unsteady_file):
        """Test that StormGenerator DataFrame works with set_precipitation_hyetograph."""
        from ras_commander import RasUnsteady

        # Create DataFrame in StormGenerator format
        hours = np.arange(1.0, 25.0, 1.0)
        incremental = np.array([
            0.04, 0.05, 0.06, 0.08, 0.10, 0.15, 0.25, 0.40, 0.60, 0.90,
            1.30, 2.00, 2.00, 1.30, 0.90, 0.60, 0.40, 0.25, 0.15, 0.10,
            0.08, 0.06, 0.05, 0.04
        ])
        cumulative = np.cumsum(incremental)

        hyeto_df = pd.DataFrame({
            'hour': hours,
            'incremental_depth': incremental,
            'cumulative_depth': cumulative
        })

        # Should not raise
        RasUnsteady.set_precipitation_hyetograph(temp_unsteady_file, hyeto_df)

        content = temp_unsteady_file.read_text()
        assert "Precipitation Hydrograph= 24" in content

    def test_depth_conservation_in_file(self, temp_unsteady_file):
        """Test that total depth is preserved in file."""
        from ras_commander import RasUnsteady

        target_depth = 10.0
        hours = np.arange(1.0, 11.0, 1.0)
        incremental = np.ones(10) * 1.0  # 1.0 inch each hour
        cumulative = np.cumsum(incremental)

        hyeto_df = pd.DataFrame({
            'hour': hours,
            'incremental_depth': incremental,
            'cumulative_depth': cumulative
        })

        RasUnsteady.set_precipitation_hyetograph(temp_unsteady_file, hyeto_df)

        # Read back and verify
        content = temp_unsteady_file.read_text()
        lines = content.split('\n')

        # Find data lines and sum depths
        data_started = False
        total_depth_from_file = 0.0

        for line in lines:
            if 'Precipitation Hydrograph=' in line:
                data_started = True
                continue
            if data_started and line.strip():
                if '=' in line:
                    break
                for i in range(0, len(line), 8):
                    depth_str = line[i:i + 8].strip()
                    if depth_str:
                        total_depth_from_file += float(depth_str)

        assert abs(total_depth_from_file - target_depth) < 0.01, \
            f"Expected total depth {target_depth}, got {total_depth_from_file}"


class TestPrecipitationHydrographConsistency:
    """Regression coverage for HEC-RAS incremental-depth inline tables."""

    GUI_DEPTHS = [
        0.1, 0.1, 0.1, 0.25, 0.25, 0.25, 0.25, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
    ]

    @pytest.fixture
    def gui_authored_unsteady_file(self, tmp_path):
        unsteady_file = tmp_path / "gui_authored.u01"
        unsteady_file.write_text(
            """Flow Title=GUI-authored Precip
Boundary Location=                ,                ,        ,        ,                ,Area1           ,                ,                                ,
Interval=1HOUR
Precipitation Hydrograph= 21
      .1      .1      .1     .25     .25     .25     .25       0       0       0
       0       0       0       0       0       0       0       0       0       0
       0
DSS Path=
Use DSS=False
""",
            encoding="utf-8",
        )
        return unsteady_file

    def test_extract_tables_reads_exact_gui_authored_fields(
        self, gui_authored_unsteady_file
    ):
        from ras_commander import RasUnsteady

        tables = RasUnsteady.extract_tables(
            gui_authored_unsteady_file,
            ras_object=_InitializedRas(),
        )

        precip_values = tables["Precipitation Hydrograph="]["Value"].tolist()
        assert len(precip_values) == 21
        assert precip_values == self.GUI_DEPTHS

        lines = gui_authored_unsteady_file.read_text(encoding="utf-8").splitlines(True)
        precip_table = next(
            table for table in RasUnsteady.identify_tables(lines)
            if table[0] == "Precipitation Hydrograph="
        )
        assert precip_table[2] - precip_table[1] == 3

    def test_extract_boundary_and_tables_reads_exact_gui_authored_fields(
        self, gui_authored_unsteady_file
    ):
        from ras_commander import RasUnsteady

        boundaries = RasUnsteady.extract_boundary_and_tables(
            gui_authored_unsteady_file,
            ras_object=_InitializedRas(),
        )

        table = boundaries.iloc[0]["Tables"]["Precipitation Hydrograph"]
        assert len(table) == 21
        assert table["Value"].tolist() == self.GUI_DEPTHS

    def test_rasprj_boundary_parser_reads_exact_gui_authored_fields(self):
        from ras_commander.RasPrj import RasPrj

        block = """Boundary Location=                ,                ,        ,        ,                ,Area1           ,                ,                                ,
Interval=1HOUR
Precipitation Hydrograph= 21
      .1      .1      .1     .25     .25     .25     .25       0       0       0
       0       0       0       0       0       0       0       0       0       0
       0
DSS Path=
Use DSS=False
"""

        prj = RasPrj()
        bc_info, unparsed_lines = prj._parse_boundary_condition(block, "01", 1)

        assert bc_info["hydrograph_num_values"] == 21
        assert len(bc_info["hydrograph_values"]) == 21
        assert [float(value) for value in bc_info["hydrograph_values"]] == self.GUI_DEPTHS
        assert unparsed_lines == ""

    def test_usgs_boundary_update_replaces_exact_precipitation_rows(self, tmp_path):
        from ras_commander.usgs.boundary_generation import BoundaryGenerator

        unsteady_file = tmp_path / "replace_precip.u01"
        unsteady_file.write_text(
            """Flow Title=Replace Precip
Boundary Location=                ,                ,        ,        ,                ,Area1           ,                ,                                ,
Interval=1HOUR
Precipitation Hydrograph= 11
     0.1     0.2     0.3     0.4     0.5     0.6     0.7     0.8     0.9     1.0
     1.1
DSS Path=
Use DSS=False
""",
            encoding="utf-8",
        )

        BoundaryGenerator.update_boundary_hydrograph(
            unsteady_file=unsteady_file,
            boundary_location="Area1",
            hydrograph_table=(
                "Interval=1HOUR\n"
                "Precipitation Hydrograph= 1\n"
                "    0.05"
            ),
            table_type="Precipitation Hydrograph=",
        )

        content = unsteady_file.read_text(encoding="utf-8")
        assert "Precipitation Hydrograph= 1\n    0.05\nDSS Path=" in content
        assert "     1.1" not in content
        assert "Use DSS=False" in content
        assert content.count("Precipitation Hydrograph=") == 1


class TestRealProjectIntegration:
    """Integration tests with real HEC-RAS example projects.

    These tests use RasExamples.extract_project() following TDD approach.
    They are marked with pytest.mark.slow for CI/CD filtering.
    """

    @pytest.fixture
    def davis_project(self, tmp_path):
        """Extract Davis example project if available."""
        try:
            from ras_commander import RasExamples
            project_path = RasExamples.extract_project(
                "Davis",
                output_path=tmp_path,
                suffix="_precip_test"
            )
            return project_path
        except Exception:
            pytest.skip("Davis example project not available")

    @pytest.mark.slow
    def test_davis_project_update(self, davis_project):
        """Test updating Davis project unsteady file with new hyetograph."""
        from ras_commander import RasUnsteady
        from pathlib import Path

        # Find unsteady file
        unsteady_files = list(davis_project.glob("*.u01"))
        if not unsteady_files:
            pytest.skip("No .u01 file in Davis project")

        unsteady_file = unsteady_files[0]

        # Check if it has Precipitation Hydrograph section
        content = unsteady_file.read_text()
        if "Precipitation Hydrograph=" not in content:
            pytest.skip("Davis .u01 has no Precipitation Hydrograph section")

        # Create new hyetograph
        hours = np.arange(1.0, 25.0, 1.0)
        incremental = np.array([
            0.10, 0.10, 0.10, 0.25, 0.25, 0.25, 0.25, 0.50, 0.75, 1.00,
            1.50, 2.00, 2.50, 2.00, 1.50, 1.00, 0.75, 0.50, 0.25, 0.25,
            0.25, 0.25, 0.10, 0.10
        ])

        hyeto_df = pd.DataFrame({
            'hour': hours,
            'incremental_depth': incremental,
            'cumulative_depth': np.cumsum(incremental)
        })

        # Update file
        RasUnsteady.set_precipitation_hyetograph(unsteady_file, hyeto_df)

        # Verify update
        new_content = unsteady_file.read_text()
        assert "Precipitation Hydrograph= 24" in new_content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
