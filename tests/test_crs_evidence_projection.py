"""CRS evidence cross-check behind HdfBase.get_projection and RasPrj.project_crs.

Covers agreement, conflict (HDF vs .rasmap projection vs terrain), missing and
invalid evidence, and the public return form (EPSG vs ESRI-only vs WKT-only).
"""
import logging
import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest
from pyproj import CRS

from ras_commander import HdfBase, RasPrj
from ras_commander.hdf import HdfProject
from ras_commander.hdf.HdfUtils import (
    CRS_CONFLICT,
    CRS_EVIDENCE_ABSENT,
    CRS_EVIDENCE_FOUND,
    CRS_EVIDENCE_INVALID,
    CRS_EVIDENCE_MISSING_FILE,
    CRS_MISSING,
    CRS_RESOLVED,
    CrsEvidence,
    HdfUtils,
)


PA_NORTH_FTUS = 2271  # NAD83 / Pennsylvania North (ftUS)
PA_NORTH_M = 32128  # NAD83 / Pennsylvania North (metres)
TX_SC_FTUS = 2278  # NAD83 / Texas South Central (ftUS)
TX_SC_HARN_FTUS = 2919  # NAD83(HARN) / Texas South Central (ftUS)

# ESRI WKT1 spelling of EPSG:2271, as RASMapper/ArcGIS write .prj files.
ESRI_PA_NORTH_FTUS = (
    'PROJCS["NAD_1983_StatePlane_Pennsylvania_North_FIPS_3701_Feet",'
    'GEOGCS["GCS_North_American_1983",DATUM["D_North_American_1983",'
    'SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],'
    'UNIT["Degree",0.0174532925199433]],PROJECTION["Lambert_Conformal_Conic"],'
    'PARAMETER["False_Easting",1968500.0],PARAMETER["False_Northing",0.0],'
    'PARAMETER["Central_Meridian",-77.75],'
    'PARAMETER["Standard_Parallel_1",40.88333333333333],'
    'PARAMETER["Standard_Parallel_2",41.95],'
    'PARAMETER["Latitude_Of_Origin",40.16666666666666],'
    'UNIT["Foot_US",0.3048006096012192]]'
)

# A local transverse Mercator with no authority code anywhere.
CUSTOM_WKT = (
    'PROJCS["Local_TM",GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
    'SPHEROID["WGS_1984",6378137.0,298.257223563]],PRIMEM["Greenwich",0.0],'
    'UNIT["Degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],'
    'PARAMETER["False_Easting",12345.0],PARAMETER["False_Northing",0.0],'
    'PARAMETER["Central_Meridian",-91.123],PARAMETER["Scale_Factor",0.9999],'
    'PARAMETER["Latitude_Of_Origin",30.5],UNIT["Meter",1.0]]'
)


def _wkt(epsg: int) -> str:
    return CRS.from_epsg(epsg).to_wkt()


def _write_hdf(path: Path, wkt=None, geometry_group_wkt=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as hdf:
        if wkt is not None:
            hdf.attrs["Projection"] = wkt
        if geometry_group_wkt is not None:
            hdf.create_group("Geometry").attrs["Projection"] = geometry_group_wkt
    return path


def _write_prj(path: Path, wkt: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(wkt, encoding="utf-8")
    return path


def _write_rasmap(path: Path, projection=None, terrains=()) -> Path:
    parts = ["<RASMapper>"]
    if projection is not None:
        parts.append(f'  <RASProjectionFilename Filename="{projection}" />')
    if terrains:
        parts.append("  <Terrains>")
        parts.extend(
            f'    <Layer Name="T{i}" Type="TerrainLayer" Filename="{t}" />'
            for i, t in enumerate(terrains)
        )
        parts.append("  </Terrains>")
    parts.append("</RASMapper>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def _project(tmp_path, hdf_wkt=None, prj_wkt=None, terrain_wkt=None, name="Model"):
    """Plan HDF + .rasmap with optional projection file and terrain HDF."""
    hdf = _write_hdf(tmp_path / f"{name}.p01.hdf", hdf_wkt)
    projection = None
    if prj_wkt is not None:
        _write_prj(tmp_path / "Projection" / "model.prj", prj_wkt)
        projection = ".\\Projection\\model.prj"
    terrains = []
    if terrain_wkt is not None:
        _write_hdf(tmp_path / "Terrain" / "Terrain.hdf", terrain_wkt)
        terrains.append(".\\Terrain\\Terrain.hdf")
    _write_rasmap(tmp_path / f"{name}.rasmap", projection, terrains)
    return hdf


def _resolve(hdf):
    return HdfUtils.resolve_crs_evidence(HdfUtils.collect_hdf_crs_evidence(hdf))


# --------------------------------------------------------------------------
# Agreement
# --------------------------------------------------------------------------

def test_all_sources_agree_across_wkt_dialects_returns_epsg(tmp_path):
    hdf = _project(
        tmp_path,
        hdf_wkt=_wkt(PA_NORTH_FTUS),
        prj_wkt=ESRI_PA_NORTH_FTUS,
        terrain_wkt=CRS.from_epsg(PA_NORTH_FTUS).to_wkt("WKT1_GDAL"),
    )

    resolution = _resolve(hdf)

    assert resolution.status == CRS_RESOLVED
    assert resolution.source == "hdf_attribute"
    assert [e.source for e in resolution.evidence] == [
        "hdf_attribute", "rasmap_projection", "terrain_hdf",
    ]
    assert all(e.status == CRS_EVIDENCE_FOUND for e in resolution.evidence)
    assert resolution.epsg == PA_NORTH_FTUS
    assert HdfBase.get_projection(hdf) == f"EPSG:{PA_NORTH_FTUS}"


def test_main_compatible_epsg_string_for_hdf_attribute_only(tmp_path):
    hdf = _write_hdf(tmp_path / "Model.p01.hdf", _wkt(TX_SC_FTUS))

    assert HdfBase.get_projection(hdf) == f"EPSG:{TX_SC_FTUS}"


def test_rasmap_projection_only_esri_wkt_returns_epsg(tmp_path):
    hdf = _project(tmp_path, prj_wkt=ESRI_PA_NORTH_FTUS)

    assert HdfBase.get_projection(hdf) == f"EPSG:{PA_NORTH_FTUS}"


def test_terrain_only_evidence_resolves(tmp_path):
    hdf = _project(tmp_path, terrain_wkt=_wkt(TX_SC_FTUS))

    resolution = _resolve(hdf)

    assert resolution.status == CRS_RESOLVED
    assert resolution.source == "terrain_hdf"
    assert HdfBase.get_projection(hdf) == f"EPSG:{TX_SC_FTUS}"


def test_geometry_group_projection_used_when_root_attribute_absent(tmp_path):
    hdf = _write_hdf(tmp_path / "Model.g01.hdf", geometry_group_wkt=_wkt(TX_SC_FTUS))

    evidence = HdfUtils.read_crs_evidence(hdf)

    assert evidence.status == CRS_EVIDENCE_FOUND
    assert HdfProject.get_project_crs(hdf) == f"EPSG:{TX_SC_FTUS}"


# --------------------------------------------------------------------------
# Conflict
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "hdf_epsg, prj_epsg, terrain_epsg",
    [
        (PA_NORTH_FTUS, TX_SC_FTUS, None),  # HDF vs .rasmap projection
        (PA_NORTH_FTUS, None, TX_SC_FTUS),  # HDF vs terrain
        (None, PA_NORTH_FTUS, TX_SC_FTUS),  # .rasmap projection vs terrain
        (PA_NORTH_FTUS, PA_NORTH_M, None),  # same zone, ftUS vs metres
        (TX_SC_FTUS, TX_SC_HARN_FTUS, None),  # NAD83 vs NAD83(HARN)
    ],
)
def test_conflicting_evidence_returns_none(tmp_path, caplog, hdf_epsg, prj_epsg, terrain_epsg):
    hdf = _project(
        tmp_path,
        hdf_wkt=_wkt(hdf_epsg) if hdf_epsg else None,
        prj_wkt=_wkt(prj_epsg) if prj_epsg else None,
        terrain_wkt=_wkt(terrain_epsg) if terrain_epsg else None,
    )

    resolution = _resolve(hdf)

    assert resolution.status == CRS_CONFLICT
    assert resolution.crs is None
    assert resolution.to_crs_string() is None
    assert len(resolution.candidates) == 2
    with caplog.at_level(logging.WARNING):
        assert HdfBase.get_projection(hdf) is None
    assert "Conflicting" in caplog.text


# --------------------------------------------------------------------------
# Missing and invalid evidence
# --------------------------------------------------------------------------

def test_no_evidence_returns_none_and_records_checked_locations(tmp_path):
    hdf = _write_hdf(tmp_path / "Model.p01.hdf")

    resolution = _resolve(hdf)

    assert resolution.status == CRS_MISSING
    assert [(e.source, e.status) for e in resolution.evidence] == [
        ("hdf_attribute", CRS_EVIDENCE_ABSENT),
        ("rasmap", CRS_EVIDENCE_MISSING_FILE),
    ]
    assert HdfBase.get_projection(hdf) is None


def test_missing_projection_file_does_not_vote(tmp_path):
    hdf = _write_hdf(tmp_path / "Model.p01.hdf", _wkt(TX_SC_FTUS))
    _write_rasmap(tmp_path / "Model.rasmap", projection=".\\Projection\\gone.prj")

    resolution = _resolve(hdf)

    assert resolution.evidence[1].status == CRS_EVIDENCE_MISSING_FILE
    assert resolution.status == CRS_RESOLVED
    assert HdfBase.get_projection(hdf) == f"EPSG:{TX_SC_FTUS}"


def test_invalid_projection_text_does_not_vote(tmp_path):
    hdf = _project(tmp_path, prj_wkt="not a coordinate system", terrain_wkt=_wkt(TX_SC_FTUS))

    resolution = _resolve(hdf)

    assert resolution.evidence[1].status == CRS_EVIDENCE_INVALID
    assert resolution.status == CRS_RESOLVED
    assert HdfBase.get_projection(hdf) == f"EPSG:{TX_SC_FTUS}"


def test_rasmap_without_projection_element_is_absent(tmp_path):
    hdf = _project(tmp_path)

    evidence = HdfUtils.collect_hdf_crs_evidence(hdf)

    assert (evidence[1].source, evidence[1].status) == ("rasmap_projection", CRS_EVIDENCE_ABSENT)
    assert HdfBase.get_projection(hdf) is None


def test_resolve_with_no_evidence_items_is_missing():
    assert HdfUtils.resolve_crs_evidence([]).status == CRS_MISSING
    absent = CrsEvidence("hdf_attribute", None, CRS_EVIDENCE_ABSENT)
    assert HdfUtils.resolve_crs_evidence([absent]).to_crs_string() is None


# --------------------------------------------------------------------------
# Return form: EPSG vs ESRI-only vs WKT-only
# --------------------------------------------------------------------------

def test_esri_only_crs_returns_wkt_not_esri_code(tmp_path):
    esri_wkt = CRS.from_user_input("ESRI:102003").to_wkt()
    hdf = _write_hdf(tmp_path / "Model.p01.hdf", esri_wkt)

    identity = HdfUtils.get_crs_identity(esri_wkt)
    value = HdfBase.get_projection(hdf)

    assert identity["authority"] == "ESRI:102003"
    assert identity["epsg"] is None
    assert value == esri_wkt
    assert not value.startswith(("ESRI:", "EPSG:"))
    assert CRS.from_user_input(value).equals(CRS.from_user_input("ESRI:102003"))


def test_wkt_only_crs_returns_source_wkt(tmp_path):
    hdf = _write_hdf(tmp_path / "Model.p01.hdf", CUSTOM_WKT)

    assert HdfBase.get_projection(hdf) == CUSTOM_WKT
    assert HdfUtils.get_crs_identity(CUSTOM_WKT)["authority"] is None


def test_epsg_label_requires_strict_equivalence():
    # A NAD83(HARN) zone must not be labelled with the NAD83 code.
    assert HdfUtils.get_equivalent_epsg(_wkt(TX_SC_HARN_FTUS)) == TX_SC_HARN_FTUS
    assert HdfUtils.format_crs(_wkt(TX_SC_HARN_FTUS)) == f"EPSG:{TX_SC_HARN_FTUS}"
    assert HdfUtils.format_crs(ESRI_PA_NORTH_FTUS) == f"EPSG:{PA_NORTH_FTUS}"
    assert HdfUtils.format_crs(CUSTOM_WKT) == CUSTOM_WKT
    assert HdfUtils.format_crs(None) is None
    assert HdfUtils.format_crs("  ") is None


def test_crs_equivalent_distinguishes_units_and_realizations():
    assert HdfUtils.crs_equivalent(ESRI_PA_NORTH_FTUS, f"EPSG:{PA_NORTH_FTUS}")
    assert not HdfUtils.crs_equivalent(f"EPSG:{PA_NORTH_FTUS}", f"EPSG:{PA_NORTH_M}")
    assert not HdfUtils.crs_equivalent(f"EPSG:{TX_SC_FTUS}", f"EPSG:{TX_SC_HARN_FTUS}")
    with pytest.raises(ValueError):
        HdfUtils.crs_equivalent("not a crs", f"EPSG:{TX_SC_FTUS}")


def test_get_crs_identity_reports_units():
    identity = HdfUtils.get_crs_identity(f"EPSG:{PA_NORTH_FTUS}")

    assert identity["is_projected"]
    assert identity["horizontal_unit_kind"] == "us_survey_foot"
    assert identity["authority"] == f"EPSG:{PA_NORTH_FTUS}"


def test_wkt_to_crs_string_uses_shared_formatter():
    assert HdfBase._wkt_to_crs_string(ESRI_PA_NORTH_FTUS, "test") == f"EPSG:{PA_NORTH_FTUS}"
    assert HdfBase._wkt_to_crs_string(CUSTOM_WKT, "test") == CUSTOM_WKT
    assert HdfBase._wkt_to_crs_string("garbage", "test") == "garbage"


# --------------------------------------------------------------------------
# RASMapper selection and paths
# --------------------------------------------------------------------------

def test_resolve_ras_relative_path_keeps_parent_components(tmp_path):
    base = tmp_path / "project"

    assert HdfUtils.resolve_ras_relative_path(base, "..\\shared\\a.prj") == base / ".." / "shared" / "a.prj"
    assert HdfUtils.resolve_ras_relative_path(base, ".\\GIS\\a.prj") == base / "GIS" / "a.prj"
    assert HdfUtils.resolve_ras_relative_path(base, "D:\\x\\a.prj") == Path("D:\\x\\a.prj")


def test_parent_relative_projection_file_is_read(tmp_path):
    project = tmp_path / "project"
    hdf = _write_hdf(project / "Model.p01.hdf")
    _write_prj(tmp_path / "shared" / "model.prj", _wkt(TX_SC_FTUS))
    _write_rasmap(project / "Model.rasmap", projection="..\\shared\\model.prj")

    assert HdfBase.get_projection(hdf) == f"EPSG:{TX_SC_FTUS}"


def test_matching_rasmap_is_selected_among_several(tmp_path):
    hdf = _write_hdf(tmp_path / "Model.p01.hdf")
    _write_prj(tmp_path / "a.prj", _wkt(TX_SC_FTUS))
    _write_prj(tmp_path / "b.prj", _wkt(PA_NORTH_FTUS))
    _write_rasmap(tmp_path / "Model.rasmap", projection=".\\a.prj")
    _write_rasmap(tmp_path / "Other.rasmap", projection=".\\b.prj")

    assert HdfBase.get_projection(hdf) == f"EPSG:{TX_SC_FTUS}"


def test_ambiguous_rasmaps_are_reported_not_guessed(tmp_path):
    hdf = _write_hdf(tmp_path / "Model.p01.hdf")
    _write_prj(tmp_path / "a.prj", _wkt(TX_SC_FTUS))
    _write_rasmap(tmp_path / "One.rasmap", projection=".\\a.prj")
    _write_rasmap(tmp_path / "Two.rasmap", projection=".\\a.prj")

    evidence = HdfUtils.collect_hdf_crs_evidence(hdf)

    assert (evidence[1].source, evidence[1].status) == ("rasmap", CRS_EVIDENCE_INVALID)
    assert HdfBase.get_projection(hdf) is None
    explicit = HdfUtils.collect_hdf_crs_evidence(hdf, rasmap_path=tmp_path / "One.rasmap")
    assert HdfUtils.resolve_crs_evidence(explicit).to_crs_string() == f"EPSG:{TX_SC_FTUS}"


def test_multi_value_projection_attribute_is_invalid(tmp_path):
    path = tmp_path / "Model.p01.hdf"
    with h5py.File(path, "w") as hdf:
        hdf.attrs["Projection"] = np.array([b"a", b"b"])

    assert HdfUtils.read_crs_evidence(path).status == CRS_EVIDENCE_INVALID


# --------------------------------------------------------------------------
# RasPrj.project_crs uses the same rule
# --------------------------------------------------------------------------

def _ras_project(tmp_path, name="Model"):
    (tmp_path / f"{name}.prj").write_text(
        "Proj Title=Test\nGeom File=g01\nPlan File=p01\n", encoding="utf-8"
    )
    (tmp_path / f"{name}.p01").write_text(
        "Plan Title=Base\nProgram Version=6.6\nGeom File=g01\nFlow File=u01\n",
        encoding="utf-8",
    )
    (tmp_path / f"{name}.g01").write_text("Geom Title=Base\n", encoding="utf-8")
    return name


def _init(tmp_path):
    project = RasPrj()
    project.initialize(tmp_path, "Ras.exe", suppress_logging=True, load_results_summary=False)
    return project


def test_project_crs_conflict_between_geometry_and_rasmap(tmp_path):
    name = _ras_project(tmp_path)
    _write_hdf(tmp_path / f"{name}.g01.hdf", _wkt(TX_SC_FTUS))
    _write_prj(tmp_path / "Projection" / "model.prj", _wkt(PA_NORTH_FTUS))
    _write_rasmap(tmp_path / f"{name}.rasmap", projection=".\\Projection\\model.prj")

    project = _init(tmp_path)

    assert project.project_crs is None
    assert project.project_crs_status == "conflict"
    assert HdfBase.get_projection(tmp_path / f"{name}.g01.hdf") is None


def test_project_crs_matches_get_projection_when_sources_agree(tmp_path):
    name = _ras_project(tmp_path)
    geom_hdf = _write_hdf(tmp_path / f"{name}.g01.hdf")
    _write_hdf(tmp_path / f"{name}.p01.hdf", _wkt(PA_NORTH_FTUS))
    _write_prj(tmp_path / "Projection" / "model.prj", ESRI_PA_NORTH_FTUS)
    _write_hdf(tmp_path / "Terrain" / "Terrain.hdf", _wkt(PA_NORTH_FTUS))
    _write_rasmap(
        tmp_path / f"{name}.rasmap",
        projection=".\\Projection\\model.prj",
        terrains=[".\\Terrain\\Terrain.hdf"],
    )

    project = _init(tmp_path)

    assert project.project_crs_status == "resolved"
    assert project.project_crs == f"EPSG:{PA_NORTH_FTUS}"
    assert project.project_crs == HdfBase.get_projection(geom_hdf)
    assert project.project_crs == HdfProject.get_project_crs(geom_hdf)


def test_project_crs_missing_status(tmp_path):
    _ras_project(tmp_path)

    project = _init(tmp_path)

    assert project.project_crs is None
    assert project.project_crs_status == "missing"


def test_cross_section_text_fallback_respects_project_conflict(tmp_path):
    from ras_commander.RasCrossSections import RasCrossSections, _ProjectContext

    _write_prj(tmp_path / "Projection" / "model.prj", _wkt(TX_SC_FTUS))
    _write_rasmap(tmp_path / "Model.rasmap", projection=".\\Projection\\model.prj")

    class _Conflicted:
        project_crs = None
        project_crs_status = "conflict"

    def context(ras_object):
        return _ProjectContext("Model", tmp_path, tmp_path / "Model.prj", ras_object, None, None)

    assert RasCrossSections._project_mapper_crs(context(None)) == f"EPSG:{TX_SC_FTUS}"
    assert RasCrossSections._project_mapper_crs(context(_Conflicted())) is None


# --------------------------------------------------------------------------
# Real RasExamples projects
# --------------------------------------------------------------------------

def _extract(name, tmp_path):
    from ras_commander import RasExamples

    try:
        folder = RasExamples.extract_project(name, output_path=tmp_path, suffix="crs")
    except Exception as exc:  # pragma: no cover - depends on example download
        pytest.skip(f"RasExamples project {name!r} unavailable: {exc}")
    return Path(folder[0] if isinstance(folder, list) else folder)


@pytest.mark.parametrize(
    "project, relative_hdf, expected",
    [
        ("Baxter RAS Mapper", "RAS Model/Baxter.g02.hdf", "EPSG:2227"),
        ("Muncie", "Muncie.g01.hdf", "WKT"),
    ],
)
def test_real_projects_resolve_consistently(tmp_path, project, relative_hdf, expected):
    folder = _extract(project, tmp_path)
    hdf = folder / relative_hdf

    value = HdfBase.get_projection(hdf)
    ras = _init(hdf.parent)

    if expected == "WKT":
        # Muncie's ESRI State Plane .prj has no strictly equivalent EPSG code.
        assert value and not value.startswith("EPSG:")
        assert "Indiana" in CRS.from_user_input(value).name
    else:
        assert value == expected
    assert ras.project_crs_status == "resolved"
    assert HdfUtils.crs_equivalent(ras.project_crs, value)


def test_real_project_conflicting_projection_file_returns_none(tmp_path):
    folder = _extract("Muncie", tmp_path)
    hdf = folder / "Muncie.g01.hdf"
    resolution = _resolve(hdf)
    projection = next(e for e in resolution.evidence if e.source == "rasmap_projection")
    assert projection.status == CRS_EVIDENCE_FOUND

    # Re-point the real .rasmap projection at a different zone; the real
    # terrain HDF still carries Indiana East, so the evidence conflicts.
    shutil.copy(projection.path, projection.path.with_suffix(".orig"))
    projection.path.write_text(_wkt(PA_NORTH_FTUS), encoding="utf-8")

    assert _resolve(hdf).status == CRS_CONFLICT
    assert HdfBase.get_projection(hdf) is None


@pytest.mark.parametrize("definition", ["ESRI:102003", b"ESRI:102003"])
def test_non_epsg_authority_is_serialized_to_wkt(tmp_path, definition):
    expected = CRS.from_user_input("ESRI:102003")
    value = HdfUtils.format_crs(definition)
    assert not value.startswith(("ESRI:", "EPSG:"))
    assert CRS.from_wkt(value).equals(expected)

    path = _write_hdf(tmp_path / "Authority.p01.hdf", definition)
    value = HdfBase.get_projection(path)
    assert not value.startswith(("ESRI:", "EPSG:"))
    assert CRS.from_wkt(value).equals(expected)
    resolution = HdfUtils.resolve_crs_evidence([
        HdfUtils.read_crs_evidence(path)
    ])
    assert resolution.to_crs_string() == value
