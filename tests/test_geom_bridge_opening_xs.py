"""
Tests for GeomBridge.get_bridge_opening_xs() — the 1D bridge inside-opening
cross-section accessor (CLB-487).
"""

import re
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from ras_commander import RasExamples
from ras_commander.geom import GeomBridge


BRIDGE_FIXTURE_WITH_BR_XS = """\
Geom Title=Bridge Opening XS Fixture
River Reach=TestRiver,TestReach
Type RM Length L Ch R = 1 ,10.2    ,100,100,100
Node Last Edited Time=Jan/01/2025 00:00:00
#Sta/Elev= 5
       0     110      50     105     100     100     150     105     200     110
Bank Sta=50,150

Type RM Length L Ch R = 3 ,10.0    ,,,
Node Last Edited Time=Jan/01/2025 00:00:00
Bridge Culvert--1,0,0,-1, 0
Deck Dist Width WeirC Skew NumUp NumDn MinLoCord MaxHiCord MaxSubmerge Is_Ogee
30,40,2.6,0, 3, 3, , , 0.95, 0, 0,0,,
       0      50     200
     115     115     115
     108     108     108
       0      50     200
     115     115     115
     108     108     108
BR U #Sta/Elev= 6
       0     112      40     107      80     101     120     101     160     107
     200     112
BR U Banks=50,150
BR D #Sta/Elev= 6
       0     111      40     106      80     100     120     100     160     106
     200     111
BR D Banks=50,150
BR Coef=-1 , 0 , 0 ,, 0 ,,0.34,0.7,0,,1,
BC HTab HWMax=120
Type RM Length L Ch R = 1 ,9.8     ,100,100,100
Node Last Edited Time=Jan/01/2025 00:00:00
#Sta/Elev= 5
       0     109      50     104     100      99     150     104     200     109
Bank Sta=50,150
"""

BRIDGE_FIXTURE_NO_BR_XS = """\
Geom Title=Bridge No Inside XS Fixture
River Reach=TestRiver,TestReach
Type RM Length L Ch R = 1 ,10.2    ,100,100,100
Node Last Edited Time=Jan/01/2025 00:00:00
#Sta/Elev= 4
       0     220      50     210     100     210     150     220
Bank Sta=50,100

Type RM Length L Ch R = 3 ,10.0    ,,,
Node Last Edited Time=Jan/01/2025 00:00:00
Bridge Culvert--1,0,0,-1, 0
Deck Dist Width WeirC Skew NumUp NumDn MinLoCord MaxHiCord MaxSubmerge Is_Ogee
30,40,2.6,0, 2, 2, , , 0.95, 0, 0,0,,
       0     150
     225     225
     215     215
       0     150
     225     225
     215     215
BR Coef=-1 , 0 , 0 ,, 0 ,,0.34,0.7,0,,1,
BC HTab HWMax=230
Type RM Length L Ch R = 1 ,9.8     ,100,100,100
Node Last Edited Time=Jan/01/2025 00:00:00
#Sta/Elev= 4
       0     219      50     209     100     209     150     219
Bank Sta=50,100
"""


def _write_fixture(tmp_path: Path, text: str) -> Path:
    geom_file = tmp_path / "test_bridge.g01"
    geom_file.write_text(text, encoding="utf-8")
    return geom_file


def _get_geom_file(project_path: Path) -> Path:
    geom_files = sorted(
        path for path in project_path.iterdir()
        if path.is_file() and re.search(r"\.g\d\d$", path.name.lower())
    )
    assert geom_files, f"No geometry files found in {project_path}"
    return geom_files[0]


class TestBridgeOpeningXsWithExplicitData:
    """Tests for bridges that have BR U / BR D #Sta/Elev records."""

    def test_upstream_returns_bridge_block_data(self, tmp_path):
        geom_file = _write_fixture(tmp_path, BRIDGE_FIXTURE_WITH_BR_XS)

        xs = GeomBridge.get_bridge_opening_xs(
            geom_file, "TestRiver", "TestReach", "10.0", section="upstream"
        )

        assert len(xs) == 6
        assert list(xs.columns) == ["Station", "Elevation", "Source"]
        assert xs["Source"].iloc[0] == "bridge_block"
        assert xs["Station"].iloc[0] == pytest.approx(0.0)
        assert xs["Elevation"].iloc[0] == pytest.approx(112.0)
        assert xs["Station"].iloc[5] == pytest.approx(200.0)
        assert xs["Elevation"].iloc[5] == pytest.approx(112.0)

    def test_downstream_returns_bridge_block_data(self, tmp_path):
        geom_file = _write_fixture(tmp_path, BRIDGE_FIXTURE_WITH_BR_XS)

        xs = GeomBridge.get_bridge_opening_xs(
            geom_file, "TestRiver", "TestReach", "10.0", section="downstream"
        )

        assert len(xs) == 6
        assert xs["Source"].iloc[0] == "bridge_block"
        assert xs["Elevation"].iloc[2] == pytest.approx(100.0)

    def test_bridge_block_source_differs_from_adjacent_regular_xs(self, tmp_path):
        geom_file = _write_fixture(tmp_path, BRIDGE_FIXTURE_WITH_BR_XS)

        xs_up = GeomBridge.get_bridge_opening_xs(
            geom_file, "TestRiver", "TestReach", "10.0", section="upstream"
        )

        assert xs_up["Source"].iloc[0] == "bridge_block"
        assert len(xs_up) == 6
        assert xs_up["Elevation"].min() == pytest.approx(101.0)


class TestBridgeOpeningXsFallback:
    """Tests for bridges without BR U / BR D data — should fall back to approach XS."""

    def test_upstream_falls_back_to_approach_xs(self, tmp_path):
        geom_file = _write_fixture(tmp_path, BRIDGE_FIXTURE_NO_BR_XS)

        xs = GeomBridge.get_bridge_opening_xs(
            geom_file, "TestRiver", "TestReach", "10.0", section="upstream"
        )

        assert len(xs) == 4
        assert xs["Source"].iloc[0] == "approach_xs"
        assert xs["Station"].iloc[0] == pytest.approx(0.0)
        assert xs["Elevation"].iloc[0] == pytest.approx(220.0)

    def test_downstream_falls_back_to_approach_xs(self, tmp_path):
        geom_file = _write_fixture(tmp_path, BRIDGE_FIXTURE_NO_BR_XS)

        xs = GeomBridge.get_bridge_opening_xs(
            geom_file, "TestRiver", "TestReach", "10.0", section="downstream"
        )

        assert len(xs) == 4
        assert xs["Source"].iloc[0] == "approach_xs"
        assert xs["Elevation"].iloc[0] == pytest.approx(219.0)


class TestBridgeOpeningXsErrors:
    """Tests for error cases."""

    def test_invalid_section_raises(self, tmp_path):
        geom_file = _write_fixture(tmp_path, BRIDGE_FIXTURE_WITH_BR_XS)

        with pytest.raises(ValueError, match="section must be"):
            GeomBridge.get_bridge_opening_xs(
                geom_file, "TestRiver", "TestReach", "10.0", section="left"
            )

    def test_bridge_not_found_raises(self, tmp_path):
        geom_file = _write_fixture(tmp_path, BRIDGE_FIXTURE_WITH_BR_XS)

        with pytest.raises(ValueError, match="Bridge not found"):
            GeomBridge.get_bridge_opening_xs(
                geom_file, "TestRiver", "TestReach", "999"
            )

    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            GeomBridge.get_bridge_opening_xs(
                tmp_path / "missing.g01", "R", "R", "1"
            )


class TestBridgeOpeningXsRealExample:
    """Integration test against the Bridge Hydraulics example project."""

    def test_real_bridge_returns_approach_xs_fallback(self):
        project_path = RasExamples.extract_project(
            "Bridge Hydraulics",
            suffix="test_bridge_opening_xs",
        )
        geom_file = _get_geom_file(project_path)
        bridges = GeomBridge.get_bridges(geom_file)
        assert not bridges.empty

        row = bridges.iloc[0]
        xs = GeomBridge.get_bridge_opening_xs(
            geom_file, row["River"], row["Reach"], str(row["RS"]),
            section="upstream"
        )

        assert len(xs) > 0
        assert "Station" in xs.columns
        assert "Elevation" in xs.columns
        assert "Source" in xs.columns
        assert xs["Source"].iloc[0] == "approach_xs"
