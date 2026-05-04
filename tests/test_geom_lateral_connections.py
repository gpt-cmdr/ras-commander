"""Regression coverage for SA/2D connection blocks in .g## geometry files."""

from pathlib import Path
import shutil

import pandas as pd
import pytest

from ras_commander.RasExamples import RasExamples
from ras_commander.geom.GeomLateral import GeomLateral


@pytest.fixture(scope="module")
def example_output_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("ras_examples")


@pytest.fixture(scope="module")
def bald_eagle_project(example_output_dir):
    return RasExamples.extract_project("BaldEagleCrkMulti2D", output_path=example_output_dir)


@pytest.fixture(scope="module")
def muncie_project(example_output_dir):
    return RasExamples.extract_project("Muncie", output_path=example_output_dir)


def _write_geom_file(tmp_path: Path, lines: list[str]) -> Path:
    geom_file = tmp_path / "connections.g01"
    geom_file.write_text("".join(lines), encoding="utf-8")
    return geom_file


def test_bald_eagle_g13_connection_blocks_are_parsed(bald_eagle_project):
    geom_file = bald_eagle_project / "BaldEagleDamBrk.g13"

    connections = GeomLateral.get_connections(geom_file)

    assert list(connections["Name"]) == [
        "Dam",
        "Lower Levee",
        "Middle Levee",
        "Upper Levee",
    ]
    assert len(connections) == 4
    assert set(connections["Header"]) == {"Connection"}

    dam = connections.loc[connections["Name"] == "Dam"].iloc[0]
    assert dam["From"] == "Reservoir Pool"
    assert dam["To"] == "BaldEagleCr"
    assert dam["Type"] == "SA to 2D"
    assert dam["NumPoints"] == 6
    assert dam["LinePoints"] == 18
    assert bool(dam["HasGate"]) is True

    levee = connections.loc[connections["Name"] == "Lower Levee"].iloc[0]
    assert levee["Type"] == "2D to 2D"
    assert levee["NumPoints"] == 94


def test_muncie_connections_and_conn_weir_se_profile_are_parsed(muncie_project):
    geom_file = muncie_project / "Muncie.g01"

    connections = GeomLateral.get_connections(geom_file)
    profile = GeomLateral.get_connection_profile(geom_file, "162")

    assert len(connections) == 10
    assert list(connections["Name"].head(4)) == ["162", "163", "164", "165"]

    first = connections.loc[connections["Name"] == "162"].iloc[0]
    assert first["NumPoints"] == 66
    assert first["From"] == "146"
    assert first["To"] == "148"

    assert len(profile) == 66
    assert profile.iloc[0]["Station"] == pytest.approx(0.0)
    assert profile.iloc[0]["Elevation"] == pytest.approx(956.819)
    assert profile.iloc[-1]["Station"] == pytest.approx(409.015)
    assert profile.iloc[-1]["Elevation"] == pytest.approx(956.886)


def test_connection_gates_parse_modern_connection_blocks(bald_eagle_project):
    geom_file = bald_eagle_project / "BaldEagleDamBrk.g13"

    gates = GeomLateral.get_connection_gates(geom_file, "Dam")

    assert len(gates) == 1
    gate = gates.iloc[0]
    assert gate["GateName"] == "Gate #1"
    assert gate["Width"] == pytest.approx(7.0)
    assert gate["Height"] == pytest.approx(15.0)
    assert gate["InvertElevation"] == pytest.approx(590.0)
    assert gate["NumOpenings"] == 2
    assert gate["OpeningStations"] == [5745.0, 5765.0]


def test_legacy_sa2d_area_conn_blocks_still_parse(tmp_path):
    geom_file = _write_geom_file(
        tmp_path,
        [
            "Geom Title=Legacy Connection Test\n",
            "SA/2D Area Conn=Legacy Connection\n",
            "From Storage Area=Legacy Pool\n",
            "To 2D Area=Legacy Mesh\n",
            "#Conn Weir Sta/Elev= 2\n",
            "    0.00  100.00   50.00  101.25\n",
            "Storage Area=Legacy Mesh,0,0\n",
            "Storage Area Is2D=-1\n",
        ],
    )

    connections = GeomLateral.get_connections(geom_file)
    profile = GeomLateral.get_connection_profile(geom_file, "Legacy Connection")

    assert len(connections) == 1
    assert connections.iloc[0]["Header"] == "SA/2D Area Conn"
    assert connections.iloc[0]["Type"] == "SA to 2D"
    assert connections.iloc[0]["NumPoints"] == 2
    assert list(profile["Station"]) == [0.0, 50.0]
    assert list(profile["Elevation"]) == [100.0, 101.25]


def test_set_connection_profile_round_trips_existing_connection_block(tmp_path, bald_eagle_project):
    source_geom = bald_eagle_project / "BaldEagleDamBrk.g13"
    geom_file = tmp_path / "BaldEagleDamBrk.g13"
    shutil.copy2(source_geom, geom_file)

    profile = GeomLateral.get_connection_profile(geom_file, "Dam")
    modified = profile.copy()
    modified.loc[0, "Elevation"] = modified.loc[0, "Elevation"] + 0.125

    backup = GeomLateral.set_connection_profile(
        geom_file,
        "Dam",
        modified,
        create_backup=False,
    )

    updated = GeomLateral.get_connection_profile(geom_file, "Dam")
    connections = GeomLateral.get_connections(geom_file)

    assert backup is None
    assert len(updated) == len(profile)
    assert updated.iloc[0]["Elevation"] == pytest.approx(profile.iloc[0]["Elevation"] + 0.125)
    assert len(connections) == 4
    assert connections.loc[connections["Name"] == "Dam", "NumPoints"].iloc[0] == len(profile)


def test_set_connection_profile_round_trips_legacy_profile_block(tmp_path):
    geom_file = _write_geom_file(
        tmp_path,
        [
            "Geom Title=Legacy Connection Test\n",
            "SA/2D Area Conn=Legacy Connection\n",
            "From Storage Area=Legacy Pool\n",
            "To Storage Area=Legacy Downstream\n",
            "#Conn Weir Sta/Elev= 2\n",
            "    0.00  100.00   50.00  101.25\n",
        ],
    )
    replacement = pd.DataFrame(
        {
            "Station": [0.0, 25.0, 50.0],
            "Elevation": [100.0, 100.5, 101.0],
        }
    )

    GeomLateral.set_connection_profile(
        geom_file,
        "Legacy Connection",
        replacement,
        create_backup=False,
    )

    updated = GeomLateral.get_connection_profile(geom_file, "Legacy Connection")
    assert len(updated) == 3
    assert list(updated["Station"]) == [0.0, 25.0, 50.0]
    assert list(updated["Elevation"]) == [100.0, 100.5, 101.0]


# ---------------------------------------------------------------------------
# Connection line coordinate reading
# ---------------------------------------------------------------------------


def test_get_connection_line_coords(bald_eagle_project):
    geom_file = bald_eagle_project / "BaldEagleDamBrk.g13"

    coords = GeomLateral.get_connection_line_coords(geom_file, "Dam")

    assert len(coords) == 18
    assert coords.iloc[0]["X"] == pytest.approx(2002367.9)
    assert coords.iloc[0]["Y"] == pytest.approx(323639.47)
    assert coords.iloc[-1]["X"] == pytest.approx(2008369.13)
    assert coords.iloc[-1]["Y"] == pytest.approx(320174.75)


# ---------------------------------------------------------------------------
# Connection authoring (set_connection)
# ---------------------------------------------------------------------------


def test_set_connection_creates_new(tmp_path, bald_eagle_project):
    source_geom = bald_eagle_project / "BaldEagleDamBrk.g13"
    geom_file = tmp_path / "BaldEagleDamBrk.g13"
    shutil.copy2(source_geom, geom_file)

    coords = [(100.0, 200.0), (150.0, 250.0), (200.0, 300.0)]
    GeomLateral.set_connection(
        geom_file,
        "New Test Conn",
        coords,
        "Reservoir Pool",
        "BaldEagleCr",
        create_backup=False,
    )

    connections = GeomLateral.get_connections(geom_file)
    assert "New Test Conn" in connections["Name"].values
    assert len(connections) == 5

    new_coords = GeomLateral.get_connection_line_coords(geom_file, "New Test Conn")
    assert len(new_coords) == 3
    assert new_coords.iloc[0]["X"] == pytest.approx(100.0)


def test_set_connection_replaces_existing(tmp_path, bald_eagle_project):
    source_geom = bald_eagle_project / "BaldEagleDamBrk.g13"
    geom_file = tmp_path / "BaldEagleDamBrk.g13"
    shutil.copy2(source_geom, geom_file)

    new_coords = [(500.0, 600.0), (550.0, 650.0)]
    GeomLateral.set_connection(
        geom_file,
        "Dam",
        new_coords,
        "Reservoir Pool",
        "BaldEagleCr",
        create_backup=False,
    )

    connections = GeomLateral.get_connections(geom_file)
    assert len(connections) == 4
    dam = connections.loc[connections["Name"] == "Dam"].iloc[0]
    assert dam["LinePoints"] == 2

    coords_df = GeomLateral.get_connection_line_coords(geom_file, "Dam")
    assert len(coords_df) == 2
    assert coords_df.iloc[0]["X"] == pytest.approx(500.0)


def test_set_connection_default_profile(tmp_path):
    geom_file = _write_geom_file(
        tmp_path,
        [
            "Geom Title=Profile Test\n",
            "Storage Area=PoolA,0,0\n",
            "Storage Area=PoolB,0,0\n",
        ],
    )

    coords = [(0.0, 0.0), (100.0, 0.0)]
    GeomLateral.set_connection(
        geom_file,
        "TestConn",
        coords,
        "PoolA",
        "PoolB",
        create_backup=False,
    )

    profile = GeomLateral.get_connection_profile(geom_file, "TestConn")
    assert len(profile) == 2
    assert profile.iloc[0]["Station"] == pytest.approx(0.0)
    assert profile.iloc[1]["Station"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Connection gates authoring
# ---------------------------------------------------------------------------


def test_set_connection_gates_round_trip(tmp_path, bald_eagle_project):
    source_geom = bald_eagle_project / "BaldEagleDamBrk.g13"
    geom_file = tmp_path / "BaldEagleDamBrk.g13"
    shutil.copy2(source_geom, geom_file)

    new_gates = [
        {
            "GateName": "TestGate",
            "Width": 5.0,
            "Height": 10.0,
            "InvertElevation": 600.0,
            "GateCoefficient": 0.7,
            "NumOpenings": 1,
            "OpeningStations": [3000.0],
        }
    ]

    GeomLateral.set_connection_gates(
        geom_file,
        "Lower Levee",
        new_gates,
        create_backup=False,
    )

    gates = GeomLateral.get_connection_gates(geom_file, "Lower Levee")
    assert len(gates) == 1
    assert gates.iloc[0]["GateName"] == "TestGate"
    assert gates.iloc[0]["Width"] == pytest.approx(5.0)


def test_set_connection_gates_replaces_existing(tmp_path, bald_eagle_project):
    source_geom = bald_eagle_project / "BaldEagleDamBrk.g13"
    geom_file = tmp_path / "BaldEagleDamBrk.g13"
    shutil.copy2(source_geom, geom_file)

    replacement = [
        {
            "GateName": "Replaced",
            "Width": 12.0,
            "Height": 20.0,
            "InvertElevation": 580.0,
            "GateCoefficient": 0.6,
            "NumOpenings": 3,
            "OpeningStations": [5000.0, 5020.0, 5040.0],
        }
    ]

    GeomLateral.set_connection_gates(
        geom_file,
        "Dam",
        replacement,
        create_backup=False,
    )

    gates = GeomLateral.get_connection_gates(geom_file, "Dam")
    assert len(gates) == 1
    assert gates.iloc[0]["GateName"] == "Replaced"
    assert gates.iloc[0]["NumOpenings"] == 3

    old_gates_present = any(g == "Gate #1" for g in gates["GateName"])
    assert not old_gates_present


# ---------------------------------------------------------------------------
# Connection deletion
# ---------------------------------------------------------------------------


def test_delete_connection(tmp_path, bald_eagle_project):
    source_geom = bald_eagle_project / "BaldEagleDamBrk.g13"
    geom_file = tmp_path / "BaldEagleDamBrk.g13"
    shutil.copy2(source_geom, geom_file)

    GeomLateral.delete_connection(geom_file, "Upper Levee", create_backup=False)

    connections = GeomLateral.get_connections(geom_file)
    assert len(connections) == 3
    assert "Upper Levee" not in connections["Name"].values


# ---------------------------------------------------------------------------
# Coordinate overflow
# ---------------------------------------------------------------------------


def test_connection_line_overflow(tmp_path):
    """Coordinates > 10M (state plane) should round-trip through 16-char fields."""
    geom_file = _write_geom_file(
        tmp_path,
        [
            "Geom Title=Overflow Test\n",
            "Connection=BigCoords        ,12345678.5,98765432.5\n",
            "Connection Desc=\n",
            "Connection Line=2\n",
            "    12345678.123    98765432.456    12345679.789    98765433.012\n",
            "Connection Up SA=PoolA           \n",
            "Connection Dn SA=PoolB           \n",
            "Conn Routing Type= 1 \n",
            "Conn Weir SE= 2 \n",
            "   0.000   0.000   1.000   0.000\n",
            "Conn Outlet Rating Curve= 0 ,False,,\n",
        ],
    )

    coords = GeomLateral.get_connection_line_coords(geom_file, "BigCoords")
    assert len(coords) == 2
    assert coords.iloc[0]["X"] == pytest.approx(12345678.123, rel=1e-3)
    assert coords.iloc[0]["Y"] == pytest.approx(98765432.456, rel=1e-3)


# ---------------------------------------------------------------------------
# Insertion order
# ---------------------------------------------------------------------------


def test_set_connection_insert_order(tmp_path):
    """New connection goes after existing connections, before BC Line blocks."""
    geom_file = _write_geom_file(
        tmp_path,
        [
            "Geom Title=Insert Order Test\n",
            "Connection=Existing         ,100,200\n",
            "Connection Desc=\n",
            "Connection Line=2\n",
            "             100             200             300             400\n",
            "Connection Up SA=PoolA           \n",
            "Connection Dn SA=PoolB           \n",
            "Conn Routing Type= 1 \n",
            "Conn Weir SE= 2 \n",
            "   0.000   0.000   1.000   0.000\n",
            "Conn Outlet Rating Curve= 0 ,False,,\n",
            "BC Line Name=Downstream\n",
        ],
    )

    GeomLateral.set_connection(
        geom_file,
        "NewConn",
        [(500.0, 600.0), (700.0, 800.0)],
        "PoolA",
        "PoolB",
        create_backup=False,
    )

    with open(geom_file, 'r', encoding='utf-8') as f:
        text = f.read()

    existing_pos = text.index("Connection=Existing")
    new_pos = text.index("Connection=NewConn")
    bc_pos = text.index("BC Line Name=Downstream")

    assert existing_pos < new_pos < bc_pos
