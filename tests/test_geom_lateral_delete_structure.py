"""GeomLateral.delete_lateral_structure on real RasExamples projects."""

import os
import platform
from pathlib import Path

import pytest

from ras_commander import GeomLateral, RasExamples, RasPrj, init_ras_project
from ras_commander.geom import GeomCrossSection

HECRAS_INTEGRATION_ENV = "RAS_COMMANDER_RUN_HECRAS_INTEGRATION"


def _extract(name, tmp_path):
    return Path(RasExamples.extract_project(name, output_path=tmp_path))


def _nodes(geom_file):
    df = GeomCrossSection.get_cross_sections(geom_file)
    return [(row.River, row.Reach, str(row.RS), int(row.Type)) for row in df.itertuples()]


def _lines(path):
    return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()


def test_muncie_1d2d_lateral_removed_as_one_complete_block(tmp_path):
    project = _extract("Muncie", tmp_path)
    geom = project / "Muncie.g04"
    before = _lines(geom)
    nodes_before = _nodes(geom)
    plans_before = {p: p.read_bytes() for p in project.glob("Muncie.p0?")}
    start = before.index("Type RM Length L Ch R = 6 ,7300    ,,,")

    result = GeomLateral.delete_lateral_structure(geom, "White", "Muncie", 7300)

    after = _lines(geom)
    removed = result["removed_line_count"]
    # Exactly one contiguous slice is gone; every other line is unchanged.
    assert after == before[:start] + before[start + removed :]
    removed_block = before[start : start + removed]
    assert removed_block[-1] == ""
    assert any(line.startswith("Lateral Weir End=") and "2D Interior Area" in line
               for line in removed_block)
    assert not any(line.startswith("Lateral Weir") for line in after[start : start + 5])
    assert after[start].startswith("Type RM Length L Ch R = 1 ,7158.903")
    assert result["backup_path"].read_text(encoding="utf-8").splitlines() == before

    # Round trip: the edited geometry parses, keeps every other node in order,
    # and the remaining lateral structure is untouched.
    assert _nodes(geom) == [n for n in nodes_before if n[2] != "7300"]
    assert ("White", "Muncie", "13214", 6) in _nodes(geom)
    ras = init_ras_project(project, "7.0.1", ras_object=RasPrj())
    assert "04" in set(ras.geom_df["geom_number"])
    # Plans bound to g04 have no breach at RS 7300, so no plan was edited.
    assert result["removed_breach_blocks"] == []
    assert {p: p.read_bytes() for p in project.glob("Muncie.p0?")} == plans_before


def test_plan_breach_block_at_removed_lateral_is_removed(tmp_path):
    project = _extract("Muncie", tmp_path)
    ras = init_ras_project(project, "7.0.1", ras_object=RasPrj())
    p01, p04 = project / "Muncie.p01", project / "Muncie.p04"
    p04_before = p04.read_bytes()
    breach_lines = [line for line in _lines(p01) if line.startswith("Breach Loc=")]

    result = GeomLateral.delete_lateral_structure(
        project / "Muncie.g01", "White", "Muncie", "7300", ras_object=ras
    )

    assert [b["plan_file"].name for b in result["removed_breach_blocks"]] == ["Muncie.p01"]
    remaining = [line for line in _lines(p01) if line.startswith("Breach Loc=")]
    assert len(remaining) == len(breach_lines) - 1
    assert not any(",7300    ," in line for line in remaining)
    # The neighbouring breach blocks are intact and still parse.
    from ras_commander.RasBreach import RasBreach

    stations = [b.location.station for b in RasBreach._read_breach_blocks_internal(p01)]
    assert "7300" not in stations and "13214" in stations and "12300" in stations
    # p04 uses another geometry and is not edited.
    assert p04.read_bytes() == p04_before


def test_culvert_sub_blocks_are_removed_with_the_structure(tmp_path):
    project = _extract("Lateral Structure with Culverts", tmp_path)
    geom = next(project.glob("*.g01"))
    assert any(line.startswith("LW Culv=") for line in _lines(geom))

    GeomLateral.delete_lateral_structure(geom, "Beaver Creek", "Kentwood", "5.4")

    after = _lines(geom)
    assert not any(line.startswith(("LW ", "Lateral Weir")) for line in after)
    assert not any(n[2] == "5.4" for n in _nodes(geom))


def test_unsteady_gate_boundary_blocks_removal_without_writing(tmp_path):
    project = _extract("Lateral Strcuture with Gates", tmp_path)
    geom = next(project.glob("*.g01"))
    files = {p: p.read_bytes() for p in project.iterdir() if p.is_file()}

    with pytest.raises(ValueError, match="RasUnsteady.delete_boundary"):
        GeomLateral.delete_lateral_structure(geom, "Beaver Creek", "Kentwood", "5.4")

    assert {p: p.read_bytes() for p in project.iterdir() if p.is_file()} == files


def test_non_lateral_and_missing_stations_are_rejected(tmp_path):
    project = _extract("Muncie", tmp_path)
    geom = project / "Muncie.g04"
    before = geom.read_bytes()
    with pytest.raises(ValueError, match="type 1, not a lateral structure"):
        GeomLateral.delete_lateral_structure(geom, "White", "Muncie", "7158.903")
    with pytest.raises(ValueError, match=r"Lateral structures in this reach: \['13214', '7300'\]"):
        GeomLateral.delete_lateral_structure(geom, "White", "Muncie", "7301")
    with pytest.raises(ValueError, match="not found"):
        GeomLateral.delete_lateral_structure(geom, "White", "Other", "7300")
    assert geom.read_bytes() == before


def test_unrecognized_record_inside_block_is_not_deleted(tmp_path):
    project = _extract("Muncie", tmp_path)
    geom = project / "Muncie.g04"
    text = geom.read_text(encoding="utf-8")
    marker = "Lateral Weir Distance=175"
    geom.write_text(text.replace(marker, marker + "\nUnknown Record=1", 1), encoding="utf-8")
    before = geom.read_bytes()
    with pytest.raises(ValueError, match="unrecognized record"):
        GeomLateral.delete_lateral_structure(geom, "White", "Muncie", "7300")
    assert geom.read_bytes() == before


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.skipif(
    platform.system() != "Windows" or os.environ.get(HECRAS_INTEGRATION_ENV) != "1",
    reason="Requires Windows, HEC-RAS, and explicit opt-in integration execution",
)
def test_edited_muncie_geometry_preprocesses(tmp_path):
    import h5py

    from ras_commander.geom import GeomPreprocessor

    version = os.environ.get("RAS_COMMANDER_HECRAS_VERSION", "7.0.1")
    project = _extract("Muncie", tmp_path)
    GeomLateral.delete_lateral_structure(project / "Muncie.g04", "White", "Muncie", "7300")
    ras = init_ras_project(project, version, ras_object=RasPrj())
    result = GeomPreprocessor.run_geometry_preprocessor("04", ras_object=ras, max_wait=3600)
    assert result.success, result.error
    with h5py.File(project / "Muncie.g04.hdf", "r") as hdf:
        attrs = hdf["Geometry/Structures/Attributes"][()]
        stations = [bytes(a["RS"]).decode().strip() for a in attrs]
    assert stations == ["13214"]
