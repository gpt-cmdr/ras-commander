"""Public ``RasFim.read_terrain_modifications`` against the private reader.

The public method is a thin wrapper of ``_terrain_mods.read_layers`` with the
project's HEC-RAS version and unit system resolved as
``RasFim.build_effective_terrain`` resolves them. These tests use the synthetic
terrain-modification fixtures of ``test_fim_terrain_mods``.
"""

import json
import logging
import os

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")

import ras_commander  # noqa: E402
from ras_commander.fim import RasFim, _terrain_mods  # noqa: E402
from ras_commander.fim.errors import FimUnsupportedError  # noqa: E402

from test_fim_terrain_mods import (  # noqa: E402
    _circle,
    _control_point_group,
    _ground_line,
    _hdf,
    _polygon,
    _set_attr,
)

RECORD_KEYS = {
    "schema", "terrain_hdf", "method_id", "status", "refusal", "refusal_reason", "hecras_version",
    "hecras_version_basis", "length_units", "length_units_basis", "layers", "warnings",
}
GROUND_LINE_FEATURE_KEYS = {
    "elevation_type", "top_width", "left_slope", "right_slope", "max_reach", "points",
    "profile", "system_name", "transition_percent", "elev_pt_tolerance",
}
POLYGON_FEATURE_KEYS = {
    "elevation_type", "elevation", "rings", "generate_boundary", "use_shape_z", "profile",
    "elev_pt_tolerance",
}
ELLIPSE_FEATURE_KEYS = {"elevation_type", "elevation", "center", "radius_x", "radius_y", "rotation"}


def _project(tmp_path, units_line="English Units", version="7.00"):
    """A terrain HDF inside a RAS project folder (prj + geometry file)."""
    (tmp_path / "Terrain").mkdir()
    (tmp_path / "M.prj").write_text(f"Proj Title=M\n{units_line}\n")
    (tmp_path / "M.g01").write_text(f"Geom Title=g\nProgram Version={version}\n")
    return _hdf(tmp_path / "Terrain", "Terrain.hdf")


def _qualified(hdf):
    with h5py.File(hdf, "a") as f:
        mods = f["Modifications"]
        _ground_line(mods, "HighGround", 1)
        _ground_line(mods, "Channels", 2, subtype="Channel", et=b"SetIfLower")
        cp = _polygon(mods, "Pads", 3, gen=1)
        _control_point_group(cp, [[0.0, 0.0], [10.0, 10.0]], [40.0, np.nan])
        _circle(mods, "Mound", 0, rotation=30.0)


def test_public_api_is_exported():
    assert ras_commander.RasFim is RasFim
    assert callable(RasFim.read_terrain_modifications)
    assert RasFim.TERRAIN_MODIFICATIONS_SCHEMA == "ras-commander-terrain-modifications/1"


@pytest.mark.parametrize("units_line, units, version, expected", [
    ("English Units", "feet", "7.00", "7.0.1"),
    ("SI Units", "meters", "6.60", "6.6"),
])
def test_matches_the_private_reader_and_documented_shape(tmp_path, units_line, units, version,
                                                         expected):
    hdf = _project(tmp_path, units_line, version)
    _qualified(hdf)
    record = RasFim.read_terrain_modifications(hdf)
    assert set(record) == RECORD_KEYS
    assert record["schema"] == RasFim.TERRAIN_MODIFICATIONS_SCHEMA
    assert record["method_id"] == "rasmapper-effective-terrain/2"
    assert record["terrain_hdf"] == str(hdf.resolve())
    assert record["status"] == "staged" and record["refusal"] is None
    assert record["warnings"] == []
    assert record["refusal_reason"] is None
    assert record["hecras_version"] == expected
    assert record["hecras_version_basis"] == f"Program Version {version} in {tmp_path.name}"
    assert record["length_units"] == units and record["length_units_basis"] == "project"
    # Identical to what the private reader stages (and the /2 request carries).
    assert record["layers"] == _terrain_mods.read_layers(
        hdf, length_units=units, hecras_version=expected)
    json.dumps(record, allow_nan=False)  # the record is plain JSON

    kinds = {layer["name"]: layer for layer in record["layers"]}
    assert {k: v["kind"] for k, v in kinds.items()} == {
        "HighGround": "ground_line", "Channels": "ground_line", "Pads": "polygon",
        "Mound": "ellipse",
    }
    for layer in record["layers"]:
        assert isinstance(layer["priority"], int)
        keys = {"ground_line": GROUND_LINE_FEATURE_KEYS, "polygon": POLYGON_FEATURE_KEYS,
                "ellipse": ELLIPSE_FEATURE_KEYS}[layer["kind"]]
        for feature in layer["features"]:
            assert keys <= set(feature)
        if layer["kind"] != "ellipse":
            assert layer["length_units"] == units
    assert kinds["Channels"]["subtype"] == "channel"
    assert kinds["Pads"]["control_points"] == [
        {"x": 0.0, "y": 0.0, "elevation": 40.0}, {"x": 10.0, "y": 10.0, "elevation": None},
    ]
    assert kinds["Mound"]["features"][0]["rotation"] == 30.0


def test_arguments_override_project_resolution(tmp_path):
    hdf = _project(tmp_path, "English Units", "7.00")
    _qualified(hdf)
    record = RasFim.read_terrain_modifications(hdf, hecras_version="6.60", length_units="meters")
    assert (record["hecras_version"], record["hecras_version_basis"]) == ("6.6", "argument")
    assert (record["length_units"], record["length_units_basis"]) == ("meters", "argument")
    assert record["layers"] == _terrain_mods.read_layers(
        hdf, length_units="meters", hecras_version="6.6")

    class Project:
        ras_version = "6.6"
        ras_exe_path = None
        prj_file = tmp_path / "SI.prj"

    (tmp_path / "SI.prj").write_text("Proj Title=SI\nSI Units\n")
    record = RasFim.read_terrain_modifications(hdf, ras_object=Project())
    assert record["hecras_version"] == "6.6"
    assert record["hecras_version_basis"] == "ras_object.ras_version 6.6"
    assert record["length_units"] == "meters"


def test_unmodified_and_skipped_terrains_are_none(tmp_path):
    hdf = tmp_path / "plain.hdf"
    with h5py.File(hdf, "w") as f:
        f.create_group("Terrain")
    record = RasFim.read_terrain_modifications(hdf)
    assert record["status"] == "none" and record["layers"] == [] and record["refusal"] is None
    assert _terrain_mods.read_layers(hdf) == []

    hdf = _hdf(tmp_path, "skipped.hdf")
    with h5py.File(hdf, "a") as f:
        old = _ground_line(f["Modifications"], "OldWriter", 0)
        old.attrs["Type"] = np.bytes_("Channel")  # RAS Mapper ignores this layer
    record = RasFim.read_terrain_modifications(hdf)
    assert record["status"] == "none" and record["layers"] == []


@pytest.mark.parametrize("build, reason, version", [
    (lambda m: _ground_line(m, "Bad", 0, et=b"Raise"), "elevation type 'Raise'", "7.0.1"),
    (lambda m: _ground_line(m, "Named66", 0, system=b"s"), "HEC-RAS 6.6", "6.6"),
    (lambda m: _polygon(m, "Sampled", 0, gen=1), "sampled from the terrain", "7.0.1"),
    (lambda m: _set_attr(_polygon(m, "ShapeZ", 0), "Use ShapeFile Z Elevations", 1),
     "shapefile Z", "7.0.1"),
    (lambda m: (_polygon(m, "A", 0), _polygon(m, "B", 0)), "share a Priority", "7.0.1"),
])
def test_refusals_carry_the_private_readers_reason(tmp_path, build, reason, version):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        build(f["Modifications"])
    with pytest.raises(FimUnsupportedError) as private:
        _terrain_mods.read_layers(hdf, hecras_version=version)
    record = RasFim.read_terrain_modifications(hdf, hecras_version=version, length_units="feet")
    assert set(record) == RECORD_KEYS
    assert record["status"] == "refused" and record["layers"] == []
    assert record["refusal"] == str(private.value) and reason in record["refusal"]
    assert record["refusal_reason"] == getattr(private.value, "reason", None)
    assert record["hecras_version"] == version
    with pytest.raises(FimUnsupportedError, match=reason):
        RasFim.read_terrain_modifications(hdf, hecras_version=version, strict=True)


def test_conflicting_project_units_refuse_only_layers_to_stage(tmp_path):
    """A units conflict refuses a terrain with layers; an unmodified one is ``"none"``.

    ``build_effective_terrain`` resolves the project units only for a modified
    terrain, so the reader does not refuse a terrain with nothing to stage.
    """
    (tmp_path / "Terrain").mkdir()
    (tmp_path / "A.prj").write_text("Proj Title=A\nEnglish Units\n")
    (tmp_path / "B.prj").write_text("Proj Title=B\nSI Units\n")
    hdf = _hdf(tmp_path / "Terrain", "Terrain.hdf")
    record = RasFim.read_terrain_modifications(hdf)
    assert record["status"] == "none" and record["refusal"] is None and record["layers"] == []
    assert record["hecras_version"] == "7.0.1"
    assert record["length_units"] is None and record["length_units_basis"] is None

    _qualified(hdf)
    record = RasFim.read_terrain_modifications(hdf)
    assert record["status"] == "refused" and "different units" in record["refusal"]
    assert record["hecras_version"] == "7.0.1" and record["length_units"] is None
    with pytest.raises(FimUnsupportedError, match="different units"):
        RasFim.read_terrain_modifications(hdf, strict=True)


def test_units_basis_reports_the_feet_default(tmp_path):
    """Feet assumed because no project file states units is ``"default"``, not ``"project"``."""
    (tmp_path / "Terrain").mkdir()
    hdf = _hdf(tmp_path / "Terrain", "Terrain.hdf")
    _qualified(hdf)
    record = RasFim.read_terrain_modifications(hdf)
    assert (record["length_units"], record["length_units_basis"]) == ("feet", "default")
    assert _terrain_mods.resolve_length_units(hdf) == ("feet", "default")
    (tmp_path / "M.prj").write_text("Proj Title=M\nEnglish Units\n")
    record = RasFim.read_terrain_modifications(hdf)
    assert (record["length_units"], record["length_units_basis"]) == ("feet", "project")
    assert _terrain_mods.project_length_units(hdf) == "feet"


def test_linked_terrain_uses_its_own_project(tmp_path):
    """A link elsewhere resolves to the HDF before the project folder is searched."""
    (tmp_path / "real").mkdir()
    hdf = _project(tmp_path / "real", "SI Units", "6.60")
    _qualified(hdf)
    elsewhere = tmp_path / "other"
    (elsewhere / "Terrain").mkdir(parents=True)
    (elsewhere / "O.prj").write_text("Proj Title=O\nEnglish Units\n")
    (elsewhere / "O.g01").write_text("Geom Title=g\nProgram Version=7.00\n")
    link = elsewhere / "Terrain" / "Terrain.hdf"
    try:
        os.symlink(hdf, link)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available")
    record = RasFim.read_terrain_modifications(link)
    assert record["terrain_hdf"] == str(hdf.resolve())
    assert (record["hecras_version"], record["length_units"]) == ("6.6", "meters")
    assert record["hecras_version_basis"] == "Program Version 6.60 in real"


def _rasmap(folder, hdf, groups):
    """A rasmap registering ``hdf`` with ``{group name: [layer names]}`` groups."""
    body = "".join(
        f'<Layer Name="{name}" Type="ElevationModificationGroup">'
        + "".join(f'<Layer Name="{layer}" Type="X"/>' for layer in layers) + "</Layer>"
        for name, layers in groups.items())
    rasmap = folder / "M.rasmap"
    rasmap.write_text(
        f'<RASMapper><Terrains><Layer Name="T" Type="TerrainLayer" Filename=".\\Terrain\\{hdf.name}">'
        f"{body}</Layer></Terrains></RASMapper>", encoding="utf-8")
    return rasmap


def test_rasmap_registration_warnings(tmp_path):
    """Layers the rasmap lists but the HDF lacks are a warning; status is unchanged."""
    hdf = _project(tmp_path)
    _qualified(hdf)
    rasmap = _rasmap(tmp_path, hdf, {"Modifications": ["HighGround", "Pads", "Ghost"]})
    record = RasFim.read_terrain_modifications(hdf, rasmap_path=rasmap)
    assert record["status"] == "staged" and len(record["layers"]) == 4
    assert [w["code"] for w in record["warnings"]] == ["rasmap_layer_not_in_hdf"]
    assert record["warnings"][0]["layers"] == ["Ghost"]
    assert "build_effective_terrain refuses" in record["warnings"][0]["message"]
    json.dumps(record, allow_nan=False)

    rasmap = _rasmap(tmp_path, hdf, {"Modifications": ["HighGround"]})
    assert RasFim.read_terrain_modifications(hdf, rasmap_path=rasmap)["warnings"] == []

    rasmap = _rasmap(tmp_path, hdf, {"Terrain Mods": ["HighGround"]})
    record = RasFim.read_terrain_modifications(hdf, rasmap_path=rasmap)
    assert [w["code"] for w in record["warnings"]] == ["modification_group_misnamed"]
    assert record["status"] == "staged"

    other = tmp_path / "Other.rasmap"
    other.write_text("<RASMapper><Terrains/></RASMapper>", encoding="utf-8")
    record = RasFim.read_terrain_modifications(hdf, rasmap_path=other)
    assert [w["code"] for w in record["warnings"]] == ["rasmap_not_checked"]
    assert "does not register" in record["warnings"][0]["message"]


def test_skipped_layer_without_attributes_is_logged(tmp_path, caplog):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        layer = f["Modifications"].create_group("Empty")
        layer.attrs["Type"] = np.bytes_("Polygon")
        layer.attrs["Priority"] = np.int32(0)
    with caplog.at_level(logging.WARNING, logger="ras_commander.fim._terrain_mods"):
        record = RasFim.read_terrain_modifications(hdf, hecras_version="7.0.1", length_units="feet")
    assert record["status"] == "none"
    assert any("'Empty'" in r.getMessage() and "no Attributes table" in r.getMessage()
               for r in caplog.records)


def test_multi_ring_polygon_refusal_reason_from_the_reader(tmp_path):
    """The real reader's ``multi_ring_polygon`` code reaches ``refusal_reason``."""
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        g = _polygon(f["Modifications"], "Pond", 0)
        ring = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        hole = [(2, 2), (4, 2), (4, 4), (2, 4), (2, 2)]
        for name in ("Polygon Info", "Polygon Parts", "Polygon Points"):
            del g[name]
        g.create_dataset("Polygon Info", data=np.array([[0, 10, 0, 2]], np.int32))
        g.create_dataset("Polygon Parts", data=np.array([[0, 5], [5, 5]], np.int32))
        g.create_dataset("Polygon Points", data=np.asarray(ring + hole, float))
    record = RasFim.read_terrain_modifications(hdf, hecras_version="7.0.1", length_units="feet")
    assert record["status"] == "refused"
    assert record["refusal_reason"] == "multi_ring_polygon"


def test_invalid_length_units_raise(tmp_path):
    with pytest.raises(ValueError, match="length_units"):
        RasFim.read_terrain_modifications(_hdf(tmp_path), length_units="yards")


def test_refusal_reason_code_is_surfaced(tmp_path, monkeypatch):
    """A reader refusal's ``reason`` code (for example ``multi_ring_polygon``
    from a polygon with more than one ring) is returned as ``refusal_reason``."""
    error = FimUnsupportedError("modification 'Pond' feature 0: multi-ring polygon (2 rings) "
                                "is not qualified [reason: multi_ring_polygon]")
    error.reason = "multi_ring_polygon"

    def refuse(*args, **kwargs):
        raise error

    monkeypatch.setattr(_terrain_mods, "read_layers", refuse)
    record = RasFim.read_terrain_modifications(_hdf(tmp_path), hecras_version="7.0.1",
                                               length_units="feet")
    assert record["status"] == "refused"
    assert record["refusal_reason"] == "multi_ring_polygon"
    assert "multi-ring polygon" in record["refusal"]
    with pytest.raises(FimUnsupportedError) as raised:
        RasFim.read_terrain_modifications(_hdf(tmp_path, "b.hdf"), strict=True)
    assert raised.value.reason == "multi_ring_polygon"
