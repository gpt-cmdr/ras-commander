from pathlib import Path

import numpy as np
import pandas as pd

from ras_commander.geom.GeomCrossSection import GeomCrossSection
from ras_commander.fixit.RasFixit import RasFixit
from ras_commander.fixit.obstructions import BlockedObstruction, has_overlaps


RIVER = "TestRiver"
REACH = "TestReach"


def _sta_elev_line(values):
    return "".join(f"{value:8.2f}" for value in values)


def _blocked_obstruction_lines(obstructions):
    values = []
    for start_sta, end_sta, elevation in obstructions:
        values.extend([start_sta, end_sta, elevation])

    lines = [f"#Block Obstruct= {len(obstructions)}\n"]
    for idx in range(0, len(values), GeomCrossSection.BLOCKED_OBSTRUCTION_VALUES_PER_LINE):
        lines.append(_sta_elev_line(values[idx:idx + 9]) + "\n")
    return lines


def _xs_block(
    rs,
    sta_elev_values,
    bank_line=None,
    exp_cntr_line=None,
    blocked_obstructions=None,
    levee_line=None,
):
    lines = [
        f"Type RM Length L Ch R = 1 ,{rs},     0.0,     0.0,     0.0\n",
        "Node Last Edited Time=Jan/01/2025 00:00:00\n",
    ]
    if blocked_obstructions:
        lines.extend(_blocked_obstruction_lines(blocked_obstructions))
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
    if levee_line:
        lines.append(levee_line)
    return "".join(lines)


def _write_geom(
    tmp_path: Path,
    include_banks=True,
    include_exp_cntr=False,
    blocked_obstructions=None,
):
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
            blocked_obstructions=blocked_obstructions,
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


def test_get_blocked_obstructions_reads_dataframe(tmp_path):
    geom_file = _write_geom(
        tmp_path,
        blocked_obstructions=[
            (100.0, 200.0, 91.5),
            (250.0, 300.0, 92.0),
        ],
    )

    obstructions = GeomCrossSection.get_blocked_obstructions(geom_file)

    assert {
        "xs_id",
        "start_sta",
        "end_sta",
        "elevation",
    }.issubset(obstructions.columns)
    assert list(obstructions["xs_id"].unique()) == [f"{RIVER}|{REACH}|1000"]
    assert np.allclose(obstructions["start_sta"], [100.0, 250.0])
    assert np.allclose(obstructions["end_sta"], [200.0, 300.0])
    assert np.allclose(obstructions["elevation"], [91.5, 92.0])


def test_set_blocked_obstructions_round_trip_and_preserves_following_xs(tmp_path):
    geom_file = _write_geom(tmp_path, include_banks=True)
    new_obstructions = pd.DataFrame({
        "start_sta": [100.0, 210.0, 320.0, 430.0],
        "end_sta": [150.0, 260.0, 370.0, 480.0],
        "elevation": [91.0, 92.0, 93.0, 94.0],
    })

    backup_path = GeomCrossSection.set_blocked_obstructions(
        geom_file,
        "1000",
        new_obstructions,
    )

    assert backup_path is not None
    assert backup_path.exists()
    roundtrip = GeomCrossSection.get_blocked_obstructions(geom_file, "1000")
    assert np.allclose(roundtrip["start_sta"], new_obstructions["start_sta"])
    assert np.allclose(roundtrip["end_sta"], new_obstructions["end_sta"])
    assert np.allclose(roundtrip["elevation"], new_obstructions["elevation"])

    xs_df = GeomCrossSection.get_cross_sections(geom_file)
    assert list(xs_df["RS"]) == ["1000", "2000"]

    text = geom_file.read_text(encoding="utf-8")
    target_block = text.split("#Block Obstruct= 4\n", 1)[1].split("Bank Sta=", 1)[0]
    data_lines = [line for line in target_block.splitlines() if line.strip()]
    assert len(data_lines) == 2


def test_set_blocked_obstructions_updates_existing_block(tmp_path):
    geom_file = _write_geom(
        tmp_path,
        blocked_obstructions=[
            (111.0, 222.0, 91.0),
            (333.0, 444.0, 92.0),
        ],
    )

    GeomCrossSection.set_blocked_obstructions(
        geom_file,
        f"{RIVER}|{REACH}|1000",
        [(555.0, 666.0, 93.0)],
        create_backup=False,
    )

    roundtrip = GeomCrossSection.get_blocked_obstructions(geom_file, "1000")
    assert len(roundtrip) == 1
    assert np.isclose(roundtrip["start_sta"].iloc[0], 555.0)
    assert "#Block Obstruct= 1" in geom_file.read_text(encoding="utf-8")


def test_validate_blocked_obstructions_hdf_compares_text_counts_to_mode(tmp_path, monkeypatch):
    geom_file = _write_geom(
        tmp_path,
        blocked_obstructions=[
            (100.0, 200.0, 91.5),
        ],
    )
    hdf_file = tmp_path / "clb306.g01.hdf"
    hdf_file.write_text("stub", encoding="utf-8")

    from ras_commander.hdf.HdfXsec import HdfXsec

    def fake_get_cross_sections(hdf_path, datetime_to_str=True, ras_object=None):
        return pd.DataFrame({
            "River": [RIVER, RIVER],
            "Reach": [REACH, REACH],
            "RS": ["1000", "2000"],
            "Obstr Block Mode": [1, 0],
        })

    monkeypatch.setattr(HdfXsec, "get_cross_sections", staticmethod(fake_get_cross_sections))

    validation = GeomCrossSection.validate_blocked_obstructions_hdf(
        geom_file,
        hdf_path=hdf_file,
    )

    assert list(validation["text_obstruction_count"]) == [1, 0]
    assert list(validation["hdf_has_blocked_obstructions"]) == [True, False]
    assert validation["matches_hdf"].all()


def test_rasfixit_repairs_blocked_obstructions_through_geom_api(tmp_path):
    geom_file = _write_geom(
        tmp_path,
        blocked_obstructions=[
            (100.0, 200.0, 91.0),
            (150.0, 250.0, 90.0),
        ],
    )

    results = RasFixit.fix_blocked_obstructions(
        geom_file,
        backup=False,
        dry_run=False,
    )

    assert results.total_xs_fixed == 1
    fixed_df = GeomCrossSection.get_blocked_obstructions(geom_file, "1000")
    fixed = [
        BlockedObstruction(row.start_sta, row.end_sta, row.elevation)
        for row in fixed_df.itertuples()
    ]
    assert not has_overlaps(fixed)
    assert np.isclose(fixed_df["start_sta"].iloc[1], 200.02)


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


def test_set_station_elevation_expanding_block_preserves_following_xs(tmp_path):
    geom_file = _write_geom(tmp_path, include_banks=True)
    new_profile = pd.DataFrame({
        "Station": [0.0, 100.0, 200.0, 400.0, 800.0, 1000.0],
        "Elevation": [100.0, 98.0, 94.0, 93.0, 98.0, 100.0],
    })

    GeomCrossSection.set_station_elevation(
        geom_file, RIVER, REACH, "1000", new_profile, create_backup=False
    )

    xs_df = GeomCrossSection.get_cross_sections(geom_file)
    assert list(xs_df["RS"]) == ["1000", "2000"]
    assert len(GeomCrossSection.get_station_elevation(geom_file, RIVER, REACH, "1000")) == 6
    assert len(GeomCrossSection.get_station_elevation(geom_file, RIVER, REACH, "2000")) == 4

    text = geom_file.read_text(encoding="utf-8")
    target_block = text.split("Type RM Length L Ch R = 1 ,1000", 1)[1].split(
        "Type RM Length L Ch R = 1 ,2000", 1
    )[0]
    assert "#Mann= 2 , 0 , 0" in target_block
    assert "Bank Sta=200,800" in target_block


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


def test_set_expansion_contraction_preserves_new_value_precision(tmp_path):
    geom_file = _write_geom(tmp_path, include_banks=True, include_exp_cntr=True)
    geom_file.write_text(
        geom_file.read_text(encoding="utf-8").replace(
            "Exp/Cntr=0.30,0.10",
            "Exp/Cntr=0.3,0.1",
        ),
        encoding="utf-8",
    )

    GeomCrossSection.set_expansion_contraction(
        geom_file, RIVER, REACH, "1000", 0.45, 0.15, create_backup=False
    )

    assert GeomCrossSection.get_expansion_contraction(geom_file, RIVER, REACH, "1000") == (
        0.45,
        0.15,
    )
    assert "Exp/Cntr=0.45,0.15" in geom_file.read_text(encoding="utf-8")


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


def _write_geom_with_levees(tmp_path: Path):
    text = (
        "Geom Title=CLB-639 Test\n"
        "Program Version=6.50\n"
        f"River Reach={RIVER}    ,{REACH}\n"
        "Reach XY= 2\n"
        "         0.00         0.00\n"
        "      3000.00         0.00\n"
        + _xs_block(
            "1000",
            [0.0, 100.0, 500.0, 90.0, 1000.0, 100.0],
            bank_line="Bank Sta=200,800\n",
            levee_line="Levee=-1,125.5,105.25,-1,875.25,106.5,,\n",
        )
        + _xs_block(
            "2000",
            [0.0, 102.0, 250.0, 95.0, 750.0, 95.0, 1000.0, 102.0],
            bank_line="Bank Sta=250,850\n",
            levee_line="Levee=0,,,-1,900,103.75,,\n",
        )
        + _xs_block(
            "3000",
            [0.0, 103.0, 300.0, 96.0, 900.0, 97.0, 1000.0, 104.0],
            bank_line="Bank Sta=300,900\n",
        )
    )

    geom_file = tmp_path / "clb639.g01"
    geom_file.write_text(text, encoding="utf-8")
    return geom_file


def test_get_levees_reads_multiple_xs_and_missing_values(tmp_path):
    geom_file = _write_geom_with_levees(tmp_path)

    levees = GeomCrossSection.get_levees(geom_file, river=RIVER, reach=REACH)

    assert {
        "xs_id", "River", "Reach", "RS",
        "left_station", "left_elevation",
        "right_station", "right_elevation",
    }.issubset(levees.columns)
    assert list(levees["xs_id"]) == [
        f"{RIVER}|{REACH}|1000",
        f"{RIVER}|{REACH}|2000",
        f"{RIVER}|{REACH}|3000",
    ]

    xs_1000 = levees.loc[levees["xs_id"].eq(f"{RIVER}|{REACH}|1000")].iloc[0]
    assert np.isclose(xs_1000["left_station"], 125.5)
    assert np.isclose(xs_1000["left_elevation"], 105.25)
    assert np.isclose(xs_1000["right_station"], 875.25)
    assert np.isclose(xs_1000["right_elevation"], 106.5)

    xs_2000 = levees.loc[levees["xs_id"].eq(f"{RIVER}|{REACH}|2000")].iloc[0]
    assert np.isnan(xs_2000["left_station"])
    assert np.isnan(xs_2000["left_elevation"])
    assert np.isclose(xs_2000["right_station"], 900.0)
    assert np.isclose(xs_2000["right_elevation"], 103.75)

    xs_3000 = levees.loc[levees["xs_id"].eq(f"{RIVER}|{REACH}|3000")].iloc[0]
    assert np.isnan(xs_3000["left_station"])
    assert np.isnan(xs_3000["right_station"])


def test_set_levees_updates_and_inserts_round_trip(tmp_path):
    geom_file = _write_geom_with_levees(tmp_path)

    backup_path = GeomCrossSection.set_levees(
        geom_file,
        f"{RIVER}|{REACH}|1000",
        left_station=150.0,
        left_elevation=108.5,
        right_station=None,
        right_elevation=None,
    )
    assert backup_path is not None
    assert backup_path.exists()

    GeomCrossSection.set_levees(
        geom_file,
        left_station=None,
        left_elevation=None,
        right_station=920.25,
        right_elevation=109.75,
        river=RIVER,
        reach=REACH,
        rs="3000",
        create_backup=False,
    )

    levees = GeomCrossSection.get_levees(geom_file, river=RIVER, reach=REACH)
    xs_1000 = levees.loc[levees["xs_id"].eq(f"{RIVER}|{REACH}|1000")].iloc[0]
    assert np.isclose(xs_1000["left_station"], 150.0)
    assert np.isclose(xs_1000["left_elevation"], 108.5)
    assert np.isnan(xs_1000["right_station"])
    assert np.isnan(xs_1000["right_elevation"])

    xs_3000 = levees.loc[levees["xs_id"].eq(f"{RIVER}|{REACH}|3000")].iloc[0]
    assert np.isnan(xs_3000["left_station"])
    assert np.isclose(xs_3000["right_station"], 920.25)
    assert np.isclose(xs_3000["right_elevation"], 109.75)

    text = geom_file.read_text(encoding="utf-8")
    assert "Levee=-1,150.0,108.50,0,,,,\n" in text

    target_block = text.split("Type RM Length L Ch R = 1 ,3000", 1)[1]
    mann_idx = target_block.index("#Mann= 2 , 0 , 0\n")
    levee_idx = target_block.index("Levee=0,,,-1,920.25,109.75,,\n")
    assert mann_idx < levee_idx
