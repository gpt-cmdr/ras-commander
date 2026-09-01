import json
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest

import ras_commander
from ras_commander import RasCrossSections, RasPrj, VerticalTransform
from ras_commander.geom.GeomCrossSection import (
    CrossSectionBankStations,
    CrossSectionManningsN,
    CrossSectionReachLengths,
    GeomCrossSection,
)
from ras_commander.hdf import HdfXsec
from ras_commander.schemas import DATAFRAME_SCHEMAS


def _write_project(
    tmp_path: Path,
    *,
    si_units: int = 0,
    unit_marker: str | None = None,
) -> Path:
    project = tmp_path / "Model.prj"
    units_line = unit_marker if unit_marker is not None else f"SI Units={si_units}"
    project.write_text(
        "Proj Title=Cross Section Point Test\n"
        f"{units_line}\n"
        "Geom File=g01\n",
        encoding="utf-8",
    )
    return project


def _write_geometry_hdf(tmp_path: Path) -> Path:
    pyproj = pytest.importorskip("pyproj")
    path = tmp_path / "Model.g01.hdf"
    attributes_dtype = np.dtype(
        [
            ("River", "S16"),
            ("Reach", "S16"),
            ("RS", "S8"),
            ("Left Bank", "<f4"),
            ("Right Bank", "<f4"),
        ]
    )
    attributes = np.array(
        [(b"Test River", b"Test Reach", b"1000", 130.0, 180.0)],
        dtype=attributes_dtype,
    )

    with h5py.File(path, "w") as hdf:
        hdf.attrs["File Type"] = np.bytes_("HEC-RAS Geometry")
        hdf.attrs["Units System"] = np.bytes_("US Customary")
        hdf.attrs["Projection"] = np.bytes_(pyproj.CRS.from_epsg(2278).to_wkt())
        hdf.attrs["Vertical Units"] = np.bytes_("ft")
        hdf.attrs["Vertical Datum"] = np.bytes_("NAVD88")
        cross_sections = hdf.require_group("Geometry/Cross Sections")
        cross_sections.create_dataset("Attributes", data=attributes)
        cross_sections.create_dataset(
            "Polyline Info", data=np.array([[0, 3, 0, 1]], dtype=np.int32)
        )
        cross_sections.create_dataset(
            "Polyline Parts", data=np.array([[0, 3]], dtype=np.int32)
        )
        cross_sections.create_dataset(
            "Polyline Points",
            data=np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]], dtype=float),
        )
        cross_sections.create_dataset(
            "Station Elevation Info", data=np.array([[0, 5]], dtype=np.int32)
        )
        cross_sections.create_dataset(
            "Station Elevation Values",
            data=np.array(
                [
                    [100.0, 10.0],
                    [130.0, 9.0],
                    [150.0, 8.0],
                    [180.0, 9.5],
                    [200.0, 11.0],
                ],
                dtype=np.float32,
            ),
        )
        cross_sections.create_dataset(
            "Manning's n Info", data=np.array([[0, 3]], dtype=np.int32)
        )
        cross_sections.create_dataset(
            "Manning's n Values",
            data=np.array(
                [[100.0, 0.08], [130.0, 0.04], [180.0, 0.09]],
                dtype=np.float32,
            ),
        )
    return path


def _write_text_geometry(tmp_path: Path) -> Path:
    shapely = pytest.importorskip("shapely.geometry")
    profile = pd.DataFrame(
        {
            "Station": [100.0, 130.0, 150.0, 180.0, 200.0],
            "Elevation": [10.0, 9.0, 8.0, 9.5, 11.0],
        }
    )
    result = GeomCrossSection.build_cross_section(
        river="Test River",
        reach="Test Reach",
        rs="1000",
        station_elevation=profile,
        cut_line=shapely.LineString([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]),
        bank_stations=CrossSectionBankStations(130.0, 180.0, 9.0, 9.5),
        mannings_n=CrossSectionManningsN(0.08, 0.04, 0.09),
        reach_lengths=CrossSectionReachLengths(100.0, 100.0, 100.0),
    )
    path = tmp_path / "Model.g01"
    path.write_text(
        "Geom Title=Unified Point Test\n"
        "Program Version=6.50\n"
        "River Reach=Test River      ,Test Reach\n"
        "Reach XY= 2\n"
        "            0.00            0.00\n"
        "           10.00           10.00\n"
        + result.text,
        encoding="utf-8",
    )
    return path


def test_hdf_get_xs_coords_extracts_native_points_and_attributes(tmp_path):
    hdf_path = _write_geometry_hdf(tmp_path)

    points = HdfXsec.get_xs_coords(hdf_path)

    assert points["river"].unique().tolist() == ["Test River"]
    assert points["reach"].unique().tolist() == ["Test Reach"]
    assert points["river_station"].unique().tolist() == ["1000"]
    assert points["point_order"].tolist() == [0, 1, 2, 3, 4]
    assert points["station_order"].tolist() == [0, 1, 2, 3, 4]
    assert points["relative_distance"].to_numpy() == pytest.approx([0.0, 6.0, 10.0, 16.0, 20.0])
    np.testing.assert_allclose(
        points[["x", "y"]].to_numpy(),
        [[0.0, 0.0], [6.0, 0.0], [10.0, 0.0], [10.0, 6.0], [10.0, 10.0]],
    )
    assert points["z"].tolist() == [10.0, 9.0, 8.0, 9.5, 11.0]
    assert points["mannings_n"].to_numpy() == pytest.approx([0.08, 0.04, 0.04, 0.09, 0.09])
    assert points["bank_region"].tolist() == [
        "left_overbank", "channel", "channel", "channel", "right_overbank"
    ]
    assert points["is_bank_station"].tolist() == [False, True, False, True, False]
    assert points.loc[1, "bank_side"] == "left"
    assert points.loc[3, "bank_side"] == "right"
    assert points.loc[[0, 2, 4], "bank_side"].isna().all()
    assert points["vertical_units"].unique().tolist() == ["ft"]
    assert points["vertical_datum"].unique().tolist() == ["NAVD88"]
    assert points["extraction_method"].unique().tolist() == ["geometry_hdf"]
    assert points.attrs["native_elevations"] is True


def test_common_api_has_identical_schema_for_hdf_and_text(tmp_path):
    project = _write_project(tmp_path)
    hdf_path = _write_geometry_hdf(tmp_path)

    hdf_points = RasCrossSections.get_points(project, "01")
    hdf_native_z = HdfXsec.get_xs_coords(hdf_path)["z"].to_numpy()
    schema_columns = [
        column["name"] for column in DATAFRAME_SCHEMAS["cross_section_points"]["columns"]
    ]
    assert tuple(hdf_points.columns) == RasCrossSections.POINT_COLUMNS
    assert schema_columns == list(RasCrossSections.POINT_COLUMNS)
    assert {"RasCrossSections", "VerticalTransform"}.issubset(ras_commander.__all__)
    assert hdf_points["z"].to_numpy() == pytest.approx(hdf_native_z)
    assert hdf_points["model_id"].unique().tolist() == ["Model"]
    assert hdf_points["geometry_id"].unique().tolist() == ["01"]
    assert hdf_points["reach_id"].unique().tolist() == ["Test River|Test Reach"]
    assert hdf_points["xs_id"].unique().tolist() == ["Test River|Test Reach|1000"]
    assert hdf_points["vertical_transform_applied"].eq(False).all()
    native_provenance = json.loads(hdf_points["vertical_transform_provenance"].iloc[0])
    assert native_provenance["coordinate_strategy"] == "native_z_preserved"
    assert hdf_points.attrs["provenance"]["native_elevations"] is True

    hdf_path.unlink()
    _write_text_geometry(tmp_path)
    text_points = RasCrossSections.get_points(
        project,
        "01",
        horizontal_crs="EPSG:2278",
        vertical_datum="NAVD88",
    )
    assert tuple(text_points.columns) == RasCrossSections.POINT_COLUMNS
    assert text_points["extraction_method"].unique().tolist() == ["text_geometry"]
    assert text_points["geometry_title"].unique().tolist() == ["Unified Point Test"]
    assert text_points["z"].tolist() == [10.0, 9.0, 8.0, 9.5, 11.0]
    assert text_points["mannings_n"].to_numpy() == pytest.approx([0.08, 0.04, 0.04, 0.09, 0.09])


def test_project_units_override_embedded_hdf_units(tmp_path):
    project = _write_project(tmp_path, unit_marker="SI Units")
    _write_geometry_hdf(tmp_path)

    points = RasCrossSections.get_points(project, "01")

    assert points["vertical_units"].unique().tolist() == ["m"]


@pytest.mark.parametrize(
    ("template_version", "expected_units"),
    [("RAS_7.0", "ft"), ("RAS_6.6", "m")],
)
def test_project_units_parse_real_hec_ras_template_markers(
    template_version,
    expected_units,
):
    template = (
        Path(ras_commander.__file__).parent
        / "resources"
        / "templates"
        / template_version
        / "TEMPLATE.prj"
    )

    assert RasPrj.get_project_units(template) == expected_units


@pytest.mark.parametrize(
    ("si_units", "expected_units"),
    [(0, "ft"), (1, "m")],
)
def test_project_units_preserve_boolean_form(tmp_path, si_units, expected_units):
    project = _write_project(tmp_path, si_units=si_units)

    assert RasPrj.get_project_units(project) == expected_units


@pytest.mark.parametrize(
    ("unit_marker", "expected_units"),
    [("English Units", "ft"), ("SI Units", "m")],
)
def test_text_source_uses_canonical_project_unit_markers(
    tmp_path,
    unit_marker,
    expected_units,
):
    project = _write_project(tmp_path, unit_marker=unit_marker)
    _write_text_geometry(tmp_path)

    points = RasCrossSections.get_points(project, "01", source="text")

    assert points["horizontal_units"].unique().tolist() == [expected_units]
    assert points["vertical_units"].unique().tolist() == [expected_units]


def test_explicit_vertical_transform_is_per_point_and_audited(tmp_path):
    project = _write_project(tmp_path)
    _write_geometry_hdf(tmp_path)
    native = RasCrossSections.get_points(project, "01")
    transform = VerticalTransform(
        source_vertical_datum="NAVD88",
        target_vertical_datum="Local project datum",
        source_vertical_units="ft",
        target_vertical_units="ft",
        pipeline="+proj=pipeline +step +proj=affine +zoff=10",
    )

    adjusted = RasCrossSections.get_points(
        project,
        "01",
        vertical_transform=transform,
    )

    assert adjusted["x"].to_numpy() == pytest.approx(native["x"].to_numpy())
    assert adjusted["y"].to_numpy() == pytest.approx(native["y"].to_numpy())
    assert adjusted["z"].to_numpy() == pytest.approx(native["z"].to_numpy() + 10.0)
    assert adjusted["vertical_datum"].unique().tolist() == ["Local project datum"]
    assert adjusted["vertical_transform_applied"].eq(True).all()
    provenance = json.loads(adjusted["vertical_transform_provenance"].iloc[0])
    assert provenance["coordinate_strategy"] == "per_point_xyz"
    assert provenance["requested_pipeline"].endswith("+zoff=10")
    assert provenance["operation_definition"]
    assert provenance["pyproj_version"]
    assert provenance["proj_version"]
    assert adjusted.attrs["provenance"]["native_elevations"] is False


def test_common_api_resolves_geometry_from_rasprj_dataframe(tmp_path):
    project_file = _write_project(tmp_path)
    hdf_path = _write_geometry_hdf(tmp_path)
    ras_object = SimpleNamespace(
        project_folder=tmp_path,
        project_name="Model",
        prj_file=project_file,
        project_crs="EPSG:2278",
        geom_df=pd.DataFrame(
            [
                {
                    "geom_number": "01",
                    "geom_file": "g01",
                    "geom_title": "DataFrame Geometry",
                    "full_path": str(tmp_path / "Model.g01"),
                    "hdf_path": str(hdf_path),
                }
            ]
        ),
    )

    points = RasCrossSections.get_points(ras_object, "01")

    assert points["geometry_title"].unique().tolist() == ["DataFrame Geometry"]
    assert points["horizontal_crs"].unique().tolist() == ["EPSG:2278"]
    assert points["extraction_method"].unique().tolist() == ["geometry_hdf"]


def test_vertical_transform_rejects_source_unit_mismatch(tmp_path):
    project = _write_project(tmp_path)
    _write_geometry_hdf(tmp_path)
    transform = VerticalTransform(
        source_vertical_datum="NAVD88",
        target_vertical_datum="NAVD88",
        source_vertical_units="m",
        target_vertical_units="m",
        pipeline="+proj=noop",
    )

    with pytest.raises(ValueError, match="source units"):
        RasCrossSections.get_points(project, "01", vertical_transform=transform)
