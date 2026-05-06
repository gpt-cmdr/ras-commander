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
        np.testing.assert_allclose(
            mod["Profile"][:],
            np.array([[0.0, 572.0], [100.0, 573.0], [200.0, 574.0]]),
        )

        attrs = mod["Attributes"][0]
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
        depth=4.0,
        max_extent=75.0,
    )

    with h5py.File(terrain_hdf, "r") as hdf:
        mod = hdf["Modifications/Pilot Channel"]
        assert _decode(mod.attrs["Subtype"]) == "Channel"
        np.testing.assert_allclose(
            mod["Profile Values"][:],
            np.array([[0.0, -4.0], [25.0, -4.0], [50.0, -4.0]]),
        )
        assert _decode(mod["Attributes"][0]["Elevation Type"]) == "SetIfLower"

    layer = _mod_layer(rasmap, "Pilot Channel")
    assert layer.find("DefaultModificationType").get("Value") == str(
        MODIFICATION_TAKE_LOWER
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
