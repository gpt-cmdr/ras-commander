"""Persisted spacing contract for native child-mesh acceptance."""
import pytest
from ras_commander.geom.GeomStorage import GeomStorage


def geometry(tmp_path, raw):
    path = tmp_path / "spacing.g01"
    path.write_text(
        "Storage Area=AREA,0,0\nStorage Area Is2D=-1\n"
        f"Storage Area Point Generation Data={raw}\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("raw", ["0,0,200,100", ",,200.000000,100.000000"])
def test_spacing_reads_anisotropic_values_without_mutation(tmp_path, raw):
    path = geometry(tmp_path, raw)
    before = path.read_bytes()
    assert GeomStorage.get_2d_flow_area_cell_spacing(path, "AREA") == (200.0, 100.0)
    assert path.read_bytes() == before


@pytest.mark.parametrize("raw", [",,0,200", ",,200,-1", ",,nan,200", ",,200,inf", ",,abc,200", ",,200"])
def test_spacing_rejects_invalid_values(tmp_path, raw):
    with pytest.raises(ValueError):
        GeomStorage.get_2d_flow_area_cell_spacing(geometry(tmp_path, raw), "AREA")


def test_spacing_rejects_missing_or_duplicate_area(tmp_path):
    path = geometry(tmp_path, ",,200,200")
    with pytest.raises(ValueError, match="unavailable"):
        GeomStorage.get_2d_flow_area_cell_spacing(path, "MISSING")
    path.write_text(path.read_text() * 2)
    with pytest.raises(ValueError, match="unavailable"):
        GeomStorage.get_2d_flow_area_cell_spacing(path, "AREA")
