"""
Tests for RasUnsteady.set_normal_depth_boundary().

Validates that:
1. Adding a Normal Depth boundary to a block that has another BC type writes
   `Friction Slope=<slope>,<flag>` and strips the prior type's header,
   inline data, and DSS metadata.
2. Updating the slope on an existing Normal Depth block overwrites the line
   in place without inserting or removing other lines.
3. Selectors validate (1D triple complete; 2D area required) and slope is
   range-checked.
4. The 2D BC line selector resolves boundaries by 2D Flow Area name and
   optional BC line name (positions 5 / 7 in `Boundary Location=`).

Tests are self-contained: they synthesize minimal `.u##` content matching
the HEC-RAS line conventions observed in real projects and exercise the
writer end-to-end via the public RasUnsteady API.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def _write_unsteady(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def unsteady_with_flow_hydrograph_2d(tmp_path):
    """A 2D BC line block typed as Flow Hydrograph with inline data + DSS metadata.

    Mirrors the layout produced by HEC-RAS:
    - 9 comma-separated fields on `Boundary Location=`
    - 2D Flow Area name in field 5; BC line / SA name in field 7
    - One inline-data row for the Flow Hydrograph
    - DSS metadata lines that must be stripped on conversion to Normal Depth
    """
    body = (
        "Flow Title=Mixed BC Project\n"
        "Program Version=6.60\n"
        "Use Restart= 0 \n"
        # 1D upstream Flow Hydrograph (river/reach/station populated)
        "Boundary Location=White           ,Muncie          ,15696.24,        ,                ,                ,                ,                                ,                                \n"
        "Interval=1HOUR\n"
        "Flow Hydrograph= 2 \n"
        "  100.00  150.00\n"
        "DSS Path=\n"
        "Use DSS=False\n"
        # 2D downstream BC line where we will install Normal Depth
        "Boundary Location=                ,                ,        ,        ,                ,DS Channel      ,                ,DS Normal                       ,                                \n"
        "Interval=1HOUR\n"
        "Flow Hydrograph= 2 \n"
        "  500.00  600.00\n"
        "DSS Path=\n"
        "Use DSS=False\n"
    )
    return _write_unsteady(tmp_path / "project.u01", body)


@pytest.fixture
def unsteady_with_existing_normal_depth(tmp_path):
    """A 2D BC line block already typed as Normal Depth with `Friction Slope=`."""
    body = (
        "Flow Title=Existing ND\n"
        "Program Version=6.60\n"
        "Use Restart= 0 \n"
        "Boundary Location=                ,                ,        ,        ,                ,DS Channel      ,                ,DS Normal                       ,                                \n"
        "Friction Slope=0.003,0\n"
        # A second, unrelated boundary to make sure we don't touch it.
        "Boundary Location=                ,                ,        ,        ,                ,area2           ,                ,                                ,                                \n"
        "Interval=1HOUR\n"
        "Precipitation Hydrograph= 1 \n"
        "    0.10\n"
    )
    return _write_unsteady(tmp_path / "project.u01", body)


@pytest.fixture
def unsteady_with_1d_flow_hydrograph(tmp_path):
    """A 1D river boundary block with a Flow Hydrograph (river/reach/station)."""
    body = (
        "Flow Title=1D Convert\n"
        "Program Version=6.60\n"
        "Use Restart= 0 \n"
        "Boundary Location=White           ,Muncie          ,15696.24,        ,                ,                ,                ,                                ,                                \n"
        "Interval=1HOUR\n"
        "Flow Hydrograph= 3 \n"
        "  100.00  200.00  150.00\n"
        "DSS Path=\n"
        "Use DSS=False\n"
    )
    return _write_unsteady(tmp_path / "project.u01", body)


# ---------------------------------------------------------------------------
# Acceptance: adding Normal Depth where none exists (type conversion path)
# ---------------------------------------------------------------------------


class TestSetNormalDepthBoundaryAdd:
    def test_2d_bc_line_converts_flow_hydrograph_to_normal_depth(
        self, unsteady_with_flow_hydrograph_2d
    ):
        from ras_commander import RasUnsteady

        result = RasUnsteady.set_normal_depth_boundary(
            unsteady_with_flow_hydrograph_2d,
            friction_slope=0.0003,
            area_2d="DS Channel",
            bc_line="DS Normal",
        )

        assert result["new_friction_slope"] == 0.0003
        # Insert path with no fallback: flag is omitted (matches HEC-RAS 2D form).
        assert result["flag"] is None
        assert result["updated_in_place"] is False
        assert result["lines_inserted"] == 1
        # 1 Flow Hydrograph header + 1 inline data line + 3 DSS metadata
        # (Interval, DSS Path, Use DSS) = 5 lines stripped on conversion.
        assert result["lines_removed"] == 5
        assert result["previous_bc_type"] == "Flow Hydrograph"
        assert result["previous_friction_slope"] is None

        text = unsteady_with_flow_hydrograph_2d.read_text(encoding="utf-8")
        # The targeted 2D block now starts with Friction Slope on the next line.
        ds_block = text.split(
            "Boundary Location=                ,                ,        ,        ,                ,DS Channel"
        )[1]
        # Snip to the next Boundary Location or end of file.
        ds_block_lines = ds_block.splitlines()
        # Line 0 is the rest of this Boundary Location line itself.
        assert ds_block_lines[1] == "Friction Slope=0.0003"
        # And no Flow Hydrograph / DSS metadata in this block anymore.
        for line in ds_block_lines[1:]:
            if line.startswith("Boundary Location="):
                break
            assert not line.startswith("Flow Hydrograph=")
            assert not line.startswith("DSS Path=")
            assert not line.startswith("Use DSS=")
            assert not line.startswith("Interval=")

        # The 1D block at the top must be untouched (still Flow Hydrograph).
        assert "Flow Hydrograph= 2 " in text
        assert "  100.00  150.00" in text

    def test_1d_river_boundary_converts_to_normal_depth(
        self, unsteady_with_1d_flow_hydrograph
    ):
        from ras_commander import RasUnsteady

        result = RasUnsteady.set_normal_depth_boundary(
            unsteady_with_1d_flow_hydrograph,
            friction_slope=0.001,
            river="White",
            reach="Muncie",
            station="15696.24",
        )

        assert result["new_friction_slope"] == 0.001
        assert result["previous_bc_type"] == "Flow Hydrograph"
        assert result["updated_in_place"] is False
        assert result["lines_inserted"] == 1
        # Flow Hydrograph header + 1 inline row + Interval + DSS Path + Use DSS = 5
        assert result["lines_removed"] == 5
        # Insert path with no fallback: line is written without the flag.
        assert result["flag"] is None

        text = unsteady_with_1d_flow_hydrograph.read_text(encoding="utf-8")
        assert "Flow Hydrograph=" not in text
        assert re.search(r"^Friction Slope=0\.001\s*$", text, re.MULTILINE)

    def test_2d_bc_line_insert_with_critical_fallback_writes_flag(
        self, unsteady_with_flow_hydrograph_2d
    ):
        from ras_commander import RasUnsteady

        result = RasUnsteady.set_normal_depth_boundary(
            unsteady_with_flow_hydrograph_2d,
            friction_slope=0.0005,
            area_2d="DS Channel",
            bc_line="DS Normal",
            use_critical_fallback=True,
        )

        assert result["flag"] == 1
        text = unsteady_with_flow_hydrograph_2d.read_text(encoding="utf-8")
        assert "Friction Slope=0.0005,1" in text


# ---------------------------------------------------------------------------
# Acceptance: updating an existing Normal Depth slope (in-place path)
# ---------------------------------------------------------------------------


class TestSetNormalDepthBoundaryUpdate:
    def test_updates_existing_friction_slope_with_flag_preserved(
        self, unsteady_with_existing_normal_depth
    ):
        """Existing line had `,0` flag → updated line keeps the `,0` form."""
        from ras_commander import RasUnsteady

        result = RasUnsteady.set_normal_depth_boundary(
            unsteady_with_existing_normal_depth,
            friction_slope=0.0005,
            area_2d="DS Channel",
            bc_line="DS Normal",
        )

        assert result["previous_bc_type"] == "Normal Depth"
        assert result["previous_friction_slope"] == 0.003
        assert result["new_friction_slope"] == 0.0005
        assert result["updated_in_place"] is True
        assert result["lines_inserted"] == 0
        assert result["lines_removed"] == 0
        # The original line was `Friction Slope=0.003,0` (flag present) →
        # the updated line preserves the flag form, defaulting flag value to 0.
        assert result["flag"] == 0

        text = unsteady_with_existing_normal_depth.read_text(encoding="utf-8")
        assert "Friction Slope=0.0005,0" in text
        assert "Friction Slope=0.003,0" not in text
        # Unrelated second boundary still has its Precipitation Hydrograph data.
        assert "Precipitation Hydrograph= 1" in text
        assert "    0.10" in text

    def test_updates_existing_2d_friction_slope_without_flag(self, tmp_path):
        """2D BC line existing line has no flag → updated line stays no-flag."""
        from ras_commander import RasUnsteady

        body = (
            "Flow Title=BaldEagle-style 2D\n"
            "Boundary Location=                ,                ,        ,        ,                ,BaldEagleCr     ,                ,DSNormalDepth   \n"
            "Friction Slope=0.0003\n"
        )
        f = _write_unsteady(tmp_path / "project.u01", body)

        result = RasUnsteady.set_normal_depth_boundary(
            f,
            friction_slope=0.001,
            area_2d="BaldEagleCr",
            bc_line="DSNormalDepth",
        )

        assert result["updated_in_place"] is True
        assert result["previous_friction_slope"] == 0.0003
        assert result["new_friction_slope"] == 0.001
        # No flag on previous line and no fallback request → no flag on output.
        assert result["flag"] is None

        text = f.read_text(encoding="utf-8")
        # Use a regex anchored to line start so we don't accidentally match
        # `Friction Slope=0.001,...` if a flag had crept in.
        assert re.search(r"^Friction Slope=0\.001\s*$", text, re.MULTILINE)

    def test_use_critical_fallback_writes_flag_one(
        self, unsteady_with_existing_normal_depth
    ):
        from ras_commander import RasUnsteady

        result = RasUnsteady.set_normal_depth_boundary(
            unsteady_with_existing_normal_depth,
            friction_slope=0.002,
            area_2d="DS Channel",
            bc_line="DS Normal",
            use_critical_fallback=True,
        )

        assert result["flag"] == 1
        text = unsteady_with_existing_normal_depth.read_text(encoding="utf-8")
        assert "Friction Slope=0.002,1" in text


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestSetNormalDepthBoundaryValidation:
    def test_rejects_zero_slope(self, unsteady_with_existing_normal_depth):
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="outside the supported range"):
            RasUnsteady.set_normal_depth_boundary(
                unsteady_with_existing_normal_depth,
                friction_slope=0.0,
                area_2d="DS Channel",
                bc_line="DS Normal",
            )

    def test_rejects_negative_slope(self, unsteady_with_existing_normal_depth):
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="outside the supported range"):
            RasUnsteady.set_normal_depth_boundary(
                unsteady_with_existing_normal_depth,
                friction_slope=-0.001,
                area_2d="DS Channel",
                bc_line="DS Normal",
            )

    def test_rejects_non_numeric_slope(self, unsteady_with_existing_normal_depth):
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="must be a real number"):
            RasUnsteady.set_normal_depth_boundary(
                unsteady_with_existing_normal_depth,
                friction_slope="0.001",  # type: ignore[arg-type]
                area_2d="DS Channel",
                bc_line="DS Normal",
            )

    def test_rejects_partial_1d_selector(
        self, unsteady_with_1d_flow_hydrograph
    ):
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="1D selector requires"):
            RasUnsteady.set_normal_depth_boundary(
                unsteady_with_1d_flow_hydrograph,
                friction_slope=0.001,
                river="White",
                reach="Muncie",
                # station missing
            )

    def test_rejects_mixed_selectors(self, unsteady_with_1d_flow_hydrograph):
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="exactly one selector group"):
            RasUnsteady.set_normal_depth_boundary(
                unsteady_with_1d_flow_hydrograph,
                friction_slope=0.001,
                river="White",
                reach="Muncie",
                station="15696.24",
                area_2d="DS Channel",
            )

    def test_rejects_no_selector(self, unsteady_with_1d_flow_hydrograph):
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="exactly one selector group"):
            RasUnsteady.set_normal_depth_boundary(
                unsteady_with_1d_flow_hydrograph,
                friction_slope=0.001,
            )

    def test_unknown_target_raises(self, unsteady_with_existing_normal_depth):
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="No boundary matched"):
            RasUnsteady.set_normal_depth_boundary(
                unsteady_with_existing_normal_depth,
                friction_slope=0.002,
                area_2d="Nonexistent Area",
                bc_line="Phantom BC",
            )

    def test_missing_unsteady_file_raises(self, tmp_path):
        from ras_commander import RasUnsteady

        with pytest.raises(FileNotFoundError):
            RasUnsteady.set_normal_depth_boundary(
                tmp_path / "missing.u01",
                friction_slope=0.001,
                area_2d="DS Channel",
                bc_line="DS Normal",
            )


# ---------------------------------------------------------------------------
# 2D BC line selectors
# ---------------------------------------------------------------------------


class TestSetNormalDepthBoundary2DSelectors:
    def test_2d_selector_requires_bc_line(self, unsteady_with_existing_normal_depth):
        """Normal Depth must attach to a specific BC line; area-only is invalid."""
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="2D selector requires both area_2d and bc_line"):
            RasUnsteady.set_normal_depth_boundary(
                unsteady_with_existing_normal_depth,
                friction_slope=0.001,
                area_2d="DS Channel",
                # bc_line missing
            )

    def test_2d_field_count_8_layout_matches(self, tmp_path):
        """Real BaldEagleCrkMulti2D-style 8-field Boundary Location matches."""
        from ras_commander import RasUnsteady

        # 7 commas → 8 fields. BC line at index 7.
        body = (
            "Flow Title=BaldEagle-style 8-field\n"
            "Boundary Location=                ,                ,        ,        ,                ,BaldEagleCr     ,                ,DSNormalDepth   \n"
            "Friction Slope=0.0003\n"
        )
        f = _write_unsteady(tmp_path / "project.u01", body)

        result = RasUnsteady.set_normal_depth_boundary(
            f,
            friction_slope=0.0007,
            area_2d="BaldEagleCr",
            bc_line="DSNormalDepth",
        )
        assert result["updated_in_place"] is True
        assert result["new_friction_slope"] == 0.0007


# ---------------------------------------------------------------------------
# Real HEC-RAS example projects (RasExamples)
# ---------------------------------------------------------------------------


class TestSetNormalDepthBoundaryRealProjects:
    @pytest.mark.slow
    def test_chippewa_geometry_bc_location_creation_and_normal_depth_roundtrip(
        self,
        tmp_path,
    ):
        """Create a real-format geometry BC, associate it, and type it in .u##."""
        try:
            from ras_commander import GeomBcLines, RasExamples, RasPrj, RasUnsteady

            project = RasExamples.extract_project(
                "Chippewa_2D",
                output_path=tmp_path,
                suffix="_new_nd_location",
            )
        except Exception as exc:
            pytest.skip(f"Chippewa_2D example project not available: {exc}")
        if isinstance(project, list):
            project = project[0]

        geometry_file = next(
            (
                path
                for path in sorted(Path(project).glob("*.g0*"))
                if "hdf" not in path.name.lower()
                and "Storage Area=Perimeter 1" in path.read_text(
                    encoding="utf-8", errors="ignore"
                )
            ),
            None,
        )
        unsteady_file = next(
            (
                path
                for path in sorted(Path(project).glob("*.u0*"))
                if "hdf" not in path.name.lower()
                and "Boundary Location=" in path.read_text(
                    encoding="utf-8", errors="ignore"
                )
            ),
            None,
        )
        if geometry_file is None or unsteady_file is None:
            pytest.skip("Chippewa_2D geometry/unsteady fixtures not present")

        GeomBcLines.add_bc_lines(
            geometry_file,
            lines=[{
                "name": "QualificationND",
                "storage_area": "Perimeter 1",
                "coordinates": [
                    (1027205.96, 7858200.24),
                    (1025994.94, 7858316.68),
                ],
            }],
        )
        ras_obj = RasPrj()
        ras_obj.initialize(Path(project), "ras", suppress_logging=True)

        created = RasUnsteady.ensure_2d_boundary_location(
            unsteady_file,
            area_2d="Perimeter 1",
            bc_line="QualificationND",
            geometry_file=geometry_file,
            ras_object=ras_obj,
        )
        assert created["created"] is True
        assert created["geometry_coordinate_count"] == 2
        assert created["dataframe_verified"] is True
        assert Path(created["backup_path"]).is_file()

        idempotent = RasUnsteady.ensure_2d_boundary_location(
            unsteady_file,
            area_2d="Perimeter 1",
            bc_line="QualificationND",
            geometry_file=geometry_file,
            ras_object=ras_obj,
        )
        assert idempotent["created"] is False
        assert idempotent["backup_path"] is None

        normal_depth = RasUnsteady.set_normal_depth_boundary(
            unsteady_file,
            friction_slope=0.0003,
            area_2d="Perimeter 1",
            bc_line="QualificationND",
            ras_object=ras_obj,
        )
        assert normal_depth["new_friction_slope"] == 0.0003

        rows = ras_obj.boundaries_df[
            (ras_obj.boundaries_df["area_2d"].astype(str) == "Perimeter 1")
            & (ras_obj.boundaries_df["bc_line_name"].astype(str) == "QualificationND")
        ]
        assert len(rows) == 1
        assert rows.iloc[0]["bc_type"] == "Normal Depth"
        assert rows.iloc[0]["friction_slope_value"] == pytest.approx(0.0003)

    @pytest.mark.slow
    def test_muncie_1d_normal_depth_in_place_update(self, tmp_path):
        """Update the existing 1D Normal Depth in the Muncie example project.

        Muncie.u01 ships with `Friction Slope=0.00064,0` on the downstream
        White/Muncie/237.6455 boundary. Updating the slope should preserve the
        `,<flag>` form because it was present in the original file.
        """
        try:
            from ras_commander import RasExamples, RasUnsteady
            project = RasExamples.extract_project(
                "Muncie", output_path=tmp_path, suffix="_nd_test"
            )
        except Exception:
            pytest.skip("Muncie example project not available")

        if isinstance(project, list):
            project = project[0]
        u_files = list(Path(project).glob("*.u01"))
        if not u_files:
            pytest.skip("No .u01 in Muncie project")
        u_file = u_files[0]
        original = u_file.read_text(encoding="utf-8", errors="ignore")
        if "Friction Slope=" not in original:
            pytest.skip("Muncie .u01 has no Friction Slope= line")

        result = RasUnsteady.set_normal_depth_boundary(
            u_file,
            friction_slope=0.001,
            river="White",
            reach="Muncie",
            station="237.6455",
        )

        assert result["updated_in_place"] is True
        assert result["previous_bc_type"] == "Normal Depth"
        # Real Muncie ships with 0.00064; preserving flag form yields `,0`.
        assert result["flag"] == 0

        new_text = u_file.read_text(encoding="utf-8", errors="ignore")
        assert "Friction Slope=0.001,0" in new_text
        assert "Friction Slope=0.00064" not in new_text

    @pytest.mark.slow
    def test_bald_eagle_2d_normal_depth_no_flag_preserved(self, tmp_path):
        """Update the 2D BC line Normal Depth in BaldEagleCrkMulti2D.

        That project's .u## ships with `Friction Slope=0.0003` (no flag).
        After update the no-flag form must be preserved — losing it would
        change the file's binary equivalence to HEC-RAS-emitted output.
        """
        try:
            from ras_commander import RasExamples, RasUnsteady
            project = RasExamples.extract_project(
                "BaldEagleCrkMulti2D", output_path=tmp_path, suffix="_nd_2d_test"
            )
        except Exception:
            pytest.skip("BaldEagleCrkMulti2D example project not available")

        if isinstance(project, list):
            project = project[0]
        u_files = sorted(Path(project).glob("*.u*"))
        u_files = [u for u in u_files if "hdf" not in u.name.lower()]
        if not u_files:
            pytest.skip("No .u## in BaldEagleCrkMulti2D project")

        # Find a (.u##, area_2d, bc_line) combination that ships with a
        # no-flag `Friction Slope=...` on a 2D BC line. We discover it
        # dynamically so the test stays decoupled from which project plan
        # ships which BC line names.
        target_file = None
        target_area = None
        target_bc_line = None
        nd_pattern = re.compile(
            r"^Boundary Location=(.+?)\n(Friction Slope=\d+(?:\.\d+)?)\s*$",
            re.MULTILINE,
        )
        for u in u_files:
            text = u.read_text(encoding="utf-8", errors="ignore")
            for m in nd_pattern.finditer(text):
                parts = [p.strip() for p in m.group(1).split(",")]
                if len(parts) < 8:
                    continue
                area_2d, bc_line = parts[5], parts[7]
                if area_2d and bc_line:
                    target_file, target_area, target_bc_line = u, area_2d, bc_line
                    break
            if target_file is not None:
                break
        if target_file is None:
            pytest.skip(
                "No no-flag 2D Friction Slope= line found in BaldEagleCrkMulti2D"
            )

        result = RasUnsteady.set_normal_depth_boundary(
            target_file,
            friction_slope=0.0007,
            area_2d=target_area,
            bc_line=target_bc_line,
        )

        assert result["updated_in_place"] is True
        assert result["flag"] is None  # No flag preserved
        new_text = target_file.read_text(encoding="utf-8", errors="ignore")
        assert re.search(r"^Friction Slope=0\.0007\s*$", new_text, re.MULTILINE)


# ---------------------------------------------------------------------------
# Fix-coverage tests added 2026-05-02 in response to independent code review
# (see H:/Symphony/ras-commander/CLB-310/REVIEW.md):
#   - numpy scalar acceptance (numbers.Real)
#   - flag integer value preservation on in-place update
#   - type-conversion stripping of Flow-Hydrograph-specific extras
#   - Friction Slope value surfaced in boundaries_df
# ---------------------------------------------------------------------------


@pytest.fixture
def realistic_flow_hydrograph_2d_block(tmp_path):
    """A 2D Flow Hydrograph block that mirrors real HEC-RAS-emitted output.

    Includes every line that ships with a real BaldEagleCrkMulti2D /
    Muncie Flow Hydrograph block: Interval, count, inline data, then the
    Flow-Hydrograph-specific tail (Stage Hydrograph TW Check,
    Flow Hydrograph QMult, Flow Hydrograph Slope, DSS metadata,
    Use Fixed Start Time, Fixed Start Date/Time, Is Critical Boundary,
    Critical Boundary Flow). Used to verify type-conversion to Normal
    Depth strips ALL of them, not just the obvious DSS metadata.
    """
    body = (
        "Flow Title=Realistic FH conversion\n"
        "Program Version=6.60\n"
        "Use Restart= 0 \n"
        "Boundary Location=                ,                ,        ,        ,                ,BaldEagleCr     ,                ,Upstream Inflow                 ,                                \n"
        "Interval=1HOUR\n"
        "Flow Hydrograph= 3 \n"
        "    1000    3000    6500\n"
        "Stage Hydrograph TW Check=0\n"
        "Flow Hydrograph QMult= 0.5 \n"
        "Flow Hydrograph Slope= 0.005 \n"
        "DSS Path=\n"
        "Use DSS=False\n"
        "Use Fixed Start Time=False\n"
        "Fixed Start Date/Time=,\n"
        "Is Critical Boundary=False\n"
        "Critical Boundary Flow=\n"
    )
    return _write_unsteady(tmp_path / "project.u01", body)


@pytest.fixture
def unsteady_with_existing_normal_depth_flag_one(tmp_path):
    """Normal Depth block with `Friction Slope=0.003,1` (critical fallback ON)."""
    body = (
        "Flow Title=Existing ND with flag=1\n"
        "Boundary Location=                ,                ,        ,        ,                ,DS Channel      ,                ,DS Normal                       ,                                \n"
        "Friction Slope=0.003,1\n"
    )
    return _write_unsteady(tmp_path / "project.u01", body)


class TestRealisticFlowHydrographConversion:
    """Verify that converting a real-shape Flow Hydrograph block to Normal
    Depth strips every BC-type-specific line from the prior type."""

    def test_conversion_strips_all_flow_hydrograph_extras(
        self, realistic_flow_hydrograph_2d_block
    ):
        from ras_commander import RasUnsteady

        result = RasUnsteady.set_normal_depth_boundary(
            realistic_flow_hydrograph_2d_block,
            friction_slope=0.0003,
            area_2d="BaldEagleCr",
            bc_line="Upstream Inflow",
        )

        assert result["previous_bc_type"] == "Flow Hydrograph"
        assert result["new_friction_slope"] == 0.0003
        assert result["lines_inserted"] == 1
        # Lines stripped on conversion:
        #   Interval=                       (1)
        #   Flow Hydrograph= 3              (1)
        #   inline data (1 row, 3 values)   (1)
        #   Stage Hydrograph TW Check=0     (1)
        #   Flow Hydrograph QMult=          (1)
        #   Flow Hydrograph Slope=          (1)
        #   DSS Path=                       (1)
        #   Use DSS=False                   (1)
        #   Use Fixed Start Time=False      (1)
        #   Fixed Start Date/Time=,         (1)
        #   Is Critical Boundary=False      (1)
        #   Critical Boundary Flow=         (1)
        # Total = 12 lines removed.
        assert result["lines_removed"] == 12

        text = realistic_flow_hydrograph_2d_block.read_text(encoding="utf-8")
        # The block now contains ONLY Boundary Location + Friction Slope.
        assert "Friction Slope=0.0003" in text
        for orphaned_keyword in [
            "Flow Hydrograph=",
            "Flow Hydrograph Slope=",
            "Flow Hydrograph QMult=",
            "Stage Hydrograph TW Check=",
            "Use Fixed Start Time=",
            "Fixed Start Date/Time=",
            "Is Critical Boundary=",
            "Critical Boundary Flow=",
            "Interval=",
            "DSS Path=",
            "Use DSS=",
        ]:
            assert orphaned_keyword not in text, (
                f"{orphaned_keyword!r} should have been stripped on conversion "
                f"to Normal Depth but is still present"
            )


class TestFlagIntegerValuePreserved:
    """The flag VALUE (not just presence) must be preserved on in-place
    update. Calling without `use_critical_fallback` on an existing
    `Friction Slope=X,1` boundary must not silently clear the flag to 0."""

    def test_existing_flag_one_is_preserved_on_update(
        self, unsteady_with_existing_normal_depth_flag_one
    ):
        from ras_commander import RasUnsteady

        result = RasUnsteady.set_normal_depth_boundary(
            unsteady_with_existing_normal_depth_flag_one,
            friction_slope=0.001,
            area_2d="DS Channel",
            bc_line="DS Normal",
        )

        assert result["updated_in_place"] is True
        assert result["previous_friction_slope"] == 0.003
        assert result["new_friction_slope"] == 0.001
        # Flag value 1 from the original line must be preserved — NOT
        # silently reset to 0.
        assert result["flag"] == 1

        text = unsteady_with_existing_normal_depth_flag_one.read_text(
            encoding="utf-8"
        )
        assert "Friction Slope=0.001,1" in text
        assert "Friction Slope=0.001,0" not in text

    def test_existing_flag_zero_stays_zero_on_update(
        self, unsteady_with_existing_normal_depth
    ):
        """Original flag=0 → preserved as 0 (no spurious change)."""
        from ras_commander import RasUnsteady

        result = RasUnsteady.set_normal_depth_boundary(
            unsteady_with_existing_normal_depth,
            friction_slope=0.0005,
            area_2d="DS Channel",
            bc_line="DS Normal",
        )
        assert result["flag"] == 0
        text = unsteady_with_existing_normal_depth.read_text(encoding="utf-8")
        assert "Friction Slope=0.0005,0" in text


class TestNumpyScalarAcceptance:
    """`numbers.Real` validation must accept numpy scalars from DataFrame
    columns. Under NumPy 2.x, `np.float64` is no longer a subclass of
    `float`, so `isinstance(x, (int, float))` rejects the most natural
    call pattern (taking a slope value out of `boundaries_df` and passing
    it back in)."""

    def test_np_float64_is_accepted(self, unsteady_with_existing_normal_depth):
        import numpy as np
        from ras_commander import RasUnsteady

        slope = np.float64(0.0007)
        result = RasUnsteady.set_normal_depth_boundary(
            unsteady_with_existing_normal_depth,
            friction_slope=slope,
            area_2d="DS Channel",
            bc_line="DS Normal",
        )
        assert result["new_friction_slope"] == 0.0007

    def test_np_float32_is_accepted(self, unsteady_with_existing_normal_depth):
        import numpy as np
        from ras_commander import RasUnsteady

        slope = np.float32(0.0009)
        result = RasUnsteady.set_normal_depth_boundary(
            unsteady_with_existing_normal_depth,
            friction_slope=slope,
            area_2d="DS Channel",
            bc_line="DS Normal",
        )
        # np.float32 → float() may have small precision drift; just check it
        # converted and was written.
        assert abs(result["new_friction_slope"] - 0.0009) < 1e-7

    def test_bool_still_rejected(self, unsteady_with_existing_normal_depth):
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="must be a real number"):
            RasUnsteady.set_normal_depth_boundary(
                unsteady_with_existing_normal_depth,
                friction_slope=True,  # type: ignore[arg-type]
                area_2d="DS Channel",
                bc_line="DS Normal",
            )


class TestBoundariesDfSurfacesFrictionSlope:
    """`Friction Slope` must appear as a column in `boundaries_df` after
    the writer succeeds — this closes the AC partial on 'reflects the
    updated boundary type/value'."""

    @pytest.mark.slow
    def test_friction_slope_column_in_boundaries_df(self, tmp_path):
        """End-to-end: use Muncie's real .u01, set a slope, refresh
        boundaries_df, verify the Friction Slope column carries the value."""
        try:
            from ras_commander import RasExamples, RasUnsteady, RasPrj
            project = RasExamples.extract_project(
                "Muncie", output_path=tmp_path, suffix="_fs_df"
            )
        except Exception:
            pytest.skip("Muncie example project not available")
        if isinstance(project, list):
            project = project[0]

        prj_files = list(Path(project).glob("*.prj"))
        prj_files = [p for p in prj_files if not p.name.endswith(".rasprj.json")]
        if not prj_files:
            pytest.skip("No .prj file in Muncie")

        # Initialize a RasPrj for Muncie so we can refresh boundaries_df.
        ras_obj = RasPrj()
        try:
            ras_obj.initialize(prj_files[0].parent, "ras", suppress_logging=True)
        except Exception:
            pytest.skip("Could not initialize Muncie RasPrj")

        u_files = list(Path(project).glob("*.u01"))
        if not u_files:
            pytest.skip("No .u01 in Muncie")
        u_file = u_files[0]
        if "Friction Slope=" not in u_file.read_text(encoding="utf-8"):
            pytest.skip("Muncie u01 has no Friction Slope")

        result = RasUnsteady.set_normal_depth_boundary(
            u_file,
            friction_slope=0.001,
            river="White",
            reach="Muncie",
            station="237.6455",
            ras_object=ras_obj,
        )
        assert result["boundaries_df_refreshed"] is True

        df = ras_obj.boundaries_df
        assert "Friction Slope" in df.columns, (
            "Friction Slope must be parsed into boundaries_df after refresh "
            "(known_fields update in RasPrj._parse_boundary_condition)"
        )
        # The Normal Depth row in the DataFrame should carry the new value.
        nd_rows = df[df["bc_type"] == "Normal Depth"]
        assert not nd_rows.empty
        # Friction Slope column value will be a string like "0.001,0"; just
        # confirm the slope number is in there.
        slope_values = nd_rows["Friction Slope"].astype(str).tolist()
        assert any("0.001" in s for s in slope_values), (
            f"Expected '0.001' in Friction Slope column; got {slope_values}"
        )
