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
    json.dumps(list(layers.values()))  # the request is plain JSON


@pytest.mark.parametrize("build, reason", [
    (lambda m: _ground_line(m, "Wall", 0, et=b"Add"), "elevation type 'Add'"),
    (lambda m: _ground_line(m, "Fill", 0, et=b"SetValue"), "elevation type 'SetValue'"),
    (lambda m: _ground_line(m, "Trap", 0, width=22.0, reach=22.0), "Max Reach not above Top Width"),
    (lambda m: _ground_line(m, "Sys", 0, system=b"Hoeys",
                            lines=[[(0.0, 0.0), (10.0, 0.0)], [(10.0, 0.0), (20.0, 5.0)]]), "systems"),
    (lambda m: _polygon(m, "Fix", 0, gen=1), "boundary elevations"),
    (lambda m: _circle(m, "Rot", 0, rotation=15.0), "rotated"),
])
def test_unqualified_forms_are_refused(tmp_path, build, reason):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        build(f["Modifications"])
    with pytest.raises(FimUnsupportedError, match=reason):
        _terrain_mods.read_layers(hdf)


def test_control_points_shared_priorities_and_unknown_types_are_refused(tmp_path):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        g = _ground_line(f["Modifications"], "Cut", 0)
        g.create_group("Control Points").create_dataset("Points", data=np.zeros((2, 2)))
    with pytest.raises(FimUnsupportedError, match="control points"):
        _terrain_mods.read_layers(hdf)

    hdf = _hdf(tmp_path, "shared.hdf")
    with h5py.File(hdf, "a") as f:
        _polygon(f["Modifications"], "A", 0)
        _polygon(f["Modifications"], "B", 0)
    with pytest.raises(FimUnsupportedError, match="share a Priority"):
        _terrain_mods.read_layers(hdf)

    hdf = _hdf(tmp_path, "unknown.hdf")
    with h5py.File(hdf, "a") as f:
        g = f["Modifications"].create_group("Bridge")
        g.attrs["Type"] = np.bytes_("Bridge")
        g.attrs["Priority"] = np.int32(0)
        g.create_dataset("Attributes", data=np.zeros(1, dtype=CIRCLE_DTYPE))
    with pytest.raises(FimUnsupportedError, match="type 'Bridge'"):
        _terrain_mods.read_layers(hdf)


def test_empty_control_point_group_is_not_a_control_point(tmp_path):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        g = _polygon(f["Modifications"], "Pond", 0)
        g.create_group("Control Points").create_dataset("Points", data=np.zeros((0, 2)))
    assert len(_terrain_mods.read_layers(hdf)) == 1


def _v2_engine(monkeypatch):
    monkeypatch.setattr(_effective_terrain._engine, "find_engine", lambda path=None: Path("engine.exe"))
    monkeypatch.setattr(
        _effective_terrain._engine, "engine_method",
        lambda engine: {"effective_terrain": {
            "method_id": _effective_terrain.METHOD_ID_V2,
            "compatible_method_ids": [_effective_terrain.METHOD_ID],
            "modifications": {"supported": {}},
        }},
    )


def test_v2_engine_receives_every_layer(tmp_path, monkeypatch):
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    with h5py.File(hdf, "a") as f:
        mods = f.create_group("Modifications")
        _ground_line(mods, "HighGround", 0)
        _polygon(mods, "Pad", 1)
    _v2_engine(monkeypatch)
    monkeypatch.setattr(
        _effective_terrain._engine, "terrain_identity",
        lambda *a, **k: {"epsg": 26915, "crs_identity": {"kind": "epsg"}},
    )
    captured = {}

    class Stop(Exception):
        pass

    def run_engine(args, what, timeout=None):
        captured.update(json.loads(Path(args[2]).read_text(encoding="utf-8")))
        raise Stop

    monkeypatch.setattr(_effective_terrain._engine, "run_engine", run_engine)
    assert RasFim.supports_effective_terrain() is True
    with pytest.raises(Stop):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif")
    assert captured["schema"] == _effective_terrain.SCHEMA_V2
    assert captured["modifications"] == 2
    assert sorted(layer["name"] for layer in captured["modification_layers"]) == ["HighGround", "Pad"]


def test_v2_engine_still_refuses_unqualified_modifications(tmp_path, monkeypatch):
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    with h5py.File(hdf, "a") as f:
        _ground_line(f.create_group("Modifications"), "Wall", 0, et=b"Add")
    _v2_engine(monkeypatch)

    def no_engine(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("engine called for an unqualified modification")

    monkeypatch.setattr(_effective_terrain._engine, "run_engine", no_engine)
    with pytest.raises(FimUnsupportedError, match="Add"):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif")
