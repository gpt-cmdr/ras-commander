"""
Tests for RasUnsteady.set_flow_hydrograph_slope().

Validates that:

1. Updating an existing ``Flow Hydrograph Slope=`` line on a 2D BC line
   overwrites the value in place and leaves every other line in the block
   byte-for-byte unchanged (DSS path/file/use, Interval, Flow Hydrograph
   count, inline data, sibling boundary blocks).
2. Adding a slope to a Flow Hydrograph block that has none places the new
   line in the canonical insertion position observed in HEC-RAS-emitted
   output (after ``Flow Hydrograph QMult=`` if present, else after
   ``Stage Hydrograph TW Check=``, else before the first DSS metadata line).
3. The setter refuses to operate on non-Flow-Hydrograph blocks (Normal
   Depth, Rating Curve, etc.) since the slope is meaningless there.
4. The setter validates slope range and selectors consistently with
   ``set_normal_depth_boundary``.
5. End-to-end behavior is correct against real RasExamples projects
   (BaldEagleCrkMulti2D), both for an existing-slope plan and a no-slope
   plan.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def _write_unsteady(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fh_2d_block_with_existing_slope(tmp_path):
    """A multi-boundary file: target 2D Flow Hydrograph block has slope already.

    Mirrors the BaldEagleCrkMulti2D BaldEagleDamBrk.u02 layout, with two
    extra unrelated boundary blocks so we can assert non-targets are
    untouched.
    """
    body = (
        # Unrelated 1D Flow Hydrograph block (different river/reach/station).
        "Flow Title=Multi-block FH\n"
        "Program Version=6.60\n"
        "Use Restart= 0 \n"
        "Boundary Location=White           ,Muncie          ,15696.24,        ,                ,                ,                ,                                ,                                \n"
        "Interval=1HOUR\n"
        "Flow Hydrograph= 2 \n"
        "  100.00  150.00\n"
        "Stage Hydrograph TW Check=0\n"
        "Flow Hydrograph QMult= 1.0 \n"
        "Flow Hydrograph Slope= 0.002 \n"
        "DSS Path=\n"
        "Use DSS=False\n"
        # Target 2D Flow Hydrograph block, pre-populated with a slope value.
        "Boundary Location=                ,                ,        ,        ,                ,BaldEagleCr     ,                ,Upstream Inflow                 ,                                \n"
        "Interval=1HOUR\n"
        "Flow Hydrograph= 2 \n"
        "  500.00  600.00\n"
        "Stage Hydrograph TW Check=0\n"
        "Flow Hydrograph QMult= 0.5 \n"
        "Flow Hydrograph Slope= 0.0005 \n"
        "DSS Path=\n"
        "Use DSS=False\n"
        # Unrelated 2D Normal Depth block.
        "Boundary Location=                ,                ,        ,        ,                ,BaldEagleCr     ,                ,DSNormalDepth                   ,                                \n"
        "Friction Slope=0.0003\n"
    )
    return _write_unsteady(tmp_path / "project.u01", body)


@pytest.fixture
def fh_2d_block_without_slope_with_qmult(tmp_path):
    """Flow Hydrograph block has QMult but no Flow Hydrograph Slope= yet."""
    body = (
        "Flow Title=No slope yet\n"
        "Boundary Location=                ,                ,        ,        ,                ,Upper 2D Area   ,                ,Upstream Q                      ,                                \n"
        "Interval=1HOUR\n"
        "Flow Hydrograph= 2 \n"
        "  720.00  734.88\n"
        "Stage Hydrograph TW Check=0\n"
        "Flow Hydrograph QMult= 1.0 \n"
        "DSS Path=\n"
        "Use DSS=False\n"
    )
    return _write_unsteady(tmp_path / "project.u01", body)


@pytest.fixture
def fh_block_minimal(tmp_path):
    """Flow Hydrograph block with no QMult, no TW Check, but has DSS Path=."""
    body = (
        "Flow Title=Minimal FH\n"
        "Boundary Location=                ,                ,        ,        ,                ,Area2           ,                ,Q in                            ,                                \n"
        "Interval=1HOUR\n"
        "Flow Hydrograph= 2 \n"
        "  100.00  120.00\n"
        "DSS Path=\n"
        "Use DSS=False\n"
    )
    return _write_unsteady(tmp_path / "project.u01", body)


@pytest.fixture
def normal_depth_only_block(tmp_path):
    """Block is Normal Depth, not Flow Hydrograph — setter should refuse."""
    body = (
        "Flow Title=ND only\n"
        "Boundary Location=                ,                ,        ,        ,                ,BaldEagleCr     ,                ,DSNormalDepth                   ,                                \n"
        "Friction Slope=0.0003\n"
    )
    return _write_unsteady(tmp_path / "project.u01", body)


# ---------------------------------------------------------------------------
# Update path
# ---------------------------------------------------------------------------


class TestUpdateExistingSlope:
    def test_2d_existing_slope_overwritten_in_place(self, fh_2d_block_with_existing_slope):
        from ras_commander import RasUnsteady

        before_text = fh_2d_block_with_existing_slope.read_text(encoding="utf-8")

        result = RasUnsteady.set_flow_hydrograph_slope(
            fh_2d_block_with_existing_slope,
            eg_slope=0.001,
            area_2d="BaldEagleCr",
            bc_line="Upstream Inflow",
        )

        assert result["bc_type"] == "Flow Hydrograph"
        assert result["previous_eg_slope"] == 0.0005
        assert result["new_eg_slope"] == 0.001
        assert result["updated_in_place"] is True
        assert result["lines_inserted"] == 0
        assert result["insert_anchor"] is None

        after_text = fh_2d_block_with_existing_slope.read_text(encoding="utf-8")
        # Exactly one substitution happened — the only difference between
        # before and after is the slope line value.
        diff = [
            (b, a) for b, a in zip(before_text.splitlines(), after_text.splitlines())
            if b != a
        ]
        assert diff == [
            ("Flow Hydrograph Slope= 0.0005 ", "Flow Hydrograph Slope= 0.001 ")
        ]
        # Non-target boundaries are untouched.
        assert "Friction Slope=0.0003" in after_text  # Normal Depth block
        assert "Flow Hydrograph Slope= 0.002 " in after_text  # 1D FH block
        # DSS lines and Flow Hydrograph count survive unchanged in the target.
        assert after_text.count("Flow Hydrograph= 2 ") == 2
        assert after_text.count("DSS Path=") == 2
        assert after_text.count("Use DSS=False") == 2


# ---------------------------------------------------------------------------
# Insert path
# ---------------------------------------------------------------------------


class TestInsertNewSlope:
    def test_inserts_after_qmult_when_present(self, fh_2d_block_without_slope_with_qmult):
        from ras_commander import RasUnsteady

        result = RasUnsteady.set_flow_hydrograph_slope(
            fh_2d_block_without_slope_with_qmult,
            eg_slope=0.0007,
            area_2d="Upper 2D Area",
            bc_line="Upstream Q",
        )

        assert result["updated_in_place"] is False
        assert result["lines_inserted"] == 1
        assert result["insert_anchor"] == "Flow Hydrograph QMult="
        assert result["previous_eg_slope"] is None
        assert result["new_eg_slope"] == 0.0007

        text = fh_2d_block_without_slope_with_qmult.read_text(encoding="utf-8")
        # Slope line appears immediately after QMult and immediately before
        # the first DSS metadata line.
        lines = text.splitlines()
        qmult_i = lines.index("Flow Hydrograph QMult= 1.0 ")
        slope_i = lines.index("Flow Hydrograph Slope= 0.0007 ")
        dss_i = lines.index("DSS Path=")
        assert qmult_i < slope_i < dss_i
        assert slope_i == qmult_i + 1

    def test_inserts_before_dss_when_no_qmult_or_tw_check(self, fh_block_minimal):
        from ras_commander import RasUnsteady

        result = RasUnsteady.set_flow_hydrograph_slope(
            fh_block_minimal,
            eg_slope=0.0009,
            area_2d="Area2",
            bc_line="Q in",
        )

        assert result["lines_inserted"] == 1
        assert result["insert_anchor"] == "DSS Path="

        text = fh_block_minimal.read_text(encoding="utf-8")
        # Slope line comes immediately before DSS Path=.
        lines = text.splitlines()
        slope_i = lines.index("Flow Hydrograph Slope= 0.0009 ")
        dss_i = lines.index("DSS Path=")
        assert slope_i + 1 == dss_i


# ---------------------------------------------------------------------------
# Type check
# ---------------------------------------------------------------------------


class TestRefusesNonFlowHydrograph:
    def test_normal_depth_block_raises(self, normal_depth_only_block):
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="not a Flow Hydrograph"):
            RasUnsteady.set_flow_hydrograph_slope(
                normal_depth_only_block,
                eg_slope=0.001,
                area_2d="BaldEagleCr",
                bc_line="DSNormalDepth",
            )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_rejects_zero_slope(self, fh_2d_block_with_existing_slope):
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="outside the supported range"):
            RasUnsteady.set_flow_hydrograph_slope(
                fh_2d_block_with_existing_slope,
                eg_slope=0.0,
                area_2d="BaldEagleCr",
                bc_line="Upstream Inflow",
            )

    def test_rejects_non_numeric(self, fh_2d_block_with_existing_slope):
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="must be a number"):
            RasUnsteady.set_flow_hydrograph_slope(
                fh_2d_block_with_existing_slope,
                eg_slope="0.001",  # type: ignore[arg-type]
                area_2d="BaldEagleCr",
                bc_line="Upstream Inflow",
            )

    def test_rejects_partial_1d_selector(self, fh_2d_block_with_existing_slope):
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="1D selector requires"):
            RasUnsteady.set_flow_hydrograph_slope(
                fh_2d_block_with_existing_slope,
                eg_slope=0.001,
                river="White",
                reach="Muncie",
                # station missing
            )

    def test_rejects_2d_selector_without_bc_line(self, fh_2d_block_with_existing_slope):
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="2D selector requires both area_2d and bc_line"):
            RasUnsteady.set_flow_hydrograph_slope(
                fh_2d_block_with_existing_slope,
                eg_slope=0.001,
                area_2d="BaldEagleCr",
                # bc_line missing
            )

    def test_rejects_mixed_selectors(self, fh_2d_block_with_existing_slope):
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="exactly one selector group"):
            RasUnsteady.set_flow_hydrograph_slope(
                fh_2d_block_with_existing_slope,
                eg_slope=0.001,
                river="White",
                reach="Muncie",
                station="15696.24",
                area_2d="BaldEagleCr",
                bc_line="Upstream Inflow",
            )

    def test_rejects_no_selector(self, fh_2d_block_with_existing_slope):
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="exactly one selector group"):
            RasUnsteady.set_flow_hydrograph_slope(
                fh_2d_block_with_existing_slope, eg_slope=0.001
            )

    def test_unknown_target_raises(self, fh_2d_block_with_existing_slope):
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="No boundary matched"):
            RasUnsteady.set_flow_hydrograph_slope(
                fh_2d_block_with_existing_slope,
                eg_slope=0.001,
                area_2d="Nonexistent",
                bc_line="Phantom",
            )

    def test_missing_unsteady_file_raises(self, tmp_path):
        from ras_commander import RasUnsteady

        with pytest.raises(FileNotFoundError):
            RasUnsteady.set_flow_hydrograph_slope(
                tmp_path / "missing.u01",
                eg_slope=0.001,
                area_2d="X",
                bc_line="Y",
            )


# ---------------------------------------------------------------------------
# Real RasExamples projects
# ---------------------------------------------------------------------------


class TestRealProjects:
    @pytest.mark.slow
    def test_baldeagle_existing_slope_update_round_trip(self, tmp_path):
        """Update an existing `Flow Hydrograph Slope=` on a 2D BC line and
        verify nothing else in the surrounding block changed."""
        try:
            from ras_commander import RasExamples, RasUnsteady
            project = RasExamples.extract_project(
                "BaldEagleCrkMulti2D", output_path=tmp_path, suffix="_fh_slope_update"
            )
        except Exception:
            pytest.skip("BaldEagleCrkMulti2D example not available")
        if isinstance(project, list):
            project = project[0]
        u_files = sorted(p for p in Path(project).glob("*.u*") if "hdf" not in p.name.lower())
        # Find a (.u##, area, bc_line) where Flow Hydrograph Slope= already
        # exists right after a Flow Hydrograph block.
        target_file = None
        target_area = None
        target_bc = None
        slope_pattern = re.compile(
            r"^Boundary Location=(.+?)\nInterval=.+?\nFlow Hydrograph=.+?(?:\n.*)*?\nFlow Hydrograph Slope=\s*([\d.]+)",
            re.MULTILINE,
        )
        for u in u_files:
            text = u.read_text(encoding="utf-8", errors="ignore")
            m = slope_pattern.search(text)
            if not m:
                continue
            parts = [p.strip() for p in m.group(1).split(",")]
            if len(parts) >= 8 and parts[5] and parts[7]:
                target_file, target_area, target_bc = u, parts[5], parts[7]
                break
        if target_file is None:
            pytest.skip("No 2D Flow Hydrograph with existing slope found")

        before = target_file.read_text(encoding="utf-8", errors="ignore")
        result = RasUnsteady.set_flow_hydrograph_slope(
            target_file,
            eg_slope=0.0009,
            area_2d=target_area,
            bc_line=target_bc,
        )
        assert result["updated_in_place"] is True
        assert result["new_eg_slope"] == 0.0009

        after = target_file.read_text(encoding="utf-8", errors="ignore")
        # The only differences must be the changed slope line.
        diff = [
            (b, a) for b, a in zip(before.splitlines(), after.splitlines())
            if b != a
        ]
        assert len(diff) == 1
        assert diff[0][1].startswith("Flow Hydrograph Slope=")
        assert "0.0009" in diff[0][1]
        # Same file length (in-place update).
        assert len(before.splitlines()) == len(after.splitlines())

    @pytest.mark.slow
    def test_baldeagle_insert_when_no_slope_in_block(self, tmp_path):
        """Insert a slope into a Flow Hydrograph block that lacks one.

        Every BaldEagle 2D Flow Hydrograph block in the shipped dataset
        already has a slope line, so this test deterministically constructs
        a no-slope variant: extract BaldEagleCrkMulti2D, pick a 2D Flow
        Hydrograph block, strip its `Flow Hydrograph Slope=` line in place,
        and verify the writer re-inserts at the canonical anchor without
        touching any other line.
        """
        try:
            from ras_commander import RasExamples, RasUnsteady
            project = RasExamples.extract_project(
                "BaldEagleCrkMulti2D", output_path=tmp_path, suffix="_fh_slope_insert"
            )
        except Exception:
            pytest.skip("BaldEagleCrkMulti2D example not available")
        if isinstance(project, list):
            project = project[0]
        u_files = sorted(
            p for p in Path(project).glob("*.u*") if "hdf" not in p.name.lower()
        )

        # Find a 2D Flow Hydrograph block that already has a slope line.
        target_file = None
        target_area = None
        target_bc = None
        original_slope_line = None
        for u in u_files:
            text = u.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(
                r"^Boundary Location=(.+?)(?=\nBoundary Location=|\Z)",
                text,
                re.MULTILINE | re.DOTALL,
            ):
                block = m.group(0)
                if "Flow Hydrograph=" not in block:
                    continue
                if "Flow Hydrograph Slope=" not in block:
                    continue
                # Parse only the first (location) line — `m.group(1)` spans
                # the whole block under DOTALL.
                first_line = block.splitlines()[0]
                loc_value = first_line[len("Boundary Location="):]
                parts = [p.strip() for p in loc_value.split(",")]
                if len(parts) < 8 or not (parts[5] and parts[7]):
                    continue
                target_file = u
                target_area = parts[5]
                target_bc = parts[7]
                original_slope_line = next(
                    line for line in block.splitlines()
                    if line.startswith("Flow Hydrograph Slope=")
                )
                break
            if target_file is not None:
                break
        if target_file is None:
            pytest.skip("No 2D Flow Hydrograph with slope found in BaldEagle")

        # Strip the slope line so we can validate the insert path.
        original = target_file.read_text(encoding="utf-8", errors="ignore")
        stripped = original.replace(original_slope_line + "\n", "", 1)
        target_file.write_text(stripped, encoding="utf-8")

        before = target_file.read_text(encoding="utf-8", errors="ignore")
        assert "Flow Hydrograph Slope=" not in before  # sanity

        result = RasUnsteady.set_flow_hydrograph_slope(
            target_file,
            eg_slope=0.0011,
            area_2d=target_area,
            bc_line=target_bc,
        )
        assert result["updated_in_place"] is False
        assert result["lines_inserted"] == 1
        assert result["new_eg_slope"] == 0.0011
        assert result["insert_anchor"] in {
            "Flow Hydrograph QMult=",
            "Stage Hydrograph TW Check=",
            "DSS Path=",
            "DSS File=",
            "Use DSS=",
            "<inline-data-tail>",
        }

        after = target_file.read_text(encoding="utf-8", errors="ignore")
        assert len(after.splitlines()) == len(before.splitlines()) + 1
        assert "Flow Hydrograph Slope= 0.0011 " in after
        # Every line that was in the stripped file must still be there.
        before_lines = set(before.splitlines())
        after_lines = set(after.splitlines())
        assert before_lines - after_lines == set()
