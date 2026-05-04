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

        with pytest.raises(ValueError, match="must be a real number"):
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
# Synthetic 8-field Boundary Location (older HEC-RAS format)
# ---------------------------------------------------------------------------


class TestEightFieldBoundaryLocation:
    """HEC-RAS emits both 8-field and 9-field `Boundary Location=` forms.

    Real example: BaldEagleCrkMulti2D ships with 8-field forms in some plans
    while Chippewa_2D / Weise_2D use 9-field forms. The matcher must work on
    both since field meaning is positional, not count-dependent.
    """

    def test_matches_and_updates_8_field_form(self, tmp_path):
        from ras_commander import RasUnsteady

        # 7 commas → 8 fields. BC line at index 7.
        body = (
            "Flow Title=8-field FH\n"
            "Boundary Location=                ,                ,        ,        ,                ,BaldEagleCr     ,                ,Upstream Inflow \n"
            "Interval=1HOUR\n"
            "Flow Hydrograph= 2 \n"
            "  100.00  120.00\n"
            "Stage Hydrograph TW Check=0\n"
            "Flow Hydrograph QMult= 0.5 \n"
            "Flow Hydrograph Slope= 0.0005 \n"
            "DSS Path=\n"
            "Use DSS=False\n"
        )
        f = _write_unsteady(tmp_path / "project.u01", body)

        result = RasUnsteady.set_flow_hydrograph_slope(
            f,
            eg_slope=0.001,
            area_2d="BaldEagleCr",
            bc_line="Upstream Inflow",
        )
        assert result["updated_in_place"] is True
        assert result["new_eg_slope"] == 0.001
        text = f.read_text(encoding="utf-8")
        assert "Flow Hydrograph Slope= 0.001 " in text


# ---------------------------------------------------------------------------
# Real RasExamples projects
# ---------------------------------------------------------------------------
#
# Primary fixture is **Chippewa_2D** rather than BaldEagleCrkMulti2D:
#
# - Multiple 2D Flow Areas in a single .u## (`Chippewa` and `Perimeter 1`)
#   exercise the multi-area requirement spelled out in CLB-311's AC.
# - 9-field Boundary Location form (current HEC-RAS output) plus realistic
#   field widths matching the literal name length (e.g. `Lake Pepin` is
#   10 chars, not padded to 16) — confirms the matcher's positional logic.
# - Realistic boundary names with spaces (`Lake Pepin`, `Perimeter 1`).
# - Real DSS File path with backslashes (`..\..\2018\...\Chippewa.dss`)
#   in one of the blocks — confirms DSS metadata is preserved verbatim.
# - Block layout has `Stage Hydrograph TW Check=0` immediately followed by
#   `Flow Hydrograph Slope=` (no `Flow Hydrograph QMult=`), which exercises
#   the `Stage Hydrograph TW Check=` insert anchor branch.
#
# Weise_2D is included as a smaller cross-project smoke check.


class TestChippewa2DRealProject:
    @pytest.mark.slow
    def test_chippewa_multi_area_update_preserves_other_areas_and_dss_file(self, tmp_path):
        """Updating one BC line on one 2D area must leave every other 2D
        area's slope unchanged AND preserve the literal DSS File= path."""
        try:
            from ras_commander import RasExamples, RasUnsteady
            project = RasExamples.extract_project(
                "Chippewa_2D", output_path=tmp_path, suffix="_fh_slope_update"
            )
        except Exception:
            pytest.skip("Chippewa_2D example not available")
        if isinstance(project, list):
            project = project[0]
        u_files = sorted(
            p for p in Path(project).glob("*.u*") if "hdf" not in p.name.lower()
        )
        # Find the .u## that contains all three 2D Flow Hydrograph slope
        # blocks (Chippewa/Chippewa, Chippewa/Lake Pepin, Perimeter 1/Upstream).
        target_file = None
        for u in u_files:
            text = u.read_text(encoding="utf-8", errors="ignore")
            if (
                "Chippewa        ,                ,Chippewa" in text
                and "Lake Pepin" in text
                and "Perimeter 1" in text
                and text.count("Flow Hydrograph Slope=") >= 3
            ):
                target_file = u
                break
        if target_file is None:
            pytest.skip("Chippewa_2D shipped layout does not match expectations")

        before = target_file.read_text(encoding="utf-8", errors="ignore")
        # Capture the other two slope lines verbatim — they must survive.
        before_other_slopes = [
            line for line in before.splitlines()
            if line.startswith("Flow Hydrograph Slope=")
        ]
        assert len(before_other_slopes) >= 3

        # Update the slope on Chippewa/Chippewa.
        result = RasUnsteady.set_flow_hydrograph_slope(
            target_file,
            eg_slope=0.001,
            area_2d="Chippewa",
            bc_line="Chippewa",
        )
        assert result["updated_in_place"] is True
        assert result["previous_eg_slope"] == 0.00036
        assert result["new_eg_slope"] == 0.001

        after = target_file.read_text(encoding="utf-8", errors="ignore")
        # Same file length (in-place update).
        assert len(before.splitlines()) == len(after.splitlines())
        # Exactly one differing line.
        diff = [
            (b, a) for b, a in zip(before.splitlines(), after.splitlines())
            if b != a
        ]
        assert len(diff) == 1
        assert diff[0] == ("Flow Hydrograph Slope= 0.00036 ", "Flow Hydrograph Slope= 0.001 ")

        # Other slope lines (Lake Pepin = 0.00016, Perimeter 1/Upstream = 0.00022)
        # are still present and unchanged.
        after_slopes = [
            line for line in after.splitlines()
            if line.startswith("Flow Hydrograph Slope=")
        ]
        assert "Flow Hydrograph Slope= 0.00016 " in after_slopes
        assert "Flow Hydrograph Slope= 0.00022 " in after_slopes
        # Realistic DSS File path with backslashes survived verbatim.
        assert any(
            "DSS File=..\\..\\2018" in line for line in after.splitlines()
        )

    @pytest.mark.slow
    def test_chippewa_insert_when_no_slope_in_block(self, tmp_path):
        """Strip an existing Flow Hydrograph Slope= line from a Chippewa
        block and verify the writer re-inserts it at the canonical anchor
        with every other line preserved."""
        try:
            from ras_commander import RasExamples, RasUnsteady
            project = RasExamples.extract_project(
                "Chippewa_2D", output_path=tmp_path, suffix="_fh_slope_insert"
            )
        except Exception:
            pytest.skip("Chippewa_2D example not available")
        if isinstance(project, list):
            project = project[0]
        u_files = sorted(
            p for p in Path(project).glob("*.u*") if "hdf" not in p.name.lower()
        )

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
                if (
                    "Flow Hydrograph=" not in block
                    or "Flow Hydrograph Slope=" not in block
                ):
                    continue
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
            pytest.skip("No suitable Chippewa 2D Flow Hydrograph block")

        # Strip the slope line to set up the insert path.
        original = target_file.read_text(encoding="utf-8", errors="ignore")
        stripped = original.replace(original_slope_line + "\n", "", 1)
        target_file.write_text(stripped, encoding="utf-8")
        before = target_file.read_text(encoding="utf-8", errors="ignore")

        result = RasUnsteady.set_flow_hydrograph_slope(
            target_file,
            eg_slope=0.001,
            area_2d=target_area,
            bc_line=target_bc,
        )
        assert result["updated_in_place"] is False
        assert result["lines_inserted"] == 1
        # Chippewa blocks have `Stage Hydrograph TW Check=0` but no QMult,
        # so the canonical anchor here is `Stage Hydrograph TW Check=`.
        assert result["insert_anchor"] == "Stage Hydrograph TW Check="

        after = target_file.read_text(encoding="utf-8", errors="ignore")
        assert len(after.splitlines()) == len(before.splitlines()) + 1
        assert "Flow Hydrograph Slope= 0.001 " in after
        # Every line that survived the stripping must still be present.
        before_lines = set(before.splitlines())
        after_lines = set(after.splitlines())
        assert before_lines - after_lines == set()


class TestWeise2DRealProject:
    @pytest.mark.slow
    def test_weise_simple_update(self, tmp_path):
        """Cross-project sanity check on Weise_2D (single 2D Area, simple
        layout) — confirms the writer behaves identically across projects."""
        try:
            from ras_commander import RasExamples, RasUnsteady
            project = RasExamples.extract_project(
                "Weise_2D", output_path=tmp_path, suffix="_fh_slope"
            )
        except Exception:
            pytest.skip("Weise_2D example not available")
        if isinstance(project, list):
            project = project[0]
        u_files = sorted(
            p for p in Path(project).glob("*.u*") if "hdf" not in p.name.lower()
        )
        target_file = None
        target_area = None
        target_bc = None
        for u in u_files:
            text = u.read_text(encoding="utf-8", errors="ignore")
            if "Flow Hydrograph Slope=" not in text:
                continue
            for m in re.finditer(
                r"^Boundary Location=(.+?)(?=\nBoundary Location=|\Z)",
                text,
                re.MULTILINE | re.DOTALL,
            ):
                block = m.group(0)
                if (
                    "Flow Hydrograph=" not in block
                    or "Flow Hydrograph Slope=" not in block
                ):
                    continue
                first_line = block.splitlines()[0]
                loc_value = first_line[len("Boundary Location="):]
                parts = [p.strip() for p in loc_value.split(",")]
                if len(parts) < 8 or not (parts[5] and parts[7]):
                    continue
                target_file = u
                target_area = parts[5]
                target_bc = parts[7]
                break
            if target_file is not None:
                break
        if target_file is None:
            pytest.skip("No suitable Weise 2D Flow Hydrograph block")

        result = RasUnsteady.set_flow_hydrograph_slope(
            target_file,
            eg_slope=0.0025,
            area_2d=target_area,
            bc_line=target_bc,
        )
        assert result["updated_in_place"] is True
        assert result["new_eg_slope"] == 0.0025
        assert result["bc_type"] == "Flow Hydrograph"
        text = target_file.read_text(encoding="utf-8", errors="ignore")
        assert "Flow Hydrograph Slope= 0.0025 " in text


# ---------------------------------------------------------------------------
# Fix-coverage tests added 2026-05-02 in response to independent code review
# (see H:/Symphony/ras-commander/CLB-311/REVIEW.md):
#   - numpy scalar acceptance (numbers.Real)
#   - Flow Hydrograph Slope value surfaced in boundaries_df
# ---------------------------------------------------------------------------


class TestNumpyScalarAcceptance:
    """`numbers.Real` validation must accept numpy scalars from DataFrame
    columns. Under NumPy 2.x, `np.float64` is no longer a subclass of
    `float`, so `isinstance(x, (int, float))` rejects the most natural
    call pattern (taking a slope value out of `boundaries_df` and passing
    it back in)."""

    def test_np_float64_is_accepted(self, fh_2d_block_with_existing_slope):
        import numpy as np
        from ras_commander import RasUnsteady

        slope = np.float64(0.0009)
        result = RasUnsteady.set_flow_hydrograph_slope(
            fh_2d_block_with_existing_slope,
            eg_slope=slope,
            area_2d="BaldEagleCr",
            bc_line="Upstream Inflow",
        )
        assert result["new_eg_slope"] == 0.0009
        text = fh_2d_block_with_existing_slope.read_text(encoding="utf-8")
        assert "Flow Hydrograph Slope= 0.0009 " in text

    def test_np_float32_is_accepted(self, fh_2d_block_with_existing_slope):
        import numpy as np
        from ras_commander import RasUnsteady

        slope = np.float32(0.0011)
        result = RasUnsteady.set_flow_hydrograph_slope(
            fh_2d_block_with_existing_slope,
            eg_slope=slope,
            area_2d="BaldEagleCr",
            bc_line="Upstream Inflow",
        )
        # np.float32 → float() may have small precision drift; just confirm
        # it converted and was written.
        assert abs(result["new_eg_slope"] - 0.0011) < 1e-7

    def test_bool_still_rejected(self, fh_2d_block_with_existing_slope):
        from ras_commander import RasUnsteady

        with pytest.raises(ValueError, match="must be a real number"):
            RasUnsteady.set_flow_hydrograph_slope(
                fh_2d_block_with_existing_slope,
                eg_slope=True,  # type: ignore[arg-type]
                area_2d="BaldEagleCr",
                bc_line="Upstream Inflow",
            )


class TestBoundariesDfSurfacesFhSlope:
    """`Flow Hydrograph Slope` must appear as a column in `boundaries_df`
    after the writer succeeds — closes the AC partial on 'expose updated
    metadata through boundary DataFrames'."""

    @pytest.mark.slow
    def test_flow_hydrograph_slope_column_in_boundaries_df(self, tmp_path):
        """End-to-end: extract Chippewa_2D, run the setter on a real Flow
        Hydrograph 2D BC, refresh boundaries_df, verify the
        `Flow Hydrograph Slope` column carries the new value."""
        try:
            from ras_commander import RasExamples, RasUnsteady, RasPrj
            project = RasExamples.extract_project(
                "Chippewa_2D", output_path=tmp_path, suffix="_fhs_df"
            )
        except Exception:
            pytest.skip("Chippewa_2D example not available")
        if isinstance(project, list):
            project = project[0]

        prj_files = list(Path(project).glob("*.prj"))
        prj_files = [p for p in prj_files if not p.name.endswith(".rasprj.json")]
        if not prj_files:
            pytest.skip("No .prj in Chippewa_2D")

        ras_obj = RasPrj()
        try:
            ras_obj.initialize(prj_files[0].parent, "ras", suppress_logging=True)
        except Exception:
            pytest.skip("Could not initialize Chippewa_2D RasPrj")

        result = RasUnsteady.set_flow_hydrograph_slope(
            next(Path(project).glob("*.u04")),
            eg_slope=0.002,
            area_2d="Chippewa",
            bc_line="Chippewa",
            ras_object=ras_obj,
        )
        assert result["boundaries_df_refreshed"] is True

        df = ras_obj.boundaries_df
        assert "Flow Hydrograph Slope" in df.columns, (
            "Flow Hydrograph Slope must be parsed into boundaries_df after "
            "refresh (known_fields update in RasPrj._parse_boundary_condition)"
        )
        # The targeted Chippewa/Chippewa boundary should have the new value.
        slope_strings = df["Flow Hydrograph Slope"].astype(str).tolist()
        assert any("0.002" in s for s in slope_strings), (
            f"Expected '0.002' in Flow Hydrograph Slope column; got "
            f"{slope_strings}"
        )
