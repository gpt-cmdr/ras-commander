import xml.etree.ElementTree as ET
import sys
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander.terrain.RasTerrainModWriter import (
    MODIFICATION_SET_VALUE,
    MODIFICATION_TAKE_HIGHER,
    MODIFICATION_TAKE_LOWER,
    RasTerrainModification,
    RasTerrainModWriter,
)


def _write_minimal_terrain(tmp_path):
    terrain_dir = tmp_path / "Terrain"
    terrain_dir.mkdir()
    terrain_hdf = terrain_dir / "Terrain.Clone.hdf"
    with h5py.File(terrain_hdf, "w") as hdf:
        hdf.create_group("Terrain")

    rasmap = tmp_path / "Project.rasmap"
    rasmap.write_text(
        """<RASMapper>
  <Version>2.0.0</Version>
  <Terrains Checked="True" Expanded="True">
    <Layer Name="Terrain Clone" Type="TerrainLayer" Checked="True" Filename=".\\Terrain\\Terrain.Clone.hdf">
      <ResampleMethod>near</ResampleMethod>
      <Surface On="True" />
    </Layer>
  </Terrains>
</RASMapper>""",
        encoding="utf-8",
    )
    return terrain_hdf, rasmap


def _decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8").rstrip("\x00")
    if isinstance(value, np.bytes_):
        return bytes(value).decode("utf-8").rstrip("\x00")
    return value


def _decode_array(values):
    return [_decode(value) for value in values]


def _mod_layer(rasmap, name):
    root = ET.parse(rasmap).getroot()
    for layer in root.findall(".//Layer"):
        if layer.get("Name") == name:
            return layer
    raise AssertionError(f"Layer not found: {name}")


class _FakeRaster:
    nodata = -9999.0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def sample(self, coords):
        for x, y in coords:
            yield np.array([900.0 + float(x) + float(y)], dtype=np.float64)


def test_top_level_exports_polygon_modification_alias():
    import ras_commander as ras
    from ras_commander.terrain import RasTerrainModification as terrain_alias

    assert ras.RasTerrainModification is terrain_alias
    assert terrain_alias.add_modification_polygon is not None


def test_add_polygon_modification_samples_boundary_and_writes_control_points(
    tmp_path, monkeypatch
):
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    terrain_hdf.with_suffix(".tif").write_text("fake raster", encoding="utf-8")

    opened_paths = []

    def fake_open(path):
        opened_paths.append(path)
        return _FakeRaster()

    monkeypatch.setitem(sys.modules, "rasterio", SimpleNamespace(open=fake_open))

    result = RasTerrainModification.add_modification_polygon(
        terrain_hdf,
        name="Wetland Pond",
        polygon_coords=[
            [0.0, 0.0],
            [10.0, 0.0],
            [10.0, 10.0],
            [0.0, 10.0],
        ],
        control_points=[
            {"x": 3.0, "y": 4.0, "elevation": 930.0, "name": "Rim"},
            (7.0, 6.0, 925.0, "Pool Bottom"),
        ],
        elev_pt_tolerance=15.0,
    )

    assert result == terrain_hdf
    assert opened_paths == [terrain_hdf.with_suffix(".tif")]

    expected_boundary = np.array(
        [
            [0.0, 0.0, 900.0],
            [10.0, 0.0, 910.0],
            [10.0, 10.0, 920.0],
            [0.0, 10.0, 910.0],
            [0.0, 0.0, 900.0],
        ]
    )

    with h5py.File(terrain_hdf, "r") as hdf:
        mod = hdf["Modifications/Wetland Pond"]
        assert _decode(mod.attrs["Type"]) == "Polygon"
        assert _decode(mod.attrs["Subtype"]) == "Multipoint"
        assert _decode(mod.attrs["Boundary Elevation Method"]) == "boundary_from_terrain"
        assert mod["Polygon Info"].attrs["Feature Type"] == b"Polygon"
        assert _decode_array(mod["Polygon Info"].attrs["Column"]) == [
            "Point Starting Index",
            "Point Count",
            "Part Starting Index",
            "Part Count",
        ]
        np.testing.assert_array_equal(mod["Polygon Info"][:], np.array([[0, 5, 0, 1]]))
        assert _decode_array(mod["Polygon Parts"].attrs["Column"]) == [
            "Point Starting Index",
            "Point Count",
        ]
        np.testing.assert_array_equal(mod["Polygon Parts"][:], np.array([[0, 5]]))
        assert _decode_array(mod["Polygon Points"].attrs["Column"]) == ["X", "Y"]
        np.testing.assert_allclose(mod["Polygon Points"][:], expected_boundary[:, :2])
        np.testing.assert_array_equal(mod["Profile Info"][:], np.array([[0, 5]]))
        np.testing.assert_allclose(
            mod["Profile Values"][:],
            np.column_stack(
                [
                    [0.0, 10.0, 20.0, 30.0, 40.0],
                    expected_boundary[:, 2],
                ]
            ),
        )
        np.testing.assert_allclose(mod["Boundary Points"][:], expected_boundary)
        np.testing.assert_allclose(mod["Boundary Elevations"][:], expected_boundary[:, 2])
        np.testing.assert_allclose(
            mod["Control Points/Points"][:],
            np.array([[3.0, 4.0], [7.0, 6.0]]),
        )
        np.testing.assert_allclose(
            mod["Control Points/Elevations"][:],
            np.array([930.0, 925.0]),
        )
        np.testing.assert_allclose(
            mod["Control Points/Elevation Points"][:],
            np.array([[3.0, 4.0, 930.0], [7.0, 6.0, 925.0]]),
        )
        np.testing.assert_allclose(
            mod["Elevation Points"][-2:],
            np.array([[3.0, 4.0, 930.0], [7.0, 6.0, 925.0]]),
        )

        attrs = mod["Attributes"][0]
        assert set(mod["Attributes"].dtype.names) == {
            "Name",
            "Elevation Value",
            "Elevation Type",
            "Elev Pt Tolerance",
            "Generate Boundary Elevations",
            "Use ShapeFile Z Elevations",
        }
        assert _decode(attrs["Name"]) == "Wetland Pond"
        assert attrs["Elevation Value"] == pytest.approx(0.0)
        assert _decode(attrs["Elevation Type"]) == "SetValue"
        assert attrs["Elev Pt Tolerance"] == pytest.approx(15.0)
        assert attrs["Generate Boundary Elevations"] == 1
        assert attrs["Use ShapeFile Z Elevations"] == 0

        assert mod["Control Points/Points"].attrs["Feature Type"] == b"Point"
        assert _decode_array(mod["Control Points/Points"].attrs["Column"]) == ["X", "Y"]

        cp_attrs = mod["Control Points/Attributes"][:]
        assert [_decode(value) for value in cp_attrs["Name"]] == ["Rim", "Pool Bottom"]
        np.testing.assert_allclose(cp_attrs["Elevation"], np.array([930.0, 925.0]))

    layer = _mod_layer(rasmap, "Wetland Pond")
    assert layer.get("Type") == "PolygonElevationModificationLayer"
    assert layer.get("Checked") == "True"
    assert layer.get("Expanded") == "True"
    assert layer.find("DefaultModificationType").get("Value") == str(
        MODIFICATION_SET_VALUE
    )
    assert layer.find("DefaultElevPtTol").get("Value") == "15"
    cp_layer = layer.find("Layer")
    assert cp_layer.get("Name") == "Control Points"
    assert cp_layer.get("Type") == "ElevationControlPointLayer"
    assert cp_layer.get("Checked") == "True"


def test_add_polygon_modification_uses_shape_z_boundary_elevations(tmp_path):
    terrain_hdf, _rasmap = _write_minimal_terrain(tmp_path)

    RasTerrainModWriter.add_modification_polygon(
        terrain_hdf,
        name="Shape Z Pond",
        polygon_coords=[
            [0.0, 0.0, 942.0],
            [20.0, 0.0, 943.0],
            [20.0, 20.0, 944.0],
            [0.0, 20.0, 945.0],
        ],
        elevation_method="shape_z",
        control_points=[(10.0, 10.0, 925.0)],
    )

    with h5py.File(terrain_hdf, "r") as hdf:
        mod = hdf["Modifications/Shape Z Pond"]
        np.testing.assert_allclose(
            mod["Boundary Elevations"][:],
            np.array([942.0, 943.0, 944.0, 945.0, 942.0]),
        )
        np.testing.assert_allclose(
            mod["Profile Values"][:, 1],
            np.array([942.0, 943.0, 944.0, 945.0, 942.0]),
        )
        assert mod["Attributes"][0]["Use ShapeFile Z Elevations"] == 1
        np.testing.assert_allclose(
            mod["Control Points/Elevations"][:],
            np.array([925.0]),
        )

    layer = _mod_layer(tmp_path / "Project.rasmap", "Shape Z Pond")
    assert layer.get("Type") == "PolygonElevationModificationLayer"


def test_polygon_modification_validates_control_points_inside_polygon(tmp_path):
    terrain_hdf, _rasmap = _write_minimal_terrain(tmp_path)

    with pytest.raises(ValueError, match="inside the polygon"):
        RasTerrainModWriter.add_modification_polygon(
            terrain_hdf,
            name="Bad Pond",
            polygon_coords=[
                [0.0, 0.0, 1.0],
                [10.0, 0.0, 1.0],
                [10.0, 10.0, 1.0],
                [0.0, 10.0, 1.0],
            ],
            elevation_method="shape_z",
            control_points=[(30.0, 30.0, 925.0)],
        )


def test_add_high_ground_modification_writes_hdf_and_rasmap(tmp_path):
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    points = np.array(
        [
            [0.0, 0.0, 572.0],
            [100.0, 0.0, 573.0],
            [200.0, 0.0, 574.0],
        ]
    )

    result = RasTerrainModWriter.add_high_ground_modification(
        terrain_hdf,
        rasmap,
        name="Upper Levee",
        polyline_points=points,
        top_width=20.0,
        side_slope=2.0,
        max_extent=100.0,
        elev_pt_tolerance=25.0,
    )

    assert result == terrain_hdf
    with h5py.File(terrain_hdf, "r") as hdf:
        mod = hdf["Modifications/Upper Levee"]
        assert _decode(mod.attrs["Type"]) == "Levee"
        assert _decode(mod.attrs["Subtype"]) == "Levee"
        np.testing.assert_allclose(mod["Polyline Points"][:], points[:, :2])
        np.testing.assert_array_equal(mod["Profile Info"][:], np.array([[0, 3]]))
        np.testing.assert_allclose(
            mod["Profile Values"][:],
            np.array([[0.0, 572.0], [100.0, 573.0], [200.0, 574.0]]),
        )
        # RAS Mapper reads Profile Info/Values only and saves no Profile
        # dataset and no empty Control Points group.
        assert "Profile" not in mod and "Control Points" not in mod

        attrs = mod["Attributes"][0]
        assert _decode(attrs["System Name"]) == ""
        assert np.isnan(attrs["Transition Percent"]) and np.isnan(attrs["Top Elevation"])
        assert _decode(attrs["Elevation Type"]) == "SetIfHigher"
        assert attrs["Top Width"] == pytest.approx(20.0)
        assert attrs["Left Slope"] == pytest.approx(2.0)
        assert attrs["Right Slope"] == pytest.approx(2.0)
        assert attrs["Max Reach"] == pytest.approx(100.0)
        assert attrs["Elev Pt Tolerance"] == pytest.approx(25.0)

    layer = _mod_layer(rasmap, "Upper Levee")
    assert layer.get("Type") == "GroundLineModificationLayer"
    assert layer.find("DefaultModificationType").get("Value") == str(
        MODIFICATION_TAKE_HIGHER
    )
    assert layer.find("DefaultElevPtTol").get("Value") == "25"

    modifications = RasTerrainModWriter.list_modifications(terrain_hdf)
    assert modifications.loc[0, "name"] == "Upper Levee"
    assert modifications.loc[0, "subtype"] == "Levee"
    assert modifications.loc[0, "modification_type"] == MODIFICATION_TAKE_HIGHER
    assert modifications.loc[0, "modification_mode"] == "take_higher"
    assert modifications.loc[0, "profile_points"] == 3

    profile = RasTerrainModWriter.get_modification_profile(terrain_hdf, "Upper Levee")
    assert profile["elevation"].tolist() == [572.0, 573.0, 574.0]


def test_add_fill_surface_modification_uses_set_value_mode(tmp_path):
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)

    RasTerrainModWriter.add_fill_surface_modification(
        terrain_hdf,
        rasmap,
        name="Floodway Fill",
        polyline_points=np.array([[0.0, 0.0], [0.0, 50.0]]),
        top_width=30.0,
        left_slope=3.0,
        right_slope=4.0,
        max_extent=120.0,
        elevation=535.5,
    )

    with h5py.File(terrain_hdf, "r") as hdf:
        mod = hdf["Modifications/Floodway Fill"]
        assert _decode(mod.attrs["Subtype"]) == "Levee"
        np.testing.assert_allclose(
            mod["Profile Values"][:],
            np.array([[0.0, 535.5], [50.0, 535.5]]),
        )

        attrs = mod["Attributes"][0]
        assert _decode(attrs["Elevation Type"]) == "SetValue"
        assert attrs["Top Width"] == pytest.approx(30.0)
        assert attrs["Left Slope"] == pytest.approx(3.0)
        assert attrs["Right Slope"] == pytest.approx(4.0)

    layer = _mod_layer(rasmap, "Floodway Fill")
    assert layer.find("DefaultModificationType").get("Value") == str(
        MODIFICATION_SET_VALUE
    )


def test_add_channel_modification_keeps_take_lower_mode(tmp_path):
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)

    RasTerrainModWriter.add_channel_modification(
        terrain_hdf,
        rasmap,
        name="Pilot Channel",
        polyline_points=np.array([[0.0, 0.0], [30.0, 40.0]]),
        width=15.0,
        profile_points=[[0.0, 96.0], [50.0, 95.0]],
        max_extent=75.0,
    )

    with h5py.File(terrain_hdf, "r") as hdf:
        mod = hdf["Modifications/Pilot Channel"]
        assert _decode(mod.attrs["Type"]) == "Levee"
        assert _decode(mod.attrs["Subtype"]) == "Channel"
        # RAS Mapper's profile is the absolute invert elevation.
        np.testing.assert_allclose(
            mod["Profile Values"][:], np.array([[0.0, 96.0], [50.0, 95.0]])
        )
        assert _decode(mod["Attributes"][0]["Elevation Type"]) == "SetIfLower"
        assert _decode(mod["Attributes"][0]["System Name"]) == ""

    layer = _mod_layer(rasmap, "Pilot Channel")
    assert layer.find("DefaultModificationType").get("Value") == str(
        MODIFICATION_TAKE_LOWER
    )


def test_profile_readback_reads_profile_values_like_ras_mapper(tmp_path):
    """RAS Mapper reads the float32 Profile Values; the float64 Profile
    dataset older writers added is never read, so the helpers must not
    prefer it."""
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    profile_points = np.array([[0.0, 601.1234567], [250.5, 601.7654321]])
    RasTerrainModWriter.add_high_ground_modification(
        terrain_hdf, rasmap, name="Old",
        polyline_points=np.array([[0.0, 0.0], [250.5, 0.0]]),
        profile_points=profile_points,
    )
    with h5py.File(terrain_hdf, "a") as hdf:
        hdf["Modifications/Old"].create_dataset(
            "Profile", data=np.array([[0.0, 1.0], [250.5, 2.0]])
        )
    profile = RasTerrainModWriter.get_modification_profile(terrain_hdf, "Old")
    np.testing.assert_array_equal(
        profile[["station", "elevation"]].to_numpy(),
        profile_points.astype(np.float32).astype(np.float64),
    )


def test_channel_depth_is_measured_below_the_sampled_terrain(tmp_path, monkeypatch):
    """depth used to be written as an absolute -depth profile: HEC-RAS 6.6 and
    7.0.1 then cut the channel to -10 ft, up to 1,825 ft below ground."""
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    monkeypatch.setattr(
        RasTerrainModWriter, "_sample_terrain_elevations",
        staticmethod(lambda hdf, xy: 900.0 + xy[:, 0]),
    )
    RasTerrainModWriter.add_channel_modification(
        terrain_hdf, rasmap, name="Cut",
        polyline_points=np.array([[0.0, 0.0], [30.0, 40.0], [60.0, 80.0]]),
        width=15.0, depth=4.0, max_extent=75.0,
    )
    profile = RasTerrainModWriter.get_modification_profile(terrain_hdf, "Cut")
    np.testing.assert_allclose(profile["station"], [0.0, 50.0, 100.0])
    np.testing.assert_allclose(profile["elevation"], [896.0, 926.0, 956.0])

    with pytest.raises(ValueError, match="depth cannot be combined"):
        RasTerrainModWriter.add_channel_modification(
            terrain_hdf, rasmap, name="Both",
            polyline_points=np.array([[0.0, 0.0], [30.0, 40.0]]),
            depth=4.0, elevation=95.0,
        )


def test_ground_line_layout_matches_ras_mapper(tmp_path):
    """Field by field, the layout RasMapperLib 6.6/7.0.1 saves for a channel."""
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    RasTerrainModWriter.add_channel_modification(
        terrain_hdf, rasmap, name="chan",
        polyline_points=np.array([[0.0, 0.0], [30.0, 40.0], [100.0, 40.0]]),
        width=40.0, left_slope=3.0, right_slope=3.0, max_extent=160.0,
        profile_points=[[0.0, 1200.0], [120.0, 1100.0]],
    )
    with h5py.File(terrain_hdf, "r") as hdf:
        mod = hdf["Modifications/chan"]
        assert {k: _decode(v) for k, v in mod.attrs.items()} == {
            "Type": "Levee", "Subtype": "Channel", "Priority": 0,
        }
        assert sorted(mod.keys()) == [
            "Attributes", "Polyline Info", "Polyline Parts", "Polyline Points",
            "Profile Info", "Profile Values",
        ]
        assert mod["Attributes"].dtype.names == (
            "System Name", "Name", "Elevation Type", "Top Elevation", "Top Width",
            "Left Slope", "Right Slope", "Max Reach", "Transition Percent",
            "Elev Pt Tolerance",
        )
        assert mod["Attributes"].dtype["Elevation Type"] == np.dtype("S11")
        assert mod["Profile Values"].dtype == np.dtype("float32")
        assert mod["Polyline Points"].dtype == np.dtype("float64")
        assert _decode(mod["Polyline Info"].attrs["Feature Type"]) == "Polyline"
        np.testing.assert_array_equal(mod["Polyline Info"][:], [[0, 3, 0, 1]])
        np.testing.assert_array_equal(mod["Polyline Parts"][:], [[0, 3]])


def test_named_system_is_opt_in(tmp_path, caplog):
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    with caplog.at_level("WARNING"):
        RasTerrainModWriter.add_high_ground_modification(
            terrain_hdf, rasmap, name="Wall",
            polyline_points=np.array([[0.0, 0.0, 10.0], [100.0, 0.0, 10.0]]),
            system_name="Ring Levee", transition_fraction=0.5,
        )
    assert "system path" in caplog.text
    with h5py.File(terrain_hdf, "r") as hdf:
        attrs = hdf["Modifications/Wall/Attributes"][0]
        assert _decode(attrs["System Name"]) == "Ring Levee"
        assert attrs["Transition Percent"] == pytest.approx(0.5)
    listing = RasTerrainModWriter.list_modifications(terrain_hdf)
    assert listing.loc[0, "system_names"] == ["Ring Levee"]
    assert listing.loc[0, "feature_count"] == 1


def test_update_rasmap_xml_raises_clear_error_when_group_missing(
    tmp_path, monkeypatch
):
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    monkeypatch.setattr(
        RasTerrainModWriter,
        "_ensure_modification_group_in_rasmap",
        staticmethod(lambda *args, **kwargs: None),
    )

    with pytest.raises(
        RuntimeError, match="ElevationModificationGroup not found after rasmap update"
    ):
        RasTerrainModWriter._update_rasmap_xml(
            rasmap,
            terrain_hdf,
            name="Missing Group",
            mod_type="GroundLineModificationLayer",
            default_mod_type=MODIFICATION_TAKE_HIGHER,
            elev_pt_tolerance=50.0,
            group_name="Modifications",
        )


def test_sample_modification_surface_applies_take_higher(tmp_path):
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    RasTerrainModWriter.add_high_ground_modification(
        terrain_hdf,
        rasmap,
        name="Verification Levee",
        polyline_points=np.array([[0.0, 0.0, 10.0], [100.0, 0.0, 10.0]]),
        top_width=10.0,
        side_slope=2.0,
        max_extent=30.0,
    )

    sampled = RasTerrainModWriter.sample_modification_surface(
        terrain_hdf,
        "Verification Levee",
        points=np.array([[50.0, 0.0], [50.0, 10.0], [50.0, 40.0]]),
        existing_elevations=np.array([5.0, 9.0, 5.0]),
    )

    assert sampled["line_station"].tolist() == [50.0, 50.0, 50.0]
    assert sampled["offset"].tolist() == [0.0, 10.0, 40.0]
    assert sampled["modification_surface"].iloc[0] == pytest.approx(10.0)
    assert sampled["modification_surface"].iloc[1] == pytest.approx(7.5)
    assert np.isnan(sampled["modification_surface"].iloc[2])
    assert sampled["modified_elevation"].tolist() == [10.0, 9.0, 5.0]
    assert sampled["difference"].tolist() == [5.0, 0.0, 0.0]


def test_apply_modification_to_profile_reconstructs_xy_from_station(tmp_path):
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    RasTerrainModWriter.add_high_ground_modification(
        terrain_hdf,
        rasmap,
        name="Profile Levee",
        polyline_points=np.array([[0.0, 0.0, 10.0], [100.0, 0.0, 10.0]]),
        top_width=10.0,
        side_slope=2.0,
        max_extent=30.0,
    )

    profile = pd.DataFrame(
        {
            "station": [0.0, 20.0, 25.0, 30.0, 40.0],
            "elevation": [5.0, 5.0, 5.0, 9.0, 5.0],
        }
    )
    comparison = RasTerrainModWriter.apply_modification_to_profile(
        terrain_hdf,
        "Profile Levee",
        profile,
        x_coords=[50.0, 50.0],
        y_coords=[-20.0, 20.0],
    )

    assert comparison["x"].tolist() == [50.0] * 5
    assert comparison["y"].tolist() == [-20.0, 0.0, 5.0, 10.0, 20.0]
    assert comparison["proposed_elevation"].tolist() == [5.0, 10.0, 10.0, 9.0, 5.0]
    assert comparison["difference"].tolist() == [0.0, 5.0, 5.0, 0.0, 0.0]


def test_high_ground_requires_elevation_for_xy_only_points(tmp_path):
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)

    with pytest.raises(ValueError, match="elevation or profile_points is required"):
        RasTerrainModWriter.add_high_ground_modification(
            terrain_hdf,
            rasmap,
            name="Missing Elevation",
            polyline_points=np.array([[0.0, 0.0], [10.0, 0.0]]),
        )


def test_explicit_elevation_overrides_nonfinite_z_values(tmp_path):
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)

    RasTerrainModWriter.add_high_ground_modification(
        terrain_hdf,
        rasmap,
        name="Constant Crest",
        polyline_points=np.array([[0.0, 0.0, np.nan], [10.0, 0.0, np.nan]]),
        elevation=601.25,
    )

    profile = RasTerrainModWriter.get_modification_profile(terrain_hdf, "Constant Crest")
    assert profile["elevation"].tolist() == [601.25, 601.25]


def test_provided_level_boundary_is_stored_as_the_constant_elevation(tmp_path):
    """RAS Mapper sets a polygon with Generate Boundary Elevations off to its
    Elevation Value; writing 0.0 there flattened provided 700 ft boundaries to
    0 ft in HEC-RAS 7.0.1's export."""
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    RasTerrainModWriter.add_modification_polygon(
        terrain_hdf,
        name="Pad",
        polygon_coords=[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
        elevation_method="provided",
        boundary_elevations=[700.0] * 5,
        rasmap_path=rasmap,
    )
    with h5py.File(terrain_hdf, "r") as hdf:
        attrs = hdf["Modifications/Pad/Attributes"][0]
        assert attrs["Elevation Value"] == pytest.approx(700.0)
        assert attrs["Generate Boundary Elevations"] == 0


def test_layers_get_unique_priorities_newest_on_top(tmp_path):
    """RAS Mapper numbers modification layers 0..n-1 by list position, puts a
    new layer on top and applies Priority 0 last (it wins); equal priorities
    leave the application order undefined."""
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    RasTerrainModWriter.add_channel_modification(
        terrain_hdf, rasmap, name="A", polyline_points=np.array([[0.0, 0.0], [30.0, 40.0]]),
        width=15.0, elevation=4.0, max_extent=75.0,
    )
    RasTerrainModWriter.add_modification_polygon(
        terrain_hdf, name="B", polygon_coords=[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]],
        elevation_method="provided", boundary_elevations=[5.0] * 4, rasmap_path=rasmap,
    )
    RasTerrainModWriter.add_channel_modification(
        terrain_hdf, rasmap, name="A", polyline_points=np.array([[0.0, 0.0], [30.0, 40.0]]),
        width=15.0, elevation=4.0, max_extent=75.0,
    )
    with h5py.File(terrain_hdf, "r") as hdf:
        priorities = {name: int(grp.attrs["Priority"]) for name, grp in hdf["Modifications"].items()}
    assert priorities == {"A": 0, "B": 1}

    RasTerrainModWriter.add_modification_polygon(
        terrain_hdf, name="C", polygon_coords=[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]],
        elevation=7.0, rasmap_path=rasmap, priority=2,
    )
    with h5py.File(terrain_hdf, "r") as hdf:
        priorities = {name: int(grp.attrs["Priority"]) for name, grp in hdf["Modifications"].items()}
    assert priorities == {"A": 0, "B": 1, "C": 2}


@pytest.mark.parametrize("method", ["shape_z", "provided"])
def test_varying_polygon_boundary_is_stored_as_vertex_z(tmp_path, method):
    """Vertex Z with Use ShapeFile Z on is the varying-boundary form RAS
    Mapper 6.6, 7.0 and 7.0.1 all read (6.6 stores no polygon profile). A
    varying provided boundary is stored the same way (it used to store a 0
    constant that RAS Mapper applied)."""
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    xyz = [[0.0, 0.0, 10.0], [10.0, 0.0, 11.0], [10.0, 10.0, 12.0], [0.0, 10.0, 11.0]]
    if method == "shape_z":
        kwargs = dict(polygon_coords=xyz)
    else:
        kwargs = dict(polygon_coords=[p[:2] for p in xyz],
                      boundary_elevations=[10.0, 11.0, 12.0, 11.0, 10.0])
    RasTerrainModWriter.add_modification_polygon(
        terrain_hdf, name="Pond", elevation_method=method, rasmap_path=rasmap, **kwargs,
    )
    with h5py.File(terrain_hdf, "r") as hdf:
        mod = hdf["Modifications/Pond"]
        np.testing.assert_allclose(mod["Polygon Points"][:, 2], [10.0, 11.0, 12.0, 11.0, 10.0])
        assert _decode_array(mod["Polygon Points"].attrs["Column"]) == ["X", "Y", "Z"]
        attrs = mod["Attributes"][0]
        assert attrs["Use ShapeFile Z Elevations"] == 1
        assert attrs["Generate Boundary Elevations"] == 0
        assert np.isfinite(attrs["Elevation Value"])  # NaN would make RAS skip it


def test_constant_polygon_and_ellipse_writers(tmp_path):
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    RasTerrainModWriter.add_modification_polygon(
        terrain_hdf, name="Pad", polygon_coords=[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]],
        elevation=700.0, rasmap_path=rasmap,
    )
    RasTerrainModWriter.add_ellipse_modification(
        terrain_hdf, rasmap, "Mounds",
        [{"center": (5.0, 6.0), "radius_x": 4.0, "radius_y": 2.0, "rotation": 30.0, "elevation": 47.75},
         {"center": (50.0, 6.0), "radius_x": 3.0, "elevation": 40.0, "mode": "take_higher"}],
    )
    with h5py.File(terrain_hdf, "r") as hdf:
        pad = hdf["Modifications/Pad/Attributes"][0]
        assert pad["Elevation Value"] == pytest.approx(700.0)
        assert pad["Generate Boundary Elevations"] == 0 and pad["Use ShapeFile Z Elevations"] == 0
        mounds = hdf["Modifications/Mounds"]
        assert _decode(mounds.attrs["Type"]) == "Circle" and "Subtype" not in mounds.attrs
        np.testing.assert_allclose(
            mounds["Circles"][:], [[5.0, 6.0, 4.0, 2.0, 30.0], [50.0, 6.0, 3.0, 3.0, 0.0]]
        )
        assert _decode_array(mounds["Attributes"]["Elevation Type"]) == ["SetValue", "SetIfHigher"]
    assert _mod_layer(rasmap, "Mounds").get("Type") == "EllipseElevationModificationLayer"
    group = next(
        layer for layer in ET.parse(rasmap).getroot().iter("Layer")
        if layer.get("Type") == "ElevationModificationGroup"
    )
    assert [layer.get("Name") for layer in group.findall("Layer")] == ["Mounds", "Pad"]


def test_read_layers_round_trips_through_add_modification_layer(tmp_path):
    """A layer read from a terrain and written back reads identically."""
    from ras_commander.fim import _terrain_mods

    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    RasTerrainModWriter.add_modification_layer(terrain_hdf, rasmap, {
        "kind": "ground_line", "name": "Levees", "subtype": "levee", "features": [
            {"elevation_type": "SetIfHigher", "top_width": 20.0, "left_slope": 2.0,
             "right_slope": 3.0, "max_reach": 100.0,
             "points": [[0.0, 0.0], [100.0, 0.0], [150.0, 50.0]],
             "profile": [[0.0, 10.0], [170.5, 12.0]]},
            {"elevation_type": "SetValue", "top_width": 600.0, "left_slope": 2.0,
             "right_slope": 2.0, "max_reach": 100.0,
             "points": [[0.0, 10.0], [50.0, 10.0]], "profile": [[0.0, 5.0], [50.0, 5.0]]},
        ]})
    RasTerrainModWriter.add_modification_layer(terrain_hdf, rasmap, {
        "kind": "polygon", "name": "Pads", "features": [
            {"elevation_type": "SetValue", "elevation": 40.5,
             # Single ring: read_layers refuses multi-ring polygons (Fast-Map #42).
             "rings": [[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 0.0]]]},
            {"elevation_type": "SetIfLower", "elevation": 1.0,
             "rings": [[[20.0, 0.0], [30.0, 0.0], [30.0, 10.0], [20.0, 0.0]]]},
        ]})
    RasTerrainModWriter.add_modification_layer(terrain_hdf, rasmap, {
        "kind": "ellipse", "name": "E", "features": [
            {"elevation_type": "SetValue", "elevation": 47.75, "center": [5.0, 6.0],
             "radius_x": 4.0, "radius_y": 2.0, "rotation": -63.5}]})
    first = _terrain_mods.read_layers(terrain_hdf)
    assert [layer["name"] for layer in first] == ["E", "Levees", "Pads"]
    assert [layer["priority"] for layer in first] == [0, 2, 1]

    (tmp_path / "copy").mkdir()
    copy_hdf, copy_rasmap = _write_minimal_terrain(tmp_path / "copy")
    for layer in sorted(first, key=lambda layer: -layer["priority"]):
        RasTerrainModWriter.add_modification_layer(copy_hdf, copy_rasmap, layer)
    assert _terrain_mods.read_layers(copy_hdf) == first


def test_round_trip_of_binary32_profile_stations_does_not_warn(tmp_path, caplog):
    """A read-back profile ending one float32 step past the line is not an overrun."""
    from ras_commander.fim import _terrain_mods

    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    # Length 3383.914...: float32 rounds it up, so the stored last station
    # reads back larger than the binary64 length of the same vertices.
    line = np.array([[0.0, 0.0], [1500.0, 1000.0], [2000.0, 2500.0]])
    length = float(RasTerrainModWriter._station_values(line)[-1])
    assert float(np.float32(length)) > length
    RasTerrainModWriter.add_high_ground_modification(
        terrain_hdf, rasmap, "Levee", line, top_width=20.0, side_slope=3.0,
        max_extent=120.0, elevation=562.0,
    )
    (layer,) = _terrain_mods.read_layers(terrain_hdf)
    (tmp_path / "copy").mkdir()
    copy_hdf, copy_rasmap = _write_minimal_terrain(tmp_path / "copy")
    with caplog.at_level("WARNING"):
        RasTerrainModWriter.add_modification_layer(copy_hdf, copy_rasmap, layer)
    assert "fall outside the line length" not in caplog.text
    assert _terrain_mods.read_layers(copy_hdf) == [layer]

    with caplog.at_level("WARNING"):
        RasTerrainModWriter.add_high_ground_modification(
            copy_hdf, copy_rasmap, "Long", line, top_width=20.0, side_slope=3.0,
            max_extent=120.0, profile_points=[[0.0, 1.0], [length + 1.0, 1.0]],
        )
    assert "fall outside the line length" in caplog.text


@pytest.mark.parametrize("channel, offset, expected", [
    (False, 0.0, 10.0),
    (False, 10.0, 7.5),     # 5 ft down a 2:1 side
    (False, 16.0, np.nan),  # beyond Max Reach / 2 = 15
    (True, 10.0, 12.5),     # channel sides rise
])
def test_sample_modification_surface_follows_ras_template(tmp_path, channel, offset, expected):
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    line = np.array([[0.0, 0.0, 10.0], [100.0, 0.0, 10.0]])
    if channel:
        RasTerrainModWriter.add_channel_modification(
            terrain_hdf, rasmap, "T", line, width=10.0, left_slope=2.0, right_slope=2.0,
            max_extent=30.0,
        )
    else:
        RasTerrainModWriter.add_high_ground_modification(
            terrain_hdf, rasmap, "T", line, top_width=10.0, side_slope=2.0, max_extent=30.0,
        )
    sampled = RasTerrainModWriter.sample_modification_surface(
        terrain_hdf, "T", points=np.array([[50.0, offset]])
    )
    value = sampled["modification_surface"].iloc[0]
    if np.isnan(expected):
        assert np.isnan(value)
    else:
        assert value == pytest.approx(expected)


def test_failed_replacement_keeps_the_existing_layer(tmp_path):
    """An out-of-range priority is refused before the old layer is deleted."""
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    RasTerrainModWriter.add_modification_polygon(
        terrain_hdf, name="Pad", polygon_coords=[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]],
        elevation=7.0, rasmap_path=rasmap,
    )
    with pytest.raises(ValueError, match="priority must be between 0 and 0"):
        RasTerrainModWriter.add_modification_polygon(
            terrain_hdf, name="Pad", polygon_coords=[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]],
            elevation=9.0, rasmap_path=rasmap, priority=3,
        )
    with h5py.File(terrain_hdf, "r") as hdf:
        assert "Attributes" in hdf["Modifications/Pad"]
        assert float(hdf["Modifications/Pad/Attributes"]["Elevation Value"][0]) == 7.0


@pytest.mark.parametrize("layer, reason", [
    ({"kind": "polygon", "name": "P", "control_points": [{"x": 1.0, "y": 1.0, "elevation": 3.0}],
      "features": [{"elevation_type": "SetValue", "elevation": 1.0,
                    "rings": [[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 0.0]]]}]},
     "control points"),
    ({"kind": "polygon", "name": "P", "features": [
        {"elevation_type": "SetValue", "elevation": 1.0, "generate_boundary": True,
         "profile": [[0.0, 1.0], [30.0, 2.0]],
         "rings": [[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 0.0]]]}]},
     "only constant polygons"),
])
def test_add_modification_layer_refuses_fields_it_cannot_store(tmp_path, layer, reason):
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    with pytest.raises(ValueError, match=reason):
        RasTerrainModWriter.add_modification_layer(terrain_hdf, rasmap, layer)
    with h5py.File(terrain_hdf, "r") as hdf:
        assert "Modifications" not in hdf or "P" not in hdf["Modifications"]


def test_add_modification_layer_writes_null_template_values_as_nan(tmp_path):
    from ras_commander.fim import _terrain_mods

    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    RasTerrainModWriter.add_modification_layer(terrain_hdf, rasmap, {
        "kind": "ground_line", "name": "L", "subtype": "levee", "features": [
            {"elevation_type": "SetIfHigher", "top_width": 20.0, "left_slope": None,
             "right_slope": 3.0, "max_reach": None, "elev_pt_tolerance": None,
             "transition_percent": None,
             "points": [[0.0, 0.0], [100.0, 0.0]], "profile": [[0.0, 10.0], [100.0, 12.0]]}]})
    feature = _terrain_mods.read_layers(terrain_hdf)[0]["features"][0]
    assert (feature["left_slope"], feature["max_reach"], feature["elev_pt_tolerance"]) == (None, None, None)
    assert feature["transition_percent"] is None


def test_terrain_sources_are_sampled_in_priority_order(tmp_path):
    """Samplers keep the first finite value, so the priority-0 source comes first."""
    terrain_dir = tmp_path / "Terrain"
    terrain_dir.mkdir()
    hdf_path = terrain_dir / "T.hdf"
    for name in ("a_low.tif", "z_high.tif"):
        (terrain_dir / name).write_bytes(b"")
    with h5py.File(hdf_path, "w") as hdf:
        for group, file, priority in (("T.a_low", "a_low.tif", 1), ("T.z_high", "z_high.tif", 0)):
            g = hdf.create_group(f"Terrain/{group}")
            g.attrs["File"] = np.bytes_(file)
            g.attrs["Priority"] = np.int32(priority)
            mask = np.ones((1, 65536), dtype=np.uint8)
            g.create_group("0").create_dataset("Mask", data=mask)
    ordered = RasTerrainModWriter._priority_ordered(
        hdf_path, [terrain_dir / "a_low.tif", terrain_dir / "z_high.tif"])
    assert [p.name for p in ordered] == ["z_high.tif", "a_low.tif"]


def test_supplied_boundary_elevations_imply_provided(tmp_path):
    """Without elevation_method, supplied boundary elevations are stored as
    vertex Z, not as a terrain-sampled boundary (Generate on)."""
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    RasTerrainModWriter.add_modification_polygon(
        terrain_hdf, name="Pond", polygon_coords=[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
        boundary_elevations=[10.0, 11.0, 12.0, 11.0, 10.0], rasmap_path=rasmap,
    )
    with h5py.File(terrain_hdf, "r") as hdf:
        mod = hdf["Modifications/Pond"]
        attrs = mod["Attributes"][0]
        assert attrs["Generate Boundary Elevations"] == 0
        assert attrs["Use ShapeFile Z Elevations"] == 1
        np.testing.assert_allclose(mod["Polygon Points"][:, 2], [10.0, 11.0, 12.0, 11.0, 10.0])


def _modification_groups(rasmap):
    return [
        layer for layer in ET.parse(rasmap).getroot().iter("Layer")
        if layer.get("Type") == "ElevationModificationGroup"
    ]


def test_writer_registers_layers_in_the_modifications_group(tmp_path):
    """RAS Mapper (6.6, 7.0.1) applies modifications only from a group named Modifications."""
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    RasTerrainModWriter.add_high_ground_modification(
        terrain_hdf, rasmap, name="Levee", polyline_points=[[0, 0, 10], [100, 0, 10]],
    )
    RasTerrainModWriter.add_ellipse_modification(
        terrain_hdf, rasmap, name="Mound", ellipses=[{"center": (5, 5), "radius_x": 2, "elevation": 9}],
    )
    groups = _modification_groups(rasmap)
    assert [group.get("Name") for group in groups] == ["Modifications"]
    assert [layer.get("Name") for layer in groups[0].findall("Layer")] == ["Mound", "Levee"]


@pytest.mark.parametrize("group_name", ["Hydroconnectors", "modifications", ""])
def test_writer_refuses_a_group_name_ras_mapper_ignores(tmp_path, group_name):
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    before = rasmap.read_bytes()
    with pytest.raises(ValueError, match="named exactly 'Modifications'"):
        RasTerrainModWriter.add_high_ground_modification(
            terrain_hdf, rasmap, name="Levee", polyline_points=[[0, 0, 10], [100, 0, 10]],
            group_name=group_name,
        )
    with pytest.raises(ValueError, match="named exactly 'Modifications'"):
        RasTerrainModWriter.add_modification_group(terrain_hdf, rasmap, group_name=group_name)
    # Refused before anything is written.
    assert rasmap.read_bytes() == before
    with h5py.File(terrain_hdf, "r") as hdf:
        assert "Modifications" not in hdf


def test_writer_renames_an_existing_misnamed_group(tmp_path, caplog):
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    text = rasmap.read_text(encoding="utf-8").replace(
        "<Surface On=\"True\" />",
        "<Surface On=\"True\" />\n      <Layer Name=\"Hydroconnectors\" Type=\"ElevationModificationGroup\">"
        "<Layer Name=\"Old\" Type=\"GroundLineModificationLayer\" /></Layer>",
    )
    rasmap.write_text(text, encoding="utf-8")
    with caplog.at_level("WARNING"):
        RasTerrainModWriter.add_high_ground_modification(
            terrain_hdf, rasmap, name="Levee", polyline_points=[[0, 0, 10], [100, 0, 10]],
        )
    assert "Renamed .rasmap modification group 'Hydroconnectors'" in caplog.text
    groups = _modification_groups(rasmap)
    assert [group.get("Name") for group in groups] == ["Modifications"]
    assert [layer.get("Name") for layer in groups[0].findall("Layer")] == ["Levee", "Old"]


def _perimeter_pond(tmp_path, monkeypatch, **kwargs):
    terrain_hdf, rasmap = _write_minimal_terrain(tmp_path)
    terrain_hdf.with_suffix(".tif").write_text("fake raster", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "rasterio", SimpleNamespace(open=lambda path: _FakeRaster()))
    arguments = dict(
        name="Perimeter Pond",
        polygon_coords=[[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]],
        control_points=[(50.0, 50.0, 880.0)],
        perimeter_control_points=[(-10.0, 50.0, 905.0), {"x": 50.0, "y": 115.0, "z": 912.0},
                                  (110.0, -5.0, 908.0, "SE")],
        elev_pt_tolerance=20.0,
    )
    arguments.update(kwargs)
    RasTerrainModWriter.add_modification_polygon(terrain_hdf, **arguments)
    return terrain_hdf


def test_perimeter_control_points_are_written_after_interior_points(tmp_path, monkeypatch):
    terrain_hdf = _perimeter_pond(tmp_path, monkeypatch)
    with h5py.File(terrain_hdf, "r") as hdf:
        mod = hdf["Modifications/Perimeter Pond"]
        assert int(mod["Attributes"]["Generate Boundary Elevations"][0]) == 1
        cp = mod["Control Points"]
        np.testing.assert_array_equal(
            cp["Points"][:], [[50.0, 50.0], [-10.0, 50.0], [50.0, 115.0], [110.0, -5.0]]
        )
        assert cp["Attributes"]["Elevation"].tolist() == [880.0, 905.0, 912.0, 908.0]
        assert _decode_array(cp["Attributes"]["Name"]) == [
            "Control Point 1", "Perimeter Point 1", "Perimeter Point 2", "SE",
        ]
        # The writer's chunked layout, which RAS Mapper reads (a contiguous
        # Control Points group is ignored by RAS Mapper).
        assert cp["Points"].chunks is not None
    # The native reader stages it under every rule, including 6.6.
    from ras_commander.fim import _terrain_mods

    for rule in ("6.6", "6.7", "7.0.1"):
        layer = _terrain_mods.read_layers(terrain_hdf, hecras_version=rule)[0]
        assert len(layer["control_points"]) == 4


@pytest.mark.parametrize("kwargs, message", [
    ({"perimeter_control_points": [(50.0, 50.0, 900.0)]}, "outside the polygon exterior"),
    ({"perimeter_control_points": [(100.0, 50.0, 900.0)]}, "outside the polygon exterior"),
    ({"perimeter_control_points": [(-21.0, 50.0, 900.0)]}, "within elev_pt_tolerance"),
    ({"perimeter_control_points": []}, "is empty"),
    ({"perimeter_control_points": [(-5.0, 50.0, 900.0)], "elevation": 900.0},
     "boundary_from_terrain"),
    ({"perimeter_control_points": [(-5.0, 50.0, 900.0)],
      "polygon_coords": [[[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]],
                         [[20.0, 20.0], [40.0, 20.0], [40.0, 40.0], [20.0, 40.0]]]},
     "single-ring"),
])
def test_perimeter_control_points_are_validated(tmp_path, monkeypatch, kwargs, message):
    with pytest.raises(ValueError, match=message):
        _perimeter_pond(tmp_path, monkeypatch, **kwargs)
    with h5py.File(tmp_path / "Terrain" / "Terrain.Clone.hdf", "r") as hdf:
        assert "Modifications" not in hdf or "Perimeter Pond" not in hdf["Modifications"]
