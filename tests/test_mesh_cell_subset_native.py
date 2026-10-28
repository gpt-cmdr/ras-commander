"""Opt-in exact-subset qualification through the installed HEC-RAS 6.6 runtime.

Set RAS_EXACT_SUBSET_NATIVE_CASE to a local JSON case with project_directory,
project_relative, geometry_relative, source_geometry_hdf, parent_cell_ids,
mesh_name and plan_number. The project contains the prepared child text/HDF
pair, resolved terrain/classification sidecars and referencing plan/unsteady.
The entire project is copied before mutation; external source geometry stays
read-only. Private model bytes and case paths are never stored in this repo.
"""

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest


def _owned_file(root, value):
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Native case file must be inside the copied project")
    return path


@pytest.mark.integration
@pytest.mark.real_ras
@pytest.mark.destructive_copy
def test_exact_subset_survives_native_geometry_and_event_completion(tmp_path):
    if os.name != "nt":
        pytest.skip("Native exact-subset qualification requires Windows or Wine")
    case_path = os.environ.get("RAS_EXACT_SUBSET_NATIVE_CASE")
    if not case_path:
        pytest.skip("Set RAS_EXACT_SUBSET_NATIVE_CASE to an owned real-project case")
    from ras_commander.RasPrj import get_ras_exe

    executable = Path(get_ras_exe("6.6"))
    if not executable.is_file():
        pytest.skip("HEC-RAS 6.6 is not installed")
    if "clr" not in sys.modules and importlib.util.find_spec("clr") is None:
        pytest.skip("Native exact-subset qualification requires pythonnet")
    import h5py

    from ras_commander import RasPlan, RasPreprocess, RasPrj, init_ras_project
    from ras_commander.geom import GeomMesh, GeomPreprocessor

    case = json.loads(Path(case_path).read_text(encoding="utf-8"))
    source = Path(case["source_geometry_hdf"])
    original_source = source.stat()
    project = tmp_path / "model"
    shutil.copytree(Path(case["project_directory"]), project)
    project_file = _owned_file(project, case["project_relative"])
    geometry_file = _owned_file(project, case["geometry_relative"])
    _owned_file(project, str(geometry_file) + ".hdf")
    ras = init_ras_project(
        project_file,
        executable,
        ras_object=RasPrj(),
        load_results_summary=False,
        hide_intro=True,
    )
    plan_path = _owned_file(
        project, RasPlan.get_plan_path(case["plan_number"], ras_object=ras)
    )
    rows = ras.plan_df[
        ras.plan_df.plan_number.astype(str).str.zfill(2)
        == str(case["plan_number"]).zfill(2)
    ]
    assert len(rows) == 1
    row = rows.iloc[0]
    assert (
        _owned_file(
            project, RasPlan.get_geom_path(str(row.geometry_number), ras_object=ras)
        )
        == geometry_file
    )
    _owned_file(
        project, RasPlan.get_unsteady_path(str(row.unsteady_number), ras_object=ras)
    )
    plan = GeomMesh.plan_cell_subset(
        source,
        geometry_file,
        case["parent_cell_ids"],
        case["mesh_name"],
        ras_object=ras,
    )
    applied = GeomMesh.apply_cell_subset(plan, ras_object=ras, timeout=1800)
    assert applied.ok
    geometry = GeomPreprocessor.run_geometry_preprocessor(
        case["plan_number"],
        ras_object=ras,
        max_wait=1800,
        require_complete_products=True,
        force=True,
        clear_geompre=True,
    )
    assert geometry.success, geometry.error
    assert GeomMesh.validate_cell_subset(plan, ras_object=ras)["topology_exact"]
    event = RasPreprocess.preprocess_plan(
        case["plan_number"],
        ras_object=ras,
        max_wait=1800,
        clear_existing=True,
        fix_line_endings=True,
    )
    assert event.success, event.error
    # Event preprocessing is another native phase: verify the geometry again.
    evidence = GeomMesh.validate_cell_subset(plan, ras_object=ras)
    assert evidence["physical_cells"] == len(case["parent_cell_ids"])
    tmp_hdf = plan_path.with_suffix(plan_path.suffix + ".tmp.hdf")
    with h5py.File(tmp_hdf) as hdf:
        complete = hdf["Event Conditions"].attrs["Completed Successfully"]
        if isinstance(complete, bytes):
            complete = complete.decode()
        assert str(complete).casefold() == "true"
    assert source.stat().st_size == original_source.st_size
    assert source.stat().st_mtime_ns == original_source.st_mtime_ns


@pytest.mark.parametrize("relative", [True, False])
def test_native_case_paths_cannot_escape_copy(tmp_path, relative):
    project = tmp_path / "model"
    project.mkdir()
    outside = tmp_path / "outside.g02"
    outside.touch()
    with pytest.raises(ValueError, match="inside the copied project"):
        _owned_file(project, "../outside.g02" if relative else outside)
