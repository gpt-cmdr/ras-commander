"""CRS evidence, identity and unit contract shared by the Python and native HDF paths.

Real fixtures come from the public HEC 7.0 example archive (``RasExamples``) and,
for stored HEC-RAS 5.x context, from the Example_Projects.exe shipped with a local
HEC-RAS 5.0.7 install. Missing fixtures skip; they are never synthesized. Conflict
and .rasmap-selection cases use minimal files built from those real fixture WKTs.

Coordinator recovery wires the public callers in a separate integration patch;
all previous strict expected failures are now ordinary passing requirements.
"""
import math
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import pytest

CALLER_GAP = "public caller not yet wired to HdfUtils CRS evidence (integration patch)"

pyproj = pytest.importorskip("pyproj")

from ras_commander.hdf.HdfUtils import (
    HdfUtils,
    CrsEvidence,
    CRS_CONFLICT,
    CRS_MISSING,
    CRS_RESOLVED,
    US_SURVEY_FOOT_M,
)

FT_US_SQ = US_SURVEY_FOOT_M ** 2
FT_INTL_SQ = 0.3048 ** 2


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def examples(tmp_path_factory):
    from ras_commander import RasExamples

    out = tmp_path_factory.mktemp("crs_examples")
    names = ["Davis", "Muncie", "BaldEagleCrkMulti2D", "Chippewa_2D", "Weise_2D",
             "Baxter RAS Mapper"]
    try:
        paths = RasExamples.extract_project(names, output_path=out)
    except Exception as e:  # offline or archive unavailable
        pytest.skip(f"RasExamples 7.0 archive unavailable: {e}")
    return dict(zip(names, (Path(p) for p in paths)))


@pytest.fixture(scope="module")
def installer_507(tmp_path_factory):
    """BaldEagleCrkMulti2D and Sacramento from the HEC-RAS 5.0.7 installer examples."""
    from ras_commander import RasUtils

    install = RasUtils.discover_ras_versions().get("5.0.7")
    if install is None:
        pytest.skip("HEC-RAS 5.0.7 is not installed")
    install = Path(install)
    install = install if install.is_dir() else install.parent
    archive = install / "Example Projects" / "Example_Projects.exe"
    seven_zip = install / "7za.exe"
    if not archive.is_file() or not seven_zip.is_file():
        pytest.skip("HEC-RAS 5.0.7 example archive or bundled 7za.exe not found")

    out = tmp_path_factory.mktemp("crs_installer_507")
    members = [
        r"Example Data\2D Unsteady Flow Hydraulics\BaldEagleCrkMulti2D\BaldEagleDamBrk.rasmap",
        r"Example Data\2D Unsteady Flow Hydraulics\BaldEagleCrkMulti2D\BaldEagleDamBrk.g01",
        r"Example Data\2D Unsteady Flow Hydraulics\BaldEagleCrkMulti2D\Terrain\USGS_gages_Project.prj",
        r"Example Data\Water Quality\Sacramento River Temperature Example\Sacramento.g01.hdf",
    ]
    # Archive extraction only; no HEC-RAS executable is run.
    subprocess.run([str(seven_zip), "x", "-y", f"-o{out}", str(archive), *members],
                   check=True, capture_output=True)
    return out / "Example Data"


def _resolve(hdf_path):
    return HdfUtils.resolve_crs_evidence(HdfUtils.collect_hdf_crs_evidence(hdf_path))


def _by_source(evidence, source):
    return [e for e in evidence if e.source == source]


# ---------------------------------------------------------------------------
# RASMapper relative paths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("spelling,relative", [
    (r".\GIS\projection.prj", "project/GIS/projection.prj"),
    ("./GIS/projection.prj", "project/GIS/projection.prj"),
    (r"GIS\projection.prj", "project/GIS/projection.prj"),
    (r"..\shared CRS\projection.prj", "shared CRS/projection.prj"),
    (r".\a\..\GIS\projection.prj", "project/GIS/projection.prj"),
])
def test_rasmap_relative_path_reaches_named_file(tmp_path, spelling, relative):
    project = tmp_path / "project"
    project.mkdir()
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("marker", encoding="utf-8")
    (project / "a").mkdir()

    resolved = HdfUtils.resolve_ras_relative_path(project, spelling)

    assert resolved.is_file()
    assert resolved.samefile(target)


@pytest.mark.parametrize("stored", [r"C:\GIS\projection.prj", r"\\server\share\projection.prj"])
def test_rasmap_absolute_paths_are_not_rebased(tmp_path, stored):
    assert HdfUtils.resolve_ras_relative_path(tmp_path, stored) == Path(stored)


def test_chippewa_parent_relative_projection_is_reported_missing(examples):
    project = examples["Chippewa_2D"]
    evidence = HdfUtils.collect_hdf_crs_evidence(project / "Chippewa_2D.g01.hdf")

    (projection,) = _by_source(evidence, "rasmap_projection")
    assert projection.status == "missing_file"
    # "..\Winona_Upload\..." keeps its parent component instead of becoming ".Winona_Upload".
    assert projection.path == project / ".." / "Winona_Upload" / "LifeSim model" / \
        "Winona Levee SQRA 2019" / "RAS" / "AW" / "MMC_Projection.prj"


# ---------------------------------------------------------------------------
# Real-fixture CRS resolution
# ---------------------------------------------------------------------------

def test_davis_resolves_strictly_to_harn_california_zone_2_ftus(examples):
    project = examples["Davis"]
    resolution = _resolve(project / "DavisStormSystem.g02.hdf")

    assert resolution.status == CRS_RESOLVED
    assert resolution.source == "rasmap_projection"
    assert resolution.authority == "EPSG:2871"
    (terrain,) = _by_source(resolution.evidence, "terrain_hdf")
    assert terrain.status == "found"
    assert HdfUtils.crs_equivalent(terrain.wkt, resolution.crs)

    identity = HdfUtils.get_crs_identity(resolution.crs)
    assert identity["datum"] == "NAD83 (High Accuracy Reference Network)"
    assert identity["horizontal_unit_kind"] == "us_survey_foot"


def test_davis_source_wkt_equivalence_across_dialects(examples):
    wkt1_esri = (examples["Davis"] / "GIS" / "2871.prj").read_text()
    epsg = pyproj.CRS.from_epsg(2871)

    assert HdfUtils.crs_equivalent(wkt1_esri, "EPSG:2871")
    assert HdfUtils.crs_equivalent(wkt1_esri, epsg.to_wkt("WKT2_2019"))
    assert HdfUtils.crs_equivalent(wkt1_esri, epsg.to_wkt("WKT1_GDAL"))
    # Same zone, other NAD83 realizations or units are distinct CRSs.
    assert not HdfUtils.crs_equivalent(wkt1_esri, "EPSG:2226")  # NAD83 ftUS
    assert not HdfUtils.crs_equivalent(wkt1_esri, "EPSG:6418")  # NAD83(2011) ftUS
    assert not HdfUtils.crs_equivalent(wkt1_esri, "EPSG:2767")  # NAD83(HARN) metre


def test_muncie_keeps_source_wkt_without_guessing_epsg(examples):
    project = examples["Muncie"]
    prj_text = (project / "GIS_Data" / "Muncie_IA_Clip.prj").read_text().strip()
    resolution = _resolve(project / "Muncie.g01.hdf")

    assert resolution.status == CRS_RESOLVED
    assert resolution.crs == prj_text
    assert resolution.authority is None
    identity = HdfUtils.get_crs_identity(resolution.crs)
    assert identity["horizontal_unit_kind"] == "us_survey_foot"
    assert all(confidence < 100 for _, confidence in identity["authority_candidates"])
    # EPSG:2965 rounds false easting to 328083.333 ftUS; the source is 328083.3333333333.
    assert not HdfUtils.crs_equivalent(resolution.crs, "EPSG:2965")


def test_hdf_attribute_has_precedence_over_rasmap(examples):
    project = examples["BaldEagleCrkMulti2D"]
    with_attribute = _resolve(project / "BaldEagleDamBrk.g09.hdf")
    without_attribute = _resolve(project / "BaldEagleDamBrk.g06.hdf")

    assert with_attribute.source == "hdf_attribute"
    assert without_attribute.source == "rasmap_projection"
    assert with_attribute.authority == without_attribute.authority == "EPSG:2271"


def test_terrain_fallback_when_projection_file_missing_or_unset(examples):
    chippewa = _resolve(examples["Chippewa_2D"] / "Chippewa_2D.g01.hdf")
    baxter = _resolve(examples["Baxter RAS Mapper"] / "RAS Model" / "Baxter.g02.hdf")

    assert chippewa.status == CRS_RESOLVED
    assert chippewa.source == "terrain_hdf"
    assert chippewa.authority is None  # USGS Albers in ftUS has no exact authority code
    chippewa_identity = HdfUtils.get_crs_identity(chippewa.crs)
    assert chippewa_identity["horizontal_unit_kind"] == "us_survey_foot"
    # A low-confidence candidate exists but is a metre CRS: candidates never label data.
    for code, confidence in chippewa_identity["authority_candidates"]:
        assert confidence < 100
        assert not HdfUtils.crs_equivalent(chippewa.crs, code)

    assert baxter.source == "terrain_hdf"
    assert baxter.authority == "EPSG:2227"


def test_unknown_crs_remains_unknown(examples):
    hdf_path = examples["Weise_2D"] / "Weise.g08.hdf"
    resolution = _resolve(hdf_path)

    assert resolution.status == CRS_MISSING
    assert resolution.crs is None and resolution.authority is None
    assert {e.status for e in resolution.evidence} == {"absent"}
    assert HdfUtils.get_units_system(hdf_path) == "SI Units"
    assert HdfUtils.area_to_square_meters(2.5, units_system="SI Units") == 2.5


# ---------------------------------------------------------------------------
# Conflicts and evidence handling
# ---------------------------------------------------------------------------

def test_conflicting_evidence_is_explicit(examples):
    davis = HdfUtils.read_crs_evidence(examples["Davis"] / "GIS" / "2871.prj", "a")
    bald = HdfUtils.read_crs_evidence(
        examples["BaldEagleCrkMulti2D"] / "Terrain" / "Projection.prj", "b")

    resolution = HdfUtils.resolve_crs_evidence([davis, bald])

    assert resolution.status == CRS_CONFLICT
    assert resolution.crs is None and resolution.authority is None
    assert resolution.candidates == (davis.wkt, bald.wkt)


def test_equivalent_dialects_do_not_conflict(examples):
    davis = HdfUtils.read_crs_evidence(examples["Davis"] / "GIS" / "2871.prj", "prj")
    wkt2 = CrsEvidence("wkt2", None, "found", pyproj.CRS.from_epsg(2871).to_wkt("WKT2_2019"))
    invalid = CrsEvidence("bad", None, "invalid", "PROJCS[broken", "parse error")

    resolution = HdfUtils.resolve_crs_evidence([invalid, davis, wkt2])

    assert resolution.status == CRS_RESOLVED
    assert resolution.source == "prj"
    assert resolution.authority == "EPSG:2871"


def test_read_crs_evidence_statuses(tmp_path):
    empty = tmp_path / "empty.prj"
    empty.write_text("   ", encoding="utf-8")
    broken = tmp_path / "broken.prj"
    broken.write_text("PROJCS[not a crs", encoding="utf-8")

    assert HdfUtils.read_crs_evidence(tmp_path / "nope.prj").status == "missing_file"
    assert HdfUtils.read_crs_evidence(empty).status == "absent"
    assert HdfUtils.read_crs_evidence(broken).status == "invalid"


# ---------------------------------------------------------------------------
# Units and vertical metadata
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("crs,kind,sq_m", [
    ("EPSG:2871", "us_survey_foot", FT_US_SQ),
    ("EPSG:2913", "international_foot", FT_INTL_SQ),  # NAD83(HARN) / Oregon North (ft)
    ("EPSG:26918", "metre", 1.0),
])
def test_area_conversion_uses_exact_crs_unit(crs, kind, sq_m):
    assert HdfUtils.get_crs_identity(crs)["horizontal_unit_kind"] == kind
    assert math.isclose(HdfUtils.area_to_square_meters(1.0, crs), sq_m, rel_tol=1e-15)
    np.testing.assert_allclose(HdfUtils.area_to_square_meters([1.0, 4.0], crs),
                               [sq_m, 4 * sq_m], rtol=1e-15)


def test_ftus_and_international_foot_areas_differ():
    one_square_mile_ft = 5280.0 ** 2
    us = HdfUtils.area_to_square_meters(one_square_mile_ft, "EPSG:2871")
    intl = HdfUtils.area_to_square_meters(one_square_mile_ft, "EPSG:2913")
    assert math.isclose(us - intl, one_square_mile_ft * (FT_US_SQ - FT_INTL_SQ), rel_tol=1e-9)
    assert us - intl > 10.0  # about 10.4 m^2 per square mile


def test_ambiguous_or_contradictory_units_raise():
    with pytest.raises(ValueError, match="ambiguous"):
        HdfUtils.linear_unit_to_meters(units_system="US Customary")
    with pytest.raises(ValueError, match="unknown"):
        HdfUtils.linear_unit_to_meters()
    with pytest.raises(ValueError, match="angular"):
        HdfUtils.linear_unit_to_meters("EPSG:4269")
    with pytest.raises(ValueError, match="contradicts"):
        HdfUtils.linear_unit_to_meters("EPSG:2271", "SI Units")
    with pytest.raises(ValueError, match="contradicts"):
        HdfUtils.linear_unit_to_meters("EPSG:26918", "US Customary")
    assert HdfUtils.linear_unit_to_meters("EPSG:2271", "US Customary") == pytest.approx(
        US_SURVEY_FOOT_M, rel=1e-15)


def test_vertical_metadata_is_reported_separately():
    metre = HdfUtils.get_crs_identity("EPSG:2871+5703")   # NAVD88 height (m)
    feet = HdfUtils.get_crs_identity("EPSG:2871+6360")    # NAVD88 height (ftUS)
    horizontal = HdfUtils.get_crs_identity("EPSG:2871")

    assert metre["horizontal_unit_kind"] == feet["horizontal_unit_kind"] == "us_survey_foot"
    assert metre["vertical"]["unit_kind"] == "metre"
    assert feet["vertical"]["unit_kind"] == "us_survey_foot"
    assert horizontal["vertical"] is None
    assert not HdfUtils.crs_equivalent("EPSG:2871+5703", "EPSG:2871+6360")


def test_unparseable_crs_raises():
    with pytest.raises(ValueError):
        HdfUtils.get_crs_identity("not a crs")
    with pytest.raises(ValueError):
        HdfUtils.crs_equivalent("EPSG:2871", "not a crs")


# ---------------------------------------------------------------------------
# Stored versions, 5.x context and PR548 timestamps
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("HEC-RAS 5.0.7 November 2018", (5, 0, 7)),
    ("HEC-RAS 6.7 Beta 5 Development", (6, 7, 0)),
    ("HEC-RAS 6.2.0 March 2022", (6, 2, 0)),
    ("Unknown writer", None),
    (None, None),
])
def test_parse_ras_file_version(text, expected):
    assert HdfUtils.parse_ras_file_version(text) == expected


def test_stored_versions_come_from_hdf_not_archive_label(examples):
    davis = HdfUtils.get_stored_ras_version(examples["Davis"] / "DavisStormSystem.g02.hdf")
    weise = HdfUtils.get_stored_ras_version(examples["Weise_2D"] / "Weise.g08.hdf")

    assert HdfUtils.parse_ras_file_version(davis) == (6, 7, 0)
    assert HdfUtils.parse_ras_file_version(weise) == (6, 6, 0)


def test_hec_ras_507_contexts(installer_507):
    bald = installer_507 / "2D Unsteady Flow Hydraulics" / "BaldEagleCrkMulti2D"
    assert "Program Version=5.07" in (bald / "BaldEagleDamBrk.g01").read_text(errors="replace")
    # The 5.0.7 example ships no geometry HDF; the .rasmap projection carries the CRS.
    resolution = _resolve(bald / "BaldEagleDamBrk.g01.hdf")
    assert resolution.status == CRS_RESOLVED
    assert resolution.source == "rasmap_projection"
    assert resolution.authority == "EPSG:2271"

    sacramento = (installer_507 / "Water Quality" / "Sacramento River Temperature Example"
                  / "Sacramento.g01.hdf")
    version = HdfUtils.get_stored_ras_version(sacramento)
    assert HdfUtils.parse_ras_file_version(version) == (5, 0, 7)
    assert _resolve(sacramento).status == CRS_MISSING
    assert HdfUtils.get_units_system(sacramento) == "SI Units"
    assert HdfUtils.linear_unit_to_meters(units_system="SI Units") == 1.0


def test_year_3000_millisecond_timestamps_preserved():
    start = datetime(3000, 1, 1)
    index = HdfUtils.convert_timesteps_to_datetimes(
        np.array([0.0, 0.5, 1.0 + 0.25 / 86400.0]), start, round_to="1ms")

    assert index[0] == datetime(3000, 1, 1)
    assert index[1] == datetime(3000, 1, 1, 12)
    assert index[2] == datetime(3000, 1, 2, 0, 0, 0, 250000)
    # Beyond the ns range: ms here; pandas 3 itself returns us for such dates.
    assert index.unit in {"ms", "us"}


# ---------------------------------------------------------------------------
# Current public callers: HdfBase.get_projection, HdfMesh, HdfPipe
# ---------------------------------------------------------------------------

def _hdf_without_projection(path):
    with h5py.File(path, "w") as hdf_file:
        hdf_file.attrs["File Type"] = "HEC-RAS Geometry"
    return path


def test_get_projection_contract_on_real_fixtures(examples):
    from ras_commander import HdfBase

    muncie_prj = (examples["Muncie"] / "GIS_Data" / "Muncie_IA_Clip.prj").read_text().strip()

    assert HdfBase.get_projection(examples["Davis"] / "DavisStormSystem.g02.hdf") == "EPSG:2871"
    assert HdfBase.get_projection(
        examples["BaldEagleCrkMulti2D"] / "BaldEagleDamBrk.g09.hdf") == "EPSG:2271"
    assert HdfBase.get_projection(
        examples["BaldEagleCrkMulti2D"] / "BaldEagleDamBrk.g06.hdf") == "EPSG:2271"
    assert HdfBase.get_projection(examples["Muncie"] / "Muncie.g01.hdf") == muncie_prj
    assert HdfBase.get_projection(examples["Weise_2D"] / "Weise.g08.hdf") is None


def test_hdf_mesh_labels_with_get_projection(examples):
    from ras_commander import HdfMesh

    areas = HdfMesh.get_mesh_areas(examples["BaldEagleCrkMulti2D"] / "BaldEagleDamBrk.g09.hdf")
    assert areas.crs is not None and areas.crs.to_epsg() == 2271


@pytest.mark.parametrize("project,hdf", [
    ("Chippewa_2D", "Chippewa_2D.g01.hdf"),
    ("Baxter RAS Mapper", "RAS Model/Baxter.g02.hdf"),
])
def test_get_projection_uses_terrain_evidence(examples, project, hdf):
    from ras_commander import HdfBase

    hdf_path = examples[project] / hdf
    expected = _resolve(hdf_path)
    assert expected.status == CRS_RESOLVED
    assert HdfBase.get_projection(hdf_path) is not None
    assert HdfUtils.crs_equivalent(HdfBase.get_projection(hdf_path), expected.crs)


def test_hdfbase_rasmap_path_keeps_parent_component(tmp_path):
    from ras_commander import HdfBase

    resolved = HdfBase._resolve_rasmap_path(tmp_path, r"..\shared\projection.prj")
    assert resolved == HdfUtils.resolve_ras_relative_path(tmp_path, r"..\shared\projection.prj")


def test_get_projection_prefers_rasmap_matching_project(tmp_path, examples):
    from ras_commander import HdfBase

    shutil.copy(examples["Davis"] / "GIS" / "2871.prj", tmp_path / "davis.prj")
    shutil.copy(examples["BaldEagleCrkMulti2D"] / "Terrain" / "Projection.prj",
                tmp_path / "bald.prj")
    for stem, prj in (("Aaa_Other", "bald.prj"), ("Model", "davis.prj")):
        (tmp_path / f"{stem}.rasmap").write_text(
            '<RASMapper><RASProjectionFilename Filename=".\\' + prj + '" /></RASMapper>',
            encoding="utf-8")
    hdf_path = _hdf_without_projection(tmp_path / "Model.g01.hdf")

    assert _resolve(hdf_path).authority == "EPSG:2871"
    assert HdfBase.get_projection(hdf_path) == "EPSG:2871"


@pytest.mark.synthetic_hdf_layout
def test_get_projection_does_not_label_conflicting_evidence(tmp_path, examples):
    from ras_commander import HdfBase

    shutil.copy(examples["Davis"] / "GIS" / "2871.prj", tmp_path / "davis.prj")
    (tmp_path / "Model.rasmap").write_text(
        '<RASMapper><RASProjectionFilename Filename=".\\davis.prj" /></RASMapper>',
        encoding="utf-8")
    hdf_path = tmp_path / "Model.g01.hdf"
    with h5py.File(hdf_path, "w") as hdf_file:
        hdf_file.attrs["Projection"] = (
            examples["BaldEagleCrkMulti2D"] / "Terrain" / "Projection.prj").read_text()

    assert _resolve(hdf_path).status == CRS_CONFLICT
    assert HdfBase.get_projection(hdf_path) is None


def test_davis_pipes_are_labeled_with_project_crs_not_wgs84(examples):
    from ras_commander.hdf.HdfPipe import HdfPipe

    hdf_path = examples["Davis"] / "DavisStormSystem.g02.hdf"
    conduits = HdfPipe.get_pipe_conduits(hdf_path)
    nodes = HdfPipe.get_pipe_nodes(hdf_path)

    assert len(conduits) == 132 and len(nodes) == 133
    # Stored coordinates are State Plane ftUS (x ~ 6.63e6); labeling never transforms.
    assert conduits.total_bounds[0] > 6.6e6
    assert conduits.crs.to_epsg() == 2871
    assert nodes.crs.to_epsg() == 2871


def test_rasmap_selection_keeps_dotted_project_name(tmp_path):
    for name in ('Model.rasmap', 'Model.v2.rasmap'):
        (tmp_path / name).write_text('<RASMapper />', encoding='utf-8')
    assert HdfUtils._select_rasmap(tmp_path / 'Model.v2.g01.hdf').name == 'Model.v2.rasmap'


def test_multiple_unmatched_rasmaps_do_not_guess(tmp_path):
    for name in ('Other.rasmap', 'Foreign.rasmap'):
        (tmp_path / name).write_text('<RASMapper />', encoding='utf-8')
    hdf = _hdf_without_projection(tmp_path / 'Model.g01.hdf')
    evidence = HdfUtils.collect_hdf_crs_evidence(hdf)
    assert _resolve(hdf).status == CRS_MISSING
    assert any(e.source == 'rasmap' and 'Ambiguous' in (e.detail or '') for e in evidence)


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize('suffix', ['.hdf', '.h5', '.hdf5'])
def test_scalar_array_projection_metadata_is_supported(tmp_path, suffix):
    path = tmp_path / ('projection' + suffix)
    wkt = pyproj.CRS.from_epsg(2271).to_wkt()
    with h5py.File(path, 'w') as f:
        f.attrs['Projection'] = np.array([wkt], dtype=h5py.string_dtype())
    evidence = HdfUtils.read_crs_evidence(path)
    assert evidence.status == 'found'
    assert HdfUtils.crs_equivalent(evidence.wkt, wkt)


@pytest.mark.synthetic_hdf_layout
def test_multiple_projection_attributes_do_not_choose_first(tmp_path):
    path = tmp_path / 'ambiguous.hdf'
    with h5py.File(path, 'w') as f:
        f.attrs['Projection'] = np.array(['EPSG:2271', 'EPSG:2871'], dtype=h5py.string_dtype())
    evidence = HdfUtils.read_crs_evidence(path)
    assert evidence.status == 'invalid'
    assert evidence.wkt is None
