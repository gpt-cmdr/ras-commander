"""Tests for SA/2D connection culvert read/author (GeomLateral).

Pure-logic coverage of the fixed-width parser, plus a model-based round-trip that
authors a culvert onto BaldEagle's Lower Levee connection (downloaded once) and
reads it back. Skips cleanly when the example model is unavailable. End-to-end
HEC-RAS acceptance is exercised by examples/227_2d_connection_culvert_authoring.ipynb.
"""
from pathlib import Path

import pytest

from ras_commander.geom import GeomLateral


class TestFixedWidthFloatParser:
    def test_whitespace_separated(self):
        vals = GeomLateral._parse_fw_floats("   85.24   85.24")
        assert vals == [85.24, 85.24]

    def test_packed_16char(self):
        # two 16-char coordinate fields with no delimiter between them
        line = f"{2055956.24304882:16.8f}{353790.63030504:16.8f}"
        vals = GeomLateral._parse_fw_floats(line)
        assert len(vals) == 2
        assert abs(vals[0] - 2055956.24304882) < 1e-4
        assert abs(vals[1] - 353790.63030504) < 1e-4

    def test_four_value_coord_line(self):
        line = ("      2673720.12       678043.93"
                "      2673774.66       678051.46")
        vals = GeomLateral._parse_fw_floats(line)
        assert len(vals) == 4
        assert vals == [2673720.12, 678043.93, 2673774.66, 678051.46]


@pytest.fixture(scope="module")
def baldeagle(tmp_path_factory):
    from ras_commander import RasExamples
    out = tmp_path_factory.mktemp("baldeagle_culvauth")
    try:
        proj = Path(RasExamples.extract_project(
            "BaldEagleCrkMulti2D", output_path=out, suffix="culvauthtest"))
    except Exception as exc:
        pytest.skip(f"BaldEagleCrkMulti2D unavailable: {exc}")
    geom = proj / "BaldEagleDamBrk.g01"
    if not geom.exists():
        pytest.skip("BaldEagle geometry not extracted")
    return geom


# A plausible culvert on the Lower Levee embankment (coords in EPSG:2271).
_CULVERT = {
    "Shape": 2, "Span": 8.0, "Rise": 6.0, "Length": 60.0, "ManningsN": 0.024,
    "EntranceLoss": 0.5, "ExitLoss": 1.0, "Chart": 8, "Scale": 1,
    "UpstreamInvert": 540.0, "DownstreamInvert": 539.5, "Name": "Retrofit Culv",
    "barrels": [{"name": "8x6 RCB",
                 "us_xy": (2055956.243, 353790.630),
                 "ds_xy": (2055952.001, 353730.780)}],
}


class TestAuthorRoundTrip:
    def test_author_and_read_back(self, baldeagle):
        # Lower Levee starts weir-only (no culverts)
        before = GeomLateral.get_connection_culverts(baldeagle, "Lower Levee")
        assert before.empty

        res = GeomLateral.set_connection_culverts(baldeagle, "Lower Levee", [_CULVERT])
        assert res["culverts_written"] == 1
        assert res["barrels_written"] == 1

        after = GeomLateral.get_connection_culverts(baldeagle, "Lower Levee")
        assert len(after) == 1
        row = after.iloc[0]
        assert row["ShapeName"] == "Box"
        assert abs(row["Span"] - 8.0) < 1e-6
        assert abs(row["Length"] - 60.0) < 1e-6
        # GIS endpoints round-trip
        assert abs(row["us_x"] - 2055956.243) < 0.01
        assert abs(row["ds_y"] - 353730.780) < 0.01

    def test_has_culvert_flag_after_authoring(self, baldeagle):
        GeomLateral.set_connection_culverts(baldeagle, "Lower Levee", [_CULVERT])
        conns = GeomLateral.get_connections(baldeagle)
        assert bool(conns.set_index("Name").loc["Lower Levee", "HasCulvert"])

    def test_length_warning_on_mismatch(self, baldeagle):
        bad = dict(_CULVERT)
        bad["Length"] = 200.0  # GIS endpoints are ~60 ft apart -> >1% mismatch
        res = GeomLateral.set_connection_culverts(baldeagle, "Lower Levee", [bad])
        assert res["length_warnings"]

    def test_empty_barrels_raises(self, baldeagle):
        bad = dict(_CULVERT); bad["barrels"] = []
        with pytest.raises(ValueError):
            GeomLateral.set_connection_culverts(baldeagle, "Lower Levee", [bad])


# ---------------------------------------------------------------------------
# Regression tests for QAQC blockers (pure synthetic geometry; no HEC-RAS).
# ---------------------------------------------------------------------------
_NEW = {
    "Shape": 2, "Span": 8.0, "Rise": 6.0, "Length": 60.0, "ManningsN": 0.024,
    "EntranceLoss": 0.5, "ExitLoss": 1.0, "Chart": 8, "Scale": 1,
    "UpstreamInvert": 540.0, "DownstreamInvert": 539.5, "Name": "New Culv",
    "barrels": [{"name": "B1", "us_xy": (1000.0, 2000.0), "ds_xy": (1060.0, 2000.0),
                 "us_station": 50.0, "ds_station": 50.0}],
}

_EXISTING_CULV_BLOCK = (
    "Connection=Test            ,500,500\n"
    "Connection Line=2\n"
    "             0.0           0.0           100.0           0.0\n"
    "Conn Weir SE= 1 \n"
    "       0   10.0\n"
    "Connection Culv=1,5,5,40,0.013,0.5,1,1,1,10.0,9.5, 1 ,Old Culv    , 0 ,\n"
    "    50.0    50.0\n"
    "Conn Culvert Barrel=1,B1,2\n"
    "          0.0          0.0         40.0          0.0\n"
    "Conn Culv Bottom n=0.013\n"
    "Conn HTab FreeFlow Pts= 100 \n"
    "Conn HTab Sub Flow Curves= 60 \n"
    "Conn HTab Sub Flow Pts= 50 \n"
    "\n"
)


def _write(tmp_path, text):
    p = tmp_path / "synthetic.g01"
    p.write_text(text, encoding="utf-8")
    return p


class TestWriterSafety:
    def test_no_rating_curve_preserves_downstream_storage_area(self, tmp_path):
        # CRITICAL: replacing a culvert on a connection with no
        # Conn Outlet Rating Curve= must not delete the following Storage Area.
        geom = _write(tmp_path, _EXISTING_CULV_BLOCK
                      + "Storage Area=KEEP_ME      ,0,0\n"
                      + "Storage Area Surface Line= 0 \n")
        GeomLateral.set_connection_culverts(geom, "Test", [_NEW])
        txt = geom.read_text()
        assert "Storage Area=KEEP_ME" in txt
        assert "River" not in txt or "KEEP_ME" in txt  # sanity
        after = GeomLateral.get_connection_culverts(geom, "Test")
        assert len(after) == 1 and after.iloc[0]["CulvertName"] == "New Culv"

    def test_legacy_sa2d_area_conn_next_block_preserved(self, tmp_path):
        # CRITICAL: a legacy "SA/2D Area Conn=" header must terminate the scan.
        block = _EXISTING_CULV_BLOCK.replace("Connection=Test            ,500,500",
                                             "SA/2D Area Conn=First           ,0,0")
        geom = _write(tmp_path, block
                      + "SA/2D Area Conn=Second          ,1,1\n"
                      + "Conn Weir SE= 1 \n")
        GeomLateral.set_connection_culverts(geom, "First", [_NEW])
        assert "SA/2D Area Conn=Second" in geom.read_text()

    def test_six_barrel_round_trip(self, tmp_path):
        # HIGH: >5 barrels wrap stations onto 2 lines; reader must read all 6.
        geom = _write(tmp_path, _EXISTING_CULV_BLOCK
                      + "Conn Outlet Rating Curve= 0 ,False,,\n")
        six = dict(_NEW)
        six["barrels"] = [{"name": f"B{i}", "us_station": 100.0 + i, "ds_station": 100.0 + i,
                           "us_xy": (1000.0 + 10 * i, 2000.0), "ds_xy": (1060.0 + 10 * i, 2000.0)}
                          for i in range(6)]
        GeomLateral.set_connection_culverts(geom, "Test", [six])
        after = GeomLateral.get_connection_culverts(geom, "Test")
        assert len(after) == 6
        assert not after["us_station"].isna().any()

    def test_packed_8char_stations_parse(self, tmp_path):
        # HIGH: packed 8-char station line must not parse as NaN.
        block = _EXISTING_CULV_BLOCK.replace(
            "Connection Culv=1,5,5,40,0.013,0.5,1,1,1,10.0,9.5, 1 ,Old Culv    , 0 ,\n"
            "    50.0    50.0\n"
            "Conn Culvert Barrel=1,B1,2\n",
            "Connection Culv=1,5,5,40,0.013,0.5,1,1,1,10.0,9.5, 2 ,Old Culv    , 0 ,\n"
            "12345.6712345.6812345.6912345.70\n"
            "Conn Culvert Barrel=1,B1,2\n"
            "          0.0          0.0         40.0          0.0\n"
            "Conn Culvert Barrel=2,B2,2\n")
        geom = _write(tmp_path, block)
        df = GeomLateral.get_connection_culverts(geom, "Test")
        assert len(df) == 2
        assert not df["us_station"].isna().any()
        assert abs(df.iloc[0]["us_station"] - 12345.67) < 0.01
