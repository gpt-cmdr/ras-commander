"""Opt-in HEC-RAS 6.6 compiled read-back on disposable public examples.

Run with RAS_COMMANDER_RUN_HECRAS_INTEGRATION=1. Set
RAS_COMMANDER_FIXED_WIDTH_EVIDENCE_DIRECTORY to retain the staged projects
and evidence outside pytest's temporary directory.
"""

import hashlib
import json
import os
import shutil
from dataclasses import asdict
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import (
    RasExamples,
    RasPreprocess,
    RasPrj,
    RasTcu,
    init_ras_project,
)
from ras_commander.geom import GeomStorage
from ras_commander.hdf import HdfBase, HdfStorageArea
from ras_commander.usgs.boundary_generation import BoundaryGenerator

pytestmark = [
    pytest.mark.real_ras,
    pytest.mark.destructive_copy,
    pytest.mark.skipif(
        os.environ.get("RAS_COMMANDER_RUN_HECRAS_INTEGRATION") != "1",
        reason="Opt-in native HEC-RAS 6.6 fixed-width read-back",
    ),
]


def _hash_tree(folder):
    return {
        str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def _stage(tmp_path, example):
    root = (
        Path(os.environ.get("RAS_COMMANDER_FIXED_WIDTH_EVIDENCE_DIRECTORY", tmp_path))
        / example
    )
    root.mkdir(parents=True, exist_ok=False)
    source = RasExamples.extract_project(example, output_path=root / "source")
    hashes = _hash_tree(source)
    child = root / "child"
    shutil.copytree(source, child)
    project = RasPrj()
    init_ras_project(child, "6.6", ras_object=project, hide_intro=True)
    tcu = RasTcu.status(ras_object=project)
    evidence = {
        "example": example,
        "source_sha256_before": hashes,
        "tcu_before": asdict(tcu),
    }
    if not tcu.accepted:
        tcu = RasTcu.accept(ras_object=project)
        evidence["tcu_acceptance_method"] = "RasTcu.accept API registry acceptance"
    assert tcu.accepted
    evidence["tcu_after"] = asdict(tcu)
    evidence["runtime"] = str(project.ras_exe_path)
    return root, source, project, evidence


def _compile(project, plan_number, evidence):
    result = RasPreprocess.preprocess_plan(
        plan_number, ras_object=project, max_wait=300
    )
    evidence["preprocess"] = asdict(result)
    assert result.success, result.error
    assert result.tmp_hdf_path and result.tmp_hdf_path.exists()
    evidence["compiled_sha256"] = hashlib.sha256(
        result.tmp_hdf_path.read_bytes()
    ).hexdigest()
    return result.tmp_hdf_path


def _finish(root, source, evidence):
    evidence["source_sha256_after"] = _hash_tree(source)
    evidence["source_unchanged"] = (
        evidence["source_sha256_before"] == evidence["source_sha256_after"]
    )
    assert evidence["source_unchanged"]
    (root / "evidence.json").write_text(
        json.dumps(evidence, indent=2, default=str), encoding="utf-8"
    )


def test_native_geometry_elevation_volume(tmp_path):
    root, source, project, evidence = _stage(tmp_path, "BaldEagleCrkMulti2D")
    plan_number = "15"
    plan = project.plan_df.loc[project.plan_df.plan_number == plan_number].iloc[0]
    geom = Path(
        project.geom_df.loc[
            project.geom_df.geom_number == plan["Geom File"], "full_path"
        ].iloc[0]
    )
    original = GeomStorage.get_elevation_volume(geom, "255")
    assert len(original) == 12
    volumes = [i * 10000.0 for i in range(10)] + [108765.38, 163148.07725]
    expected = [i * 10000.0 for i in range(10)] + [108765.4, 163148.1]
    GeomStorage.set_elevation_volume(geom, "255", original.Elevation.tolist(), volumes)
    compiled = _compile(project, plan_number, evidence)
    curve = HdfStorageArea.get_volume_elevation_curve(compiled, "255")
    np.testing.assert_allclose(curve.elevation, original.Elevation, rtol=0, atol=0.01)
    np.testing.assert_allclose(curve.volume, expected, rtol=0, atol=0.02)
    evidence.update(
        plan_number=plan_number,
        storage_name="255",
        input_volumes_acre_feet=volumes,
        expected_volumes_acre_feet=expected,
        compiled_curve=curve.to_dict(orient="records"),
    )
    _finish(root, source, evidence)


def test_native_usgs_generated_hydrograph(tmp_path):
    root, source, project, evidence = _stage(tmp_path, "Muncie")
    plan_number = "01"
    plan = project.plan_df.loc[project.plan_df.plan_number == plan_number].iloc[0]
    unsteady = Path(
        project.unsteady_df.loc[
            project.unsteady_df.unsteady_number == plan.unsteady_number, "full_path"
        ].iloc[0]
    )
    location = next(
        line.split("=", 1)[1].strip()
        for line in unsteady.read_text().splitlines()
        if line.startswith("Boundary Location=")
    )
    values = [108765.38, 163148.07725] * 32 + [108765.38]
    table = BoundaryGenerator.generate_flow_hydrograph_table(values)
    BoundaryGenerator.update_boundary_hydrograph(unsteady, location, table)
    compiled = _compile(project, plan_number, evidence)
    HdfBase.get_dataset_info(compiled, "Event Conditions")
    # The focused read-back below deliberately reads the engine-authored
    # event-condition input, rather than re-reading the source text table.
    name = (
        "Event Conditions/Unsteady/Boundary Conditions/Flow Hydrographs/"
        "River: White  Reach: Muncie  RS: 15696.24"
    )
    with h5py.File(compiled, "r") as hdf:
        data = hdf[name][()]
    # HEC-RAS compiles only the selected plan's 24-hour window (25 hourly
    # points), not all 65 ordinates in the authored source hydrograph.
    assert data.shape == (25, 2)
    np.testing.assert_allclose(data[:, 0], np.arange(25) / 24, rtol=0, atol=1e-7)
    expected = np.asarray([108765.4, 163148.1] * 12 + [108765.4])
    np.testing.assert_allclose(data[:, 1], expected, rtol=0, atol=0.02)
    column = 1
    ordinates = data[:, column].tolist()
    evidence.update(
        plan_number=plan_number,
        generator="BoundaryGenerator.generate_flow_hydrograph_table",
        input_flow_cfs=values,
        expected_flow_cfs=expected.tolist(),
        compiled_dataset=name,
        compiled_column=column,
        compiled_flow_cfs=ordinates,
    )
    _finish(root, source, evidence)
