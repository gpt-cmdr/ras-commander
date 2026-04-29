import sys
import types
from pathlib import Path

import numpy as np

county_module = types.ModuleType("ras_commander.sources.county")
county_module.M3Model = object
sys.modules.setdefault("ras_commander.sources.county", county_module)

from ras_commander.sources.federal.ebfe_models import RasEbfeModels


def _fmt(value: float) -> str:
    return f"{value:<16.7f}"[:16]


def _write_ma03_geometry(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    points = [
        (3087000.0, 13615000.0),
        (3087200.0, 13615200.0),
        (3087941.383, 13615809.857),
        (3087928.130, 13615683.945),
    ]
    coord_line = "".join(_fmt(value) for point in points for value in point)
    path.write_text(
        "\n".join(
            [
                "Geom Title=MA_3",
                "Storage Area=MA_3_2DArea     ,3087000,13615000",
                "Storage Area Point Generation Data=0,0,200,200",
                "Storage Area 2D Points= 4 ",
                coord_line,
                "Storage Area 2D PointsPerimeterTime=10Nov2022 16:06:22",
                "Storage Area Mannings=0.06",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_lower_brazos_ma03_mesh_seed_patch_is_idempotent(tmp_path):
    ras_root = tmp_path / "RAS Model"
    geom_path = ras_root / "LB_MA03" / "MA_3.g02"
    _write_ma03_geometry(geom_path)

    first = RasEbfeModels._apply_lower_brazos_ma03_mesh_seed_patch(ras_root)

    assert first["status"] == "applied"
    assert first["old_seed_count"] == 4
    assert first["new_seed_count"] == 8
    assert first["points_added"] == 4

    points = RasEbfeModels._parse_storage_area_seed_points(
        geom_path,
        "MA_3_2DArea",
    )
    expected_patch = np.array(RasEbfeModels._LOWER_BRAZOS_MA03_MESH_PATCH_POINTS)
    assert len(points) == 8
    assert np.allclose(points[-4:], expected_patch, atol=1e-6)
    assert "Storage Area 2D Points= 8" in geom_path.read_text(encoding="utf-8")

    second = RasEbfeModels._apply_lower_brazos_ma03_mesh_seed_patch(ras_root)

    assert second["status"] == "already_applied"
    assert second["points_added"] == 0
    assert second["new_seed_count"] == 8
