"""
Tests for RasMap land-classification parsing and API scaffolding.
"""

import inspect
import os
import runpy
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
import ras_commander._land_classification_helper as _lch


def _read_projection_wkt() -> str:
    return (
        REPO_ROOT
        / "example_projects"
        / "BaldEagleCrkMulti2D"
        / "Terrain"
        / "Projection.prj"
    ).read_text(encoding="utf-8")


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

    def test_muncie_nonstandard_names_still_classify_as_landcover(self):
        project_path = REPO_ROOT / "example_projects" / "Muncie_test_export"
        rasmap_path = project_path / "Muncie.rasmap"

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
