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


@pytest.mark.parametrize("reverse", [False, True])
def test_native_perimeter_requires_exact_fixed_width_serialization(reverse):
    from ras_commander.geom._preprocess_contract import _perimeter_serialization_matches
    from ras_commander.geom.GeomStorage import GeomStorage
    from ras_commander.geom.GeomParser import GeomParser

    native = np.array(
        [
            [1762812.6010300105, 13948229.492235743],
            [1762912.6010300105, 13948229.492235743],
            [1762912.6010300105, 13948329.492235743],
            [1762812.6010300105, 13948229.492235743],
        ]
    )
    text = np.array(
        [
            v
            for line in GeomStorage._format_surface_line_lines(native)
            for v in GeomParser.parse_fixed_width(line, 16)
        ]
    ).reshape(-1, 2)
    assert not np.array_equal(native, text)
    assert _perimeter_serialization_matches(native, text[::-1] if reverse else text)
    moved = native.copy()
    moved[1, 0] += 1e-5
    assert not _perimeter_serialization_matches(moved, text)


@pytest.mark.synthetic_hdf_layout
def test_bound_native_perimeter_must_remain_exactly_unchanged(tmp_path):
    text, path, expected = fixture(tmp_path)
    ring = expected["perimeters"]["Synthetic"].copy()
    expected["native_perimeters"] = {"Synthetic": ring}
    with h5py.File(path, "r+") as h:
        h[f"{AREA}/Synthetic"].create_dataset("Perimeter", data=ring)
    changed, missing, evidence = validate(text, path, expected, time.time() - 1)
    assert not changed and not missing
    assert (
        evidence["areas"]["Synthetic"]["perimeter_binding"]
        == "exact_fixed_width_serialization"
    )
    with h5py.File(path, "r+") as h:
        ds = h[f"{AREA}/Synthetic/Perimeter"]
        ds[1, 0] += 1e-9
    changed, _, _ = validate(text, path, expected, time.time() - 1)
    assert any("bound native perimeter changed" in issue for issue in changed)


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
        area.create_dataset(
            "Cells Center Coordinate", data=[[0.2, 0.2], [0.6, 0.6], [2.0, 2.0]]
        )
        area.create_dataset(
            "FacePoints Coordinate",
            data=np.array([[0, 0], [1, 0], [1, 1], [0.5, 0.25]], dtype=float),
        )
        area.create_dataset("Faces FacePoint Indexes", data=[[0, 1], [1, 2]])
        area.create_dataset("Faces Cell Indexes", data=[[0, 1], [1, 2]])
        for name, data in {
            "Cells Face and Orientation Info": [[0, 1], [1, 2], [3, 1]],
            "Cells Face and Orientation Values": [[0, 1], [0, -1], [1, 1], [1, -1]],
            "Cells FacePoint Indexes": [[0, 1, -1, -1], [0, 1, 2, -1], [1, 2, -1, -1]],
            "Faces NormalUnitVector and Length": [[0, -1, 1], [1, 0, 1]],
            "Faces Perimeter Info": [[0, 0], [0, 0]],
            "Faces Perimeter Values": np.empty((0, 2)),
            "FacePoints Cell Info": [[0, 2], [2, 3], [5, 2], [7, 0]],
            "FacePoints Cell Index Values": [0, 1, 0, 1, 2, 1, 2],
            "FacePoints Face and Orientation Info": [[0, 1], [1, 2], [3, 1], [4, 0]],
            "FacePoints Face and Orientation Values": [
                [0, -1],
                [0, 1],
                [1, -1],
                [1, 1],
            ],
            "FacePoints Is Perimeter": [0, 0, 0, 0],
        }.items():
            area.create_dataset(name, data=data)
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


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize(
    "dataset,value",
    [
        ("Cells FacePoint Indexes", 999999),
        ("Cells Face and Orientation Info", 999999),
        ("FacePoints Coordinate", 999999),
        ("Faces Cell Indexes", 0),
        ("Cells Face and Orientation Values", 999999),
        ("FacePoints Cell Info", 999999),
        ("FacePoints Cell Index Values", 999999),
        ("FacePoints Face and Orientation Info", 999999),
        ("FacePoints Face and Orientation Values", 999999),
        ("Faces NormalUnitVector and Length", 0),
        ("Faces Perimeter Info", 999999),
        ("FacePoints Is Perimeter", 99),
    ],
)
def test_corrupt_required_topology_fails_completion(tmp_path, dataset, value):
    text, path, _ = fixture(tmp_path)
    expected = snapshot(text, path)
    assert validate(text, path, expected, time.time() - 1)[:2] == ([], [])
    with h5py.File(path, "r+") as hdf:
        hdf[f"{AREA}/Synthetic/{dataset}"][...] = value
    changed, missing, evidence = validate(text, path, expected, time.time() - 1)
    assert missing and not evidence["products_complete"]
    assert changed == []  # Regenerated products, rather than authored inputs.


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize(
    "dataset,index,value",
    [
        ("Cells Face and Orientation Info", (1, 0), 0),
        ("Cells Face and Orientation Values", (0, 1), -1),
        ("FacePoints Face and Orientation Values", (0, 1), 1),
        ("FacePoints Cell Index Values", 0, 2),
        ("Cells FacePoint Indexes", (0, 1), 2),
        ("Cells FacePoint Indexes", (0, 2), 0),
        ("Faces Cell Indexes", (0, 0), 2),
        ("Faces FacePoint Indexes", (0, 0), 2),
        ("FacePoints Coordinate", (0, 0), 0.1),
    ],
)
def test_in_domain_but_inconsistent_topology_fails(tmp_path, dataset, index, value):
    text, path, expected = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        hdf[f"{AREA}/Synthetic/{dataset}"][index] = value
    assert validate(text, path, expected, time.time() - 1)[1]


@pytest.mark.synthetic_hdf_layout
def test_fresh_child_topology_replaces_stale_parent_without_preserving_indexes(
    tmp_path,
):
    text, path, _ = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        hdf[f"{AREA}/Synthetic/Cells FacePoint Indexes"][...] = 999999
        hdf[f"{AREA}/Synthetic/Cells Face and Orientation Info"][...] = 999999
    expected = snapshot(text, path)
    assert validate(text, path, expected, time.time() - 1)[1]
    with h5py.File(path, "r+") as hdf:
        del hdf[f"{AREA}/Synthetic"]
        del hdf["Geometry/GeomPreprocess"]
    products(path)
    assert validate(text, path, expected, time.time() - 1)[:2] == ([], [])


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize(
    "dataset", ["FacePoints Coordinate", "Cells Center Coordinate"]
)
def test_coherent_translation_is_not_current_authored_mesh(tmp_path, dataset):
    text, path, expected = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        obj = hdf[f"{AREA}/Synthetic/{dataset}"]
        obj[...] = obj[()] + 1_000_000
    changed, missing, evidence = validate(text, path, expected, time.time() - 1)
    assert not changed and missing
    assert not evidence["products_complete"]


@pytest.mark.synthetic_hdf_layout
def test_centers_require_exact_native_precision_but_ghosts_are_not_seeds(tmp_path):
    text, path, expected = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        obj = hdf[f"{AREA}/Synthetic/Cells Center Coordinate"]
        obj[2] = [-100, -100]  # Ghost centers can lie outside the perimeter.
    assert validate(text, path, expected, time.time() - 1)[:2] == ([], [])
    with h5py.File(path, "r+") as hdf:
        obj = hdf[f"{AREA}/Synthetic/Cells Center Coordinate"]
        obj[0, 0] = np.nextafter(obj[0, 0], np.inf)
    assert any(
        "interior centers" in v
        for v in validate(text, path, expected, time.time() - 1)[1]
    )


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("direction", [-np.inf, np.inf])
def test_current_native_seed_mirror_allows_one_ulp_decimal_parsing(tmp_path, direction):
    text, path, expected = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        current = hdf[f"{AREA}/Cell Points"][()]
        current[0, 0] = np.nextafter(current[0, 0], direction)
        hdf[f"{AREA}/Cell Points"][...] = current
        hdf[f"{AREA}/Synthetic/Cells Center Coordinate"][:2] = current
    assert validate(text, path, expected, time.time() - 1)[:2] == ([], [])


@pytest.mark.synthetic_hdf_layout(
    "1000000.0",
    "two_ulps",
)
@pytest.mark.parametrize("value", [np.nan, np.inf, 1_000_000.0, "two_ulps"])
def test_current_native_seed_and_center_displacement_is_not_waived(tmp_path, value):
    text, path, expected = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        current = hdf[f"{AREA}/Cell Points"][()]
        current[0, 0] = (
            np.nextafter(np.nextafter(current[0, 0], np.inf), np.inf)
            if value == "two_ulps"
            else value
        )
        hdf[f"{AREA}/Cell Points"][...] = current
        hdf[f"{AREA}/Synthetic/Cells Center Coordinate"][:2] = current
    changed, _, evidence = validate(text, path, expected, time.time() - 1)
    assert any("authored computation points changed" in issue for issue in changed)
    assert not evidence["inputs_preserved"]


@pytest.mark.synthetic_hdf_layout
def test_regenerated_seed_mirror_replaces_stale_parent_coordinates(tmp_path):
    text, path, expected = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        hdf[f"{AREA}/Cell Points"][...] = [[99.0, 99.0], [98.0, 98.0]]
    expected = snapshot(text, path)
    with h5py.File(path, "r+") as hdf:
        hdf[f"{AREA}/Cell Points"][...] = [[0.2, 0.2], [0.6, 0.6]]
    assert validate(text, path, expected, time.time() - 1)[:2] == ([], [])


@pytest.mark.synthetic_hdf_layout
def test_face_perimeter_roundoff_and_concave_ring(tmp_path):
    from ras_commander.geom._preprocess_contract import _mesh_binding_issues

    _, path, expected = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        area = hdf[f"{AREA}/Synthetic"]
        points = area["FacePoints Coordinate"]
        ring = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
        points[0] = [0.0, -np.spacing(1.0)]
        assert not _mesh_binding_issues(
            area, expected["seed_points"]["Synthetic"], ring
        )
        points[0] = [0.0, -16 * np.spacing(1.0)]
        assert _mesh_binding_issues(area, expected["seed_points"]["Synthetic"], ring)
        points[...] = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.5, 0.75]]
        concave = np.array(
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.5, 0.25], [0.0, 1.0]]
        )
        for current in (concave, concave[::-1]):
            assert _mesh_binding_issues(
                area, expected["seed_points"]["Synthetic"], current
            )


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("bend", [False, True])
@pytest.mark.parametrize("offset", [(0.0, 0.0), (1_000_000.0, 10_000_000.0)])
def test_native_concave_face_uses_intermediates_not_endpoint_chord(
    tmp_path, reverse, bend, offset
):
    from ras_commander.geom._preprocess_contract import _mesh_binding_issues

    _, path, expected = fixture(tmp_path)
    ring = np.array([(0, 0), (1, 0), (0.8, 0.5), (1, 1), (0, 1), (0, 0)])
    with h5py.File(path, "r+") as hdf:
        area = hdf[f"{AREA}/Synthetic"]
        if bend:
            del area["Faces Perimeter Values"]
            area.create_dataset("Faces Perimeter Values", data=[[0.8, 0.5]])
            area["Faces Perimeter Info"][...] = [[0, 0], [0, 1]]
        ring += offset
        for name in (
            "Cells Center Coordinate",
            "FacePoints Coordinate",
            "Faces Perimeter Values",
        ):
            area[name][...] = area[name][()] + offset
        issues = _mesh_binding_issues(
            area,
            expected["seed_points"]["Synthetic"] + offset,
            ring[::-1] if reverse else ring,
        )
    assert bool(issues) is (not bend)
    if not bend:
        assert any("face segments outside" in issue for issue in issues)


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("bend", [False, True])
@pytest.mark.parametrize("offset", [(0.0, 0.0), (-1_000_000.0, 10_000_000.0)])
def test_native_faces_honor_keyhole_ring_and_ghosts(tmp_path, reverse, bend, offset):
    from ras_commander.geom._preprocess_contract import _mesh_binding_issues

    _, path, expected = fixture(tmp_path)
    ring = np.array(
        [
            (0, 0),
            (1, 0),
            (1, 1),
            (0, 1),
            (0, 0),
            (0.4, 0.3),
            (0.4, 0.5),
            (0.6, 0.5),
            (0.6, 0.3),
            (0.4, 0.3),
            (0, 0),
        ]
    )
    with h5py.File(path, "r+") as hdf:
        area = hdf[f"{AREA}/Synthetic"]
        area["FacePoints Coordinate"][...] = [
            [0.2, 0.4],
            [0.8, 0.4],
            [0.8, 0.8],
            [0.1, 0.1],
        ]
        area["Cells Center Coordinate"][2] = [100.0, 100.0]
        if bend:
            del area["Faces Perimeter Values"]
            area.create_dataset("Faces Perimeter Values", data=[[0.4, 0.3], [0.6, 0.3]])
            area["Faces Perimeter Info"][...] = [[0, 2], [2, 0]]
        ring += offset
        for name in (
            "Cells Center Coordinate",
            "FacePoints Coordinate",
            "Faces Perimeter Values",
        ):
            area[name][...] = area[name][()] + offset
        issues = _mesh_binding_issues(
            area,
            expected["seed_points"]["Synthetic"] + offset,
            ring[::-1] if reverse else ring,
        )
    assert bool(issues) is (not bend)


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("sign", [1, -1])
def test_slanted_offset_boundary_binding_is_read_only(tmp_path, reverse, sign):
    from ras_commander.geom._preprocess_contract import _mesh_binding_issues

    _, path, _ = fixture(tmp_path)
    ring = sign * (
        np.array([(0.0, 0.0), (5670.0, 216.0), (2472.0, 3239.0), (0.0, 6000.0)])
        + [1_000_000.0, 10_000_000.0]
    )
    if reverse:
        ring = ring[::-1].copy()
    ring = np.vstack([ring, ring[0]])
    seeds = np.array([ring[:4].mean(axis=0)])
    with h5py.File(path, "r+") as hdf:
        area = hdf[f"{AREA}/Synthetic"]
        replacements = {
            "Cells Center Coordinate": seeds,
            "Cells FacePoint Indexes": [[0, 1, 2, 3]],
            "FacePoints Coordinate": ring[:4],
            "Faces FacePoint Indexes": [[0, 1], [1, 2], [2, 3], [3, 0]],
            "Faces Perimeter Info": [[0, 1], [1, 1], [2, 1], [3, 1]],
            "Faces Perimeter Values": (ring[:4] + np.roll(ring[:4], -1, axis=0)) / 2,
        }
        for name, data in replacements.items():
            del area[name]
            area.create_dataset(name, data=data)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    original_ring, original_seeds = ring.copy(), seeds.copy()
    with h5py.File(path, "r") as hdf:
        assert not _mesh_binding_issues(hdf[f"{AREA}/Synthetic"], seeds, ring)
    assert np.array_equal(ring, original_ring)
    assert np.array_equal(seeds, original_seeds)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("offset", [(0.0, 0.0), (1_000_000.0, 10_000_000.0)])
@pytest.mark.parametrize("ulps", [4, 8, 16])
@pytest.mark.parametrize("target", ["endpoint", "intermediate", "seed"])
def test_local_binding_preserves_world_ulp_limit(tmp_path, offset, ulps, target):
    from ras_commander.geom._preprocess_contract import _mesh_binding_issues

    _, path, expected = fixture(tmp_path)
    ring = np.array([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]) + offset
    seeds = expected["seed_points"]["Synthetic"] + offset
    spacing = np.spacing(max(1.0, float(np.max(np.abs(ring)))))
    with h5py.File(path, "r+") as hdf:
        area = hdf[f"{AREA}/Synthetic"]
        area["Cells Center Coordinate"][...] = (
            area["Cells Center Coordinate"][()] + offset
        )
        area["FacePoints Coordinate"][...] = area["FacePoints Coordinate"][()] + offset
        if target == "endpoint":
            area["FacePoints Coordinate"][0] = [offset[0], offset[1] - ulps * spacing]
        elif target == "intermediate":
            del area["Faces Perimeter Values"]
            area.create_dataset(
                "Faces Perimeter Values",
                data=[[offset[0] + 0.5, offset[1] - ulps * spacing]],
            )
            area["Faces Perimeter Info"][...] = [[0, 1], [1, 0]]
        else:
            area["Cells Center Coordinate"][0] = seeds[0] + [ulps * spacing, 0.0]
        issues = _mesh_binding_issues(area, seeds, ring)
    assert bool(issues) is (target == "seed" or ulps > 8)
    if target == "seed":
        assert any("interior centers differ" in issue for issue in issues)


@pytest.mark.synthetic_hdf_layout
def test_exterior_native_intermediate_vertex_fails_complete_contract(tmp_path):
    text, path, expected = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        area = hdf[f"{AREA}/Synthetic"]
        del area["Faces Perimeter Values"]
        area.create_dataset("Faces Perimeter Values", data=[[1_000_000.0, 1_000_000.0]])
        area["Faces Perimeter Info"][...] = [[0, 0], [0, 1]]
    changed, missing, evidence = validate(text, path, expected, time.time() - 1)
    assert not changed and any(
        "Faces Perimeter Values: points outside" in issue for issue in missing
    )
    assert not evidence["products_complete"]


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


@pytest.mark.synthetic_hdf_layout
def test_disjoint_manning_polygon_preserved_without_inapplicable_mappings(tmp_path):
    text, path, _ = fixture(tmp_path)
    expected = manning_region(text, path)
    changed, missing, evidence = validate(text, path, expected, time.time() - 1)
    assert changed == missing == []
    assert evidence["manning_region_interactions"] == [
        {"name": "Override", "areas": [], "reason": "outside_current_mesh"}
    ]


@pytest.mark.synthetic_hdf_layout
def test_intersecting_manning_polygon_still_requires_mappings(tmp_path):
    text, path, _ = fixture(tmp_path)
    expected = manning_region(text, path, outside=False)
    changed, missing, _ = validate(text, path, expected, time.time() - 1)
    assert changed == []
    assert all(
        any(name in issue for issue in missing)
        for name in ["External Faces", "Internal Faces", "Internal Cells"]
    )


@pytest.mark.synthetic_hdf_layout
def test_disjoint_manning_polygon_change_is_not_waived(tmp_path):
    text, path, _ = fixture(tmp_path)
    expected = manning_region(text, path)
    with h5py.File(path, "r+") as hdf:
        hdf["Geometry/Land Cover (Manning's n)/Polygon Points"][0, 0] += 0.01
    assert any(
        "authored identity or coordinates changed" in issue
        for issue in validate(text, path, expected, time.time() - 1)[0]
    )


@pytest.mark.synthetic_hdf_layout
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


@pytest.mark.synthetic_hdf_layout
def test_table_name_without_polygon_has_no_attachment_requirement(tmp_path):
    text, path, _ = fixture(tmp_path)
    with text.open("a") as stream:
        stream.write(
            "LCMann Region Name=TableOnly\nLCMann Region Table=1\nOpen Water,0.04\n"
        )
    expected = snapshot(text, path)
    assert expected["manning_regions"] == []
    assert validate(text, path, expected, time.time() - 1)[:2] == ([], [])


@pytest.mark.synthetic_hdf_layout
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


@pytest.mark.synthetic_hdf_layout
def test_polygon_part_topology_is_preserved(tmp_path):
    text, path, _ = fixture(tmp_path)
    expected = manning_region(text, path)
    with h5py.File(path, "r+") as hdf:
        hdf["Geometry/Land Cover (Manning's n)/Polygon Parts"][0, 1] = 3
    assert any(
        "polygon part ranges" in issue
        for issue in validate(text, path, expected, time.time() - 1)[0]
    )


@pytest.mark.synthetic_hdf_layout
def test_current_explicit_bc_type_survives_reclassification(tmp_path):
    text, path, _ = fixture(tmp_path)
    points = np.array([[0.0, 0.0], [0.2, 0.2]])
    with text.open("a") as stream:
        stream.write(
            "BC Line Name=Outlet\nBC Line Arc=2\n"
            + "".join(f"{x:16.6f}{y:16.6f}" for x, y in points)
            + "\n"
        )
    with h5py.File(path, "r+") as hdf:
        group = hdf.create_group("Geometry/Boundary Condition Lines")
        group.create_dataset(
            "Attributes",
            data=np.array(
                [(b"Outlet", b"Synthetic", b"External")],
                dtype=[("Name", "S16"), ("SA-2D", "S16"), ("Type", "S16")],
            ),
        )
        group.create_dataset("Polyline Info", data=[[0, 2, 0, 1]])
        group.create_dataset("Polyline Points", data=points)
    expected = snapshot(text, path)
    assert (
        expected["feature_geometry"]["Geometry/Boundary Condition Lines"][0]["bc_type"]
        == b"External"
    )
    with h5py.File(path, "r+") as hdf:
        attrs = hdf["Geometry/Boundary Condition Lines/Attributes"][()]
        attrs["Type"] = b"Internal"
        hdf["Geometry/Boundary Condition Lines/Attributes"][:] = attrs
    assert any(
        "authored BC Type changed" in issue
        for issue in validate(text, path, expected, time.time() - 1)[0]
    )
    with h5py.File(path, "r+") as hdf:
        attrs = hdf["Geometry/Boundary Condition Lines/Attributes"][()]
        attrs["Name"] = b"ParentOnly"
        hdf["Geometry/Boundary Condition Lines/Attributes"][:] = attrs
    fresh_expected = snapshot(text, path)
    assert (
        "bc_type"
        not in fresh_expected["feature_geometry"]["Geometry/Boundary Condition Lines"][
            0
        ]
    )


@pytest.mark.synthetic_hdf_layout
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


@pytest.mark.synthetic_hdf_layout
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


@pytest.mark.synthetic_hdf_layout
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


@pytest.mark.synthetic_hdf_layout
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


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("span", [[0, -1], [3, 2], [0, 0]])
def test_malformed_active_cell_table_ranges_fail(tmp_path, monkeypatch, span):
    text, path, expected = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        hdf[f"{AREA}/Synthetic/Cells Volume Elevation Info"][0] = span
    assert any(
        "invalid packed ranges" in error
        for error in validate(text, path, expected, time.time() - 1)[1]
    )


@pytest.mark.synthetic_hdf_layout
def test_authored_projection_value_change_fails(tmp_path, monkeypatch):
    text, path, expected = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        del hdf["Projection"]
        hdf.create_dataset("Projection", data=np.bytes_("different CRS"))
    assert validate(text, path, expected, time.time() - 1)[0] == ["Projection"]


@pytest.mark.synthetic_hdf_layout
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


@pytest.mark.synthetic_hdf_layout
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


@pytest.mark.synthetic_hdf_layout
def test_text_modification_is_not_accepted_as_recompiled_input(tmp_path, monkeypatch):
    text, path, expected = fixture(tmp_path)
    text.write_text("Geom Title=changed\n")
    assert "geometry text" in validate(text, path, expected, time.time() - 1)[0]
    assert expected["text_sha256"] != hashlib.sha256(text.read_bytes()).hexdigest()


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("file_type", ["HEC-RAS Geometry", "HEC-RAS Results"])
@pytest.mark.parametrize("version", ["HEC-RAS 7.0.1 June 2026", "HEC-RAS 7.1"])
def test_7x_product_invalidation_preserves_authored_geometry(tmp_path, version, file_type):
    text, path, expected = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        hdf.attrs["File Version"] = version
        hdf.attrs["File Type"] = file_type
        seeds = hdf[f"{AREA}/Cell Points"][()]
        perimeter = hdf[f"{AREA}/Polygon Points"][()]
        hdf[f"{AREA}/Synthetic"].attrs["Property Tables Last Computed"] = "old"
    removed = invalidate_products(path)
    assert f"{AREA}/Synthetic/Cells Volume Elevation Info" in removed
    with h5py.File(path) as hdf:
        np.testing.assert_array_equal(hdf[f"{AREA}/Cell Points"][()], seeds)
        np.testing.assert_array_equal(hdf[f"{AREA}/Polygon Points"][()], perimeter)
        assert "Property Tables Last Computed" not in hdf[f"{AREA}/Synthetic"].attrs
    assert invalidate_products(path) == []
    assert validate(text, path, expected, time.time() - 1)[1]


@pytest.mark.parametrize("version", ["HEC-RAS 8.0", "HEC-RAS 70.1", "unknown"])
def test_unsupported_product_version_does_not_modify_file(tmp_path, version):
    _, path, _ = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        hdf.attrs["File Version"] = version
    before = path.read_bytes()
    with pytest.raises(ValueError, match="GEOMETRY_CACHE_SCHEMA_UNSUPPORTED"):
        invalidate_products(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("group", ["Results", "Event Conditions", "Plan Data"])
def test_7x_results_file_is_not_invalidated(tmp_path, group):
    _, path, _ = fixture(tmp_path)
    with h5py.File(path, "r+") as hdf:
        hdf.attrs["File Version"] = "HEC-RAS 7.0.1 June 2026"
        hdf.attrs["File Type"] = "HEC-RAS Results"
        hdf.create_group(group)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="GEOMETRY_CACHE_SCHEMA_UNSUPPORTED"):
        invalidate_products(path)
    assert path.read_bytes() == before
