"""Completion contracts on native-layout HDF fixtures, including ghost cells."""

import hashlib
import time

import h5py
import numpy as np
import pytest

from ras_commander.geom._preprocess_contract import (
    AREA,
    CELL_PRODUCTS,
    FACE_PRODUCTS,
    _projection_equal,
    invalidate_products,
    snapshot,
    validate,
)


def fixture(tmp_path):
    text = tmp_path / "Synthetic.g01"
    text.write_text(
        "Geom Title=Synthetic\nStorage Area=Synthetic,0,0\nStorage Area Surface Line= 4\n"
        + "\n".join(f"{x:16.6f}{y:16.6f}" for x, y in [(0, 0), (1, 0), (1, 1), (0, 0)])
        + "\nStorage Area Is2D=-1\nStorage Area 2D Points= 2\n"
        + f"{0.2:16.6f}{0.2:16.6f}{0.6:16.6f}{0.6:16.6f}\n"
    )
    path = text.with_suffix(".g01.hdf")
    with h5py.File(tmp_path / "Soils.hdf", "w") as soils:
        soils.attrs["LC Type"] = np.bytes_("InfiltrationSCSCurveNumber")
    with h5py.File(path, "w") as hdf:
        hdf.attrs["File Type"] = np.bytes_("HEC-RAS Geometry")
        hdf.attrs["File Version"] = np.bytes_("HEC-RAS 6.6")
        hdf.create_dataset("Projection", data=np.bytes_("synthetic projected CRS"))
        hdf.create_group("Geometry")
        hdf["Geometry"].attrs["Infiltration Filename"] = np.bytes_("Soils.hdf")
        hdf.create_dataset(
            f"{AREA}/Attributes",
            data=np.array(
                [(b"Synthetic", 2)], dtype=[("Name", "S16"), ("Cell Count", "i4")]
            ),
        )
        hdf.create_dataset(f"{AREA}/Cell Info", data=[[0, 2]])
        hdf.create_dataset(f"{AREA}/Cell Points", data=[[0.2, 0.2], [0.6, 0.6]])
        hdf.create_dataset(f"{AREA}/Polygon Info", data=[[0, 4, 0, 1]])
        hdf.create_dataset(
            f"{AREA}/Polygon Points", data=[[0, 0], [1, 0], [1, 1], [0, 0]]
        )
    expected = snapshot(text, path)
    # Test the compiled native product dimensions separately from text parser
    # checks, which have their own real-format regressions in GeomMesh.
    expected["areas"] = {"Synthetic": {"seed_count": 2}}
    products(path)
    return text, path, expected


def products(path):
    with h5py.File(path, "r+") as hdf:
        hdf.require_group("Geometry/GeomPreprocess").create_dataset(
            "Node Info", data=[1]
        )
        area = hdf.require_group(f"{AREA}/Synthetic")
        area.create_dataset("Cells Center Coordinate", data=np.zeros((3, 2)))
        area.create_dataset("FacePoints Coordinate", data=np.zeros((4, 2)))
        area.create_dataset("Faces FacePoint Indexes", data=[[0, 1], [1, 2]])
        area.create_dataset("Faces Cell Indexes", data=[[0, 1], [1, 2]])
        for name, shape in (
            ("Cells Face and Orientation Info", (3, 2)),
            ("Cells Face and Orientation Values", (4, 2)),
            ("Cells FacePoint Indexes", (3, 4)),
            ("Faces NormalUnitVector and Length", (2, 3)),
            ("Faces Perimeter Info", (2, 2)),
            ("Faces Perimeter Values", (2, 2)),
            ("FacePoints Cell Info", (4, 2)),
            ("FacePoints Cell Index Values", (4,)),
            ("FacePoints Face and Orientation Info", (4, 2)),
            ("FacePoints Face and Orientation Values", (4, 2)),
            ("FacePoints Is Perimeter", (4,)),
        ):
            area.create_dataset(name, data=np.zeros(shape, dtype=int))
        for name in CELL_PRODUCTS[:3]:
            area.create_dataset(name, data=np.ones(3))
        for name in FACE_PRODUCTS[2:]:
            area.create_dataset(name, data=np.ones(2))
        area.create_dataset(
            "Cells Volume Elevation Info", data=[[0, 2], [2, 2], [4, 0]]
        )
        area.create_dataset("Cells Volume Elevation Values", data=np.ones((4, 2)))
        area.create_dataset("Faces Area Elevation Info", data=[[0, 2], [2, 2]])
        area.create_dataset("Faces Area Elevation Values", data=np.ones((4, 4)))
        area.attrs["Infiltration Filename"] = np.bytes_("Soils.hdf")
        area.create_dataset("Infiltration/Cell Center Classifications", data=[1, 1])
        area.create_dataset("Infiltration/Face Center Classifications", data=[1, 1])
        area.create_dataset("Infiltration/Curve Number", data=[75.0, 75.0])
        area.create_dataset("Infiltration/Abstraction Ratio", data=[0.2, 0.2])
        area.create_dataset("Infiltration/Minimum Infiltration Rate", data=[0.0, 0.0])
        area.create_dataset("Infiltration/Properties", data=[1])


def manning_region(text, path, outside=True):
    origin = 2.0 if outside else 0.1
    coordinates = np.array(
        [
            (origin, origin),
            (origin + 0.2, origin),
            (origin + 0.2, origin + 0.1),
            (origin, origin),
        ]
    )
    with text.open("a") as stream:
        stream.write(
            "LCMann Region Name=Override\nLCMann Region Table=1\nOpen Water,0.04\nLCMann Region Polygon=4\n"
        )
        stream.write("".join(f"{x:16.6f}{y:16.6f}" for x, y in coordinates) + "\n")
    group = "Geometry/Land Cover (Manning's n)"
    with h5py.File(path, "r+") as hdf:
        hdf.create_dataset(
            group + "/Attributes",
            data=np.array(
                [(b"Override", b"" if outside else b"Synthetic")],
                dtype=[("Name", "S16"), ("2D Area Name", "S16")],
            ),
        )
        hdf.create_dataset(group + "/Polygon Info", data=[[0, 4, 0, 1]])
        hdf.create_dataset(group + "/Polygon Parts", data=[[0, 4]])
        hdf.create_dataset(group + "/Polygon Points", data=coordinates)
    return snapshot(text, path)


def test_disjoint_manning_polygon_preserved_without_inapplicable_mappings(tmp_path):
    text, path, _ = fixture(tmp_path)
    expected = manning_region(text, path)
    changed, missing, evidence = validate(text, path, expected, time.time() - 1)
    assert changed == missing == []
    assert evidence["manning_region_interactions"] == [
        {"name": "Override", "areas": [], "reason": "outside_current_mesh"}
    ]


def test_intersecting_manning_polygon_still_requires_mappings(tmp_path):
    text, path, _ = fixture(tmp_path)
    expected = manning_region(text, path, outside=False)
    changed, missing, _ = validate(text, path, expected, time.time() - 1)
    assert changed == []
    assert all(
        any(name in issue for issue in missing)
        for name in ["External Faces", "Internal Faces", "Internal Cells"]
    )


def test_disjoint_manning_polygon_change_is_not_waived(tmp_path):
    text, path, _ = fixture(tmp_path)
    expected = manning_region(text, path)
    with h5py.File(path, "r+") as hdf:
        hdf["Geometry/Land Cover (Manning's n)/Polygon Points"][0, 0] += 0.01
    assert any(
        "authored identity or coordinates changed" in issue
        for issue in validate(text, path, expected, time.time() - 1)[0]
    )


def test_disjoint_region_does_not_accept_stale_attachment_indexes(tmp_path):
    text, path, _ = fixture(tmp_path)
    expected = manning_region(text, path)
    with h5py.File(path, "r+") as hdf:
        hdf.create_dataset(
            "Geometry/Land Cover (Manning's n)/Internal Cells",
            data=np.array(
                [(0, 999)], dtype=[("Region ID", "i4"), ("Cell Index", "i4")]
            ),
        )
    assert any(
        "indexes outside current mesh" in issue
        for issue in validate(text, path, expected, time.time() - 1)[1]
    )


def test_table_name_without_polygon_has_no_attachment_requirement(tmp_path):
    text, path, _ = fixture(tmp_path)
    with text.open("a") as stream:
        stream.write(
            "LCMann Region Name=TableOnly\nLCMann Region Table=1\nOpen Water,0.04\n"
        )
    expected = snapshot(text, path)
    assert expected["manning_regions"] == []
    assert validate(text, path, expected, time.time() - 1)[:2] == ([], [])


def test_disjoint_region_rejects_even_in_bounds_stale_attachment(tmp_path):
    text, path, _ = fixture(tmp_path)
    expected = manning_region(text, path)
    with h5py.File(path, "r+") as hdf:
        group = hdf["Geometry/Land Cover (Manning's n)"]
        attrs = group["Attributes"][()]
        attrs["2D Area Name"] = b"Synthetic"
        group["Attributes"][:] = attrs
        group.create_dataset(
            "Internal Cells",
            data=np.array([(0, 0)], dtype=[("Region ID", "i4"), ("Cell Index", "i4")]),
        )
    assert any(
        "outside authored region interaction" in issue
        for issue in validate(text, path, expected, time.time() - 1)[1]
    )


def test_disjoint_proof_requires_complete_perimeter_inventory(tmp_path, monkeypatch):
    from ras_commander import GeomStorage

    text, path, _ = fixture(tmp_path)
    manning_region(text, path)
    areas = GeomStorage.get_storage_area_polygons(text, exclude_2d=False)
    monkeypatch.setattr(
        GeomStorage, "get_storage_area_polygons", lambda *args, **kwargs: areas.iloc[:0]
    )
    with pytest.raises(ValueError, match="incomplete current 2D perimeter inventory"):
        snapshot(text, path)


def test_polygon_part_topology_is_preserved(tmp_path):
    text, path, _ = fixture(tmp_path)
    expected = manning_region(text, path)
    with h5py.File(path, "r+") as hdf:
        hdf["Geometry/Land Cover (Manning's n)/Polygon Parts"][0, 1] = 3
    assert any(
        "polygon part ranges" in issue
        for issue in validate(text, path, expected, time.time() - 1)[0]
    )


@pytest.mark.parametrize(
    "name",
    ["Curve Number", "Abstraction Ratio", "Minimum Infiltration Rate", "Properties"],
)
def test_associated_method_requires_every_infiltration_product(tmp_path, name):
    text, path, expected = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        del hdf[f"{AREA}/Synthetic/Infiltration/{name}"]
    assert any(
        name in error for error in validate(text, path, expected, time.time() - 1)[1]
    )


def test_control_products_include_interior_and_ghost_cells(tmp_path, monkeypatch):
    text, path, expected = fixture(tmp_path)
    changed, missing, evidence = validate(text, path, expected, time.time() - 1)
    assert changed == missing == []
    assert evidence["areas"]["Synthetic"] == {
        "interior_cells": 2,
        "total_cells": 3,
        "faces": 2,
    }


@pytest.mark.parametrize(
    "marker",
    [
        "Connection=Bridge,0,0",
        "SA/2D Area Conn=Bridge",
        "Bridge Culvert-",
        "IW Pilot Flow=0",
        "Lat Struct=Lateral",
        "Type RM Length L Ch R = 2,100,0,0,0",
        "Type RM Length L Ch R = unknown,100",
    ],
)
def test_authored_structure_unknown_product_schema_fails_before_mutation(
    tmp_path, marker
):
    text, path, _ = fixture(tmp_path)
    original = path.read_bytes()
    with text.open("a") as stream:
        stream.write(marker + "\n")
    with pytest.raises(
        NotImplementedError, match="GEOMETRY_PRODUCTS_SCHEMA_UNSUPPORTED"
    ):
        snapshot(text, path)
    assert path.read_bytes() == original


def test_hdf_only_infiltration_override_loss_is_rejected(tmp_path):
    text, path, _ = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        hdf.create_dataset("Geometry/Infiltration/Base Overrides", data=[75.0])
    expected = snapshot(text, path)
    with h5py.File(path, "r+") as hdf:
        del hdf["Geometry/Infiltration/Base Overrides"]
    assert (
        "Geometry/Infiltration/Base Overrides"
        in validate(text, path, expected, time.time() - 1)[0]
    )


@pytest.mark.parametrize("name", [*CELL_PRODUCTS, *FACE_PRODUCTS])
def test_missing_product_is_rejected_even_with_populated_topology(
    tmp_path, monkeypatch, name
):
    text, path, expected = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        del hdf[f"{AREA}/Synthetic/{name}"]
    changed, missing, _ = validate(text, path, expected, time.time() - 1)
    assert not changed
    assert f"{AREA}/Synthetic/{name}" in missing


def test_stale_parent_products_are_invalidated_without_restoring_them(tmp_path):
    _, path, _ = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        del hdf[f"{AREA}/Synthetic/Cells Minimum Elevation"]
        hdf.create_dataset(
            f"{AREA}/Synthetic/Cells Minimum Elevation", data=np.ones(800)
        )
        hdf.create_dataset(
            "Geometry/Land Cover (Manning's n)/Internal Faces", data=[999]
        )
    removed = invalidate_products(path)
    assert f"{AREA}/Synthetic/Cells Minimum Elevation" in removed
    with h5py.File(path, "r") as hdf:
        assert f"{AREA}/Synthetic/Cells Minimum Elevation" not in hdf
        assert f"{AREA}/Synthetic/Cells Center Coordinate" in hdf
        assert "Projection" in hdf
        assert "Geometry/Land Cover (Manning's n)/Internal Faces" not in hdf


@pytest.mark.parametrize("span", [[0, -1], [3, 2], [0, 0]])
def test_malformed_active_cell_table_ranges_fail(tmp_path, monkeypatch, span):
    text, path, expected = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        hdf[f"{AREA}/Synthetic/Cells Volume Elevation Info"][0] = span
    assert any(
        "invalid packed ranges" in error
        for error in validate(text, path, expected, time.time() - 1)[1]
    )


def test_authored_projection_value_change_fails(tmp_path, monkeypatch):
    text, path, expected = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        del hdf["Projection"]
        hdf.create_dataset("Projection", data=np.bytes_("different CRS"))
    assert validate(text, path, expected, time.time() - 1)[0] == ["Projection"]


def test_projection_accepts_equivalent_native_wkt_encoding(tmp_path):
    from pyproj import CRS

    text, path, _ = fixture(tmp_path)
    source = CRS.from_epsg(2278)
    before = source.to_wkt(version="WKT1_ESRI")
    after = source.to_wkt(version="WKT2_2019")
    with h5py.File(path, "r+") as hdf:
        hdf.attrs["Projection"] = np.bytes_(before)
    expected = snapshot(text, path)
    with h5py.File(path, "r+") as hdf:
        hdf.attrs["Projection"] = after
    assert validate(text, path, expected, time.time() - 1)[0] == []


@pytest.mark.parametrize("different", ["EPSG:2277", "OGC:CRS84"])
def test_real_projection_or_axis_change_is_rejected(different):
    reference = "EPSG:2278" if different == "EPSG:2277" else "EPSG:4326"
    assert not _projection_equal(reference, different)


def test_native_esri_projection_rounding_and_parallel_order_are_equivalent():
    from pyproj import CRS

    after = CRS.from_epsg(2278).to_wkt(version="WKT1_ESRI")
    before = (
        after.replace(
            'PARAMETER["False_Northing",13123333.333]',
            'PARAMETER["False_Northing",13123333.33333333]',
        )
        .replace(
            'PARAMETER["Standard_Parallel_1",30.2833333333333]',
            'PARAMETER["Standard_Parallel_1",28.38333333333333]',
        )
        .replace(
            'PARAMETER["Standard_Parallel_2",28.3833333333333]',
            'PARAMETER["Standard_Parallel_2",30.28333333333333]',
        )
    )
    assert before != after
    assert _projection_equal(before, after)


def test_unchanged_text_does_not_hide_missing_authored_bc(tmp_path, monkeypatch):
    text, path, expected = fixture(tmp_path)
    expected["features"]["Geometry/Boundary Condition Lines"] = 1
    expected["feature_geometry"]["Geometry/Boundary Condition Lines"] = [
        {
            "name": "Inlet",
            "storage_area": "Synthetic",
            "coordinates": np.array([[0.0, 0.0], [1.0, 0.0]]),
        }
    ]
    assert (
        "Geometry/Boundary Condition Lines"
        in validate(text, path, expected, time.time() - 1)[0]
    )


def test_empty_authored_2d_area_is_rejected(tmp_path, monkeypatch):
    text, path, expected = fixture(tmp_path)
    expected["areas"]["Synthetic"]["seed_count"] = 0
    assert any(
        "no computation points" in error
        for error in validate(text, path, expected, time.time() - 1)[1]
    )


def test_text_modification_is_not_accepted_as_recompiled_input(tmp_path, monkeypatch):
    text, path, expected = fixture(tmp_path)
    text.write_text("Geom Title=changed\n")
    assert "geometry text" in validate(text, path, expected, time.time() - 1)[0]
    assert expected["text_sha256"] != hashlib.sha256(text.read_bytes()).hexdigest()
