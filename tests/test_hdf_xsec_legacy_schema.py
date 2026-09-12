from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import HdfXsec
from ras_commander.RasPrj import RasPrj
from ras_commander.geom.GeomMetadata import GeomMetadata
from ras_commander.hdf.HdfBase import HdfBase


def _write_legacy_geometry_hdf(path: Path) -> None:
    float32_missing = np.finfo(np.float32).max
    with h5py.File(path, "w") as hdf:
        xs = hdf.create_group("Geometry/Cross Sections")
        xs.create_dataset(
            "Polyline Info",
            data=np.array([[0, 2, 0, 1], [2, 3, 1, 1]], dtype=np.int32),
        )
        xs.create_dataset(
            "Polyline Parts",
            data=np.array([[0, 2], [0, 3]], dtype=np.int32),
        )
        xs.create_dataset(
            "Polyline Points",
            data=np.array(
                [[0.0, 10.0], [10.0, 10.0], [0.0, 0.0], [5.0, 1.0], [10.0, 0.0]],
                dtype=np.float64,
            ),
        )
        xs.create_dataset(
            "Station Elevation Info",
            data=np.array([[0, 3], [3, 3]], dtype=np.int32),
        )
        xs.create_dataset(
            "Station Elevation Values",
            data=np.array(
                [
                    [0.0, 101.0],
                    [5.0, 99.0],
                    [10.0, 101.0],
                    [0.0, 98.0],
                    [5.0, 96.0],
                    [10.0, 98.0],
                ],
                dtype=np.float32,
            ),
        )
        xs.create_dataset(
            "Station Manning's n Info",
            data=np.array([[0, 3], [3, 4]], dtype=np.int32),
        )
        xs.create_dataset(
            "Station Manning's n Values",
            data=np.array(
                [
                    [0.0, 0.04],
                    [2.0, 0.03],
                    [8.0, 0.05],
                    [0.0, 0.045],
                    [2.0, 0.035],
                    [8.0, 0.04],
                    [10.0, 0.05],
                ],
                dtype=np.float32,
            ),
        )
        xs.create_dataset("River Names", data=np.array([b"River A", b"River A"], dtype="S16"))
        xs.create_dataset("Reach Names", data=np.array([b"Reach 1", b"Reach 1"], dtype="S16"))
        xs.create_dataset("River Stations", data=np.array([b"200", b"100"], dtype="S8"))
        xs.create_dataset("Node Names", data=np.array([b"Upper", b"Lower"], dtype="S16"))
        xs.create_dataset(
            "Node Descriptions",
            data=np.array([b"Upstream section", b"Downstream section"], dtype="S64"),
        )
        xs.create_dataset(
            "Lengths",
            data=np.array(
                [[100.0, 110.0, 120.0], [float32_missing] * 3],
                dtype=np.float32,
            ),
        )
        xs.create_dataset(
            "Bank Stations",
            data=np.array([[2.0, 8.0], [2.0, 8.0]], dtype=np.float32),
        )
        xs.create_dataset(
            "Contr Expan Coef",
            data=np.array([[0.1, 0.3], [0.2, 0.4]], dtype=np.float32),
        )
        xs.create_dataset(
            "Hydraulic Tables Starting Elevation and Increment Size",
            data=np.array([[95.0, 1.0], [94.0, 0.5]], dtype=np.float32),
        )
        xs.create_dataset(
            "Hydraulic Tables Vertical and Horizontal Slices",
            data=np.array([[20, 5, 6, 7], [30, 8, 9, 10]], dtype=np.int32),
        )
        xs.create_dataset(
            "Blocked Ineffective Info",
            data=np.array([[0, 1], [1, 0]], dtype=np.int32),
        )
        xs.create_dataset(
            "Blocked Ineffective Values",
            data=np.array([[0.0, 1.5, 100.0]], dtype=np.float32),
        )

        centerline = hdf.create_group("Geometry/River Centerlines")
        centerline.create_dataset(
            "Polyline Info", data=np.array([[0, 3, 0, 1]], dtype=np.int32)
        )
        centerline.create_dataset(
            "Polyline Parts", data=np.array([[0, 3]], dtype=np.int32)
        )
        centerline.create_dataset(
            "Polyline Points",
            data=np.array([[5.0, 12.0], [5.0, 5.0], [5.0, -2.0]], dtype=np.float64),
        )
        centerline.create_dataset("River Names", data=np.array([b"River A"], dtype="S16"))
        centerline.create_dataset("Reach Names", data=np.array([b"Reach 1"], dtype="S16"))
        for name in ("US Junction", "US SA-2D", "DS Junction", "DS SA-2D"):
            centerline.create_dataset(name, data=np.array([b""], dtype="S16"))

        bank_lines = hdf.create_group("Geometry/River Bank Lines")
        bank_lines.create_dataset(
            "Bank Lines Info",
            data=np.array([[0, 2, 0, 1], [2, 2, 1, 1]], dtype=np.int32),
        )
        bank_lines.create_dataset(
            "Bank Lines Parts", data=np.array([[0, 2], [0, 2]], dtype=np.int32)
        )
        bank_lines.create_dataset(
            "Bank Lines Points",
            data=np.array(
                [[2.0, 12.0], [2.0, -2.0], [8.0, 12.0], [8.0, -2.0]],
                dtype=np.float64,
            ),
        )


def _convert_fixture_to_modern_schema(path: Path) -> None:
    attributes_dtype = np.dtype(
        [
            ("River", "S16"),
            ("Reach", "S16"),
            ("RS", "S8"),
            ("Name", "S16"),
            ("Description", "S64"),
            ("Len Left", "f4"),
            ("Len Channel", "f4"),
            ("Len Right", "f4"),
            ("Left Bank", "f4"),
            ("Right Bank", "f4"),
            ("Contr", "f4"),
            ("Expan", "f4"),
        ]
    )
    attributes = np.array(
        [
            (
                b"River A",
                b"Reach 1",
                b"200",
                b"Upper",
                b"Upstream section",
                100.0,
                110.0,
                120.0,
                2.0,
                8.0,
                0.1,
                0.3,
            ),
            (
                b"River A",
                b"Reach 1",
                b"100",
                b"Lower",
                b"Downstream section",
                0.0,
                0.0,
                0.0,
                2.0,
                8.0,
                0.2,
                0.4,
            ),
        ],
        dtype=attributes_dtype,
    )
    ineffective_dtype = np.dtype(
        [
            ("Left Sta", "f4"),
            ("Right Sta", "f4"),
            ("Elevation", "f4"),
            ("Permanent", "?"),
        ]
    )

    with h5py.File(path, "a") as hdf:
        xs = hdf["Geometry/Cross Sections"]
        xs.create_dataset("Attributes", data=attributes)
        xs.move("Station Manning's n Info", "Manning's n Info")
        xs.move("Station Manning's n Values", "Manning's n Values")
        xs.create_dataset("Ineffective Info", data=xs["Blocked Ineffective Info"][()])
        xs.create_dataset(
            "Ineffective Blocks",
            data=np.array([(0.0, 1.5, 100.0, True)], dtype=ineffective_dtype),
        )
        legacy_only = (
            "River Names",
            "Reach Names",
            "River Stations",
            "Node Names",
            "Node Descriptions",
            "Lengths",
            "Bank Stations",
            "Contr Expan Coef",
            "Hydraulic Tables Starting Elevation and Increment Size",
            "Hydraulic Tables Vertical and Horizontal Slices",
            "Blocked Ineffective Info",
            "Blocked Ineffective Values",
        )
        for name in legacy_only:
            del xs[name]

        centerline = hdf["Geometry/River Centerlines"]
        centerline_dtype = np.dtype(
            [
                ("River Name", "S16"),
                ("Reach Name", "S16"),
                ("US Type", "S16"),
                ("US Name", "S16"),
                ("DS Type", "S16"),
                ("DS Name", "S16"),
            ]
        )
        centerline.create_dataset(
            "Attributes",
            data=np.array(
                [(b"River A", b"Reach 1", b"External", b"", b"External", b"")],
                dtype=centerline_dtype,
            ),
        )

        bank_lines = hdf["Geometry/River Bank Lines"]
        bank_lines.move("Bank Lines Info", "Polyline Info")
        bank_lines.move("Bank Lines Parts", "Polyline Parts")
        bank_lines.move("Bank Lines Points", "Polyline Points")


def test_reads_hec_ras_5_separated_cross_section_schema(tmp_path, monkeypatch):
    hdf_path = tmp_path / "Legacy.g01.hdf"
    _write_legacy_geometry_hdf(hdf_path)
    monkeypatch.setattr(HdfBase, "get_projection", lambda *_args, **_kwargs: "EPSG:26916")

    cross_sections = HdfXsec.get_cross_sections(hdf_path)

    assert len(cross_sections) == 2
    assert cross_sections.crs.to_epsg() == 26916
    assert cross_sections["River"].tolist() == ["River A", "River A"]
    assert cross_sections["Reach"].tolist() == ["Reach 1", "Reach 1"]
    assert cross_sections["RS"].tolist() == ["200", "100"]
    assert cross_sections["Name"].tolist() == ["Upper", "Lower"]
    assert cross_sections.geometry.apply(lambda geometry: len(geometry.coords)).tolist() == [2, 3]
    assert cross_sections.iloc[0]["station_elevation"].shape == (3, 2)
    assert cross_sections.iloc[1]["mannings_n"]["Mann n"] == pytest.approx(
        [0.045, 0.035, 0.04, 0.05]
    )
    assert cross_sections["n_lob"].tolist() == pytest.approx([0.04, 0.045])
    assert cross_sections["n_channel"].tolist() == pytest.approx([0.03, 0.035])
    assert cross_sections["n_rob"].tolist() == pytest.approx([0.05, 0.04])
    assert cross_sections["Len Channel"].iloc[0] == pytest.approx(110.0)
    assert np.isnan(cross_sections["Len Channel"].iloc[1])
    assert cross_sections["Contr"].tolist() == pytest.approx([0.1, 0.2])
    assert cross_sections["Expan"].tolist() == pytest.approx([0.3, 0.4])
    assert cross_sections["HP Count"].tolist() == [20, 30]
    assert cross_sections["HP Chan Slices"].tolist() == [6, 9]
    assert cross_sections.iloc[0]["ineffective_blocks"] == [
        {
            "Left Sta": 0.0,
            "Right Sta": 1.5,
            "Elevation": 100.0,
            "Permanent": False,
        }
    ]
    assert cross_sections.iloc[1]["ineffective_blocks"] == []


def test_legacy_schema_count_classifies_as_1d(tmp_path):
    hdf_path = tmp_path / "Legacy.g01.hdf"
    _write_legacy_geometry_hdf(hdf_path)

    metadata = GeomMetadata.get_geometry_counts(None, hdf_path)

    assert metadata["geometry_metadata_source"] == "hdf"
    assert metadata["geometry_metadata_valid"] is True
    assert metadata["num_cross_sections"] == 2
    assert metadata["has_1d_xs"] is True
    assert metadata["has_2d_mesh"] is False
    assert RasPrj._classify_geometry(pd.Series(metadata)) == "1D"


def test_legacy_schema_row_mismatch_fails_closed(tmp_path):
    hdf_path = tmp_path / "Legacy.g01.hdf"
    _write_legacy_geometry_hdf(hdf_path)
    with h5py.File(hdf_path, "a") as hdf:
        del hdf["Geometry/Cross Sections/Node Names"]
        hdf["Geometry/Cross Sections"].create_dataset(
            "Node Names", data=np.array([b"Only one"], dtype="S16")
        )

    metadata = GeomMetadata.get_geometry_counts(None, hdf_path)

    assert metadata["geometry_metadata_valid"] is False
    assert metadata["has_1d_xs"] is None
    assert "row count mismatch" in metadata["geometry_metadata_error"]
    assert HdfXsec.get_cross_sections(hdf_path).empty


def test_legacy_schema_out_of_bounds_profile_slice_fails_closed(tmp_path):
    hdf_path = tmp_path / "Legacy.g01.hdf"
    _write_legacy_geometry_hdf(hdf_path)
    with h5py.File(hdf_path, "a") as hdf:
        hdf["Geometry/Cross Sections/Station Elevation Info"][1] = [5, 2]

    assert HdfXsec.get_cross_sections(hdf_path).empty


def test_legacy_schema_fractional_profile_slice_fails_closed(tmp_path):
    hdf_path = tmp_path / "Legacy.g01.hdf"
    _write_legacy_geometry_hdf(hdf_path)
    with h5py.File(hdf_path, "a") as hdf:
        xs = hdf["Geometry/Cross Sections"]
        del xs["Station Elevation Info"]
        xs.create_dataset(
            "Station Elevation Info",
            data=np.array([[0.0, 3.0], [3.5, 2.0]], dtype=np.float64),
        )

    assert HdfXsec.get_cross_sections(hdf_path).empty


def test_legacy_schema_out_of_bounds_declared_polyline_fails_closed(tmp_path):
    hdf_path = tmp_path / "Legacy.g01.hdf"
    _write_legacy_geometry_hdf(hdf_path)
    with h5py.File(hdf_path, "a") as hdf:
        hdf["Geometry/Cross Sections/Polyline Info"][0] = [0, 99, 0, 1]

    assert HdfXsec.get_cross_sections(hdf_path).empty


def test_reads_legacy_centerline_and_bank_line_schemas(tmp_path, monkeypatch):
    hdf_path = tmp_path / "Legacy.g01.hdf"
    _write_legacy_geometry_hdf(hdf_path)
    monkeypatch.setattr(HdfBase, "get_projection", lambda *_args, **_kwargs: None)

    centerlines = HdfXsec.get_river_centerlines(hdf_path)
    reaches = HdfXsec.get_river_reaches(hdf_path)
    bank_lines = HdfXsec.get_river_bank_lines(hdf_path)

    assert len(centerlines) == 1
    assert centerlines.loc[0, "River Name"] == "River A"
    assert centerlines.loc[0, "Reach Name"] == "Reach 1"
    assert centerlines.loc[0, "US Type"] == "External"
    assert centerlines.loc[0, "DS Type"] == "External"
    assert len(centerlines.geometry.iloc[0].coords) == 3
    assert reaches["river_id"].tolist() == [0]
    assert reaches["River Name"].tolist() == ["River A"]
    assert len(bank_lines) == 2
    assert bank_lines["bank_side"].tolist() == ["Left", "Right"]
    assert bank_lines.geometry.apply(lambda geometry: len(geometry.coords)).tolist() == [2, 2]


def test_multipart_legacy_centerline_preserves_disjoint_parts(tmp_path, monkeypatch):
    hdf_path = tmp_path / "Legacy.g01.hdf"
    _write_legacy_geometry_hdf(hdf_path)
    monkeypatch.setattr(HdfBase, "get_projection", lambda *_args, **_kwargs: None)
    with h5py.File(hdf_path, "a") as hdf:
        centerline = hdf["Geometry/River Centerlines"]
        del centerline["Polyline Info"]
        del centerline["Polyline Parts"]
        del centerline["Polyline Points"]
        centerline.create_dataset(
            "Polyline Info", data=np.array([[0, 4, 0, 2]], dtype=np.int32)
        )
        centerline.create_dataset(
            "Polyline Parts", data=np.array([[0, 2], [2, 2]], dtype=np.int32)
        )
        centerline.create_dataset(
            "Polyline Points",
            data=np.array(
                [[5.0, 12.0], [5.0, 8.0], [6.0, 2.0], [6.0, -2.0]],
                dtype=np.float64,
            ),
        )

    centerlines = HdfXsec.get_river_centerlines(hdf_path)

    assert len(centerlines) == 1
    assert centerlines.geometry.iloc[0].geom_type == "MultiLineString"
    assert len(centerlines.geometry.iloc[0].geoms) == 2

    with h5py.File(hdf_path, "a") as hdf:
        hdf["Geometry/River Centerlines/Polyline Parts"][:] = [[0, 2], [1, 2]]

    assert HdfXsec.get_river_centerlines(hdf_path).empty


def test_modern_compound_schema_remains_supported(tmp_path, monkeypatch):
    hdf_path = tmp_path / "Modern.g01.hdf"
    _write_legacy_geometry_hdf(hdf_path)
    _convert_fixture_to_modern_schema(hdf_path)
    monkeypatch.setattr(HdfBase, "get_projection", lambda *_args, **_kwargs: None)

    cross_sections = HdfXsec.get_cross_sections(hdf_path)

    assert len(cross_sections) == 2
    assert cross_sections["RS"].tolist() == ["200", "100"]
    assert cross_sections["Len Channel"].tolist() == pytest.approx([110.0, 0.0])
    assert cross_sections.iloc[0]["mannings_n"]["Mann n"] == pytest.approx(
        [0.04, 0.03, 0.05]
    )
    assert cross_sections.iloc[0]["ineffective_blocks"][0]["Permanent"] is True

    centerlines = HdfXsec.get_river_centerlines(hdf_path)
    bank_lines = HdfXsec.get_river_bank_lines(hdf_path)
    assert centerlines["River Name"].tolist() == ["River A"]
    assert centerlines["US Type"].tolist() == ["External"]
    assert bank_lines["bank_side"].tolist() == ["Left", "Right"]
