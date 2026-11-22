"""1D storage areas with leftover 2D point data are not 2D flow areas.

BaldEagleCrkMulti2D g13 has a 1D storage area, ``Reservoir Pool``
(``Storage Area Is2D=0``), that still carries point-generation data and 1,066
computation points from an earlier 2D definition. HEC-RAS never writes it to
``Geometry/2D Flow Areas``. GeomMesh read it as a 2D area and reported
"Reservoir Pool: missing from compiled HDF", so the pre-mesh audit stopped even
after HEC-RAS had rebuilt the geometry HDF.
"""

from pathlib import Path

import pytest

from ras_commander import RasExamples, RasPrj, init_ras_project
from ras_commander.geom import GeomMesh
from ras_commander.geom.GeomMesh import (
    _mesh_hdf_consistency_issues,
    _read_cell_size_from_text,
    _read_mesh_metadata_from_text,
)


@pytest.fixture
def bald_eagle(tmp_path):
    project = Path(RasExamples.extract_project("BaldEagleCrkMulti2D", output_path=tmp_path))
    return project, project / "BaldEagleDamBrk.g13"


def test_real_1d_storage_area_with_points_is_not_a_2d_area(bald_eagle):
    _, geom = bald_eagle
    text = geom.read_text(encoding="utf-8", errors="replace")
    assert "Storage Area=Reservoir Pool" in text and "Storage Area Is2D=0" in text
    assert list(_read_mesh_metadata_from_text(geom)) == ["BaldEagleCr"]
    assert _mesh_hdf_consistency_issues(geom, Path(str(geom) + ".hdf")) == []


def test_real_audit_reaches_containment_verdict(bald_eagle):
    project, _ = bald_eagle
    ras = init_ras_project(project, "7.0.1", ras_object=RasPrj())
    result = GeomMesh.audit_domain_containment("13", ras_object=ras)
    # The audit now runs; its verdict is the containment policy, not a stale HDF.
    assert all("missing from compiled HDF" not in str(v) for v in result.violations)


def _text(tmp_path, blocks):
    path = tmp_path / "Synthetic.g01"
    path.write_text("Geom Title=Synthetic\n" + "".join(blocks), encoding="utf-8")
    return path


def _block(name, is2d, points=4, spacing=100):
    lines = [f"Storage Area={name:<16},0,0\n"]
    if is2d is not None:
        lines.append(f"Storage Area Is2D={is2d}\n")
    lines += [
        f"Storage Area Point Generation Data=,,{spacing},{spacing}\n",
        f"Storage Area 2D Points= {points}\n",
    ]
    return "".join(lines)


def test_index_and_cell_size_skip_preceding_1d_area(tmp_path):
    path = _text(tmp_path, [_block("Pond", 0, spacing=500), _block("Main", -1, spacing=50)])
    assert list(_read_mesh_metadata_from_text(path)) == ["Main"]
    assert _read_cell_size_from_text(path, mesh_index=0) == 50.0
    assert _read_cell_size_from_text(path, mesh_name="Pond") is None


def test_block_without_is2d_record_keeps_previous_behavior(tmp_path):
    path = _text(tmp_path, [_block("Legacy", None)])
    assert list(_read_mesh_metadata_from_text(path)) == ["Legacy"]
