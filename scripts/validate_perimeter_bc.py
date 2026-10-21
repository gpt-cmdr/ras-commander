"""Validate perimeter/BC replacement on a disposable Chippewa example clone.

Run with the repository's Python environment. Native compilation is opt-in:
  uv run python scripts/validate_perimeter_bc.py --output working/bc-check --native
For Wine, run this same script using the v8 image's Windows Python and --ras-exe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from dataclasses import asdict
from pathlib import Path

from ras_commander import (
    RasExamples,
    RasPreprocess,
    RasPrj,
    RasTcu,
    RasUtils,
    init_ras_project,
)
from ras_commander.geom import GeomBcLines
from ras_commander.hdf import HdfBndry, HdfMesh


def _hash_tree(folder):
    return {
        str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def _validate(output: Path, native: bool, ras_exe: str) -> dict:
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=False)
    source = RasExamples.extract_project("Chippewa_2D", output_path=output / "source")
    source_hashes = _hash_tree(source)
    clone = output / "child"
    shutil.copytree(source, clone)
    project = RasPrj()
    init_ras_project(clone, ras_exe, ras_object=project, hide_intro=True)
    plan_number = project.plan_df["plan_number"].iloc[0]
    geom_file = Path(project.geom_df["full_path"].iloc[0])
    geom_hdf = Path(str(geom_file) + ".hdf")
    flow_files = project.unsteady_df["full_path"].tolist()
    original = HdfBndry.get_bc_lines(geom_hdf)
    downstream = original.loc[original["Name"] == "Downstream"].iloc[0]
    area = downstream["SA-2D"]
    before = HdfMesh.get_mesh_perimeter_faces(geom_hdf, area)
    replacement = GeomBcLines.replace_bc_lines(
        geom_file,
        flow_files,
        area_2d=area,
        lines=[
            {
                "name": "CLB_OUTLET",
                "coordinates": list(downstream.geometry.coords),
                "bc_type": "Normal Depth",
                "friction_slope": 0.001,
            }
        ],
        ras_object=project,
    )
    evidence = {
        "source": str(source),
        "clone": str(clone),
        "plan_number": plan_number,
        "area_2d": area,
        "before_perimeter_faces": len(before),
        "before_assigned_faces": int(before.bc_line_id.notna().sum()),
        "replacement_rows": len(replacement),
        "native_requested": native,
        "source_sha256_before": source_hashes,
    }
    if native:
        tcu = RasTcu.status(ras_object=project)
        evidence["tcu_before"] = asdict(tcu)
        if not tcu.accepted:
            tcu = RasTcu.accept(ras_object=project)
            evidence["tcu_acceptance_method"] = "RasTcu.accept API registry acceptance"
            if not tcu.accepted:
                raise RuntimeError(f"Native terms acceptance unresolved: {tcu}")
        evidence["tcu_after"] = asdict(tcu)
        result = RasPreprocess.preprocess_plan(
            plan_number, ras_object=project, max_wait=300
        )
        evidence["preprocessing"] = asdict(result)
        if not result.success:
            (output / "evidence.json").write_text(
                json.dumps(evidence, default=str, indent=2)
            )
            raise RuntimeError(f"Native preprocessing failed: {result.error}")
        after = HdfMesh.get_mesh_perimeter_faces(geom_hdf, area)
        compiled_lines = HdfBndry.get_bc_lines(geom_hdf)
        compiled_names = set(
            compiled_lines.loc[compiled_lines["SA-2D"] == area, "Name"]
        )
        assert compiled_names == {"CLB_OUTLET"}, compiled_names
        native_names = set(after.bc_line_name.dropna())
        assert native_names == {"CLB_OUTLET"}, native_names
        assert after.bc_line_id.isna().any(), (
            "Child must deliberately retain unassigned faces"
        )
        assert not after.face_id.duplicated().any()
        assert set(before.face_id) == set(after.face_id), (
            "Unchanged mesh face identity drift"
        )
        evidence.update(
            after_perimeter_faces=len(after),
            after_assigned_faces=int(after.bc_line_id.notna().sum()),
            after_unassigned_faces=int(after.bc_line_id.isna().sum()),
            native_owner_names=sorted(native_names),
        )
        after.drop(columns="geometry").to_csv(
            output / "perimeter_faces.csv", index=False
        )
    else:
        evidence["native_skip_reason"] = "Native opt-in flag --native was not supplied"
    assert source_hashes == _hash_tree(source), "Source example changed"
    evidence["source_sha256_after"] = _hash_tree(source)
    evidence["source_unchanged"] = True
    evidence["elapsed_seconds"] = time.monotonic() - started
    (output / "evidence.json").write_text(json.dumps(evidence, default=str, indent=2))
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="New, short disposable workspace"
    )
    parser.add_argument("--native", action="store_true")
    parser.add_argument(
        "--ras-exe", default="6.6", help="HEC-RAS version or explicit executable path"
    )
    parser.add_argument(
        "--example-cache",
        type=Path,
        help="Writable cache containing Example_Projects_6_6.zip",
    )
    options = parser.parse_args()
    if options.example_cache:
        RasExamples._user_data_dir = RasUtils.safe_resolve(options.example_cache)
    _validate(RasUtils.safe_resolve(options.output), options.native, options.ras_exe)
