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
