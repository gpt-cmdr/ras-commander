"""Opt-in stored-map qualification of a mapping-only plan HDF cell subset.

Set RAS_RESULTS_SUBSET_NATIVE_CASE to a local JSON case with parent_plan_hdf,
mesh_name, parent_cell_ids (a list, or a .npy path), terrain_hdf (a RAS Mapper
terrain covering the selected cells; its folder is copied and must hold
Projection.prj), output_rows and units ("US Customary" or "SI Units"). The parent and terrain stay read-only;
the child project is built under the pytest temporary folder. Private model
bytes and case paths are never stored in this repo.
"""

import hashlib
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pytest

RASMAP = """<?xml version='1.0' encoding='utf-8'?>
<RASMapper>
  <Version>2.0.0</Version>
  <RASProjectionFilename Filename=".\\Terrain\\Projection.prj" />
  <Results Checked="True" Expanded="True" />
  <Terrains Checked="True" Expanded="True">
    <Layer Name="Terrain" Type="TerrainLayer" Checked="True" Filename=".\\Terrain\\{terrain}">
      <ResampleMethod>near</ResampleMethod>
      <Surface On="True" />
    </Layer>
  </Terrains>
  <Units>{units}</Units>
  <RenderMode>horizontal</RenderMode>
</RASMapper>
"""


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _mapping_project(folder, child_hdf, terrain_hdf, units):
    """Minimal project: stub text files, one plan, the child plan HDF, terrain."""
    folder.mkdir()
    shutil.copytree(terrain_hdf.parent, folder / "Terrain")
    assert (folder / "Terrain" / "Projection.prj").is_file()
    english = "English Units\n" if units == "US Customary" else "SI Units\n"
    (folder / "Child.prj").write_text(
        "Proj Title=Child\nCurrent Plan=p01\n"
        + english
        + "Geom File=g01\nUnsteady File=u01\nPlan File=p01\n"
    )
    (folder / "Child.p01").write_text(
        "Plan Title=Child\nShort Identifier=child\n"
        "Simulation Date=01JAN2000,0000,02JAN2000,0000\n"
        "Geom File=g01\nFlow File=u01\n"
    )
    (folder / "Child.u01").write_text("Flow Title=Child\n")
    (folder / "Child.g01").write_text("Geom Title=Child\n")
    (folder / "Child.rasmap").write_text(
        RASMAP.format(units=units, terrain=terrain_hdf.name)
    )
    shutil.copy(child_hdf, folder / "Child.p01.hdf")
    return folder


@pytest.mark.integration
@pytest.mark.real_ras
def test_results_subset_survives_native_stored_map_generation(tmp_path):
    if os.name != "nt":
        pytest.skip("Native stored-map qualification requires Windows or Wine")
    case_path = os.environ.get("RAS_RESULTS_SUBSET_NATIVE_CASE")
    if not case_path:
        pytest.skip("Set RAS_RESULTS_SUBSET_NATIVE_CASE to a local plan HDF case")
    from ras_commander.RasPrj import get_ras_exe

    if not Path(get_ras_exe("6.6")).is_file():
        pytest.skip("HEC-RAS 6.6 is not installed")
    import h5py
    import rasterio

    from ras_commander import RasPrj, init_ras_project
    from ras_commander.hdf import HdfResultsMesh
    from ras_commander.RasProcess import RasProcess

    case = json.loads(Path(case_path).read_text(encoding="utf-8"))
    parent = Path(case["parent_plan_hdf"])
    ids = case["parent_cell_ids"]
    ids = np.load(ids) if isinstance(ids, str) else np.asarray(ids)
    parent_hash = _sha256(parent)
    child = tmp_path / "child.p01.hdf"
    sub = HdfResultsMesh.write_cell_subset(
        parent, child, ids, case["mesh_name"], output_rows=case["output_rows"]
    )
    assert _sha256(parent) == parent_hash
    project = _mapping_project(
        tmp_path / "model", child, Path(case["terrain_hdf"]), case["units"]
    )
    with h5py.File(child, "r") as hdf:
        stamps = [
            s.decode()
            for s in hdf[
                "Results/Unsteady/Output/Output Blocks/Base Output/"
                "Unsteady Time Series/Time Date Stamp"
            ][()]
        ]
    assert len(stamps) == len(sub.output_rows)
    ras = init_ras_project(
        project, "6.6", ras_object=RasPrj(), load_results_summary=False, hide_intro=True
    )
    for index, profile in enumerate([*stamps, "Max"]):
        maps = RasProcess.store_maps(
            "01",
            output_path=tmp_path / "maps" / str(index),
            profile=profile,
            wse=True,
            depth=True,
            velocity=profile == "Max",
            render_mode="horizontal",
            ras_object=ras,
            ras_version="6.6",
            timeout=3600,
        )
        for kind in ("wse", "depth"):
            assert len(maps[kind]) == 1, (profile, kind, maps)
            with rasterio.open(maps[kind][0]) as raster:
                assert (~raster.read(1, masked=True).mask).sum() > 0, (profile, kind)
