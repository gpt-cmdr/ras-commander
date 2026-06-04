"""
Tests for create_project_from_template: instantiate a new HEC-RAS project from
a bundled, terrain-stripped seed template.

Pure-Python (copy / rename / .rasmap rewrite / reprojection) — no HEC-RAS or
RasMapperLib required, so these run in headless CI.
"""

from __future__ import annotations

import pytest

from ras_commander import create_project_from_template
from ras_commander.RasPrj import AVAILABLE_TEMPLATE_VERSIONS


@pytest.mark.parametrize("version", AVAILABLE_TEMPLATE_VERSIONS)
def test_creates_renamed_components(tmp_path, version):
    prj = create_project_from_template(
        tmp_path / "proj", project_name="EtherHollow", version=version
    )
    assert prj.name == "EtherHollow.prj"
    names = {p.name for p in (tmp_path / "proj").iterdir()}
    assert {
        "EtherHollow.prj",
        "EtherHollow.g01",
        "EtherHollow.g01.hdf",
        "EtherHollow.rasmap",
    } <= names
    # no TEMPLATE.* leftovers
    assert not any(n.startswith("TEMPLATE") for n in names)


def test_rasmap_geometry_reference_rewritten(tmp_path):
    create_project_from_template(tmp_path / "p", project_name="Burn", version="7.0")
    rasmap = (tmp_path / "p" / "Burn.rasmap").read_text(encoding="utf-8")
    assert "Burn.g01.hdf" in rasmap
    assert "TEMPLATE.g01.hdf" not in rasmap


def test_project_title_rewritten(tmp_path):
    create_project_from_template(tmp_path / "p", project_name="Burn", version="7.0")
    prj_text = (tmp_path / "p" / "Burn.prj").read_text(encoding="utf-8")
    assert "Proj Title=Burn" in prj_text
    assert "Proj Title=TEMPLATE" not in prj_text


def test_reprojection_writes_target_crs(tmp_path):
    create_project_from_template(
        tmp_path / "p", project_name="Burn", version="7.0", target_crs="EPSG:2256"
    )
    wkt = (tmp_path / "p" / "Burn.projection.prj").read_text(encoding="utf-8")
    # EPSG:2256 is a US survey-foot State Plane CRS
    assert "Foot" in wkt or "FOOT" in wkt or "feet" in wkt.lower()


def test_default_projection_is_template_default(tmp_path):
    create_project_from_template(tmp_path / "p", project_name="Burn", version="7.0")
    wkt = (tmp_path / "p" / "Burn.projection.prj").read_text(encoding="utf-8")
    assert "Albers" in wkt  # template default EPSG:5070 (NAD83 CONUS Albers, meters)


def test_rejects_pre_66_version(tmp_path):
    with pytest.raises(ValueError):
        create_project_from_template(tmp_path / "p", version="6.3")


def test_overwrite_guard(tmp_path):
    create_project_from_template(tmp_path / "p", project_name="Burn", version="7.0")
    with pytest.raises(FileExistsError):
        create_project_from_template(tmp_path / "p", project_name="Burn", version="7.0")
    # overwrite=True succeeds
    create_project_from_template(
        tmp_path / "p", project_name="Burn", version="7.0", overwrite=True
    )
