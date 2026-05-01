from importlib import import_module

import numpy as np
import pytest


gpd = pytest.importorskip("geopandas")
pytest.importorskip("shapely")
h5py = pytest.importorskip("h5py")

ras_terrain_module = import_module("ras_commander.terrain.RasTerrain")
RasTerrain = ras_terrain_module.RasTerrain


def _format_sta_elev(pairs):
    values = []
    for station, elevation in pairs:
        values.append(f"{station:8.1f}")
        values.append(f"{elevation:8.1f}")
    return "".join(values)


def _write_text_geometry(path):
    sta_elev = _format_sta_elev([
        (0.0, 100.0),
        (100.0, 95.0),
        (500.0, 90.0),
        (900.0, 95.0),
        (1000.0, 100.0),
    ])

    sections = []
    for rs, y in [
        ("3000.000", 3000.0),
        ("2000.000", 2000.0),
        ("1000.000", 1000.0),
    ]:
        sections.append(
            f"""Type RM Length L Ch R = 1 ,{rs},     0.0,     0.0,     0.0
Node Last Edited Time=Jan/01/2026 00:00:00
Bank Sta=100,900
XS GIS Cut Line=2
             0.0          {y:.1f}
          1000.0          {y:.1f}
Node Name=
#Sta/Elev= 5
{sta_elev}
#Mann= 3 , 0 , 0
     0   .04     0     0 100   .035    0     0 900   .04     0     0
"""
        )

    path.write_text(
        "Geom Title=Bank Line Test\n"
        "Program Version=6.50\n"
        "River Reach=TestRiver    ,TestReach\n"
        "Reach XY= 2\n"
        "             0.0          4000.0\n"
        "             0.0             0.0\n"
        + "".join(sections),
        encoding="utf-8",
    )


def _write_geometry_hdf(path):
    station_values_one = np.array(
        [
            [0.0, 100.0],
            [100.0, 95.0],
            [500.0, 90.0],
            [900.0, 95.0],
            [1000.0, 100.0],
        ],
        dtype="f8",
    )
    station_values = np.vstack([station_values_one] * 3)
    mann_values_one = np.array(
        [
            [0.0, 0.04],
            [100.0, 0.035],
            [900.0, 0.04],
        ],
        dtype="f8",
    )
    mann_values = np.vstack([mann_values_one] * 3)

    attrs_dtype = np.dtype(
        [
            ("River", "S32"),
            ("Reach", "S32"),
            ("RS", "S32"),
            ("Name", "S32"),
            ("Description", "S32"),
            ("Len Left", "f8"),
            ("Len Channel", "f8"),
            ("Len Right", "f8"),
            ("Left Bank", "f8"),
            ("Right Bank", "f8"),
            ("Friction Mode", "S16"),
            ("Contr", "f8"),
            ("Expan", "f8"),
        ]
    )
    attrs = np.array(
        [
            (
                b"TestRiver",
                b"TestReach",
                b"3000.000",
                b"",
                b"",
                0.0,
                0.0,
                0.0,
                100.0,
                900.0,
                b"",
                0.1,
                0.3,
            ),
            (
                b"TestRiver",
                b"TestReach",
                b"2000.000",
                b"",
                b"",
                0.0,
                0.0,
                0.0,
                100.0,
                900.0,
                b"",
                0.1,
                0.3,
            ),
            (
                b"TestRiver",
                b"TestReach",
                b"1000.000",
                b"",
                b"",
                0.0,
                0.0,
                0.0,
                100.0,
                900.0,
                b"",
                0.1,
                0.3,
            ),
        ],
        dtype=attrs_dtype,
    )

    with h5py.File(path, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        xsec = geometry.create_group("Cross Sections")
        xsec.create_dataset(
            "Polyline Info",
            data=np.array(
                [
                    [0, 2, 0, 1],
                    [2, 2, 1, 1],
                    [4, 2, 2, 1],
                ],
                dtype="i8",
            ),
        )
        xsec.create_dataset(
            "Polyline Parts",
            data=np.array(
                [
                    [0, 2],
                    [0, 2],
                    [0, 2],
                ],
                dtype="i8",
            ),
        )
        xsec.create_dataset(
            "Polyline Points",
            data=np.array(
                [
                    [0.0, 3000.0],
                    [1000.0, 3000.0],
                    [0.0, 2000.0],
                    [1000.0, 2000.0],
                    [0.0, 1000.0],
                    [1000.0, 1000.0],
                ],
                dtype="f8",
            ),
        )
        xsec.create_dataset(
            "Station Elevation Info",
            data=np.array([[0, 5], [5, 5], [10, 5]], dtype="i8"),
        )
        xsec.create_dataset("Station Elevation Values", data=station_values)
        xsec.create_dataset(
            "Manning's n Info",
            data=np.array([[0, 3], [3, 3], [6, 3]], dtype="i8"),
        )
        xsec.create_dataset("Manning's n Values", data=mann_values)
        xsec.create_dataset("Attributes", data=attrs)


def test_compute_bank_lines_from_text_geometry(tmp_path):
    geom_path = tmp_path / "BankLineTest.g01"
    _write_text_geometry(geom_path)

    bank_lines = RasTerrain.compute_bank_lines(geom_path, crs="EPSG:26915")

    assert isinstance(bank_lines, gpd.GeoDataFrame)
    assert list(bank_lines["bank_side"]) == ["Left", "Right"]
    assert bank_lines.crs.to_epsg() == 26915

    left = bank_lines[bank_lines["bank_side"] == "Left"].iloc[0]
    right = bank_lines[bank_lines["bank_side"] == "Right"].iloc[0]

    assert left["river"] == "TestRiver"
    assert left["reach"] == "TestReach"
    assert left["xs_count"] == 3
    assert left["rs_values"] == ["3000.000", "2000.000", "1000.000"]
    assert list(left.geometry.coords) == [
        (100.0, 3000.0),
        (100.0, 2000.0),
        (100.0, 1000.0),
    ]
    assert list(right.geometry.coords) == [
        (900.0, 3000.0),
        (900.0, 2000.0),
        (900.0, 1000.0),
    ]
    assert left["length"] == pytest.approx(2000.0)
    assert right["length"] == pytest.approx(2000.0)


def test_compute_bank_lines_from_geometry_hdf(tmp_path):
    hdf_path = tmp_path / "BankLineTest.g01.hdf"
    _write_geometry_hdf(hdf_path)

    bank_lines = RasTerrain.compute_bank_lines(hdf_path, crs="EPSG:26915")

    assert isinstance(bank_lines, gpd.GeoDataFrame)
    assert list(bank_lines["bank_side"]) == ["Left", "Right"]
    assert bank_lines.crs.to_epsg() == 26915

    left = bank_lines[bank_lines["bank_side"] == "Left"].iloc[0]
    right = bank_lines[bank_lines["bank_side"] == "Right"].iloc[0]

    assert left["river"] == "TestRiver"
    assert left["reach"] == "TestReach"
    assert left["xs_count"] == 3
    assert left["rs_values"] == ["3000.000", "2000.000", "1000.000"]
    assert list(left.geometry.coords) == [
        (100.0, 3000.0),
        (100.0, 2000.0),
        (100.0, 1000.0),
    ]
    assert list(right.geometry.coords) == [
        (900.0, 3000.0),
        (900.0, 2000.0),
        (900.0, 1000.0),
    ]
    assert left["length"] == pytest.approx(2000.0)
    assert right["length"] == pytest.approx(2000.0)


def test_compute_bank_lines_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="Geometry file not found"):
        RasTerrain.compute_bank_lines(tmp_path / "missing.g01")
