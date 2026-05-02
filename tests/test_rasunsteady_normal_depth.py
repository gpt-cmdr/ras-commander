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
        assert result["flag"] == 0
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
        assert ds_block_lines[1].startswith("Friction Slope=0.0003,0")
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

        text = unsteady_with_1d_flow_hydrograph.read_text(encoding="utf-8")
        assert "Flow Hydrograph=" not in text
        assert re.search(r"^Friction Slope=0\.001,0\s*$", text, re.MULTILINE)


# ---------------------------------------------------------------------------
# Acceptance: updating an existing Normal Depth slope (in-place path)
# ---------------------------------------------------------------------------


class TestSetNormalDepthBoundaryUpdate:
    def test_updates_existing_friction_slope_in_place(
        self, unsteady_with_existing_normal_depth
    ):
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

        text = unsteady_with_existing_normal_depth.read_text(encoding="utf-8")
        # The slope was overwritten and the second (unrelated) boundary still has
        # its Precipitation Hydrograph data intact.
        assert "Friction Slope=0.0005,0" in text
        assert "Friction Slope=0.003,0" not in text
        assert "Precipitation Hydrograph= 1" in text
        assert "    0.10" in text

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

        with pytest.raises(ValueError, match="must be a number"):
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
            )

    def test_missing_unsteady_file_raises(self, tmp_path):
        from ras_commander import RasUnsteady

        with pytest.raises(FileNotFoundError):
            RasUnsteady.set_normal_depth_boundary(
                tmp_path / "missing.u01",
                friction_slope=0.001,
                area_2d="DS Channel",
            )


# ---------------------------------------------------------------------------
# 2D BC line selectors
# ---------------------------------------------------------------------------


class TestSetNormalDepthBoundary2DSelectors:
    def test_area_only_selector_matches_when_unique(self, tmp_path):
        from ras_commander import RasUnsteady

        body = (
            "Flow Title=Area Only Match\n"
            "Boundary Location=                ,                ,        ,        ,                ,area2           ,                ,                                ,                                \n"
            "Flow Hydrograph= 2 \n"
            "  100.00  120.00\n"
        )
        f = _write_unsteady(tmp_path / "project.u01", body)

        result = RasUnsteady.set_normal_depth_boundary(
            f, friction_slope=0.0007, area_2d="area2"
        )
        assert result["new_friction_slope"] == 0.0007
        text = f.read_text(encoding="utf-8")
        assert "Friction Slope=0.0007,0" in text
        assert "Flow Hydrograph=" not in text
