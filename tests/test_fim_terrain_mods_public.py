"""Public ``RasFim.read_terrain_modifications`` against the private reader.

The public method is a thin wrapper of ``_terrain_mods.read_layers`` with the
project's HEC-RAS version and unit system resolved as
``RasFim.build_effective_terrain`` resolves them. These tests use the synthetic
terrain-modification fixtures of ``test_fim_terrain_mods``.
"""

import json

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
    "hecras_version_basis", "length_units", "length_units_basis", "layers",
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
    assert record["terrain_hdf"] == str(hdf)
    assert record["status"] == "staged" and record["refusal"] is None
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


def test_conflicting_project_units_are_a_refusal(tmp_path):
    (tmp_path / "Terrain").mkdir()
    (tmp_path / "A.prj").write_text("Proj Title=A\nEnglish Units\n")
    (tmp_path / "B.prj").write_text("Proj Title=B\nSI Units\n")
    hdf = _hdf(tmp_path / "Terrain", "Terrain.hdf")
    record = RasFim.read_terrain_modifications(hdf)
    assert record["status"] == "refused" and "different units" in record["refusal"]
    assert record["hecras_version"] == "7.0.1" and record["length_units"] is None


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
