from pathlib import Path
from types import SimpleNamespace

import h5py
import pandas as pd
import pytest

from ras_commander import RasMap
from ras_commander._geometry_association import landcover_association_diagnostic
from ras_commander.schemas import DATAFRAME_SCHEMAS


class _Project(SimpleNamespace):
    def check_initialized(self):
        return None


def _artifact(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("artifact", encoding="utf-8")
    return path


def _geometry_hdf(
    path: Path,
    *,
    terrain: str | None = None,
    landcover: str | None = None,
) -> Path:
    with h5py.File(path, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        if terrain is not None:
            geometry.attrs["Terrain Filename"] = terrain
            geometry.attrs["Terrain Layername"] = "Terrain"
        if landcover is not None:
            geometry.attrs["Land Cover Filename"] = landcover
            geometry.attrs["Land Cover Layername"] = "LandCover"
    return path


def _project(tmp_path: Path) -> _Project:
    terrain = _artifact(tmp_path / "Terrain" / "Terrain.hdf")
    landcover = _artifact(tmp_path / "LandCover" / "LandCover.hdf")
    g01 = tmp_path / "Project.g01"
    g01.write_text(
        "Geom Title=Spatial\nLCMann Table=1\nOpen Water,0.04\n",
        encoding="utf-8",
    )
    _geometry_hdf(
        Path(str(g01) + ".hdf"),
        terrain=r".\Terrain\Terrain.hdf",
        landcover=r".\LandCover\LandCover.hdf",
    )

    g02 = tmp_path / "Project.g02"
    g02.write_text("Geom Title=Default\n", encoding="utf-8")
    _geometry_hdf(
        Path(str(g02) + ".hdf"),
        terrain=r".\Terrain\Terrain.hdf",
    )

    g03 = tmp_path / "Project.g03"
    g03.write_text(
        "Geom Title=Broken\nLCMann Region Name=Test\n",
        encoding="utf-8",
    )
    _geometry_hdf(
        Path(str(g03) + ".hdf"),
        terrain=r".\Terrain\Terrain.hdf",
        landcover=r".\LandCover\Missing.hdf",
    )

    g04 = tmp_path / "Project.g04"
    g04.write_text("Geom Title=Uncompiled\n", encoding="utf-8")

    geom_df = pd.DataFrame(
        {
            "geom_number": ["01", "02", "03", "04"],
            "full_path": [str(g01), str(g02), str(g03), str(g04)],
            "hdf_path": [
                str(g01) + ".hdf",
                str(g02) + ".hdf",
                str(g03) + ".hdf",
                str(g04) + ".hdf",
            ],
            "has_2d_mesh": [True, True, True, False],
        }
    )
    plan_df = pd.DataFrame(
        {
            "plan_number": ["01", "02", "03", "04"],
            "geometry_number": ["01", "02", "01", "03"],
        }
    )
    return _Project(
        project_folder=tmp_path,
        project_name="Project",
        geom_df=geom_df,
        plan_df=plan_df,
        terrain=terrain,
        landcover=landcover,
    )


def test_lists_live_associations_and_referencing_plans(tmp_path):
    project = _project(tmp_path)

    inventory = RasMap.list_geometry_associations(ras_object=project)

    assert len(inventory) == 4
    spatial = inventory.set_index("geom_number").loc["01"]
    assert spatial["plan_numbers"] == ("01", "03")
    assert bool(spatial["terrain_associated"])
    assert bool(spatial["terrain_path_exists"])
    assert bool(spatial["landcover_associated"])
    assert bool(spatial["landcover_path_exists"])
    assert bool(spatial["has_spatial_mannings"])
    assert spatial["inspection_status"] == "available"

    uncompiled = inventory.set_index("geom_number").loc["04"]
    assert uncompiled["inspection_status"] == "missing_hdf"
    assert not bool(uncompiled["geom_hdf_exists"])


def test_inventory_columns_match_documented_schema(tmp_path):
    inventory = RasMap.list_geometry_associations(ras_object=_project(tmp_path))
    documented = [
        column["name"]
        for column in DATAFRAME_SCHEMAS["geometry_associations"]["columns"]
    ]

    assert list(inventory.columns) == documented


def test_validation_distinguishes_missing_and_broken_associations(tmp_path):
    project = _project(tmp_path)

    missing = RasMap.validate_geometry_associations(
        geom_number="02",
        required_layers=("terrain", "mannings_n"),
        raise_on_failure=False,
        ras_object=project,
    ).iloc[0]
    assert missing["missing_required_layers"] == ("landcover",)
    assert missing["broken_association_layers"] == ()
    assert not bool(missing["passed"])

    broken = RasMap.validate_geometry_associations(
        geom_number=3,
        required_layers=("terrain", "landcover"),
        raise_on_failure=False,
        ras_object=project,
    ).iloc[0]
    assert broken["missing_required_layers"] == ()
    assert broken["broken_association_layers"] == ("landcover",)
    assert not bool(broken["passed"])


def test_validation_raises_with_geometry_specific_diagnostic(tmp_path):
    project = _project(tmp_path)

    with pytest.raises(
        RuntimeError,
        match=r"g02: missing required layers: landcover",
    ):
        RasMap.validate_geometry_associations(
            geom_number="02",
            ras_object=project,
        )


def test_validation_accepts_complete_association(tmp_path):
    report = RasMap.validate_geometry_associations(
        geom_number="g01",
        ras_object=_project(tmp_path),
    )
    documented = [
        column["name"]
        for column in DATAFRAME_SCHEMAS["geometry_association_validation"][
            "columns"
        ]
    ]

    assert list(report.columns) == documented
    assert bool(report.loc[0, "passed"])
    assert report.loc[0, "failure_reason"] == ""


def test_missing_landcover_diagnostic_explains_silent_default(tmp_path):
    hdf_path = _geometry_hdf(tmp_path / "Project.g01.hdf")

    message = landcover_association_diagnostic(hdf_path)

    assert message is not None
    assert "No land-cover association" in message
    assert "default Manning value" in message
    assert "Cells Center Manning's n" in message
