"""Tests for bridge connection (routing type 32) sub-records in .g## geometry files."""

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
def g03_geom_file(bald_eagle_project):
    return bald_eagle_project / "BaldEagleDamBrk.g03"


# ---------------------------------------------------------------------------
# Read tests
# ---------------------------------------------------------------------------


def test_get_bridge_data_highway_120(g03_geom_file):
    data = GeomLateral.get_bridge_data(g03_geom_file, "Highway 120")

    assert data['bridge_params'] is not None
    assert data['deck'] is not None
    assert data['deck']['NumUp'] == 2
    assert data['deck']['NumDn'] == 2
    assert len(data['deck']['Points']) == 4

    assert data['bridge_xs'][0]['NumPoints'] == 66
    assert data['bridge_xs'][1]['NumPoints'] == 59

    assert len(data['piers']) == 3

    assert data['coefficients'] is not None

    assert data['approach_xs'][0]['NumPoints'] == 66
    assert data['approach_xs'][1]['NumPoints'] == 64


def test_get_bridge_deck_highway_120(g03_geom_file):
    deck = GeomLateral.get_bridge_deck(g03_geom_file, "Highway 120")

    assert len(deck) == 4
    upstream = deck[deck['Location'] == 'upstream']
    downstream = deck[deck['Location'] == 'downstream']
    assert len(upstream) == 2
    assert len(downstream) == 2

    assert upstream.iloc[0]['Station'] == pytest.approx(0.0)
    assert upstream.iloc[0]['Elevation'] == pytest.approx(580.0)


def test_get_bridge_piers_highway_120(g03_geom_file):
    piers = GeomLateral.get_bridge_piers(g03_geom_file, "Highway 120")

    assert len(piers) == 3
    assert list(piers['UpstreamStation']) == [110.0, 220.0, 330.0]
    assert piers.iloc[0]['NumUpstreamPoints'] == 2
    assert piers.iloc[0]['UpstreamWidths'] == [4.0, 4.0]
    assert piers.iloc[0]['UpstreamElevations'] == [530.0, 575.0]


def test_get_bridge_xs_highway_120(g03_geom_file):
    xs_us = GeomLateral.get_bridge_xs(g03_geom_file, "Highway 120", side=1)
    xs_ds = GeomLateral.get_bridge_xs(g03_geom_file, "Highway 120", side=2)

    assert len(xs_us) == 66
    assert xs_us.iloc[0]['Station'] == pytest.approx(0.0)
    assert xs_us.iloc[0]['Elevation'] == pytest.approx(574.05)

    assert len(xs_ds) == 59
    assert xs_ds.iloc[0]['Station'] == pytest.approx(0.0)
    assert xs_ds.iloc[0]['Elevation'] == pytest.approx(570.66)


def test_get_bridge_approach_xs_highway_120(g03_geom_file):
    xs_us = GeomLateral.get_bridge_approach_xs(g03_geom_file, "Highway 120", side=1)
    xs_ds = GeomLateral.get_bridge_approach_xs(g03_geom_file, "Highway 120", side=2)

    assert len(xs_us) == 66
    assert xs_us.iloc[0]['Station'] == pytest.approx(0.0)
    assert xs_us.iloc[0]['Elevation'] == pytest.approx(553.68)

    assert len(xs_ds) == 64
    assert xs_ds.iloc[0]['Station'] == pytest.approx(0.0)
    assert xs_ds.iloc[0]['Elevation'] == pytest.approx(546.58)


def test_get_bridge_data_standard_connection_has_skeleton(g03_geom_file):
    data = GeomLateral.get_bridge_data(g03_geom_file, "Lower Levee")

    assert data['bridge_params'] is not None
    assert data['bridge_xs'][0]['NumPoints'] == 0
    assert data['bridge_xs'][1]['NumPoints'] == 0
    assert data['piers'] == []


def test_bridge_data_nonexistent_raises(g03_geom_file):
    with pytest.raises(ValueError, match="Connection not found"):
        GeomLateral.get_bridge_data(g03_geom_file, "Nonexistent Bridge")


# ---------------------------------------------------------------------------
# Write round-trip tests
# ---------------------------------------------------------------------------


def test_set_bridge_xs_round_trip(tmp_path, g03_geom_file):
    geom = tmp_path / "test.g03"
    shutil.copy2(g03_geom_file, geom)

    xs = GeomLateral.get_bridge_xs(geom, "Highway 120", side=1)
    original_elev = xs.iloc[0]['Elevation']
    xs['Elevation'] = xs['Elevation'] + 0.5

    GeomLateral.set_bridge_xs(geom, "Highway 120", xs, side=1, create_backup=False)

    updated = GeomLateral.get_bridge_xs(geom, "Highway 120", side=1)
    assert len(updated) == len(xs)
    assert updated.iloc[0]['Elevation'] == pytest.approx(original_elev + 0.5)

    ds = GeomLateral.get_bridge_xs(geom, "Highway 120", side=2)
    assert ds.iloc[0]['Elevation'] == pytest.approx(570.66)


def test_set_bridge_approach_xs_round_trip(tmp_path, g03_geom_file):
    geom = tmp_path / "test.g03"
    shutil.copy2(g03_geom_file, geom)

    xs = GeomLateral.get_bridge_approach_xs(geom, "Highway 120", side=2)
    xs['Elevation'] = xs['Elevation'] - 0.25

    GeomLateral.set_bridge_approach_xs(geom, "Highway 120", xs, side=2, create_backup=False)

    updated = GeomLateral.get_bridge_approach_xs(geom, "Highway 120", side=2)
    assert len(updated) == len(xs)
    assert updated.iloc[0]['Elevation'] == pytest.approx(546.58 - 0.25)


def test_set_bridge_piers_round_trip(tmp_path, g03_geom_file):
    geom = tmp_path / "test.g03"
    shutil.copy2(g03_geom_file, geom)

    piers = GeomLateral.get_bridge_piers(geom, "Highway 120")
    pier_list = piers.to_dict('records')
    pier_list[0]['UpstreamWidths'] = [6.0, 6.0]

    GeomLateral.set_bridge_piers(geom, "Highway 120", pier_list, create_backup=False)

    updated = GeomLateral.get_bridge_piers(geom, "Highway 120")
    assert len(updated) == 3
    assert updated.iloc[0]['UpstreamWidths'] == [6.0, 6.0]
    assert updated.iloc[1]['UpstreamStation'] == 220.0


def test_set_bridge_piers_empty_clears(tmp_path, g03_geom_file):
    geom = tmp_path / "test.g03"
    shutil.copy2(g03_geom_file, geom)

    GeomLateral.set_bridge_piers(geom, "Highway 120", [], create_backup=False)

    with pytest.raises(ValueError, match="No piers"):
        GeomLateral.get_bridge_piers(geom, "Highway 120")


def test_set_bridge_deck_round_trip(tmp_path, g03_geom_file):
    geom = tmp_path / "test.g03"
    shutil.copy2(g03_geom_file, geom)

    deck = GeomLateral.get_bridge_deck(geom, "Highway 120")
    deck['Elevation'] = deck['Elevation'] + 1.0

    GeomLateral.set_bridge_deck(geom, "Highway 120", deck, create_backup=False)

    updated = GeomLateral.get_bridge_deck(geom, "Highway 120")
    assert len(updated) == 4
    assert updated.iloc[0]['Elevation'] == pytest.approx(580.0 + 1.0)


def test_set_bridge_coefficients(tmp_path, g03_geom_file):
    geom = tmp_path / "test.g03"
    shutil.copy2(g03_geom_file, geom)

    new_coefs = ['2', '1', '0', '', '', '0.9', '0', '', '0', '']
    GeomLateral.set_bridge_coefficients(geom, "Highway 120", new_coefs, create_backup=False)

    data = GeomLateral.get_bridge_data(geom, "Highway 120")
    assert data['coefficients'][0] == '2'
    assert data['coefficients'][5] == '0.9'


def test_write_preserves_other_connections(tmp_path, g03_geom_file):
    geom = tmp_path / "test.g03"
    shutil.copy2(g03_geom_file, geom)

    xs = GeomLateral.get_bridge_xs(geom, "Highway 120", side=1)
    xs['Elevation'] = xs['Elevation'] + 1.0
    GeomLateral.set_bridge_xs(geom, "Highway 120", xs, side=1, create_backup=False)

    conns = GeomLateral.get_connections(geom)
    assert len(conns) == 11
    assert "Highway 150" in conns["Name"].values
    assert "Lower Levee" in conns["Name"].values

    other_xs = GeomLateral.get_bridge_xs(geom, "Highway 150", side=1)
    assert len(other_xs) > 0


def test_delete_bridge_connection(tmp_path, g03_geom_file):
    geom = tmp_path / "test.g03"
    shutil.copy2(g03_geom_file, geom)

    GeomLateral.delete_connection(geom, "Highway 120", create_backup=False)

    conns = GeomLateral.get_connections(geom)
    assert len(conns) == 10
    assert "Highway 120" not in conns["Name"].values
    assert "Highway 150" in conns["Name"].values
