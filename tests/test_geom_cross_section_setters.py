from pathlib import Path

import numpy as np
import pandas as pd

from ras_commander.geom.GeomCrossSection import GeomCrossSection


RIVER = "TestRiver"
REACH = "TestReach"


def _sta_elev_line(values):
    return "".join(f"{value:8.2f}" for value in values)


def _xs_block(rs, sta_elev_values, bank_line=None, exp_cntr_line=None):
    lines = [
        f"Type RM Length L Ch R = 1 ,{rs},     0.0,     0.0,     0.0\n",
        "Node Last Edited Time=Jan/01/2025 00:00:00\n",
    ]
    if bank_line:
        lines.append(bank_line)
    if exp_cntr_line:
        lines.append(exp_cntr_line)
    lines.extend([
        f"#Sta/Elev= {len(sta_elev_values) // 2}\n",
        _sta_elev_line(sta_elev_values) + "\n",
        "#Mann= 2 , 0 , 0\n",
        _sta_elev_line([0.0, 0.04, 0.0, 500.0, 0.04, 0.0]) + "\n",
    ])
    return "".join(lines)


def _write_geom(tmp_path: Path, include_banks=True, include_exp_cntr=False):
    bank_1000 = "Bank Sta=200,800\n" if include_banks else None
    bank_2000 = "Bank Sta=250,850\n" if include_banks else None
    exp_line = "Exp/Cntr=0.30,0.10\n" if include_exp_cntr else None

    text = (
        "Geom Title=CLB-306 Test\n"
        "Program Version=6.50\n"
        f"River Reach={RIVER}    ,{REACH}\n"
        "Reach XY= 2\n"
        "         0.00         0.00\n"
        "     10000.00         0.00\n"
        + _xs_block(
            "1000",
            [0.0, 100.0, 500.0, 90.0, 1000.0, 100.0],
            bank_line=bank_1000,
            exp_cntr_line=exp_line,
        )
        + _xs_block(
            "2000",
            [0.0, 102.0, 250.0, 95.0, 750.0, 95.0, 1000.0, 102.0],
            bank_line=bank_2000,
        )
    )

    geom_file = tmp_path / "clb306.g01"
    geom_file.write_text(text, encoding="utf-8")
    return geom_file


def test_set_bank_stations_inserts_bank_points_and_backup(tmp_path):
    geom_file = _write_geom(tmp_path, include_banks=False)

    backup_path = GeomCrossSection.set_bank_stations(
        geom_file, RIVER, REACH, "1000", 250.0, 750.0
    )

    assert backup_path is not None
    assert backup_path.exists()
    assert GeomCrossSection.get_bank_stations(geom_file, RIVER, REACH, "1000") == (
        250.0,
        750.0,
    )

    sta_elev = GeomCrossSection.get_station_elevation(geom_file, RIVER, REACH, "1000")
    assert len(sta_elev) == 5
    assert np.isclose(sta_elev.loc[sta_elev["Station"].eq(250.0), "Elevation"].iloc[0], 95.0)
    assert np.isclose(sta_elev.loc[sta_elev["Station"].eq(750.0), "Elevation"].iloc[0], 95.0)

    text = geom_file.read_text(encoding="utf-8")
    assert "Bank Sta=250,750" in text
    assert "#Sta/Elev= 5" in text


def test_set_expansion_contraction_round_trip_insert_and_update(tmp_path):
    geom_file = _write_geom(tmp_path, include_banks=True, include_exp_cntr=False)

    backup_path = GeomCrossSection.set_expansion_contraction(
        geom_file, RIVER, REACH, "1000", 0.45, 0.15
    )
    assert backup_path is not None
    assert backup_path.exists()
    assert GeomCrossSection.get_expansion_contraction(geom_file, RIVER, REACH, "1000") == (
        0.45,
        0.15,
    )

    second_backup = GeomCrossSection.set_expansion_contraction(
        geom_file, RIVER, REACH, "1000", 0.50, 0.20, create_backup=False
    )
    assert second_backup is None
    assert GeomCrossSection.get_expansion_contraction(geom_file, RIVER, REACH, "1000") == (
        0.50,
        0.20,
    )


def test_interpolate_station_elevation_review_columns_and_point_limit():
    upstream = pd.DataFrame({
        "Station": [0.0, 50.0, 100.0],
        "Elevation": [10.0, 0.0, 10.0],
    })
    downstream = pd.DataFrame({
        "Station": [0.0, 25.0, 75.0, 100.0],
        "Elevation": [12.0, 2.0, 2.0, 12.0],
    })

    interpolated = GeomCrossSection.interpolate_station_elevation(
        upstream,
        downstream,
        ratio=0.5,
        bank_left=33.0,
        bank_right=66.0,
        max_points=6,
    )

    assert len(interpolated) <= 6
    assert {"UpstreamStation", "DownstreamElevation", "Source", "IsBankPoint"}.issubset(
        interpolated.columns
    )
    assert set(interpolated.loc[interpolated["IsBankPoint"], "Station"]) == {33.0, 66.0}
    assert "resampled" in set(interpolated["Source"])
    assert "bank" in set(interpolated["Source"])


def test_interpolate_cross_section_reads_banks_from_geometry(tmp_path):
    geom_file = _write_geom(tmp_path, include_banks=True)

    interpolated = GeomCrossSection.interpolate_cross_section(
        geom_file,
        RIVER,
        REACH,
        "1000",
        "2000",
        ratio=0.5,
        max_points=20,
        interpolated_rs="1500",
    )

    assert {"River", "Reach", "UpstreamRS", "DownstreamRS", "InterpolatedRS"}.issubset(
        interpolated.columns
    )
    assert set(interpolated["UpstreamRS"]) == {"1000"}
    assert set(interpolated["DownstreamRS"]) == {"2000"}
    assert np.isclose(interpolated["BankLeft"].iloc[0], 225.0)
    assert np.isclose(interpolated["BankRight"].iloc[0], 825.0)
    assert {225.0, 825.0}.issubset(
        set(interpolated.loc[interpolated["IsBankPoint"], "Station"])
    )
