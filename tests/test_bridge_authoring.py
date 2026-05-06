"""
Regression tests for bridge geometry authoring APIs.

These tests use real HEC-RAS example geometry files and verify bridge deck,
pier, abutment, coefficient, approach-section, and HTAB write paths.
"""

import re
import sys
from pathlib import Path

import pandas as pd
import pytest


# Ensure we're using local source, not installed package
repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


from ras_commander import RasExamples
from ras_commander.geom import GeomBridge


def _get_geom_file(project_path: Path) -> Path:
    """Return the first plain-text geometry file in an extracted project."""
    geom_files = sorted(
        path for path in project_path.iterdir()
        if path.is_file() and re.search(r"\.g\d\d$", path.name.lower())
    )
    assert geom_files, f"No geometry files found in {project_path}"
    return geom_files[0]


def _extract_project(project_name: str, tmp_path: Path, suffix: str) -> Path:
    """Extract an example project into pytest-managed temporary storage."""
    return RasExamples.extract_project(
        project_name,
        output_path=tmp_path / "examples",
        suffix=suffix,
    )


def test_bridge_authoring_round_trips_piers_abutments_coefficients_approach_and_htab(tmp_path):
    """Example 13 has many piers and two abutment blocks; setters should round-trip them."""
    project_path = _extract_project(
        "Example 13 - Singler Bridge (WSPRO)",
        tmp_path,
        "bridge_authoring_piers",
    )
    geom_file = _get_geom_file(project_path)

    bridge = GeomBridge.get_bridges(geom_file).iloc[0]
    river, reach, rs = bridge['River'], bridge['Reach'], str(bridge['RS'])

    assert bridge['NumDecks'] == 6
    assert bridge['NumPiers'] == 17
    assert bool(bridge['HasAbutment']) is True

    deck = GeomBridge.get_deck(geom_file, river, reach, rs)
    assert deck['Location'].value_counts().to_dict() == {
        'upstream': 6,
        'downstream': 6,
    }

    deck_update = deck.copy()
    deck_update.loc[deck_update['Location'].eq('upstream'), 'Elevation'] += 0.25
    backup = GeomBridge.set_deck(
        geom_file,
        river,
        reach,
        rs,
        deck_update,
        distance=bridge['DeckDistance'],
        width=bridge['DeckWidth'],
        weir_coefficient=2.7,
    )
    assert backup.exists()
    updated_bridge = GeomBridge.get_bridges(geom_file).iloc[0]
    assert updated_bridge['WeirCoefficient'] == pytest.approx(2.7)
    assert len(GeomBridge.get_deck(geom_file, river, reach, rs)) == 12

    piers = GeomBridge.get_piers(geom_file, river, reach, rs).head(2)
    backup = GeomBridge.set_piers(geom_file, river, reach, rs, piers)
    assert backup.exists()
    assert len(GeomBridge.get_piers(geom_file, river, reach, rs)) == 2

    abutments = GeomBridge.get_abutment(geom_file, river, reach, rs)
    assert sorted(abutments['AbutmentIndex'].unique().tolist()) == [1, 2]
    abutments_update = abutments.copy()
    abutments_update.loc[
        (abutments_update['AbutmentIndex'].eq(1)) &
        (abutments_update['Location'].eq('upstream')),
        'Parameter',
    ] += 0.1
    backup = GeomBridge.set_abutments(geom_file, river, reach, rs, abutments_update)
    assert backup.exists()
    updated_abutments = GeomBridge.get_abutment(geom_file, river, reach, rs)
    assert len(updated_abutments) == 8
    assert sorted(updated_abutments['AbutmentIndex'].unique().tolist()) == [1, 2]

    backup = GeomBridge.set_coefficients(
        geom_file,
        river,
        reach,
        rs,
        br_coef={3: 1.33},
        wspro={4: 2},
    )
    assert backup.exists()
    coefficients = GeomBridge.get_coefficients(geom_file, river, reach, rs)
    br_coef_3 = coefficients[
        (coefficients['ParameterType'].eq('br_coef')) &
        (coefficients['Index'].eq(3))
    ]['Value'].iloc[0]
    wspro_4 = coefficients[
        (coefficients['ParameterType'].eq('wspro')) &
        (coefficients['Index'].eq(4))
    ]['Value'].iloc[0]
    assert br_coef_3 == pytest.approx(1.33)
    assert wspro_4 == pytest.approx(2.0)

    approach = pd.DataFrame([
        {'Location': 'upstream', 'DataType': 'station_elevation', 'Station': 0, 'Elevation': 341},
        {'Location': 'upstream', 'DataType': 'station_elevation', 'Station': 10, 'Elevation': 342},
        {'Location': 'upstream', 'DataType': 'mannings_n', 'Station': 0, 'N_Value': 0.05},
        {'Location': 'upstream', 'DataType': 'mannings_n', 'Station': 10, 'N_Value': 0.035},
        {'Location': 'downstream', 'DataType': 'station_elevation', 'Station': 0, 'Elevation': 340},
        {'Location': 'downstream', 'DataType': 'station_elevation', 'Station': 10, 'Elevation': 341},
        {'Location': 'downstream', 'DataType': 'mannings_n', 'Station': 0, 'N_Value': 0.05},
        {'Location': 'downstream', 'DataType': 'mannings_n', 'Station': 10, 'N_Value': 0.035},
    ])
    backup = GeomBridge.set_approach_sections(
        geom_file,
        river,
        reach,
        rs,
        approach,
        upstream_banks=[0, 10],
        downstream_banks=[0, 10],
    )
    assert backup.exists()
    approach_roundtrip = GeomBridge.get_approach_sections(geom_file, river, reach, rs)
    assert len(approach_roundtrip[approach_roundtrip['DataType'].eq('station_elevation')]) == 4
    assert len(approach_roundtrip[approach_roundtrip['DataType'].eq('mannings_n')]) == 4
    assert len(approach_roundtrip[approach_roundtrip['DataType'].eq('banks')]) == 2
    written_text = geom_file.read_text(encoding='utf-8', errors='replace')
    assert "BR U #Mann= 2 , 0 , 0" in written_text
    assert "BR D #Mann= 2 , 0 , 0" in written_text

    result = GeomBridge.set_htab(
        geom_file,
        river,
        reach,
        rs,
        hw_max=340.0,
        max_flow=12345.0,
        free_flow_points=100,
        validate=False,
    )
    assert Path(result['backup_path']).exists()
    htab = GeomBridge.get_htab_dict(geom_file, river, reach, rs, include_invert=False)
    assert htab['hw_max'] == pytest.approx(340.0)
    assert htab['max_flow'] == pytest.approx(12345.0)
    assert htab['free_flow_points'] == 100


def test_bridge_authoring_recreates_removed_no_pier_bridge_block(tmp_path):
    """A no-pier SIAM bridge can be recreated at the existing reach/station."""
    project_path = _extract_project(
        "SIAM Example",
        tmp_path,
        "bridge_authoring_no_piers",
    )
    geom_file = _get_geom_file(project_path)

    bridges = GeomBridge.get_bridges(geom_file)
    no_pier_bridge = bridges[bridges['NumPiers'].eq(0)].iloc[0]
    river, reach, rs = no_pier_bridge['River'], no_pier_bridge['Reach'], str(no_pier_bridge['RS'])
    deck = GeomBridge.get_deck(geom_file, river, reach, rs)

    lines = geom_file.read_text(encoding='utf-8', errors='replace').splitlines(True)
    bridge_idx, bridge_end_idx = GeomBridge._get_bridge_range(lines, river, reach, rs)
    del lines[bridge_idx:bridge_end_idx]
    geom_file.write_text("".join(lines), encoding='utf-8')

    with pytest.raises(ValueError, match="Bridge not found"):
        GeomBridge.get_deck(geom_file, river, reach, rs)

    backup = GeomBridge.set_deck(
        geom_file,
        river,
        reach,
        rs,
        deck,
        distance=no_pier_bridge['DeckDistance'],
        width=no_pier_bridge['DeckWidth'],
    )
    assert backup.exists()

    recreated_deck = GeomBridge.get_deck(geom_file, river, reach, rs)
    assert recreated_deck['Location'].value_counts().to_dict() == {
        'upstream': 6,
        'downstream': 6,
    }

    backup = GeomBridge.set_piers(geom_file, river, reach, rs, None)
    assert backup.exists()
    recreated_bridge = GeomBridge.get_bridges(geom_file)
    recreated_row = recreated_bridge[recreated_bridge['RS'].astype(str).eq(rs)].iloc[0]
    assert recreated_row['NumPiers'] == 0
    with pytest.raises(ValueError, match="No piers found"):
        GeomBridge.get_piers(geom_file, river, reach, rs)
