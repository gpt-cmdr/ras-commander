"""Tests for HEC-RAS reference line generation and parsing."""

from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import GeomReferenceFeatures
from ras_commander.hdf import HdfBndry


shapely = pytest.importorskip("shapely")
from shapely.geometry import LineString  # noqa: E402


def test_generate_reference_lines_from_simple_longitudinal_line():
    centerline = LineString([(0.0, 0.0), (1000.0, 0.0)])

    lines = GeomReferenceFeatures.generate_reference_lines_from_longitudinal_line(
        centerline,
        spacing=250.0,
        line_length=100.0,
        longitudinal_line_name="Main",
        name_template="{source_name}_{station_int}",
    )

    assert [line["station"] for line in lines] == [
        0.0,
        250.0,
        500.0,
        750.0,
        1000.0,
    ]
    assert [line["name"] for line in lines] == [
        "Main_0",
        "Main_250",
        "Main_500",
        "Main_750",
        "Main_1000",
    ]
    assert lines[2]["source_name"] == "Main"
    assert lines[2]["orientation"] == "normal"
    assert np.isclose(lines[2]["orientation_angle"], 90.0)
    assert np.allclose(lines[2]["coordinates"], [(500.0, -50.0), (500.0, 50.0)])


def test_generate_reference_lines_selects_named_geodataframe_row():
    gpd = pytest.importorskip("geopandas")

    gdf = gpd.GeoDataFrame(
        {
            "Name": ["Upstream", "Target"],
            "geometry": [
                LineString([(0.0, 0.0), (100.0, 0.0)]),
                LineString([(0.0, 0.0), (0.0, 200.0)]),
            ],
        },
        geometry="geometry",
    )

    lines = GeomReferenceFeatures.generate_reference_lines_from_longitudinal_line(
        gdf,
        longitudinal_line_name="Target",
        spacing=100.0,
        line_length=40.0,
        name_template="{source_name}_{index:02d}",
    )

    assert len(lines) == 3
    assert [line["name"] for line in lines] == [
        "Target_01",
        "Target_02",
        "Target_03",
    ]
    assert lines[1]["station"] == 100.0
    assert np.isclose(lines[1]["orientation_angle"], 180.0)
    assert np.allclose(lines[1]["coordinates"], [(20.0, 100.0), (-20.0, 100.0)])


def test_velocity_orientation_metadata_drives_reference_line_angle(monkeypatch):
    def fake_velocity_samples(station_points, **kwargs):
        return [
            {
                "orientation_angle": 0.0,
                "velocity_x": 0.0,
                "velocity_y": 1.0,
                "velocity": 1.0,
                "depth": 2.0,
                "mesh_name": "Mesh 1",
                "cell_id": idx,
                "distance": 0.0,
            }
            for idx, _point in enumerate(station_points)
        ]

    monkeypatch.setattr(
        GeomReferenceFeatures,
        "_sample_velocity_orientation",
        staticmethod(fake_velocity_samples),
    )

    lines = GeomReferenceFeatures.generate_reference_lines_from_longitudinal_line(
        LineString([(0.0, 0.0), (100.0, 0.0)]),
        spacing=100.0,
        line_length=20.0,
        longitudinal_line_name="Channel",
        orientation="velocity",
        orientation_plan_hdf="dummy.p01.hdf",
    )

    assert lines[0]["orientation"] == "velocity"
    assert np.isclose(lines[0]["orientation_angle"], 0.0)
    assert np.allclose(lines[0]["coordinates"], [(-10.0, 0.0), (10.0, 0.0)])


def test_add_reference_lines_from_longitudinal_line_round_trips_plain_text(tmp_path):
    geom_file = tmp_path / "Model.g01"
    geom_file.write_text(
        "Geom Title=Test\n"
        "LCMann TimeDateStamp=01JAN2026 0000\n",
        encoding="utf-8",
    )

    count = GeomReferenceFeatures.add_reference_lines_from_longitudinal_line(
        geom_file,
        LineString([(0.0, 0.0), (200.0, 0.0)]),
        storage_area="Mesh 1",
        spacing=100.0,
        line_length=80.0,
        longitudinal_line_name="Channel",
        name_template="{source_name}_{index}",
    )

    assert count == 3
    assert Path(str(geom_file) + ".bak").exists()

    parsed = GeomReferenceFeatures.get_reference_lines(geom_file)
    assert [line["name"] for line in parsed] == [
        "Channel_1",
        "Channel_2",
        "Channel_3",
    ]
    assert {line["storage_area"] for line in parsed} == {"Mesh 1"}
    assert np.allclose(parsed[1]["coordinates"], [(100.0, -40.0), (100.0, 40.0)])


def test_generated_reference_lines_match_hdf_reference_line_schema(tmp_path):
    hdf_path = tmp_path / "Model.g01.hdf"
    generated = GeomReferenceFeatures.generate_reference_lines_from_longitudinal_line(
        [(0.0, 0.0), (200.0, 0.0)],
        spacing=100.0,
        line_length=80.0,
        longitudinal_line_name="Channel",
        name_template="{source_name}_{index}",
    )

    attr_dtype = np.dtype(
        [
            ("Name", "S40"),
            ("SA-2D", "S16"),
            ("Type", "S24"),
        ]
    )
    attributes = np.array(
        [
            (
                line["name"].encode("utf-8"),
                b"Mesh 1",
                b"Reference Line",
            )
            for line in generated
        ],
        dtype=attr_dtype,
    )
    points = np.array(
        [point for line in generated for point in line["coordinates"]],
        dtype=np.float64,
    )
    info = np.array(
        [
            (idx * 2, 2, idx, 1)
            for idx in range(len(generated))
        ],
        dtype=np.int32,
    )
    parts = np.array(
        [(idx * 2, 2) for idx in range(len(generated))],
        dtype=np.int32,
    )

    with h5py.File(hdf_path, "w") as hdf:
        group = hdf.create_group("Geometry/Reference Lines")
        group.create_dataset("Attributes", data=attributes)
        group.create_dataset("Polyline Info", data=info)
        group.create_dataset("Polyline Parts", data=parts)
        group.create_dataset("Polyline Points", data=points)

    hdf_lines = HdfBndry.get_reference_lines(hdf_path, mesh_name="Mesh 1")

    assert len(hdf_lines) == len(generated)
    assert hdf_lines["Name"].tolist() == [line["name"] for line in generated]
    assert hdf_lines["mesh_name"].tolist() == ["Mesh 1"] * len(generated)
    assert hdf_lines.geometry.iloc[1].equals_exact(
        LineString(generated[1]["coordinates"]),
        tolerance=1.0e-9,
    )
