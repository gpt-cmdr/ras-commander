"""
Tests for GeomBcLines: 2D BC line authoring in HEC-RAS .g## files.

Covers:

- `add_bc_lines`: insert one or more BC lines, with validation and
  upsert semantics.
- `delete_bc_line`: remove a BC line by name.
- `rename_bc_line`: change a BC line's name without disturbing its
  geometry or position.
- Real RasExamples round-trip against `Chippewa_2D` to confirm the
  emitted text matches HEC-RAS-emitted format byte-for-byte (modulo
  numerical formatting).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import numpy as np
import pytest


def _write_geom(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


# A minimal but realistic .g## skeleton with one 2D Flow Area
# (Perimeter 1) and one existing BC line (Existing). Used as the baseline
# for synthetic tests.
_SKELETON = (
    "Geom Title=Test geom\n"
    "Program Version=6.60\n"
    "Storage Area=Perimeter 1     ,,\n"
    "Storage Area Surface Line= 4 \n"
    "        0       0       1000    0       1000    1000    0       1000\n"
    "Storage Area 2D Points= 4 \n"
    "        0       0       1000    0       1000    1000    0       1000\n"
    "BC Line Name=Existing                                \n"
    "BC Line Storage Area=Perimeter 1     \n"
    "BC Line Start Position= 100 , 100 \n"
    "BC Line Middle Position= 100 , 100 \n"
    "BC Line End Position= 200 , 100 \n"
    "BC Line Arc= 2 \n"
    "             100             100             200             100\n"
    "BC Line Text Position= 1.79769313486232E+308 , 1.79769313486232E+308 \n"
    "LCMann Time=Dec/30/1899 00:00:00\n"
    "LCMann Region Time=Dec/30/1899 00:00:00\n"
)


@pytest.fixture
def skeleton_geom(tmp_path):
    return _write_geom(tmp_path / "project.g01", _SKELETON)


# ---------------------------------------------------------------------------
# add_bc_lines
# ---------------------------------------------------------------------------


class TestAddBcLines:
    def test_add_single_bc_line(self, skeleton_geom):
        from ras_commander import GeomBcLines

        result = GeomBcLines.add_bc_lines(
            skeleton_geom,
            lines=[{
                "name": "DSNormalDepth",
                "storage_area": "Perimeter 1",
                "coordinates": [(500, 100), (700, 100), (900, 100)],
            }],
        )

        assert result["inserted"] == ["DSNormalDepth"]
        assert result["replaced"] == []
        assert Path(result["backup_path"]).exists()

        text = skeleton_geom.read_text(encoding="utf-8")
        # New block emitted with HEC-RAS-style padded names.
        assert "BC Line Name=DSNormalDepth" in text
        # Storage area name padded to 16 chars.
        assert "BC Line Storage Area=Perimeter 1     " in text
        # Arc count and the canonical sentinel text position.
        assert "BC Line Arc= 3 " in text
        assert (
            "BC Line Text Position= 1.79769313486232E+308 , "
            "1.79769313486232E+308 " in text
        )
        # Coordinate block: 4 values per line, 16-char fields.
        assert re.search(
            r"^\s+500\s+100\s+700\s+100\s*$", text, re.MULTILINE
        )
        # Existing block survives unchanged.
        assert "BC Line Name=Existing" in text

    def test_added_block_groups_with_existing_bc_lines(self, skeleton_geom):
        """New BC line is inserted after the LAST `BC Line Text Position=`
        so all BC lines stay contiguous in the file (matches HEC-RAS
        layout)."""
        from ras_commander import GeomBcLines

        GeomBcLines.add_bc_lines(
            skeleton_geom,
            lines=[{
                "name": "NewBC",
                "storage_area": "Perimeter 1",
                "coordinates": [(0, 0), (10, 0)],
            }],
        )
        text = skeleton_geom.read_text(encoding="utf-8")
        existing_idx = text.index("BC Line Name=Existing")
        new_idx = text.index("BC Line Name=NewBC")
        lcmann_idx = text.index("LCMann Time=")
        assert existing_idx < new_idx < lcmann_idx

    def test_add_multiple_in_one_call(self, skeleton_geom):
        from ras_commander import GeomBcLines

        result = GeomBcLines.add_bc_lines(
            skeleton_geom,
            lines=[
                {
                    "name": "Upstream",
                    "storage_area": "Perimeter 1",
                    "coordinates": [(0, 0), (100, 0)],
                },
                {
                    "name": "Tributary",
                    "storage_area": "Perimeter 1",
                    "coordinates": [(0, 100), (100, 100)],
                },
            ],
        )
        assert result["inserted"] == ["Upstream", "Tributary"]
        text = skeleton_geom.read_text(encoding="utf-8")
        assert "BC Line Name=Upstream" in text
        assert "BC Line Name=Tributary" in text

    def test_info_summary_hides_insert_index_and_full_paths(self, skeleton_geom, caplog):
        from ras_commander import GeomBcLines

        with caplog.at_level(logging.DEBUG, logger="ras_commander.geom.GeomBcLines"):
            GeomBcLines.add_bc_lines(
                skeleton_geom,
                lines=[{
                    "name": "DSNormalDepth",
                    "storage_area": "Perimeter 1",
                    "coordinates": [(500, 100), (700, 100), (900, 100)],
                }],
            )

        info_messages = [
            record.getMessage()
            for record in caplog.records
            if record.levelno == logging.INFO
            and record.name == "ras_commander.geom.GeomBcLines"
        ]
        debug_messages = [
            record.getMessage()
            for record in caplog.records
            if record.levelno == logging.DEBUG
            and record.name == "ras_commander.geom.GeomBcLines"
        ]

        assert info_messages == ["Added 1 BC line(s) to project.g01 (replaced=0)"]
        assert all("line index" not in message for message in info_messages)
        assert all(str(skeleton_geom) not in message for message in info_messages)
        assert any("Created backup:" in message for message in debug_messages)
        assert any("Inserted BC line block(s) at line index" in message for message in debug_messages)


class TestAddBcLinesValidation:
    def test_unknown_storage_area_raises(self, skeleton_geom):
        from ras_commander import GeomBcLines

        with pytest.raises(ValueError, match="not found"):
            GeomBcLines.add_bc_lines(
                skeleton_geom,
                lines=[{
                    "name": "BadArea",
                    "storage_area": "NotAnArea",
                    "coordinates": [(0, 0), (10, 0)],
                }],
            )

    def test_missing_required_keys_raise(self, skeleton_geom):
        from ras_commander import GeomBcLines

        with pytest.raises(ValueError, match="'name'"):
            GeomBcLines.add_bc_lines(
                skeleton_geom,
                lines=[{"storage_area": "Perimeter 1", "coordinates": [(0, 0), (1, 0)]}],
            )
        with pytest.raises(ValueError, match="'storage_area'"):
            GeomBcLines.add_bc_lines(
                skeleton_geom,
                lines=[{"name": "x", "coordinates": [(0, 0), (1, 0)]}],
            )
        with pytest.raises(ValueError, match="'coordinates'"):
            GeomBcLines.add_bc_lines(
                skeleton_geom,
                lines=[{"name": "x", "storage_area": "Perimeter 1"}],
            )

    def test_too_few_points_raises(self, skeleton_geom):
        from ras_commander import GeomBcLines

        with pytest.raises(ValueError, match="at least 2 points"):
            GeomBcLines.add_bc_lines(
                skeleton_geom,
                lines=[{
                    "name": "OnePoint",
                    "storage_area": "Perimeter 1",
                    "coordinates": [(0, 0)],
                }],
            )

    def test_empty_lines_raises(self, skeleton_geom):
        from ras_commander import GeomBcLines

        with pytest.raises(ValueError, match="at least one"):
            GeomBcLines.add_bc_lines(skeleton_geom, lines=[])

    def test_duplicate_names_in_one_call_raise(self, skeleton_geom):
        from ras_commander import GeomBcLines

        with pytest.raises(ValueError, match="more than once"):
            GeomBcLines.add_bc_lines(
                skeleton_geom,
                lines=[
                    {"name": "Dup", "storage_area": "Perimeter 1",
                     "coordinates": [(0, 0), (1, 0)]},
                    {"name": "Dup", "storage_area": "Perimeter 1",
                     "coordinates": [(0, 1), (1, 1)]},
                ],
            )

    def test_existing_name_without_replace_raises(self, skeleton_geom):
        from ras_commander import GeomBcLines

        with pytest.raises(ValueError, match="already exists"):
            GeomBcLines.add_bc_lines(
                skeleton_geom,
                lines=[{
                    "name": "Existing",
                    "storage_area": "Perimeter 1",
                    "coordinates": [(0, 0), (1, 0)],
                }],
            )

    def test_missing_geom_file_raises(self, tmp_path):
        from ras_commander import GeomBcLines

        with pytest.raises(FileNotFoundError):
            GeomBcLines.add_bc_lines(
                tmp_path / "missing.g01",
                lines=[{"name": "x", "storage_area": "y",
                        "coordinates": [(0, 0), (1, 0)]}],
            )


class TestAddBcLinesUpsert:
    def test_replace_existing_overwrites_block(self, skeleton_geom):
        """`replace_existing=True` removes the prior block and inserts the
        new one with updated geometry."""
        from ras_commander import GeomBcLines

        result = GeomBcLines.add_bc_lines(
            skeleton_geom,
            lines=[{
                "name": "Existing",
                "storage_area": "Perimeter 1",
                "coordinates": [(0, 0), (50, 0), (100, 0)],
            }],
            replace_existing=True,
        )
        assert result["replaced"] == ["Existing"]
        assert result["inserted"] == []

        text = skeleton_geom.read_text(encoding="utf-8")
        # Old endpoints (100,100 → 200,100) gone; new endpoints (0,0 → 100,0)
        # present.
        assert "BC Line Start Position= 100 , 100 " not in text
        assert "BC Line Start Position= 0.0 , 0.0 " in text
        assert "BC Line Arc= 3 " in text  # was 2
        assert text.count("BC Line Name=Existing") == 1


# ---------------------------------------------------------------------------
# delete_bc_line
# ---------------------------------------------------------------------------


class TestDeleteBcLine:
    def test_delete_removes_only_matching_block(self, skeleton_geom):
        from ras_commander import GeomBcLines

        # Add a second BC line so we can verify the delete is targeted.
        GeomBcLines.add_bc_lines(
            skeleton_geom,
            lines=[{
                "name": "ToKeep",
                "storage_area": "Perimeter 1",
                "coordinates": [(0, 0), (10, 0)],
            }],
        )
        result = GeomBcLines.delete_bc_line(skeleton_geom, name="Existing")
        assert result["deleted"] is True
        assert result["lines_removed"] >= 7  # 6 keyword lines + ≥1 coord row

        text = skeleton_geom.read_text(encoding="utf-8")
        assert "BC Line Name=Existing" not in text
        assert "BC Line Name=ToKeep" in text
        # The second BC line's keyword lines all survived the delete.
        assert "BC Line Storage Area=Perimeter 1     " in text

    def test_delete_unknown_raises(self, skeleton_geom):
        from ras_commander import GeomBcLines

        with pytest.raises(ValueError, match="not found"):
            GeomBcLines.delete_bc_line(skeleton_geom, name="Phantom")


# ---------------------------------------------------------------------------
# rename_bc_line
# ---------------------------------------------------------------------------


class TestRenameBcLine:
    def test_rename_changes_only_the_name_line(self, skeleton_geom):
        from ras_commander import GeomBcLines

        before = skeleton_geom.read_text(encoding="utf-8")
        result = GeomBcLines.rename_bc_line(
            skeleton_geom, old_name="Existing", new_name="UpstreamRenamed"
        )
        assert result["new_name"] == "UpstreamRenamed"

        after = skeleton_geom.read_text(encoding="utf-8")
        # Exactly one line differs: the name line.
        diff = [
            (b, a) for b, a in zip(before.splitlines(), after.splitlines())
            if b != a
        ]
        assert len(diff) == 1
        assert diff[0][0].startswith("BC Line Name=Existing")
        assert diff[0][1].startswith("BC Line Name=UpstreamRenamed")
        # Same line count — no insertions or deletions.
        assert len(before.splitlines()) == len(after.splitlines())

    def test_rename_to_existing_name_raises(self, skeleton_geom):
        from ras_commander import GeomBcLines

        # Add a second BC line.
        GeomBcLines.add_bc_lines(
            skeleton_geom,
            lines=[{
                "name": "Other",
                "storage_area": "Perimeter 1",
                "coordinates": [(0, 0), (10, 0)],
            }],
        )
        with pytest.raises(ValueError, match="already exists"):
            GeomBcLines.rename_bc_line(
                skeleton_geom, old_name="Existing", new_name="Other"
            )

    def test_rename_unknown_raises(self, skeleton_geom):
        from ras_commander import GeomBcLines

        with pytest.raises(ValueError, match="not found"):
            GeomBcLines.rename_bc_line(
                skeleton_geom, old_name="Phantom", new_name="Real"
            )

    def test_rename_identical_names_raises(self, skeleton_geom):
        from ras_commander import GeomBcLines

        with pytest.raises(ValueError, match="identical"):
            GeomBcLines.rename_bc_line(
                skeleton_geom, old_name="Existing", new_name="Existing"
            )


# ---------------------------------------------------------------------------
# Line-ending preservation
# ---------------------------------------------------------------------------


class TestLineEndingPreservation:
    def test_crlf_round_trips(self, tmp_path):
        """A .g## with CRLF line endings (HEC-RAS native) must be written
        back with CRLF intact."""
        from ras_commander import GeomBcLines

        body_crlf = _SKELETON.replace("\n", "\r\n")
        f = tmp_path / "project.g01"
        f.write_bytes(body_crlf.encode("utf-8"))

        GeomBcLines.add_bc_lines(
            f,
            lines=[{
                "name": "CrlfTest",
                "storage_area": "Perimeter 1",
                "coordinates": [(0, 0), (10, 0)],
            }],
        )
        raw = f.read_bytes()
        # Every line should still end in CRLF; no bare LF should appear
        # outside of CRLF pairs.
        assert b"\r\n" in raw
        assert raw.count(b"\r\n") >= raw.count(b"\n") - 1, (
            "Some \\n line endings are missing their preceding \\r"
        )


# ---------------------------------------------------------------------------
# Real RasExamples project (Chippewa_2D)
# ---------------------------------------------------------------------------


class TestChippewa2DRealProject:
    @pytest.mark.slow
    def test_add_bc_line_to_real_chippewa_geometry(self, tmp_path):
        """Insert a fresh BC line into the real Chippewa_2D geometry on
        the existing `Perimeter 1` 2D Flow Area, and verify the writer's
        output keywords match HEC-RAS-emitted format."""
        try:
            from ras_commander import RasExamples, GeomBcLines
            project = RasExamples.extract_project(
                "Chippewa_2D", output_path=tmp_path, suffix="_bc_add"
            )
        except Exception:
            pytest.skip("Chippewa_2D example not available")
        if isinstance(project, list):
            project = project[0]

        g_files = sorted(p for p in Path(project).glob("*.g0*") if "hdf" not in p.name.lower())
        if not g_files:
            pytest.skip("No .g## in Chippewa_2D")
        g_file = g_files[0]
        before_text = g_file.read_text(encoding="utf-8", errors="ignore")
        # Sanity check: Perimeter 1 exists, "TestBCLine" does not.
        assert "Storage Area=Perimeter 1" in before_text
        assert "BC Line Name=TestBCLine" not in before_text

        result = GeomBcLines.add_bc_lines(
            g_file,
            lines=[{
                "name": "TestBCLine",
                "storage_area": "Perimeter 1",
                "coordinates": [
                    (1027205.96, 7858200.24),
                    (1026600.45, 7858258.46),
                    (1025994.94, 7858316.68),
                ],
            }],
        )
        assert result["inserted"] == ["TestBCLine"]

        after_text = g_file.read_text(encoding="utf-8", errors="ignore")
        # Existing BC lines untouched.
        assert "BC Line Name=Upstream" in after_text
        assert "BC Line Name=Downstream" in after_text
        # New BC line present with HEC-RAS-style padded keywords.
        assert "BC Line Name=TestBCLine" in after_text
        assert "BC Line Storage Area=Perimeter 1     " in after_text
        assert "BC Line Arc= 3 " in after_text
        assert (
            "BC Line Text Position= 1.79769313486232E+308 , "
            "1.79769313486232E+308 " in after_text
        )
        # The new block sits with the other BC line blocks (between
        # them and the LCMann section).
        new_idx = after_text.index("BC Line Name=TestBCLine")
        downstream_idx = after_text.index("BC Line Name=Downstream")
        lcmann_idx = after_text.index("LCMann ")
        assert downstream_idx < new_idx < lcmann_idx

    @pytest.mark.slow
    def test_delete_existing_bc_line_in_real_chippewa(self, tmp_path):
        """Delete the shipped `Upstream` BC line from Chippewa_2D and
        confirm only that block is removed; `Downstream` survives."""
        try:
            from ras_commander import RasExamples, GeomBcLines
            project = RasExamples.extract_project(
                "Chippewa_2D", output_path=tmp_path, suffix="_bc_del"
            )
        except Exception:
            pytest.skip("Chippewa_2D example not available")
        if isinstance(project, list):
            project = project[0]
        g_file = next(
            p for p in Path(project).glob("*.g0*") if "hdf" not in p.name.lower()
        )

        result = GeomBcLines.delete_bc_line(g_file, name="Upstream")
        assert result["deleted"] is True

        text = g_file.read_text(encoding="utf-8", errors="ignore")
        assert "BC Line Name=Upstream" not in text
        assert "BC Line Name=Downstream" in text
