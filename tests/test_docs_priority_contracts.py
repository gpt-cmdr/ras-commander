"""Focused R01–R04 snippet contracts; optional retained-data checks never run RAS.

Set RAS_DOCS_1D_HDF and RAS_DOCS_2D_HDF to retained unsteady producer results,
and RAS_DOCS_GEOM/RAS_DOCS_PLAN to real text files for copy-only writer checks.
An optional RAS_DOCS_LEGACY_2D_HDF exercises the same readers on a 5.x result.
"""

import ast
import inspect
import os
from pathlib import Path
import re
import shutil
import textwrap

import numpy as np
import pandas as pd
import pytest

import ras_commander as ras
from ras_commander.callbacks import ExecutionCallback


ROOT = Path(__file__).resolve().parents[1]
PAGES = [
    "docs/getting-started/quickstart.md",
    "docs/user-guide/plan-execution.md",
    "docs/user-guide/workflows-and-patterns.md",
    "docs/user-guide/hdf-data-extraction.md",
    "docs/user-guide/geometry-operations.md",
    "docs/user-guide/atlas14-precipitation.md",
    "docs/api/core.md",
    "docs/api/hdf.md",
]
NAMESPACES = {
    "RasPlan", "RasCmdr", "HdfMesh", "HdfResultsMesh", "HdfResultsXsec",
    "HdfStruc", "GeomLandCover",
}


def python_blocks(page):
    return [textwrap.dedent(block) for block in re.findall(
        r"```python\n(.*?)```", (ROOT / page).read_text(encoding="utf-8"), re.S
    )]


@pytest.mark.parametrize("page", PAGES)
def test_documented_core_calls_bind_public_signatures(page):
    """Resolve real exported members (including decorators/aliases), without compute."""
    for block in python_blocks(page):
        for node in ast.walk(ast.parse(block)):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in NAMESPACES):
                continue
            # These pages use explicit arguments; do not claim dynamic-call coverage.
            if any(isinstance(arg, ast.Starred) for arg in node.args) or any(
                kw.arg is None for kw in node.keywords
            ):
                continue
            method = getattr(getattr(ras, node.func.value.id), node.func.attr)
            try:
                inspect.signature(method).bind(
                    *[None for _ in node.args], **{kw.arg: None for kw in node.keywords}
                )
            except TypeError as exc:
                pytest.fail(f"{page}: {ast.unparse(node)}: {exc}")


def test_documented_callbacks_accept_protocol_arguments(capsys):
    """Instantiate the actual example classes without executing surrounding plans."""
    arguments = {
        "on_prep_start": ("01",),
        "on_prep_complete": ("01",),
        "on_exec_start": ("01", "command supplied by RasCmdr"),
        "on_exec_message": ("01", "WARNING: review this message"),
        "on_exec_complete": ("01", True, 1.25),
        "on_verify_result": ("01", True),
    }
    found = set()
    for block in python_blocks("docs/user-guide/plan-execution.md"):
        for node in ast.parse(block).body:
            if isinstance(node, ast.ClassDef) and node.name in {"MyCallback", "ErrorDetectionCallback"}:
                namespace = {"ExecutionCallback": ExecutionCallback}
                exec(compile(ast.Module(body=[node], type_ignores=[]), "<docs callback>", "exec"), namespace)
                instance = namespace[node.name]()
                for method in node.body:
                    if isinstance(method, ast.FunctionDef) and method.name.startswith("on_"):
                        assert method.name in arguments
                        inspect.signature(getattr(ExecutionCallback, method.name)).bind(
                            instance, *arguments[method.name]
                        )
                        getattr(instance, method.name)(*arguments[method.name])
                found.add(node.name)
    assert found == {"MyCallback", "ErrorDetectionCallback"}
    assert "WARNING" in capsys.readouterr().out


def test_reference_member_lists_resolve():
    """Handwritten summaries and the RasPlan generator list use exported methods."""
    hdf_page = (ROOT / "docs/api/hdf.md").read_text(encoding="utf-8")
    for name in ["HdfBase", "HdfPlan", "HdfMesh", "HdfResultsMesh", "HdfResultsXsec", "HdfStruc"]:
        section = hdf_page.split(f"### {name}\n", 1)[1].split("\n##", 1)[0]
        for method in re.findall(r"^- `(\w+)\(", section, re.M):
            assert callable(getattr(getattr(ras, name), method)), f"{name}.{method}"
    core_page = (ROOT / "docs/api/core.md").read_text(encoding="utf-8")
    section = core_page.split("::: ras_commander.RasPlan\n", 1)[1].split("\n###", 1)[0]
    for method in re.findall(r"^        - (\w+)$", section, re.M):
        assert callable(getattr(ras.RasPlan, method)), method


def retained_path(variable):
    value = os.environ.get(variable)
    if not value:
        pytest.skip(f"Set {variable} to a retained real artifact")
    path = Path(value)
    assert path.is_file(), path
    return path


def test_retained_1d_dataset_selection():
    path = retained_path("RAS_DOCS_1D_HDF")
    before = path.stat()
    result = ras.HdfResultsXsec.get_xsec_timeseries(path)
    water_surface = result["Water_Surface"]
    assert water_surface.dims == ("time", "cross_section")
    station = result["cross_section"][0].item()
    assert water_surface.sel(cross_section=station).dims == ("time",)
    assert np.isfinite(water_surface.values).any()
    assert (path.stat().st_size, path.stat().st_mtime_ns) == (before.st_size, before.st_mtime_ns)


@pytest.mark.parametrize("variable", ["RAS_DOCS_2D_HDF", "RAS_DOCS_LEGACY_2D_HDF"])
def test_retained_2d_result_shapes_and_selections(variable):
    path = retained_path(variable)
    before = path.stat()
    mesh = ras.HdfMesh.get_mesh_area_names(path)[0]
    maximum = ras.HdfResultsMesh.get_mesh_max_ws(path)
    assert not maximum.empty
    assert {"mesh_name", "cell_id", "maximum_water_surface", "geometry"} <= set(maximum.columns)
    single = ras.HdfResultsMesh.get_mesh_timeseries(path, mesh, "Water Surface", truncate=False)
    meshes = ras.HdfResultsMesh.get_mesh_cells_timeseries(path, mesh_names=mesh, var="Water Surface")
    selected = meshes[mesh]["Water Surface"]
    assert selected.dims == single.dims == ("time", "cell_id")
    np.testing.assert_allclose(selected.values, single.values, equal_nan=True)
    assert selected.isel(cell_id=slice(0, 4)).sizes["cell_id"] <= 4
    faces = ras.HdfResultsMesh.get_mesh_faces_timeseries(path, mesh, truncate=False)
    assert "face_velocity" in faces, "Retained fixture must contain face-velocity output"
    assert faces["face_velocity"].dims == ("time", "face_id")
    assert faces["face_velocity"].isel(face_id=slice(0, 3)).sizes["face_id"] <= 3
    perimeters = ras.HdfMesh.get_mesh_areas(path)
    assert mesh in perimeters["mesh_name"].values
    assert isinstance(ras.HdfStruc.list_sa2d_connections(path), list)
    assert (path.stat().st_size, path.stat().st_mtime_ns) == (before.st_size, before.st_mtime_ns)


def test_mannings_text_roundtrip_on_real_copy(tmp_path):
    source = retained_path("RAS_DOCS_GEOM")
    original = source.read_bytes()
    path = tmp_path / source.name
    shutil.copy2(source, path)
    base = ras.GeomLandCover.get_base_mannings_n(path)
    assert not base.empty, "Choose a real geometry with an existing base table"
    regional = ras.GeomLandCover.get_region_mannings_n(path)
    updated = base.copy()
    updated["Base Mannings n Value"] *= 1.10
    assert ras.GeomLandCover.set_base_mannings_n(path, updated)
    pd.testing.assert_frame_equal(ras.GeomLandCover.get_base_mannings_n(path), updated)
    pd.testing.assert_frame_equal(ras.GeomLandCover.get_region_mannings_n(path), regional)
    assert source.read_bytes() == original


def test_plan_interval_and_description_on_real_copy(tmp_path):
    source = retained_path("RAS_DOCS_PLAN")
    original = source.read_bytes()
    project_copy = tmp_path / "project"
    shutil.copytree(source.parent, project_copy)
    project = ras.init_ras_project(
        project_copy, ras_object="new", hide_intro=True, load_results_summary=False
    )
    path = project_copy / source.name
    plan_number = source.suffix[2:]
    ras.RasPlan.update_plan_intervals(plan_number, computation_interval="5MIN", ras_object=project)
    assert ras.RasPlan.update_plan_description(
        plan_number, "Documentation contract readback", ras_object=project
    )
    text = path.read_text(encoding="utf-8")
    assert "Computation Interval=5MIN" in text
    assert "Documentation contract readback" in text
    assert source.read_bytes() == original
