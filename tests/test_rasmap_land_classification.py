"""
Tests for RasMap land-classification parsing and API scaffolding.
"""

import inspect
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ras_commander import RasMap
from ras_commander.hdf import HdfInfiltration, HdfLandCover
import ras_commander._land_classification_helper as _lch


def _read_projection_wkt() -> str:
    projection_path = (
        REPO_ROOT
        / "example_projects"
        / "BaldEagleCrkMulti2D"
        / "Terrain"
        / "Projection.prj"
    )
    if projection_path.exists():
        return projection_path.read_text(encoding="utf-8")
    return "EPSG:2271"


def _make_temp_project(tmp_path: Path, project_name: str = "TestModel") -> Path:
    project_dir = tmp_path / project_name
    project_dir.mkdir()
    (project_dir / f"{project_name}.prj").write_text(
        "Proj Title=Temp Project\nCurrent Plan=\n",
        encoding="utf-8",
    )
    (project_dir / "Projection.prj").write_text(_read_projection_wkt(), encoding="utf-8")
    (project_dir / f"{project_name}.rasmap").write_text(
        (
            "<RASMapper>\n"
            '  <RASProjectionFilename Filename=".\\Projection.prj" />\n'
            "  <MapLayers />\n"
            "</RASMapper>\n"
        ),
        encoding="utf-8",
    )
    return project_dir


class TestImportSafety:
    """Importing ras_commander must not eagerly require pythonnet/clr."""

    def test_main_package_import_without_clr(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")

        code = """
import builtins

real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name == "clr":
        raise ImportError("clr blocked for import-safety test")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import

import ras_commander
from ras_commander import RasMap

assert RasMap is not None
print("ok")
"""

        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert "ok" in result.stdout


class TestPublicAPISurface:
    """New land-classification methods should exist on RasMap."""

    @pytest.mark.parametrize(
        "method_name",
        [
            "add_landcover_layer",
            "add_soils_layer",
            "add_infiltration_layer",
            "associate_geometry_layers",
            "recompute_property_tables",
            "list_land_classification_layers",
            "list_terrain_layers",
            "list_landcover_layers",
            "list_soils_layers",
            "list_infiltration_layers",
            "list_land_classification_polygons",
            "add_land_classification_polygon",
            "update_land_classification_polygon",
            "delete_land_classification_polygon",
            "get_hdf_geometry_association",
        ],
    )
    def test_method_exists_and_is_static_style(self, method_name):
        assert hasattr(RasMap, method_name)
        signature = inspect.signature(getattr(RasMap, method_name))
        assert "self" not in signature.parameters
        assert list(signature.parameters)[-1] == "ras_object"


class TestPackagedResources:
    """Packaged land-classification templates and extras should stay valid."""

    def test_packaged_land_classification_templates_open_with_h5py(self):
        template_paths = [
            _lch._RESOURCE_DIR / "landcover_template.hdf",
            _lch._RESOURCE_DIR / "soils_template.hdf",
        ]

        for template_path in template_paths:
            with h5py.File(template_path, "r") as hdf_file:
                assert len(hdf_file.keys()) > 0

    def test_all_extra_includes_pythonnet(self, monkeypatch):
        captured = {}

        def fake_setup(**kwargs):
            captured.update(kwargs)

        monkeypatch.chdir(REPO_ROOT)
        monkeypatch.setattr("setuptools.setup", fake_setup)
        runpy.run_path(str(REPO_ROOT / "setup.py"), run_name="__main__")

        extras = captured["extras_require"]
        assert "pythonnet>=3.0.5" in extras["mesh"]
        assert "pythonnet>=3.0.5" in extras["all"]


class TestClassificationTableNormalization:
    """Classification-table inputs should normalize to the v1 contract."""

    def test_normalize_dataframe(self):
        source = pd.DataFrame(
            {
                "source_value": [11, 21],
                "class_id": [1, 2],
                "class_name": ["Open Water", "Developed"],
                "mannings_n": [0.03, 0.12],
                "percent_impervious": [0.0, 85.0],
                "ignored_extra_column": ["x", "y"],
            }
        )

        normalized = _lch.normalize_classification_table(source)

        assert list(normalized.columns) == [
            "source_value",
            "class_id",
            "class_name",
            "mannings_n",
            "percent_impervious",
        ]
        assert normalized["class_id"].dtype.kind in {"i", "u"}
        assert normalized["mannings_n"].dtype.kind == "f"


class TestRealRasmapParsing:
    """Semantic land-layer classification should work on real example rasmaps."""

    def test_baldeagle_layers(self):
        project_path = REPO_ROOT / "example_projects" / "BaldEagleCrkMulti2D"
        rasmap_path = project_path / "BaldEagleDamBrk.rasmap"
        if not rasmap_path.exists():
            pytest.skip("BaldEagleCrkMulti2D example project is not available")

        layers = RasMap.list_land_classification_layers(project_path)
        assert not layers.empty

        expected = {
            "LandCover": "landcover",
            "Hydrologic Soil Groups": "soils",
            "Infiltration": "infiltration",
        }
        actual = dict(zip(layers["name"], layers["classification_kind"]))
        assert actual == expected

        parsed = RasMap.parse_rasmap(rasmap_path)
        assert parsed.at[0, "landcover_hdf_path"] == [
            str(project_path / "Land Classification" / "LandCover.hdf")
        ]
        assert parsed.at[0, "soil_layer_path"] == [
            str(project_path / "Soils Data" / "Hydrologic Soil Groups.hdf")
        ]
        assert parsed.at[0, "infiltration_hdf_path"] == [
            str(project_path / "Soils Data" / "Infiltration.hdf")
        ]

        terrain_layers = RasMap.list_terrain_layers(project_path)
        assert len(terrain_layers) == 1
        assert terrain_layers.iloc[0]["name"] == "Terrain50"
        assert terrain_layers.iloc[0]["filename"] == ".\\Terrain\\Terrain50.hdf"
        assert terrain_layers.iloc[0]["resolved_path"] == str(
            project_path / "Terrain" / "Terrain50.hdf"
        )
        assert terrain_layers.iloc[0]["resample_method"] == "near"
        assert bool(terrain_layers.iloc[0]["surface_on"]) is True
        assert parsed.at[0, "terrain_hdf_path"] == [
            terrain_layers.iloc[0]["resolved_path"]
        ]

        landcover_layers = RasMap.list_landcover_layers(project_path)
        soils_layers = RasMap.list_soils_layers(project_path)
        infiltration_layers = RasMap.list_infiltration_layers(project_path)
        assert list(landcover_layers["name"]) == ["LandCover"]
        assert list(soils_layers["name"]) == ["Hydrologic Soil Groups"]
        assert list(infiltration_layers["name"]) == ["Infiltration"]

    def test_muncie_nonstandard_names_still_classify_as_landcover(self):
        project_path = REPO_ROOT / "example_projects" / "Muncie_test_export"
        rasmap_path = project_path / "Muncie.rasmap"
        if not rasmap_path.exists():
            pytest.skip("Muncie_test_export example project is not available")

        layers = RasMap.list_land_classification_layers(project_path)
        assert not layers.empty
        assert set(layers["classification_kind"]) == {"landcover"}
        assert set(layers["name"]) == {
            "Land Cover",
            "LandCoverUSGSGrid",
            "LandCoverCombined",
        }

        parsed = RasMap.parse_rasmap(rasmap_path)
        assert len(parsed.at[0, "landcover_hdf_path"]) == 3
        assert parsed.at[0, "soil_layer_path"] == []
        assert parsed.at[0, "infiltration_hdf_path"] == []


class TestRasmapPathResolution:
    """Path normalization must preserve real .rasmap semantics."""

    def test_strips_only_exact_current_directory_prefixes(self, tmp_path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        dot_slash = _lch.resolve_rasmap_relative_path(project_dir, "./Terrain/Projection.prj")
        dot_backslash = _lch.resolve_rasmap_relative_path(project_dir, ".\\Terrain\\Projection.prj")

        assert dot_slash == project_dir / "Terrain" / "Projection.prj"
        assert dot_backslash == project_dir / "Terrain" / "Projection.prj"

    def test_preserves_parent_relative_paths(self, tmp_path):
        project_dir = tmp_path / "workspace" / "project"
        target_dir = tmp_path / "workspace" / "shared"
        project_dir.mkdir(parents=True)
        target_dir.mkdir(parents=True)
        target_path = target_dir / "Projection.prj"

        resolved = _lch.resolve_rasmap_relative_path(
            project_dir,
            "..\\shared\\Projection.prj",
        )

        assert resolved == target_path

    def test_expands_windows_style_environment_variable_paths(self, tmp_path, monkeypatch):
        local_app_data = tmp_path / "LocalAppData"
        monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

        resolved = _lch.resolve_rasmap_relative_path(
            tmp_path,
            r"%LOCALAPPDATA%\HEC\Mapping\mapper.cache",
        )

        assert resolved == local_app_data / "HEC" / "Mapping" / "mapper.cache"

    def test_absolute_paths_pass_through_unchanged(self, tmp_path):
        absolute_path = (tmp_path / "absolute" / "LandCover.hdf").resolve()
        absolute_path.parent.mkdir(parents=True)

        resolved = _lch.resolve_rasmap_relative_path(tmp_path, absolute_path)

        assert resolved == absolute_path


class TestLayerCreation:
    """Focused creation tests for the new land-classification workflow."""

    def test_add_landcover_layer_creates_outputs_and_registers_rasmap(self, tmp_path):
        rasterio = pytest.importorskip("rasterio")
        pytest.importorskip("pyproj")
        from rasterio.transform import from_origin

        project_dir = _make_temp_project(tmp_path, "LandcoverProject")
        source_raster = tmp_path / "landcover_source.tif"
        array = np.array(
            [
                [1, 1, 2, 2],
                [1, 1, 2, 2],
                [2, 2, 1, 1],
                [2, 2, 1, 1],
            ],
            dtype="int32",
        )
        with rasterio.open(
            source_raster,
            "w",
            driver="GTiff",
            height=array.shape[0],
            width=array.shape[1],
            count=1,
            dtype=array.dtype,
            crs=_read_projection_wkt(),
            transform=from_origin(0, 40, 10, 10),
            nodata=0,
        ) as dst:
            dst.write(array, 1)

        classification_table = pd.DataFrame(
            {
                "source_value": [1, 2],
                "class_id": [11, 21],
                "class_name": ["Open Water", "Developed"],
                "mannings_n": [0.03, 0.12],
                "percent_impervious": [0.0, 85.0],
            }
        )

        output_hdf = RasMap.add_landcover_layer(
            project_dir,
            source_raster,
            classification_table,
            cell_size=10.0,
        )

        assert output_hdf.exists()
        assert output_hdf.with_suffix(".tif").exists()

        with h5py.File(output_hdf, "r") as hdf_file:
            raster_map = hdf_file["Raster Map"][()]
            variables = hdf_file["Variables"][()]
            assert {int(row["ID"]) for row in raster_map} == {0, 11, 21}
            assert {
                row["Name"].decode("utf-8").strip()
                for row in variables
            } == {"NoData", "Open Water", "Developed"}

        layers = RasMap.list_land_classification_layers(project_dir)
        assert set(layers["classification_kind"]) == {"landcover"}
        assert layers.iloc[0]["resolved_path"] == str(output_hdf)

        parsed = RasMap.parse_rasmap(project_dir / "LandcoverProject.rasmap")
        assert parsed.at[0, "landcover_hdf_path"] == [str(output_hdf)]

    def test_add_soils_layer_creates_outputs_and_registers_rasmap(self, tmp_path):
        pytest.importorskip("geopandas")
        pytest.importorskip("pyproj")
        from shapely.geometry import box
        import geopandas as gpd

        project_dir = _make_temp_project(tmp_path, "SoilsProject")
        gssurgo_dir = tmp_path / "fake_gssurgo"
        spatial_dir = gssurgo_dir / "spatial"
        tabular_dir = gssurgo_dir / "tabular"
        spatial_dir.mkdir(parents=True)
        tabular_dir.mkdir(parents=True)

        soils_gdf = gpd.GeoDataFrame(
            {
                "mukey": ["100", "200"],
                "geometry": [
                    box(0, 0, 20, 20),
                    box(20, 0, 40, 20),
                ],
            },
            crs=_read_projection_wkt(),
        )
        soils_gdf.to_file(spatial_dir / "soilmu_a_test.shp")
        (tabular_dir / "muaggatt.txt").write_text(
            "mukey|hydgrpdcd\n100|A\n200|B\n",
            encoding="utf-8",
        )

        output_hdf = RasMap.add_soils_layer(
            project_dir,
            gssurgo_dir,
            cell_size=10.0,
        )

        assert output_hdf.exists()
        assert output_hdf.with_suffix(".tif").exists()

        with h5py.File(output_hdf, "r") as hdf_file:
            raster_map = hdf_file["Raster Map"][()]
            assert {
                row["Name"].decode("utf-8").strip()
                for row in raster_map
            } == {"NoData", "A", "B"}

        layers = RasMap.list_land_classification_layers(project_dir)
        assert set(layers["classification_kind"]) == {"soils"}
        parsed = RasMap.parse_rasmap(project_dir / "SoilsProject.rasmap")
        assert parsed.at[0, "soil_layer_path"] == [str(output_hdf)]

    @pytest.mark.parametrize(
        ("infiltration_method", "expected_fields"),
        [
            (
                "scs_curve_number",
                [
                    "Curve Number",
                    "Abstraction Ratio",
                    "Minimum Infiltration Rate",
                ],
            ),
            (
                "deficit_constant",
                [
                    "Maximum Deficit",
                    "Initial Deficit",
                    "Potential Percolation Rate",
                ],
            ),
            (
                "green_ampt",
                [
                    "Wetting Front Suction",
                    "Saturated Hydraulic Conductivity",
                    "Initial Soil Water Content",
                    "Saturated Soil Water Content",
                ],
            ),
        ],
    )
    def test_add_infiltration_layer_populates_variables(
        self,
        tmp_path,
        infiltration_method,
        expected_fields,
    ):
        project_dir = _make_temp_project(tmp_path, "InfiltrationProject")
        landcover_hdf_path = (
            REPO_ROOT
            / "example_projects"
            / "BaldEagleCrkMulti2D"
            / "Land Classification"
            / "LandCover.hdf"
        )
        soil_layer_path = (
            REPO_ROOT
            / "example_projects"
            / "BaldEagleCrkMulti2D"
            / "Soils Data"
            / "Hydrologic Soil Groups.hdf"
        )
        if not landcover_hdf_path.exists() or not soil_layer_path.exists():
            pytest.skip("BaldEagleCrkMulti2D land-classification sidecars are not available")

        output_hdf = RasMap.add_infiltration_layer(
            project_dir,
            infiltration_method=infiltration_method,
            landcover_hdf_path=landcover_hdf_path,
            soil_layer_path=soil_layer_path,
            scs_reset_time_hours=24.0,
        )

        assert output_hdf.exists()
        with h5py.File(output_hdf, "r") as hdf_file:
            variables = hdf_file["Variables"][()]
            dtype_names = set(variables.dtype.names)
            for field_name in expected_fields:
                assert field_name in dtype_names
                assert np.all(variables[field_name] != -9999.0)

        layers = RasMap.list_land_classification_layers(project_dir)
        assert set(layers["classification_kind"]) == {"infiltration"}


class TestClassificationPolygonAuthoring:
    """Classification polygon edits should update sidecar HDF structures."""

    def test_add_polygon_to_copied_landcover_sidecar_updates_hdf_readers(self, tmp_path):
        rasterio = pytest.importorskip("rasterio")
        pytest.importorskip("pyproj")
        shapely_box = pytest.importorskip("shapely.geometry").box
        from rasterio.transform import from_origin

        project_dir = _make_temp_project(tmp_path, "LandcoverPolygonProject")
        source_raster = tmp_path / "landcover_source.tif"
        array = np.array([[1, 2], [2, 1]], dtype="int32")
        with rasterio.open(
            source_raster,
            "w",
            driver="GTiff",
            height=array.shape[0],
            width=array.shape[1],
            count=1,
            dtype=array.dtype,
            crs=_read_projection_wkt(),
            transform=from_origin(0, 20, 10, 10),
            nodata=0,
        ) as dst:
            dst.write(array, 1)

        output_hdf = RasMap.add_landcover_layer(
            project_dir,
            source_raster,
            pd.DataFrame(
                {
                    "source_value": [1, 2],
                    "class_id": [11, 21],
                    "class_name": ["Open Water", "Developed"],
                    "mannings_n": [0.03, 0.12],
                    "percent_impervious": [0.0, 85.0],
                }
            ),
            cell_size=10.0,
        )
        copied_hdf = tmp_path / "CopiedLandCover.hdf"
        shutil.copy2(output_hdf, copied_hdf)

        polygons = RasMap.add_land_classification_polygon(
            copied_hdf,
            shapely_box(0, 0, 10, 10),
            class_name="Parking Lot",
            class_id=99,
            variable_values={
                "mannings_n": 0.105,
                "percent_impervious": 95.0,
            },
        )

        assert list(polygons["class_name"]) == ["Parking Lot"]
        assert polygons.attrs["recompute_required"] is True
        assert Path(polygons.attrs["backup_path"]).exists()

        with h5py.File(copied_hdf, "r") as hdf_file:
            attrs = hdf_file["Classification Polygons/Attributes"][()]
            assert attrs["Classification"][0].decode("utf-8") == "Parking Lot"
            raster_map = hdf_file["Raster Map"][()]
            variables = hdf_file["Variables"][()]

        assert {
            (int(row["ID"]), row["Name"].decode("utf-8").strip())
            for row in raster_map
        } >= {(99, "Parking Lot")}

        variable_lookup = {
            row["Name"].decode("utf-8").strip(): row
            for row in variables
        }
        assert np.isclose(variable_lookup["Parking Lot"]["ManningsN"], 0.105)
        assert np.isclose(
            variable_lookup["Parking Lot"]["Percent Impervious"],
            95.0,
        )

        extracted = HdfLandCover.get_classification_polygons(copied_hdf)
        assert list(extracted["class_name"]) == ["Parking Lot"]

        raster_map_df = HdfLandCover.get_landcover_raster_map(copied_hdf)
        parking_row = raster_map_df.loc[
            raster_map_df["class_name"] == "Parking Lot"
        ].iloc[0]
        assert parking_row["pixel_value"] == 99
        assert np.isclose(parking_row["mannings_n"], 0.105)

    def test_update_and_delete_landcover_classification_polygon(self, tmp_path):
        shapely_box = pytest.importorskip("shapely.geometry").box
        sidecar = tmp_path / "LandCover.hdf"
        _lch._rewrite_landcover_sidecar(
            sidecar,
            [(0, "NoData"), (11, "Open Water")],
            [("NoData", 0.035, 0.0), ("Open Water", 0.03, 0.0)],
            _read_projection_wkt(),
        )

        RasMap.add_land_classification_polygon(
            sidecar,
            shapely_box(0, 0, 10, 10),
            class_name="Temporary Class",
            class_id=42,
            variable_values={"mannings_n": 0.08},
        )

        updated = RasMap.update_land_classification_polygon(
            sidecar,
            polygon_index=0,
            polygon=shapely_box(10, 10, 20, 20),
            class_name="Updated Class",
            class_id=43,
            variable_values={"mannings_n": 0.09},
        )

        assert list(updated["class_name"]) == ["Updated Class"]
        raster_map_df = HdfLandCover.get_landcover_raster_map(sidecar)
        assert "Updated Class" in set(raster_map_df["class_name"])

        deleted = RasMap.delete_land_classification_polygon(
            sidecar,
            polygon_index=0,
            remove_unused_class=True,
        )

        assert deleted.empty
        with h5py.File(sidecar, "r") as hdf_file:
            assert "Classification Polygons" not in hdf_file
            names = {
                row["Name"].decode("utf-8").strip()
                for row in hdf_file["Variables"][()]
            }
        assert "Updated Class" not in names

    def test_add_polygon_to_infiltration_sidecar_updates_variables(self, tmp_path):
        shapely_box = pytest.importorskip("shapely.geometry").box
        sidecar = tmp_path / "Infiltration.hdf"
        dtype = np.dtype(
            [
                ("Name", "S16"),
                ("Curve Number", "<f4"),
                ("Abstraction Ratio", "<f4"),
                ("Minimum Infiltration Rate", "<f4"),
            ]
        )
        data = np.zeros(1, dtype=dtype)
        data[0]["Name"] = b"NoData"
        data[0]["Curve Number"] = 75.0
        data[0]["Abstraction Ratio"] = 0.1
        data[0]["Minimum Infiltration Rate"] = 0.12
        with h5py.File(sidecar, "w") as hdf_file:
            hdf_file.attrs["LC Type"] = np.bytes_("InfiltrationSCSCurveNumber")
            hdf_file.attrs["Projection"] = np.bytes_(_read_projection_wkt())
            hdf_file.create_dataset("Variables", data=data)

        RasMap.add_land_classification_polygon(
            sidecar,
            shapely_box(0, 0, 10, 10),
            class_name="Paved Override",
            variable_values={
                "curve_number": 98.0,
                "abstraction_ratio": 0.05,
                "minimum_infiltration_rate": 0.01,
            },
        )

        layer_data = HdfInfiltration.get_infiltration_layer_data(sidecar)
        row = layer_data.loc[layer_data["Name"] == "Paved Override"].iloc[0]
        assert np.isclose(row["Curve Number"], 98.0)
        assert np.isclose(row["Abstraction Ratio"], 0.05)
        assert np.isclose(row["Minimum Infiltration Rate"], 0.01)
        extracted = HdfInfiltration.get_classification_polygons(sidecar)
        assert list(extracted["class_name"]) == ["Paved Override"]

    def test_add_polygon_to_soils_sidecar_updates_raster_map(self, tmp_path):
        shapely_box = pytest.importorskip("shapely.geometry").box
        sidecar = tmp_path / "Hydrologic Soil Groups.hdf"
        dtype = np.dtype([("ID", "<i4"), ("Name", "S6")])
        data = np.zeros(2, dtype=dtype)
        data[0]["ID"] = 0
        data[0]["Name"] = b"NoData"
        data[1]["ID"] = 1
        data[1]["Name"] = b"A"
        with h5py.File(sidecar, "w") as hdf_file:
            hdf_file.attrs["LC Type"] = np.bytes_("Soils")
            hdf_file.attrs["Projection"] = np.bytes_(_read_projection_wkt())
            hdf_file.create_dataset("Raster Map", data=data)

        RasMap.add_land_classification_polygon(
            sidecar,
            shapely_box(0, 0, 10, 10),
            class_name="D",
            class_id=4,
        )

        with h5py.File(sidecar, "r") as hdf_file:
            raster_map = hdf_file["Raster Map"][()]
        assert {
            (int(row["ID"]), row["Name"].decode("utf-8").strip())
            for row in raster_map
        } >= {(4, "D")}
        polygons = RasMap.list_land_classification_polygons(sidecar)
        assert list(polygons["class_name"]) == ["D"]
