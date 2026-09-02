from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander.RasPlan import RasPlan
from ras_commander.RasPrj import RasPrj
from ras_commander.geom.GeomPreprocessor import GeomPreprocessor
from ras_commander.schemas import DATAFRAME_SCHEMAS, SCHEMA_VERSION


def _geometry_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "geom_number": ["01", "02", "03", "04", "05"],
            "has_1d_xs": [True, False, True, None, False],
            "has_2d_mesh": [False, True, True, None, False],
            "num_cross_sections": [12, 0, 7, None, 0],
            "mesh_cell_count": [0, 500, 250, None, 0],
            "mesh_area_names": [[], ["Mesh 2D"], ["Mixed Mesh"], None, []],
            "geometry_metadata_source": [
                "hdf", "hdf", "text", "unavailable", "hdf"
            ],
            "geometry_metadata_valid": [True, True, True, False, True],
            "geometry_metadata_error": [None, None, None, "unreadable", None],
        }
    )


def test_plan_df_uses_only_supported_compute_taxonomy():
    project = RasPrj()
    project.geom_df = _geometry_rows()
    plans = pd.DataFrame(
        {
            "plan_number": [f"{number:02d}" for number in range(1, 11)],
            "flow_file_prefix": ["f", "u", "u", "u", None, "u", "q", "f", "q", "u"],
            "unsteady_number": [None, "02", "03", "04", None, "06", None, None, None, "10"],
            "quasi_unsteady_number": [None, None, None, None, None, None, "01", None, "02", None],
            "Flow File": ["01", "02", "03", "04", None, "06", "01", "02", "02", "10"],
            "geometry_number": ["01", "02", "03", "04", "01", "99", "01", "02", "03", "05"],
        }
    )

    classified = project._enrich_plan_classification(plans)

    assert classified["flow_type"].tolist() == [
        "Steady",
        "Unsteady",
        "Unsteady",
        "Unsteady",
        "Unknown",
        "Unsteady",
        "Quasi-Unsteady",
        "Steady",
        "Quasi-Unsteady",
        "Unsteady",
    ]
    assert classified["geometry_type"].tolist() == [
        "1D", "2D", "1D/2D", "Unknown", "1D",
        "Unknown", "1D", "2D", "1D/2D", "Unknown",
    ]
    assert classified["plan_type"].tolist() == [
        "steady_1d",
        "unsteady_2d",
        "unsteady_1d_2d",
        "unknown",
        "unknown",
        "unknown",
        "quasi_unsteady_1d",
        "unknown",
        "unknown",
        "unknown",
    ]
    assert "steady_2d" not in set(classified["plan_type"])
    assert "steady_1d_2d" not in set(classified["plan_type"])
    assert bool(classified.loc[0, "plan_classification_valid"])
    assert not bool(classified.loc[7, "plan_classification_valid"])
    assert "steady solver" in classified.loc[7, "plan_classification_reason"]
    assert "Quasi-unsteady" in classified.loc[8, "plan_classification_reason"]
    assert "no supported" in classified.loc[9, "plan_classification_reason"]
    assert str(classified["has_1d_xs"].dtype) == "boolean"
    assert str(classified["mesh_cell_count"].dtype) == "Int64"


def test_classification_and_provenance_columns_are_canonical_schema() -> None:
    expected_plan_columns = {
        "geometry_type": "str",
        "has_1d_xs": "boolean",
        "has_2d_mesh": "boolean",
        "num_cross_sections": "Int64",
        "mesh_cell_count": "Int64",
        "mesh_area_names": "list[str] | None",
        "geometry_metadata_source": "str",
        "geometry_metadata_valid": "boolean",
        "geometry_metadata_error": "str | None",
        "plan_type": "str",
        "plan_classification_valid": "boolean",
        "plan_classification_reason": "str | None",
    }
    expected_geom_columns = {
        "geometry_type": "str",
        "has_1d_xs": "boolean",
        "has_2d_mesh": "boolean",
        "num_cross_sections": "Int64",
        "mesh_cell_count": "Int64",
        "geometry_metadata_source": "str",
        "geometry_metadata_valid": "boolean",
        "geometry_metadata_error": "str | None",
    }

    assert SCHEMA_VERSION == "1.9"
    for dataframe, expected in (
        ("plan_df", expected_plan_columns),
        ("geom_df", expected_geom_columns),
    ):
        schema_columns = DATAFRAME_SCHEMAS[dataframe]["columns"]
        names = [column["name"] for column in schema_columns]
        dtypes = {column["name"]: column["dtype"] for column in schema_columns}
        for name, dtype in expected.items():
            assert names.count(name) == 1
            assert dtypes[name] == dtype


def test_plan_parser_ignores_reference_like_text_in_description(tmp_path):
    plan_path = tmp_path / "Model.p01"
    plan_path.write_text(
        "Plan Title=Real Plan\n"
        "Geom File=g01\n"
        "Flow File=u01\n"
        "BEGIN DESCRIPTION:\n"
        "Flow File=q99\n"
        "Geom File=g99\n"
        "END DESCRIPTION\n",
        encoding="utf-8",
    )

    project = RasPrj()
    parsed = project._parse_plan_file(plan_path)

    assert parsed["Flow File"] == "u01"
    assert parsed["Geom File"] == "g01"


def test_rasplan_flow_type_fallback_includes_quasi_unsteady():
    project = SimpleNamespace(
        plan_df=pd.DataFrame(
            {
                "plan_number": ["01", "02", "03", "04"],
                "flow_file_prefix": ["u", "f", "q", None],
                "unsteady_number": ["01", None, None, None],
                "quasi_unsteady_number": [None, None, "01", None],
                "Flow File": ["01", "02", "01", None],
            }
        ),
        check_initialized=lambda: None,
    )

    assert RasPlan.get_plan_flow_type("01", project) == "Unsteady"
    assert RasPlan.get_plan_flow_type("02", project) == "Steady"
    assert RasPlan.get_plan_flow_type("03", project) == "Quasi-Unsteady"
    assert RasPlan.get_plan_flow_type("04", project) == "Unknown"
    assert RasPlan.is_plan_steady_state("03", project) is False
    assert GeomPreprocessor._resolve_flow_type("03", project) == "Quasi-Unsteady"


def _write_geometry_hdf(path: Path, *, one_d: bool, two_d: bool) -> None:
    with h5py.File(path, "w") as hdf:
        if one_d:
            hdf.create_dataset(
                "Geometry/Cross Sections/Attributes",
                data=np.array([(b"River",)], dtype=np.dtype([("River", "S32")])),
            )
        if two_d:
            hdf.create_dataset(
                "Geometry/2D Flow Areas/Attributes",
                data=np.array([(b"Mesh",)], dtype=np.dtype([("Name", "S32")])),
            )
            hdf.create_dataset(
                "Geometry/2D Flow Areas/Cell Info",
                data=np.array([[0, 4]], dtype=np.int64),
            )


def _mutable_project(tmp_path: Path) -> RasPrj:
    (tmp_path / "Model.prj").write_text(
        "Proj Title=Model\n"
        "Current Plan=p01\n"
        "Plan File=p01\n"
        "Geom File=g01\n"
        "Geom File=g02\n"
        "Flow File=f01\n"
        "Unsteady File=u01\n",
        encoding="utf-8",
    )
    (tmp_path / "Model.p01").write_text(
        "Plan Title=Mutation Test\n"
        "Geom File=g01\n"
        "Flow File=u01\n"
        "BEGIN DESCRIPTION:\n"
        "Flow File=q99\n"
        "END DESCRIPTION\n",
        encoding="utf-8",
    )
    (tmp_path / "Model.g01").write_text("Geom Title=One D\n", encoding="utf-8")
    (tmp_path / "Model.g02").write_text("Geom Title=Two D\n", encoding="utf-8")
    _write_geometry_hdf(tmp_path / "Model.g01.hdf", one_d=True, two_d=False)
    _write_geometry_hdf(tmp_path / "Model.g02.hdf", one_d=False, two_d=True)
    (tmp_path / "Model.f01").write_text("Flow Title=Steady\n", encoding="utf-8")
    (tmp_path / "Model.u01").write_text("Flow Title=Unsteady\n", encoding="utf-8")

    project = RasPrj()
    project.initialized = True
    project.prj_file = tmp_path / "Model.prj"
    project.project_folder = tmp_path
    project.project_name = "Model"
    project.suppress_logging = True
    project._load_project_data()
    return project


def test_plan_mutations_rederive_classification_and_preserve_schema(tmp_path):
    project = _mutable_project(tmp_path)
    assert project.plan_df.loc[0, "plan_type"] == "unsteady_1d"

    RasPlan.set_geom("01", "02", project)
    row = project.plan_df.loc[0]
    assert row["geometry_number"] == "02"
    assert row["Geom File"] == "02"
    assert row["geometry_type"] == "2D"
    assert row["plan_type"] == "unsteady_2d"

    RasPlan.set_steady("01", "01", project)
    row = project.plan_df.loc[0]
    assert row["Flow File"] == "01"
    assert row["flow_file_prefix"] == "f"
    assert row["flow_type"] == "Steady"
    assert row["plan_type"] == "unknown"
    assert "steady solver" in row["plan_classification_reason"]

    RasPlan.set_geom("01", "01", project)
    assert project.plan_df.loc[0, "plan_type"] == "steady_1d"

    RasPlan.set_unsteady("01", "01", project)
    row = project.plan_df.loc[0]
    assert row["Flow File"] == "01"
    assert row["flow_file_prefix"] == "u"
    assert row["unsteady_number"] == "01"
    assert row["plan_type"] == "unsteady_1d"

    plan_text = (tmp_path / "Model.p01").read_text(encoding="utf-8")
    assert plan_text.count("Flow File=u01") == 1
    assert "Flow File=q99" in plan_text


def test_plan_reference_mutation_refuses_missing_top_level_key():
    with pytest.raises(ValueError, match="exactly one top-level Flow File"):
        RasPlan._update_steady_in_file(
            ["BEGIN DESCRIPTION:\n", "Flow File=u01\n", "END DESCRIPTION\n"],
            "02",
        )


def test_plan_reference_mutation_preserves_crlf_and_rejects_duplicates():
    updated = RasPlan._update_unsteady_in_file(
        [
            "Flow File=f01\r\n",
            "BEGIN DESCRIPTION:\r\n",
            "Flow File=q99\r\n",
            "END DESCRIPTION\r\n",
        ],
        "02",
    )
    assert updated[0] == "Flow File=u02\r\n"
    assert updated[2] == "Flow File=q99\r\n"

    with pytest.raises(ValueError, match="found 2"):
        RasPlan._update_unsteady_in_file(
            ["Flow File=f01\n", "Flow File=u02\n"],
            "03",
        )
