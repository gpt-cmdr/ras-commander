"""Terrain modifications staged for ``rasmapper-effective-terrain/2``.

The HDF layouts below mirror RAS-Mapper-authored terrains (HCFCD Prop_Topo,
Kingswood TerrainAlt1, NewOrleansMetro): ground lines are ``Type=Levee`` with
subtype ``Levee``/``Channel``, polygons and circles carry an ``Attributes``
table. Conformance of the engine against HEC-RAS 7.0.1 exports is qualified in
ras-commander-fast-map.
"""

import json
from pathlib import Path

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")

from ras_commander.fim import RasFim, _effective_terrain, _terrain_mods  # noqa: E402
from ras_commander.fim.errors import FimUnsupportedError  # noqa: E402

from test_fim_terrain_scope_adr_velocity import _terrain  # noqa: E402

GL_DTYPE = np.dtype([
    ("System Name", "S8"), ("Name", "S16"), ("Elevation Type", "S11"), ("Top Elevation", "<f4"),
    ("Top Width", "<f4"), ("Left Slope", "<f4"), ("Right Slope", "<f4"), ("Max Reach", "<f4"),
    ("Transition Percent", "<f4"), ("Elev Pt Tolerance", "<f4"),
])
POLY_DTYPE = np.dtype([
    ("Name", "S16"), ("Elevation Value", "<f4"), ("Elevation Type", "S11"), ("Elev Pt Tolerance", "<f4"),
    ("Generate Boundary Elevations", "u1"), ("Use ShapeFile Z Elevations", "u1"),
])
CIRCLE_DTYPE = np.dtype([("Name", "S16"), ("Elevation Value", "<f4"), ("Elevation Type", "S11")])


def _ground_line(mods, name, priority, subtype="Levee", et=b"SetIfHigher", width=10.0, reach=100.0,
                 system=b"", lines=None):
    lines = lines or [[(0.0, 0.0), (100.0, 0.0), (150.0, 50.0)]]
    g = mods.create_group(name)
    g.attrs["Type"] = np.bytes_("Levee")
    g.attrs["Subtype"] = np.bytes_(subtype)
    g.attrs["Priority"] = np.int32(priority)
    attrs = np.array([(system, b"f", et, 0.0, width, 3.0, 2.0, reach, np.nan, 50.0) for _ in lines],
                     dtype=GL_DTYPE)
    g.create_dataset("Attributes", data=attrs)
    info, parts, points, pinfo, pvals = [], [], [], [], []
    for line in lines:
        info.append([len(points), len(line), len(parts), 1])
        parts.append([0, len(line)])
        pinfo.append([len(pvals), 2])
        length = float(np.hypot(*np.diff(np.asarray(line), axis=0).T).sum())
        pvals += [[0.0, 10.0], [length, 12.0]]
        points += list(line)
    g.create_dataset("Polyline Info", data=np.asarray(info, np.int32))
    g.create_dataset("Polyline Parts", data=np.asarray(parts, np.int32))
    g.create_dataset("Polyline Points", data=np.asarray(points, float))
    g.create_dataset("Profile Info", data=np.asarray(pinfo, np.int32))
    g.create_dataset("Profile Values", data=np.asarray(pvals, np.float32))
    return g


def _polygon(mods, name, priority, gen=0, et=b"SetValue"):
    g = mods.create_group(name)
    g.attrs["Type"] = np.bytes_("Polygon")
    g.attrs["Priority"] = np.int32(priority)
    g.create_dataset("Attributes", data=np.array([(b"p", 40.5, et, 20.0, gen, 0)], dtype=POLY_DTYPE))
    ring = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    g.create_dataset("Polygon Info", data=np.array([[0, 5, 0, 1]], np.int32))
    g.create_dataset("Polygon Parts", data=np.array([[0, 5]], np.int32))
    g.create_dataset("Polygon Points", data=np.asarray(ring, float))
    return g


def _circle(mods, name, priority, rotation=0.0):
    g = mods.create_group(name)
    g.attrs["Type"] = np.bytes_("Circle")
    g.attrs["Priority"] = np.int32(priority)
    g.create_dataset("Attributes", data=np.array([(b"e", 47.75, b"SetValue")], dtype=CIRCLE_DTYPE))
    g.create_dataset("Circles", data=np.array([[5.0, 6.0, 4.0, 4.0, rotation]]))
    return g


def _hdf(tmp_path, name="mods.hdf"):
    hdf = tmp_path / name
    with h5py.File(hdf, "w") as f:
        f.create_group("Modifications")
    return hdf


def test_qualified_layers_are_staged(tmp_path):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        mods = f["Modifications"]
        _ground_line(mods, "HighGround", 1)
        _ground_line(mods, "Channels", 2, subtype="Channel", et=b"SetIfLower")
        _polygon(mods, "Polygons", 3)
        _circle(mods, "Ellipses", 0)
    layers = {layer["name"]: layer for layer in _terrain_mods.read_layers(hdf)}
    hg = layers["HighGround"]
    assert hg["kind"] == "ground_line" and hg["subtype"] == "levee" and hg["priority"] == 1
    feature = hg["features"][0]
    assert feature["elevation_type"] == "SetIfHigher"
    assert feature["points"] == [[0.0, 0.0], [100.0, 0.0], [150.0, 50.0]]
    assert feature["profile"][0] == [0.0, 10.0]
    assert (feature["top_width"], feature["left_slope"], feature["right_slope"], feature["max_reach"]) == (
        10.0, 3.0, 2.0, 100.0)
    assert layers["Channels"]["subtype"] == "channel"
    poly = layers["Polygons"]["features"][0]
    assert poly["elevation"] == pytest.approx(40.5) and len(poly["rings"]) == 1
    circle = layers["Ellipses"]["features"][0]
    assert circle["center"] == [5.0, 6.0] and circle["radius_x"] == 4.0
    assert circle["rotation"] == 0.0
    assert feature["system_name"] == ""
    assert hg["length_units"] == "feet"
    json.dumps(list(layers.values()))  # the request is plain JSON


def test_forms_the_engine_now_applies_are_staged(tmp_path):
    """Ground-line SetValue, Max Reach <= Top Width and rotated ellipses are
    applied exactly by the engine (fast-map qualification, HEC-RAS 7.0.1)."""
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        mods = f["Modifications"]
        _ground_line(mods, "Fill", 0, et=b"SetValue")
        _ground_line(mods, "Trap", 1, width=600.0, reach=100.0)
        _circle(mods, "Rot", 2, rotation=-63.5)
    layers = {layer["name"]: layer for layer in _terrain_mods.read_layers(hdf, length_units="meters")}
    assert layers["Fill"]["features"][0]["elevation_type"] == "SetValue"
    assert layers["Trap"]["features"][0]["max_reach"] == 100.0
    assert layers["Rot"]["features"][0]["rotation"] == -63.5
    assert layers["Fill"]["length_units"] == "meters"


def _control_point_group(group, points, elevations):
    cp = group.create_group("Control Points")
    cp.attrs["Type"] = np.bytes_("ElevationControlPointLayer")
    cp.create_dataset("Points", data=np.asarray(points, float))
    attrs = np.zeros(len(points), dtype=[("Name", "S8"), ("Elevation", "<f4")])
    attrs["Elevation"] = elevations
    cp.create_dataset("Attributes", data=attrs)
    return cp


def _set_attr(group, column, value):
    attrs = group["Attributes"][()]
    attrs[column] = value
    group["Attributes"][...] = attrs
    return group


def test_ground_line_fields_the_engine_needs(tmp_path):
    """System Name, Transition Percent, Elev Pt Tolerance and NaN templates
    reach the engine as stored (NaN as null); Add and negative slopes pass."""
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        mods = f["Modifications"]
        g = _ground_line(mods, "Named", 0, system=b"chan", et=b"Add")
        _set_attr(g, "Transition Percent", 0.5)
        _set_attr(g, "Elev Pt Tolerance", 0.1)
        n = _ground_line(mods, "NanTemplate", 1)
        for column in ("Max Reach", "Top Width", "Right Slope", "Elev Pt Tolerance"):
            _set_attr(n, column, np.nan)
        _set_attr(n, "Left Slope", -2.0)
        _ground_line(mods, "System", 2, system=b"Hoeys",
                     lines=[[(0.0, 0.0), (10.0, 0.0)], [(10.0, 0.0), (20.0, 5.0)]])
    layers = {layer["name"]: layer for layer in _terrain_mods.read_layers(hdf)}
    named = layers["Named"]["features"][0]
    assert named["system_name"] == "chan" and named["elevation_type"] == "Add"
    assert named["transition_percent"] == 0.5
    assert named["elev_pt_tolerance"] == float(np.float32(0.1))  # binary32 as stored
    nan = layers["NanTemplate"]["features"][0]
    assert (nan["top_width"], nan["max_reach"], nan["right_slope"]) == (None, None, None)
    assert nan["left_slope"] == -2.0 and nan["transition_percent"] is None
    assert nan["elev_pt_tolerance"] is None
    assert "control_points" not in layers["NanTemplate"]
    # Joining is the engine's: both members are passed with their name.
    assert [f["system_name"] for f in layers["System"]["features"]] == ["Hoeys", "Hoeys"]
    text = json.dumps(list(layers.values()), allow_nan=False)  # strict JSON for serde
    assert "NaN" not in text


def test_missing_transition_column_reads_as_zero(tmp_path):
    hdf = _hdf(tmp_path)
    dtype = np.dtype([(n, GL_DTYPE[n]) for n in GL_DTYPE.names if n != "Transition Percent"])
    with h5py.File(hdf, "a") as f:
        g = _ground_line(f["Modifications"], "Old", 0)
        old = g["Attributes"][()]
        del g["Attributes"]
        new = np.zeros(len(old), dtype=dtype)
        for name in dtype.names:
            new[name] = old[name]
        g.create_dataset("Attributes", data=new)
    assert _terrain_mods.read_layers(hdf)[0]["features"][0]["transition_percent"] == 0.0


def test_ground_line_control_points_and_empty_profile(tmp_path):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        g = _ground_line(f["Modifications"], "Cps", 0, et=b"SetValue")
        info = g["Profile Info"][()]
        info[:, 1] = 0  # no stored profile: the control points give it
        g["Profile Info"][...] = info
        _control_point_group(g, [[1.0, 0.5, 9.0], [140.0, 40.0, 0.0]], [11.5, np.nan])
    layer = _terrain_mods.read_layers(hdf)[0]
    assert layer["features"][0]["profile"] == []
    assert layer["control_points"] == [
        {"x": 1.0, "y": 0.5, "elevation": 11.5}, {"x": 140.0, "y": 40.0, "elevation": None},
    ]
    json.dumps(layer, allow_nan=False)


def test_polygon_fields_the_engine_needs(tmp_path):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        mods = f["Modifications"]
        g = _polygon(mods, "Boundary", 0, gen=1, et=b"Add")
        g.create_dataset("Profile Info", data=np.array([[0, 2]], np.int32))
        g.create_dataset("Profile Values", data=np.array([[0.0, 40.0], [40.0, 41.0]], np.float32))
        c = _polygon(mods, "Interior", 1)
        _control_point_group(c, [[5.0, 5.0]], [44.0])
    layers = {layer["name"]: layer for layer in _terrain_mods.read_layers(hdf, length_units="meters")}
    boundary = layers["Boundary"]
    feature = boundary["features"][0]
    assert boundary["length_units"] == "meters" and "control_points" not in boundary
    assert feature["generate_boundary"] is True and feature["use_shape_z"] is False
    assert feature["elevation_type"] == "Add"
    assert feature["profile"] == [[0.0, 40.0], [40.0, 41.0]]
    assert feature["elev_pt_tolerance"] == 20.0 and "vertex_z" not in feature
    assert layers["Interior"]["control_points"] == [{"x": 5.0, "y": 5.0, "elevation": 44.0}]
    assert layers["Interior"]["features"][0]["profile"] == []


def test_shape_z_with_boundary_elevations_carries_vertex_z(tmp_path):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        g = _set_attr(_polygon(f["Modifications"], "Z", 0, gen=1), "Use ShapeFile Z Elevations", 1)
        ring = g["Polygon Points"][()]
        del g["Polygon Points"]
        ds = g.create_dataset("Polygon Points", data=np.column_stack([ring, np.arange(5.0)]))
        ds.attrs["Column"] = np.asarray([b"X", b"Y", b"Z"])
        g.create_dataset("Profile Info", data=np.array([[0, 2]], np.int32))
        g.create_dataset("Profile Values", data=np.array([[0.0, 40.0], [40.0, 40.0]], np.float32))
    feature = _terrain_mods.read_layers(hdf)[0]["features"][0]
    assert feature["use_shape_z"] is True and feature["vertex_z"] == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert feature["rings"][0][1] == [10.0, 0.0]


QUALIFIED_RELEASES = [
    # (label, Fast-Map 0.18.0 rule, rule with an engine advertising 6.7)
    ("6.6", "6.6", "6.6"), ("6.60", "6.6", "6.6"), ((6, 6, 0), "6.6", "6.6"),
    ("6.7", "6.6", "6.7"), ("6.70", "6.6", "6.7"), ("6.7 Beta 4", "6.6", "6.7"),
    ("6.7 Beta 5", "6.6", "6.7"), (r"C:\Program Files (x86)\HEC\HEC-RAS\6.7 Beta 5\Ras.exe", "6.6", "6.7"),
    ("7.0", "7.0.1", "7.0.1"), ("7.00", "7.0.1", "7.0.1"), ("7.0.0", "7.0.1", "7.0.1"),
    ("7.0.1", "7.0.1", "7.0.1"), ("7.01", "7.0.1", "7.0.1"), ("7.00.0001", "7.0.1", "7.0.1"),
    ("7.0.2", "7.0.1", "7.0.1"), ("7.02", "7.0.1", "7.0.1"), ((7, 0, 2), "7.0.1", "7.0.1"),
]
ENGINE_TABLE = {"6.6": "6.6", "6.7": "6.7", "6.7 Beta 4": "6.7", "6.7 Beta 5": "6.7",
                "7.0": "7.0.1", "7.0.0": "7.0.1", "7.0.1": "7.0.1", "7.0.2": "7.0.1"}


@pytest.mark.parametrize("label, rule_0_18, rule_table", QUALIFIED_RELEASES)
def test_qualified_releases_map_to_their_rule(label, rule_0_18, rule_table):
    assert _terrain_mods.hecras_version_for(label) == rule_0_18
    assert _terrain_mods.hecras_version_for(label, ENGINE_TABLE) == rule_table


@pytest.mark.parametrize("label", [
    "6.5", "6.50", "6.4.1", "6.41", "6.3.1", "6.0", "5.0.7", "5.07", "6.6.1", "7.0.3", "7.1",
    "7.10", "8.0", "unknown", "6.7.1",
])
def test_unqualified_releases_are_refused(label):
    for rules in (None, ENGINE_TABLE):
        with pytest.raises(FimUnsupportedError, match="no qualified native") as exc:
            _terrain_mods.hecras_version_for(label, rules)
        assert exc.value.reason == _terrain_mods.UNQUALIFIED_HECRAS_VERSION
        assert "7.0.2" in str(exc.value)


def test_release_rules_ignore_unknown_engine_rules():
    assert _terrain_mods.release_rules(None) == _terrain_mods.HECRAS_RELEASE_RULES
    assert _terrain_mods.release_rules({"7.0.2": "7.9"}) == _terrain_mods.HECRAS_RELEASE_RULES
    assert _terrain_mods.release_rules({"7.0.2": "7.0.1"}) == {"7.0.2": "7.0.1"}


def test_hecras_version_mapping_and_project_detection(tmp_path):
    assert _terrain_mods.hecras_version_for(None) == "7.0.1"
    terrain = tmp_path / "Terrain" / "T.hdf"
    terrain.parent.mkdir()
    assert _terrain_mods.project_hecras_version(terrain) == ("7.0.1", "default")
    (tmp_path / "M.p01").write_text("Plan Title=a\nProgram Version=5.10\n")
    (tmp_path / "M.g01").write_text("Geom Title=a\nProgram Version=6.60\n")
    version, basis = _terrain_mods.project_hecras_version(terrain, tmp_path / "M.rasmap")
    assert version == "6.6" and "6.60" in basis

    class Project:
        ras_version = "7.0.1"
        ras_exe_path = None

    assert _terrain_mods.project_hecras_version(terrain, None, Project())[0] == "7.0.1"
    Project.ras_version = "6.5"
    with pytest.raises(FimUnsupportedError, match="ras_object.ras_version 6.5") as exc:
        _terrain_mods.project_hecras_version(terrain, None, Project())
    assert exc.value.reason == _terrain_mods.UNQUALIFIED_HECRAS_VERSION
    (tmp_path / "M.g02").write_text("Geom Title=b\nProgram Version=7.10\n")
    with pytest.raises(FimUnsupportedError, match="Program Version 7.10"):
        _terrain_mods.project_hecras_version(terrain, tmp_path / "M.rasmap")
    with pytest.raises(ValueError, match="hecras_version"):
        _terrain_mods.read_layers(_hdf(tmp_path, "v.hdf"), hecras_version="6.5")


@pytest.mark.parametrize("build, reason, version", [
    (lambda m: _ground_line(m, "Odd", 0, subtype="levee"), "subtype 'levee'", "7.0.1"),
    (lambda m: _ground_line(m, "Bad", 0, et=b"Raise"), "elevation type 'Raise'", "7.0.1"),
    (lambda m: _set_attr(_ground_line(m, "Wide", 0), "Top Width", np.nan),
     "NaN Top Width with a finite Max Reach", "7.0.1"),
    (lambda m: _set_attr(_ground_line(m, "NamedNan", 0, system=b"s"), "Left Slope", np.nan),
     "NaN template", "7.0.1"),
    (lambda m: _control_point_group(_ground_line(m, "NamedCp", 0, system=b"s"), [[0.0, 0.0]], [1.0]),
     "control points", "7.0.1"),
    (lambda m: _ground_line(m, "Named66", 0, system=b"s"), "HEC-RAS 6.6", "6.6"),
    (lambda m: _ground_line(m, "Named67", 0, system=b"s"), "HEC-RAS 6.7", "6.7"),
    (lambda m: _polygon(m, "Sampled", 0, gen=1), "sampled from the terrain", "7.0.1"),
    (lambda m: _polygon(m, "Sampled67", 0, gen=1), "sampled from the terrain", "6.7"),
    (lambda m: _polygon(m, "Sampled66", 0, gen=1), "HEC-RAS 6.6", "6.6"),
    # Control points only inside the ring are mass points, not perimeter points.
    (lambda m: _control_point_group(_polygon(m, "Inside66", 0, gen=1), [[5.0, 5.0]], [41.0]),
     "HEC-RAS 6.6", "6.6"),
    (lambda m: _control_point_group(_polygon(m, "Inside", 0, gen=1), [[5.0, 5.0]], [41.0]),
     "sampled from the terrain", "7.0.1"),
    # Outside the ring but beyond Elev Pt Tolerance (20), or without an elevation.
    (lambda m: _control_point_group(_polygon(m, "Far66", 0, gen=1), [[-25.0, 5.0]], [41.0]),
     "HEC-RAS 6.6", "6.6"),
    (lambda m: _control_point_group(_polygon(m, "NanCp66", 0, gen=1), [[-1.0, 5.0]], [np.nan]),
     "HEC-RAS 6.6", "6.6"),
    (lambda m: _set_attr(_polygon(m, "ShapeZ", 0), "Use ShapeFile Z Elevations", 1),
     "shapefile Z", "7.0.1"),
    (lambda m: _set_attr(_circle(m, "AddEllipse", 0), "Elevation Type", b"Add"),
     "ellipse elevation type 'Add'", "7.0.1"),
])
def test_forms_the_engine_refuses_are_refused_first(tmp_path, build, reason, version):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        build(f["Modifications"])
    with pytest.raises(FimUnsupportedError, match=reason):
        _terrain_mods.read_layers(hdf, hecras_version=version)


@pytest.mark.parametrize("version", ["6.6", "6.7", "7.0.1"])
def test_perimeter_control_point_outside_the_ring_sets_the_boundary(tmp_path, version):
    """The only boundary form the 6.6 rule accepts: a control point outside the
    ring within Elev Pt Tolerance (inside points are mass points)."""
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        g = _polygon(f["Modifications"], "Perimeter", 0, gen=1)
        _control_point_group(g, [[-19.0, 5.0], [5.0, 5.0]], [40.0, 41.0])
    layer = _terrain_mods.read_layers(hdf, hecras_version=version)[0]
    assert layer["features"][0]["generate_boundary"] is True
    assert len(layer["control_points"]) == 2


@pytest.mark.parametrize("version", ["6.7", "7.0.1"])
def test_stored_profile_with_interior_points_is_staged_by_6_7_and_7_0_1(tmp_path, version):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        g = _polygon(f["Modifications"], "Stored", 0, gen=1)
        g.create_dataset("Profile Info", data=np.array([[0, 2]], np.int32))
        g.create_dataset("Profile Values", data=np.array([[0.0, 40.0], [40.0, 41.0]], np.float32))
        _control_point_group(g, [[5.0, 5.0]], [44.0])
    assert _terrain_mods.read_layers(hdf, hecras_version=version)[0]["name"] == "Stored"
    with pytest.raises(FimUnsupportedError, match="HEC-RAS 6.6 samples"):
        _terrain_mods.read_layers(hdf, hecras_version="6.6")


def test_ground_line_without_profile_or_control_points_is_refused(tmp_path):
    """RAS Mapper samples the terrain at the line ends (not reproduced)."""
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        del _ground_line(f["Modifications"], "Bare", 0)["Profile Values"]
    with pytest.raises(FimUnsupportedError, match="no stored profile and no control points"):
        _terrain_mods.read_layers(hdf)


def test_layer_without_attributes_is_skipped(tmp_path):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        f["Modifications"].create_group("Empty").attrs["Type"] = np.bytes_("Polygon")  # no Priority
        _polygon(f["Modifications"], "Pad", 0)
    assert [layer["name"] for layer in _terrain_mods.read_layers(hdf)] == ["Pad"]


def test_bad_control_points_shared_priorities_and_unknown_types_are_refused(tmp_path):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        g = _ground_line(f["Modifications"], "Cut", 0)
        g.create_group("Control Points").create_dataset("Points", data=np.zeros((2, 2)))
    with pytest.raises(FimUnsupportedError, match="Elevation attribute"):
        _terrain_mods.read_layers(hdf)

    hdf = _hdf(tmp_path, "shared.hdf")
    with h5py.File(hdf, "a") as f:
        _polygon(f["Modifications"], "A", 0)
        _polygon(f["Modifications"], "B", 0)
    with pytest.raises(FimUnsupportedError, match="share a Priority"):
        _terrain_mods.read_layers(hdf)

    hdf = _hdf(tmp_path, "pier.hdf")
    with h5py.File(hdf, "a") as f:
        g = f["Modifications"].create_group("Piers")
        g.attrs["Type"] = np.bytes_("Pier")
        g.attrs["Priority"] = np.int32(0)
        g.create_dataset("Attributes", data=np.zeros(1, dtype=CIRCLE_DTYPE))
    with pytest.raises(FimUnsupportedError, match="type 'Pier'"):
        _terrain_mods.read_layers(hdf)


def test_types_ras_mapper_ignores_are_skipped(tmp_path, caplog):
    """RAS Mapper loads only its known Types; an old writer's Type=Channel
    ground line (and any other unknown Type) leaves the export unchanged."""
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        mods = f["Modifications"]
        old = _ground_line(mods, "OldWriterChannel", 0, subtype="Channel", et=b"SetIfLower")
        old.attrs["Type"] = np.bytes_("Channel")
        g = mods.create_group("Bridge")
        g.attrs["Type"] = np.bytes_("Bridge")
        g.attrs["Priority"] = np.int32(1)
        g.create_dataset("Attributes", data=np.zeros(1, dtype=CIRCLE_DTYPE))
        _polygon(mods, "Pad", 2)
    with caplog.at_level("WARNING"):
        layers = _terrain_mods.read_layers(hdf)
    assert [layer["name"] for layer in layers] == ["Pad"]
    assert "ignored by RAS Mapper" in caplog.text and "Type=Levee" in caplog.text


def test_nan_elevation_features_are_skipped_and_nan_slope_is_null(tmp_path):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        mods = f["Modifications"]
        g = _circle(mods, "Mound", 0)
        attrs = g["Attributes"][()]
        attrs["Elevation Value"] = np.nan
        g["Attributes"][...] = attrs
        gl = _ground_line(mods, "Levee", 1)
        attrs = gl["Attributes"][()]
        attrs["Left Slope"] = np.nan
        gl["Attributes"][...] = attrs
    layers = _terrain_mods.read_layers(hdf)
    assert [layer["name"] for layer in layers] == ["Levee"]
    assert layers[0]["features"][0]["left_slope"] is None  # the engine reads NaN as 3


def test_project_length_units_follow_the_ras_project(tmp_path):
    terrain = tmp_path / "Terrain" / "T.hdf"
    terrain.parent.mkdir()
    (tmp_path / "Terrain" / "Projection.prj").write_text('PROJCS["x",UNIT["Meter",1.0]]')
    assert _terrain_mods.project_length_units(terrain) == "feet"
    (tmp_path / "M.prj").write_text("Proj Title=M\nSI Units\n")
    assert _terrain_mods.project_length_units(terrain) == "meters"
    (tmp_path / "M.prj").write_text("Proj Title=M\nEnglish Units\n")
    assert _terrain_mods.project_length_units(terrain, tmp_path / "M.rasmap") == "feet"


def test_empty_control_point_group_is_not_a_control_point(tmp_path):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        g = _polygon(f["Modifications"], "Pond", 0)
        g.create_group("Control Points").create_dataset("Points", data=np.zeros((0, 2)))
    assert len(_terrain_mods.read_layers(hdf)) == 1


def _v2_engine(monkeypatch, record=None):
    monkeypatch.setattr(_effective_terrain._engine, "find_engine", lambda path=None: Path("engine.exe"))
    record = record or {  # ras-commander-fast-map#40: /2 only, both request schemas
        "method_id": _effective_terrain.METHOD_ID_V2,
        "request_schemas": [_effective_terrain.SCHEMA, _effective_terrain.SCHEMA_V2],
        "modifications": {"supported": {}, "hecras_version": "7.0.1 (default) or 6.6"},
    }
    monkeypatch.setattr(_effective_terrain._engine, "engine_method",
                        lambda engine: {"effective_terrain": record})


class _Stop(Exception):
    pass


def _capture_request(monkeypatch):
    monkeypatch.setattr(
        _effective_terrain._engine, "terrain_identity",
        lambda *a, **k: {"epsg": 26915, "crs_identity": {"kind": "epsg"}},
    )
    captured = {}

    def run_engine(args, what, timeout=None):
        captured.update(json.loads(Path(args[2]).read_text(encoding="utf-8")))
        raise _Stop

    monkeypatch.setattr(_effective_terrain._engine, "run_engine", run_engine)
    return captured


def test_v2_engine_receives_every_layer(tmp_path, monkeypatch):
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    with h5py.File(hdf, "a") as f:
        mods = f.create_group("Modifications")
        _ground_line(mods, "HighGround", 0, system=b"named", et=b"Add")
        _polygon(mods, "Pad", 1)
    _v2_engine(monkeypatch)
    captured = _capture_request(monkeypatch)
    assert RasFim.supports_effective_terrain() is True
    with pytest.raises(_Stop):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif")
    assert captured["schema"] == _effective_terrain.SCHEMA_V2
    assert captured["modifications"] == 2
    assert sorted(layer["name"] for layer in captured["modification_layers"]) == ["HighGround", "Pad"]
    assert "hecras_version" not in captured  # 7.0.1 is the engine default


def test_hecras_version_reaches_the_engine(tmp_path, monkeypatch):
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    with h5py.File(hdf, "a") as f:
        _ground_line(f.create_group("Modifications"), "HighGround", 0)
    _v2_engine(monkeypatch)
    captured = _capture_request(monkeypatch)
    with pytest.raises(_Stop):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif", hecras_version="6.6")
    assert captured["hecras_version"] == "6.6"

    # An engine without hecras_version cannot follow HEC-RAS 6.6.
    _v2_engine(monkeypatch, {
        "method_id": _effective_terrain.METHOD_ID_V2,
        "compatible_method_ids": [_effective_terrain.METHOD_ID],
        "modifications": {"supported": {}},
    })
    with pytest.raises(FimUnsupportedError, match="hecras_version"):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif", hecras_version="6.6")


def test_engine_release_table_decides_the_rule(tmp_path, monkeypatch):
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    with h5py.File(hdf, "a") as f:
        _ground_line(f.create_group("Modifications"), "HighGround", 0)
    # Fast-Map 0.18.0: no table; 6.7 takes the 6.6 rule, 7.0.2 the default.
    _v2_engine(monkeypatch)
    captured = _capture_request(monkeypatch)
    with pytest.raises(_Stop):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif", hecras_version="6.7 Beta 5")
    assert captured["hecras_version"] == "6.6"
    captured.clear()
    with pytest.raises(_Stop):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif", hecras_version="7.0.2")
    assert "hecras_version" not in captured
    # An engine advertising hecras_versions with a 6.7 rule.
    _v2_engine(monkeypatch, {
        "method_id": _effective_terrain.METHOD_ID_V2,
        "request_schemas": [_effective_terrain.SCHEMA, _effective_terrain.SCHEMA_V2],
        "hecras_versions": ENGINE_TABLE,
        "modifications": {"supported": {}, "hecras_version": "release label"},
    })
    captured.clear()
    with pytest.raises(_Stop):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif", hecras_version="6.7 Beta 4")
    assert captured["hecras_version"] == "6.7"


@pytest.mark.parametrize("version", ["6.5", "6.4.1", "7.1"])
def test_unqualified_release_is_refused_before_the_engine(tmp_path, monkeypatch, version):
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    with h5py.File(hdf, "a") as f:
        _ground_line(f.create_group("Modifications"), "HighGround", 0)
    _v2_engine(monkeypatch)

    def no_engine(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("engine called for an unqualified release")

    monkeypatch.setattr(_effective_terrain._engine, "run_engine", no_engine)
    with pytest.raises(FimUnsupportedError, match="no qualified native") as exc:
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif", hecras_version=version)
    assert exc.value.reason == _terrain_mods.UNQUALIFIED_HECRAS_VERSION


def test_v1_engine_refuses_modified_terrains(tmp_path, monkeypatch):
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    with h5py.File(hdf, "a") as f:
        _polygon(f.create_group("Modifications"), "Pad", 0)
    _v2_engine(monkeypatch, {"method_id": _effective_terrain.METHOD_ID})
    assert RasFim.supports_effective_terrain() is True
    with pytest.raises(FimUnsupportedError, match="lacks rasmapper-effective-terrain/2"):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif")
    # /2 without a modifications record is not enough either.
    _v2_engine(monkeypatch, {"method_id": _effective_terrain.METHOD_ID_V2})
    with pytest.raises(FimUnsupportedError, match="lacks rasmapper-effective-terrain/2"):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif")


def test_v2_engine_still_refuses_unqualified_modifications(tmp_path, monkeypatch):
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    with h5py.File(hdf, "a") as f:
        _polygon(f.create_group("Modifications"), "Sampled", 0, gen=1)
    _v2_engine(monkeypatch)

    def no_engine(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("engine called for an unqualified modification")

    monkeypatch.setattr(_effective_terrain._engine, "run_engine", no_engine)
    with pytest.raises(FimUnsupportedError, match="sampled from the terrain"):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif")


def _engine_with_modifications():
    try:
        return _effective_terrain.engine_supports(_effective_terrain._engine.find_engine(None), modifications=True)
    except Exception:
        return False


@pytest.mark.skipif(not _engine_with_modifications(),
                    reason="installed engine lacks rasmapper-effective-terrain/2 modifications")
@pytest.mark.parametrize("version", ["7.0.1", "6.6", "6.7 Beta 5", "7.0.2"])
def test_real_engine_accepts_every_staged_field(tmp_path, version):
    """The engine deserializes every field read_layers sends (serde
    deny_unknown_fields) and applies a constant polygon and an ellipse.
    Release labels map to the rule the installed engine advertises (6.7: the
    6.7 rule, or 6.6 with Fast-Map 0.18.0; 7.0.2: 7.0.1)."""
    rasterio = pytest.importorskip("rasterio")
    rule = _terrain_mods.hecras_version_for(version, RasFim._engine_hecras_versions())
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    x0, y0 = 500000.0, 4000000.0
    with h5py.File(hdf, "a") as f:
        f["Terrain/T.only/0/Mask"][...] = 1
        mods = f.create_group("Modifications")
        pad = _polygon(mods, "Pad", 0)
        pad["Polygon Points"][...] = np.asarray(
            [(x0 + 100, y0 - 200), (x0 + 200, y0 - 200), (x0 + 200, y0 - 100), (x0 + 100, y0 - 100),
             (x0 + 100, y0 - 200)])
        _set_attr(pad, "Elevation Value", 50.0)
        circle = _circle(mods, "Mound", 1, rotation=30.0)
        circle["Circles"][...] = np.array([[x0 + 400, y0 - 300, 20.0, 10.0, 30.0]])
        line = [(x0 + 20, y0 - 400), (x0 + 300, y0 - 420), (x0 + 500, y0 - 380)]
        levee = _ground_line(mods, "Levee", 2, et=b"Add", width=6.0, reach=20.0, lines=[line])
        _set_attr(levee, "Transition Percent", 0.0)
        _control_point_group(levee, [[x0 + 300, y0 - 421]], [2.0])
        nan = _ground_line(mods, "Channel", 3, subtype="Channel", et=b"SetIfLower",
                           lines=[[(x0 + 20, y0 - 60), (x0 + 560, y0 - 60)]])
        _set_attr(nan, "Right Slope", np.nan)
        _set_attr(nan, "Left Slope", -1.0)
        if rule == "7.0.1":
            _ground_line(mods, "Named", 4, system=b"sys", lines=[[(x0 + 20, y0 - 480), (x0 + 560, y0 - 470)]])
    out = tmp_path / "out" / "effective.tif"
    receipt = RasFim.build_effective_terrain(hdf, out, threads=1, max_working_mib=256,
                                             hecras_version=version)
    assert receipt["method_id"] == _effective_terrain.METHOD_ID_V2
    assert receipt["hecras_version"] == rule
    changed = {layer["name"]: layer["changed_pixels"]
               for layer in receipt["engine_report"]["modifications"]["layers"]}
    assert len(changed) == (5 if rule == "7.0.1" else 4) and all(changed.values())
    with rasterio.open(out) as src:
        row, col = src.index(x0 + 150, y0 - 150)
        assert src.read(1)[row, col] == 50.0
        row, col = src.index(x0 + 400, y0 - 300)
        assert src.read(1)[row, col] == 47.75


@pytest.mark.parametrize("line, expected", [
    ("SI Units=1", "meters"), ("SI Units=True", "meters"), ("SI Units=0", "feet"),
    ("si units", "meters"), ("English Units", "feet"),
])
def test_project_length_units_accept_every_units_form(tmp_path, line, expected):
    terrain = tmp_path / "Terrain" / "T.hdf"
    terrain.parent.mkdir()
    (tmp_path / "M.prj").write_text(f"Proj Title=M\n{line}\n")
    assert _terrain_mods.project_length_units(terrain) == expected


def test_project_length_units_follow_the_selected_project(tmp_path):
    terrain = tmp_path / "Terrain" / "T.hdf"
    terrain.parent.mkdir()
    (tmp_path / "A.prj").write_text("Proj Title=A\nEnglish Units\n")
    (tmp_path / "B.prj").write_text("Proj Title=B\nSI Units\n")
    with pytest.raises(FimUnsupportedError, match="different units"):
        _terrain_mods.project_length_units(terrain)

    class Project:
        prj_file = tmp_path / "B.prj"

    assert _terrain_mods.project_length_units(terrain, None, Project()) == "meters"
    assert _terrain_mods.project_length_units(terrain, tmp_path / "A.rasmap") == "feet"


def _multi_ring_polygon(mods, name, rings):
    """Polygon feature whose ``Polygon Parts`` hold every ring of ``rings``."""
    g = _polygon(mods, name, 0)
    for table in ("Polygon Info", "Polygon Parts", "Polygon Points"):
        del g[table]
    parts, points = [], []
    for ring in rings:
        parts.append([len(points), len(ring)])
        points += ring
    g.create_dataset("Polygon Info", data=np.array([[0, len(points), 0, len(rings)]], np.int32))
    g.create_dataset("Polygon Parts", data=np.asarray(parts, np.int32))
    g.create_dataset("Polygon Points", data=np.asarray(points, float))
    return g


OUTER = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]


@pytest.mark.parametrize("rings", [
    # A hole, in either winding.
    [OUTER, [(3, 3), (3, 6), (6, 6), (6, 3), (3, 3)]],
    [OUTER, [(3, 3), (6, 3), (6, 6), (3, 6), (3, 3)]],
    # Two separate parts.
    [OUTER, [(20, 0), (30, 0), (30, 10), (20, 10), (20, 0)]],
    # Two overlapping parts.
    [OUTER, [(5, 5), (15, 5), (15, 15), (5, 15), (5, 5)]],
], ids=["hole-cw", "hole-ccw", "separate-parts", "overlapping-parts"])
def test_multi_ring_polygons_are_refused_before_the_engine(tmp_path, rings):
    """RAS Mapper joins and triangulates a polygon's rings in a way the engine
    cannot reproduce as a rule (Fast-Map #42), so the reader refuses them with
    a reason code and callers route the terrain to the RAS Mapper export."""
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        _multi_ring_polygon(f["Modifications"], "Pond", rings)
    with pytest.raises(FimUnsupportedError, match="multi-ring polygon") as caught:
        _terrain_mods.read_layers(hdf, length_units="feet")
    assert caught.value.reason == _terrain_mods.MULTI_RING_POLYGON == "multi_ring_polygon"
    assert "[reason: multi_ring_polygon]" in str(caught.value)
    assert "'Pond'" in str(caught.value)


def test_single_ring_polygon_is_still_staged(tmp_path):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        _multi_ring_polygon(f["Modifications"], "Pad", [OUTER])
    [layer] = _terrain_mods.read_layers(hdf, length_units="feet")
    assert layer["kind"] == "polygon" and len(layer["features"][0]["rings"]) == 1
