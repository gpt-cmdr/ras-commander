"""Public-example coverage for coarse grids with finer near-boundary breaklines."""

import json
import os
import platform
from pathlib import Path

import pytest

from ras_commander import RasExamples
from ras_commander.geom import GeomMesh, GeomPreprocessor, GeomStorage


def _prepare_chippewa(tmp_path):
    from shapely.geometry import LineString

    project = RasExamples.extract_project(
        "Chippewa_2D", output_path=tmp_path, suffix="mesh_handover"
    )
    geom_path = project / "Chippewa_2D.g01"
    areas = GeomStorage.get_storage_area_polygons(geom_path, exclude_2d=False)
    area = areas.loc[areas["is_2d"]].iloc[0]
    base_spacing = 200.0
    # Keep the authored line inside generate()'s one-base-cell containment gate.
    inner = area.geometry.buffer(-1.25 * base_spacing)
    assert inner.geom_type == "Polygon" and not inner.is_empty
    coords = list(inner.exterior.coords)
    segment = max(
        (LineString([a, b]) for a, b in zip(coords, coords[1:])),
        key=lambda line: line.length,
    )
    line = LineString([
        segment.interpolate(.2, normalized=True),
        segment.interpolate(.8, normalized=True),
    ])
    assert line.length > 2 * base_spacing
    assert area.geometry.buffer(-base_spacing).covers(line)
    GeomStorage.replace_breaklines(
        geom_path, area["Name"], [{
            "name": "Fine near-boundary regression",
            "coords": list(line.coords),
            "cell_size_near": base_spacing / 4,
            "cell_size_far": base_spacing / 4,
            "near_repeats": 1,
            "protection_radius": 1,
        }],
    )
    return project, geom_path, area["Name"], base_spacing


def test_public_example_breakline_fixture(tmp_path):
    """Exercise real geometry parsing and breakline authoring without the engine."""
    _, geom_path, _, base_spacing = _prepare_chippewa(tmp_path)
    spacing = GeomMesh.get_breakline_spacing(geom_path)
    assert len(spacing) == 1
    assert spacing[0][2] == base_spacing / 4
    assert spacing[0][3] == base_spacing / 4


@pytest.mark.integration
@pytest.mark.destructive_copy
@pytest.mark.slow
@pytest.mark.skipif(
    platform.system() != "Windows"
    or os.environ.get("RAS_COMMANDER_RUN_HECRAS_INTEGRATION") != "1",
    reason="Requires Windows, HEC-RAS and explicit integration opt-in",
)
@pytest.mark.parametrize("ratio", [.0025, .05, .1])
def test_fine_breaklines_pass_native_preprocessing(tmp_path, ratio):
    """Validate each authored ratio through the real preprocessor, not a replica."""
    from ras_commander import init_ras_project
    from ras_commander.hdf import HdfMesh

    hecras_dir = Path(os.environ.get(
        "RAS_COMMANDER_HECRAS_DIR", r"C:\Program Files (x86)\HEC\HEC-RAS\6.6"
    ))
    if not (hecras_dir / "Ras.exe").is_file():
        pytest.skip("Configured HEC-RAS installation is unavailable")
    project, geom_path, mesh_name, spacing = _prepare_chippewa(tmp_path)
    ras = init_ras_project(project, hecras_dir / "Ras.exe", hide_intro=True, accept_tcu=True)
    result = GeomMesh.generate(
        geom_path, mesh_name=mesh_name, cell_size=spacing,
        min_face_length_ratio=ratio, hecras_dir=hecras_dir,
        ras_object=ras, recompile_via_rasexe=True,
    )
    assert result.ok, result.error_message
    plan_number = ras.plan_df.loc[ras.plan_df["geometry_number"] == "01", "plan_number"].iloc[0]
    receipt = GeomPreprocessor.run_geometry_preprocessor(
        plan_number, ras_object=ras, force=True, clear_geompre=True, max_wait=600,
    )
    (tmp_path / "native-preprocess.json").write_text(
        json.dumps(vars(receipt), default=str, indent=2), encoding="utf-8"
    )
    assert receipt, repr(receipt)
    assert receipt.error_count == 0
    topology = HdfMesh.get_mesh_sloped_topology(Path(result.geom_hdf_path), mesh_name=mesh_name)
    counts = topology["cell_face_info"][:, 1]
    assert len(counts) > 0
    assert counts.max() <= 8
