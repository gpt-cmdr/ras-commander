"""Test 230 notebook: mesh generation only (skip HEC-RAS execution)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use('Agg')

from pathlib import Path
from ras_commander import init_ras_project, RasExamples, RasPlan
from ras_commander.geom.GeomMesh import GeomMesh
import pandas as pd

PROJECT_NAME = "BaldEagleCrkMulti2D"
RAS_VERSION = "6.6"
TEMPLATE_PLAN = "06"
SUFFIX = "230_mesh_test2"

SCENARIOS = [
    {"name": "coarse_500",   "title": "Coarse 500ft",        "cell_size": 500.0},
    {"name": "baseline_250", "title": "Baseline 250ft",       "cell_size": 250.0},
    {"name": "bl_tight",     "title": "BL Near=50 Far=150",   "cell_size": 250.0,
     "bl_spacing_near": 50.0, "bl_spacing_far": 150.0},
]

NUM_CORES = 4

project_folder = RasExamples.extract_project(PROJECT_NAME, suffix=SUFFIX)
ras = init_ras_project(project_folder, RAS_VERSION)

print(f"Project: {project_folder}")
print(f"Plans: {list(ras.plan_df['plan_number'])}")
print(f"Geometries: {list(ras.geom_df['geom_number'])}")

template_geom = ras.plan_df.loc[
    ras.plan_df['plan_number'] == TEMPLATE_PLAN, 'geometry_number'
].values[0]
template_geom_path = Path(
    ras.geom_df.loc[
        ras.geom_df['geom_number'] == template_geom, 'full_path'
    ].values[0]
)
print(f"\nTemplate: plan {TEMPLATE_PLAN} -> geom g{template_geom} ({template_geom_path.name})")

scenario_results = []
for scenario in SCENARIOS:
    name = scenario["name"]
    title = scenario["title"]
    cell_size = scenario.get("cell_size", 250.0)
    bl_near = scenario.get("bl_spacing_near")
    bl_far = scenario.get("bl_spacing_far")

    print(f"\n{'='*60}")
    print(f"Scenario: {title} (cell_size={cell_size}, bl_near={bl_near}, bl_far={bl_far})")

    new_geom = RasPlan.clone_geom(template_geom, ras_object=ras)
    print(f"  Cloned: g{template_geom} -> g{new_geom}")

    new_geom_path = Path(
        ras.geom_df.loc[
            ras.geom_df['geom_number'] == new_geom, 'full_path'
        ].values[0]
    )

    # Keep the cloned HDF — generate() uses it for .NET loading
    # and syncs text changes (breakline spacing) into HDF automatically.

    mesh_result = GeomMesh.generate(
        geom_number=new_geom_path,
        mesh_name="BaldEagleCr",
        cell_size=cell_size,
        bl_spacing_near=bl_near,
        bl_spacing_far=bl_far,
        max_iterations=8,
        ras_object=ras,
    )

    print(f"  Result: status={mesh_result.status}, "
          f"cells={mesh_result.cell_count}, faces={mesh_result.face_count}")
    if mesh_result.fixes_applied:
        print(f"  Fixes: {mesh_result.fixes_applied}")

    new_plan = RasPlan.clone_plan(
        TEMPLATE_PLAN,
        new_plan_shortid=name[:12],
        geometry=new_geom,
        num_cores=NUM_CORES,
        ras_object=ras,
    )
    print(f"  Plan: p{TEMPLATE_PLAN} -> p{new_plan} (geom=g{new_geom})")

    scenario_results.append({
        "name": name, "title": title,
        "plan_number": new_plan, "geom_number": new_geom,
        "cell_size": cell_size, "bl_near": bl_near, "bl_far": bl_far,
        "cell_count": mesh_result.cell_count,
        "face_count": mesh_result.face_count,
        "mesh_status": mesh_result.status,
    })

df = pd.DataFrame(scenario_results)
print(f"\n{'='*60}")
print("SUMMARY:")
print(df[['name', 'plan_number', 'geom_number', 'cell_size',
          'bl_near', 'bl_far', 'cell_count', 'face_count', 'mesh_status'
          ]].to_string(index=False))

all_ok = all(s['mesh_status'] == 'complete' for s in scenario_results)
print(f"\nMesh generation test {'PASSED' if all_ok else 'FAILED'}")
if not all_ok:
    for s in scenario_results:
        if s['mesh_status'] != 'complete':
            print(f"  FAILED: {s['name']} - {s['mesh_status']}")
    sys.exit(1)
