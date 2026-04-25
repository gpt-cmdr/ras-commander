# =============================================================================
# DEVELOPMENT MODE TOGGLE
# =============================================================================
USE_LOCAL_SOURCE = True  # <-- TOGGLE THIS

if USE_LOCAL_SOURCE:
    import sys
    from pathlib import Path
    local_path = str(Path.cwd().parent)
    if local_path not in sys.path:
        sys.path.insert(0, local_path)
    print(f"LOCAL SOURCE MODE: Loading from {local_path}/ras_commander")
else:
    from pathlib import Path
    print("PIP PACKAGE MODE: Loading installed ras-commander")

from ras_commander import (
    init_ras_project, RasExamples, RasPlan, RasCmdr,
    RasProcess, RasMap,
)
from ras_commander.geom.GeomMesh import GeomMesh

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

import ras_commander
print(f"Loaded: {ras_commander.__file__}")

# =============================================================================
# PARAMETERS
# =============================================================================

PROJECT_NAME = "BaldEagleCrkMulti2D"
RAS_VERSION = "6.6"
TEMPLATE_PLAN = "06"
SUFFIX = "230_mesh_sens"

# Mesh sensitivity scenarios — each dict becomes one geometry clone + plan
#
# The baseline geometry (g09) uses:
#   cell_size = 250 (feet)   — from "Storage Area Point Generation Data=,,250,250"
#   breakline spacing = not set (empty CellSize Min/Max on all 4 breaklines)
#
# Breaklines in g09:  SayersDam, Lower, Middle, Upper

SCENARIOS = [
    # ── Group 1: Base cell size variation ──
    {
        "name": "coarse_500",
        "title": "Coarse 500ft",
        "cell_size": 500.0,
    },
    {
        "name": "baseline_250",
        "title": "Baseline 250ft",
        "cell_size": 250.0,
    },
    {
        "name": "fine_150",
        "title": "Fine 150ft",
        "cell_size": 150.0,
    },

    # ── Group 2: Breakline spacing (all breaklines) ──
    {
        "name": "bl_tight",
        "title": "BL Near=50 Far=150",
        "cell_size": 250.0,
        "bl_spacing_near": 50.0,
        "bl_spacing_far": 150.0,
    },
    {
        "name": "bl_moderate",
        "title": "BL Near=100 Far=200",
        "cell_size": 250.0,
        "bl_spacing_near": 100.0,
        "bl_spacing_far": 200.0,
    },

    # ── Group 3: Combined fine mesh + tight breaklines ──
    {
        "name": "fine_bl_tight",
        "title": "Fine 150ft + BL 50/150",
        "cell_size": 150.0,
        "bl_spacing_near": 50.0,
        "bl_spacing_far": 150.0,
    },
]

# Execution settings
NUM_CORES = 4
MAX_WORKERS = 2

# Point of interest for time-series extraction (project coordinates)
POINT_OF_INTEREST = (2081544, 365715)

project_folder = RasExamples.extract_project(PROJECT_NAME, suffix=SUFFIX)
ras = init_ras_project(project_folder, RAS_VERSION)

print(f"Project: {project_folder}")
print(f"\nPlans:")
print(ras.plan_df[['plan_number', 'Plan Title', 'Short Identifier']].to_string(index=False))
print(f"\nGeometries:")
print(ras.geom_df[['geom_number', 'geom_title']].to_string(index=False))

# Get the geometry number from the template plan
template_geom = ras.plan_df.loc[
    ras.plan_df['plan_number'] == TEMPLATE_PLAN, 'geometry_number'
].values[0]
template_geom_path = Path(
    ras.geom_df.loc[
        ras.geom_df['geom_number'] == template_geom, 'full_path'
    ].values[0]
)

print(f"Template plan: {TEMPLATE_PLAN}")
print(f"Template geometry: g{template_geom} ({template_geom_path.name})")

# Read existing breakline spacing and base cell size from the text file
text = template_geom_path.read_text(encoding='utf-8', errors='replace')
for line in text.splitlines():
    if line.startswith('Storage Area Point Generation Data='):
        print(f"\nBase cell size: {line}")
    elif line.startswith('BreakLine Name='):
        print(f"  Breakline: {line.split('=', 1)[1].strip()}")
    elif line.startswith('BreakLine CellSize'):
        val = line.split('=', 1)[1].strip()
        tag = 'Min' if 'Min' in line else 'Max'
        print(f"    CellSize {tag}: {val if val else '(not set)'}")

import shutil
import re


def set_breakline_spacing_by_name(
    geom_path: Path,
    spacing_map: dict,
) -> None:
    """
    Set per-breakline CellSize Min/Max in a .g## text file.

    Args:
        geom_path: Path to .g## text file.
        spacing_map: Dict mapping breakline name to (near, far) tuple.
            Names not in the dict are left unchanged.
            Example: {"SayersDam": (25.0, 100.0), "Lower": (50.0, 150.0)}
    """
    lines = geom_path.read_text(encoding='utf-8', errors='replace').splitlines(keepends=True)
    modified = []
    current_bl = None

    for line in lines:
        if line.startswith('BreakLine Name='):
            current_bl = line.split('=', 1)[1].strip()
            modified.append(line)
        elif line.startswith('BreakLine CellSize Min=') and current_bl in spacing_map:
            near = spacing_map[current_bl][0]
            modified.append(f'BreakLine CellSize Min={near:.6f}\n' if near else 'BreakLine CellSize Min=\n')
        elif line.startswith('BreakLine CellSize Max=') and current_bl in spacing_map:
            far = spacing_map[current_bl][1]
            modified.append(f'BreakLine CellSize Max={far:.6f}\n' if far else 'BreakLine CellSize Max=\n')
        else:
            modified.append(line)

    shutil.copy2(geom_path, geom_path.with_suffix(geom_path.suffix + '.bak'))
    geom_path.write_text(''.join(modified), encoding='utf-8')
    print(f"  Updated breaklines in {geom_path.name}: {list(spacing_map.keys())}")

scenario_results = []

for scenario in SCENARIOS:
    name = scenario["name"]
    title = scenario["title"]
    cell_size = scenario.get("cell_size", 250.0)
    bl_near = scenario.get("bl_spacing_near")
    bl_far = scenario.get("bl_spacing_far")
    bl_by_name = scenario.get("bl_by_name")  # optional per-breakline dict

    print(f"\n{'='*60}")
    print(f"Scenario: {title}")
    print(f"  cell_size={cell_size}, bl_near={bl_near}, bl_far={bl_far}")

    # 1. Clone geometry
    new_geom = RasPlan.clone_geom(template_geom, ras_object=ras)
    print(f"  Cloned geometry: g{template_geom} -> g{new_geom}")

    # Get the new geometry's text file path
    new_geom_path = Path(
        ras.geom_df.loc[
            ras.geom_df['geom_number'] == new_geom, 'full_path'
        ].values[0]
    )

    # 2. Apply per-breakline spacing if specified
    if bl_by_name:
        set_breakline_spacing_by_name(new_geom_path, bl_by_name)

    # 3. Delete the cloned HDF so generate() recompiles from modified text
    cloned_hdf = new_geom_path.with_suffix(new_geom_path.suffix + '.hdf')
    if cloned_hdf.exists():
        cloned_hdf.unlink()
        print(f"  Removed stale HDF: {cloned_hdf.name}")

    # 4. Generate mesh (cell_size and breakline spacing applied internally)
    mesh_result = GeomMesh.generate(
        geom_number=new_geom_path,
        mesh_name="BaldEagleCr",
        cell_size=cell_size,
        bl_spacing_near=bl_near,
        bl_spacing_far=bl_far,
        max_iterations=8,
        ras_object=ras,
    )

    print(f"  Mesh: status={mesh_result.status}, "
          f"cells={mesh_result.cell_count}, faces={mesh_result.face_count}")
    if mesh_result.fixes_applied:
        print(f"  Fixes: {mesh_result.fixes_applied}")

    # 5. Clone plan and assign the new geometry
    new_plan = RasPlan.clone_plan(
        TEMPLATE_PLAN,
        new_plan_shortid=name[:12],
        geometry=new_geom,
        num_cores=NUM_CORES,
        ras_object=ras,
    )
    print(f"  Cloned plan: p{TEMPLATE_PLAN} -> p{new_plan} (geom=g{new_geom})")

    scenario_results.append({
        "name": name,
        "title": title,
        "plan_number": new_plan,
        "geom_number": new_geom,
        "cell_size": cell_size,
        "bl_near": bl_near,
        "bl_far": bl_far,
        "cell_count": mesh_result.cell_count,
        "face_count": mesh_result.face_count,
        "mesh_status": mesh_result.status,
        "fixes": mesh_result.fixes_applied,
    })

# Summary table
scenario_df = pd.DataFrame(scenario_results)
print(f"\n{'='*60}")
print("Scenario Summary:")
print(scenario_df[['name', 'plan_number', 'geom_number', 'cell_size',
                    'bl_near', 'bl_far', 'cell_count', 'face_count', 'mesh_status'
                    ]].to_string(index=False))

plan_numbers = [str(s['plan_number']) for s in scenario_results]
print(f"Executing {len(plan_numbers)} plans: {plan_numbers}")

exec_results = RasCmdr.compute_parallel(
    plan_number=plan_numbers,
    max_workers=MAX_WORKERS,
    num_cores=NUM_CORES,
    clear_geompre=True,
    ras_object=ras,
)

print("\nExecution results:")
for plan, result in exec_results.items():
    status = "OK" if result else "FAILED"
    print(f"  Plan {plan}: {status}")

# Set consistent render mode for all stored maps
RasMap.set_water_surface_render_mode("horizontal", ras_object=ras)

wse_tifs = {}

for s in scenario_results:
    plan = s['plan_number']
    name = s['name']
    print(f"Generating stored maps for plan {plan} ({name})...")

    try:
        maps = RasProcess.store_maps(
            plan_number=plan,
            profile="Max",
            wse=True,
            depth=True,
            velocity=False,
            ras_object=ras,
        )
        if 'wse' in maps and maps['wse']:
            wse_tifs[name] = maps['wse'][0]
            print(f"  WSE: {maps['wse'][0]}")
        if 'depth' in maps and maps['depth']:
            print(f"  Depth: {maps['depth'][0]}")
    except Exception as e:
        print(f"  ERROR: {e}")

print(f"\nGenerated {len(wse_tifs)} WSE TIFs")

import rasterio
from rasterio.plot import show


def load_wse(tif_path):
    """Load a WSE TIF, masking nodata."""
    with rasterio.open(tif_path) as src:
        data = src.read(1)
        nodata = src.nodata
        if nodata is not None:
            data = np.where(data == nodata, np.nan, data)
        else:
            data = np.where(data < -9000, np.nan, data)
        return data, src.bounds, src.transform


# Load all WSE rasters
wse_data = {}
for name, tif in wse_tifs.items():
    data, bounds, transform = load_wse(tif)
    wse_data[name] = {"data": data, "bounds": bounds, "transform": transform}
    valid = np.count_nonzero(~np.isnan(data))
    print(f"{name}: shape={data.shape}, valid_cells={valid:,}, "
          f"WSE range=[{np.nanmin(data):.1f}, {np.nanmax(data):.1f}]")

# ── Side-by-side WSE maps ──
n = len(wse_data)
if n == 0:
    print("No WSE data to plot.")
else:
    ncols = min(3, n)
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(7 * ncols, 6 * nrows))
    if n == 1:
        axes = [axes]
    else:
        axes = axes.flatten()

    # Common color scale across all scenarios
    all_valid = np.concatenate(
        [d["data"][~np.isnan(d["data"])].ravel() for d in wse_data.values()]
    )
    vmin, vmax = np.percentile(all_valid, [2, 98])

    for ax, (name, d) in zip(axes, wse_data.items()):
        title_row = next(s for s in scenario_results if s['name'] == name)
        im = ax.imshow(
            d["data"],
            extent=[
                d["bounds"].left, d["bounds"].right,
                d["bounds"].bottom, d["bounds"].top,
            ],
            vmin=vmin, vmax=vmax,
            cmap="Blues",
            origin="upper",
        )
        ax.set_title(
            f"{title_row['title']}\n"
            f"cells={title_row['cell_count']:,}  faces={title_row['face_count']:,}",
            fontsize=10,
        )
        ax.set_xlabel("Easting")
        ax.set_ylabel("Northing")

    # Hide unused axes
    for ax in axes[n:]:
        ax.set_visible(False)

    fig.colorbar(im, ax=axes[:n], label="Max WSE (ft)", shrink=0.8)
    fig.suptitle("Maximum Water Surface Elevation by Mesh Scenario", fontsize=14, y=1.02)
    plt.tight_layout()
    plt.savefig(Path(project_folder) / "wse_comparison.png", dpi=150, bbox_inches="tight")
    plt.show()
    print(f"Saved: {Path(project_folder) / 'wse_comparison.png'}")

BASELINE_NAME = "baseline_250"

if BASELINE_NAME not in wse_data:
    print(f"Baseline scenario '{BASELINE_NAME}' not found in results. Skipping diff maps.")
else:
    baseline = wse_data[BASELINE_NAME]["data"]
    diff_scenarios = {k: v for k, v in wse_data.items() if k != BASELINE_NAME}

    n = len(diff_scenarios)
    if n == 0:
        print("Only baseline scenario available, no diffs to compute.")
    else:
        ncols = min(3, n)
        nrows = (n + ncols - 1) // ncols
        fig, axes = plt.subplots(nrows, ncols, figsize=(7 * ncols, 6 * nrows))
        if n == 1:
            axes = [axes]
        else:
            axes = np.array(axes).flatten()

        # Symmetric color scale for differences
        all_diffs = []
        for name, d in diff_scenarios.items():
            other = d["data"]
            # Only compute diff where both have valid data and same shape
            if other.shape == baseline.shape:
                diff = other - baseline
                valid_diff = diff[~np.isnan(diff)]
                if len(valid_diff) > 0:
                    all_diffs.append(valid_diff)

        if all_diffs:
            combined = np.concatenate(all_diffs)
            dmax = np.percentile(np.abs(combined), 98)
        else:
            dmax = 1.0

        for ax, (name, d) in zip(axes, diff_scenarios.items()):
            title_row = next(s for s in scenario_results if s['name'] == name)
            other = d["data"]

            if other.shape != baseline.shape:
                ax.text(0.5, 0.5, "Shape mismatch\nCannot compute diff",
                        ha="center", va="center", transform=ax.transAxes)
                ax.set_title(title_row['title'])
                continue

            diff = other - baseline

            im = ax.imshow(
                diff,
                extent=[
                    d["bounds"].left, d["bounds"].right,
                    d["bounds"].bottom, d["bounds"].top,
                ],
                vmin=-dmax, vmax=dmax,
                cmap="RdBu_r",
                origin="upper",
            )
            valid_diff = diff[~np.isnan(diff)]
            stats = (
                f"mean={np.mean(valid_diff):+.2f}  "
                f"max={np.max(valid_diff):+.2f}  "
                f"min={np.min(valid_diff):+.2f}"
            ) if len(valid_diff) > 0 else "no overlap"
            ax.set_title(f"{title_row['title']} - Baseline\n{stats}", fontsize=10)
            ax.set_xlabel("Easting")
            ax.set_ylabel("Northing")

        for ax in axes[n:]:
            ax.set_visible(False)

        fig.colorbar(im, ax=list(axes[:n]), label="WSE Difference (ft)", shrink=0.8)
        fig.suptitle(
            f"WSE Difference from Baseline ({BASELINE_NAME})",
            fontsize=14, y=1.02,
        )
        plt.tight_layout()
        plt.savefig(
            Path(project_folder) / "wse_diff_maps.png", dpi=150, bbox_inches="tight"
        )
        plt.show()
        print(f"Saved: {Path(project_folder) / 'wse_diff_maps.png'}")

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

# Bar chart: cell count by scenario
names = [s['title'] for s in scenario_results]
cells = [s['cell_count'] for s in scenario_results]
faces = [s['face_count'] for s in scenario_results]

x = np.arange(len(names))
width = 0.35

ax1.bar(x - width/2, cells, width, label='Cells', color='steelblue')
ax1.bar(x + width/2, faces, width, label='Faces', color='coral')
ax1.set_xticks(x)
ax1.set_xticklabels(names, rotation=45, ha='right', fontsize=9)
ax1.set_ylabel('Count')
ax1.set_title('Mesh Density by Scenario')
ax1.legend()
ax1.grid(axis='y', alpha=0.3)

for i, (c, f) in enumerate(zip(cells, faces)):
    ax1.text(i - width/2, c + max(cells) * 0.01, f'{c:,}',
             ha='center', va='bottom', fontsize=8)

# Scatter: cell_size vs cell_count for the cell-size group
cell_size_scenarios = [s for s in scenario_results if s.get('bl_near') is None]
if len(cell_size_scenarios) >= 2:
    cs = [s['cell_size'] for s in cell_size_scenarios]
    cc = [s['cell_count'] for s in cell_size_scenarios]
    ax2.scatter(cs, cc, s=100, c='steelblue', zorder=3)
    for s in cell_size_scenarios:
        ax2.annotate(s['title'], (s['cell_size'], s['cell_count']),
                     textcoords='offset points', xytext=(10, 5), fontsize=9)

    # Theoretical inverse-square fit
    cs_arr = np.array(cs, dtype=float)
    cc_arr = np.array(cc, dtype=float)
    k = np.mean(cc_arr * cs_arr**2)
    cs_fit = np.linspace(min(cs) * 0.8, max(cs) * 1.2, 50)
    ax2.plot(cs_fit, k / cs_fit**2, '--', color='gray', alpha=0.6,
             label=r'$\sim 1/\Delta x^2$ trend')
    ax2.legend()

ax2.set_xlabel('Cell Size (ft)')
ax2.set_ylabel('Cell Count')
ax2.set_title('Cell Size vs. Mesh Density')
ax2.grid(alpha=0.3)

plt.tight_layout()
plt.savefig(Path(project_folder) / "mesh_density_comparison.png", dpi=150, bbox_inches="tight")
plt.show()

# Add WSE statistics to scenario results
summary_rows = []
for s in scenario_results:
    row = {
        "Scenario": s['title'],
        "Plan": f"p{s['plan_number']}",
        "Geom": f"g{s['geom_number']}",
        "Cell Size": s['cell_size'],
        "BL Near": s.get('bl_near', '-'),
        "BL Far": s.get('bl_far', '-'),
        "Cells": f"{s['cell_count']:,}",
        "Faces": f"{s['face_count']:,}",
        "Status": s['mesh_status'],
    }
    if s['name'] in wse_data:
        d = wse_data[s['name']]['data']
        valid = d[~np.isnan(d)]
        row["Max WSE"] = f"{np.nanmax(valid):.1f}"
        row["Mean WSE"] = f"{np.nanmean(valid):.1f}"
    summary_rows.append(row)

summary_df = pd.DataFrame(summary_rows)
print(summary_df.to_string(index=False))

# Save to CSV
csv_path = Path(project_folder) / "mesh_sensitivity_summary.csv"
summary_df.to_csv(csv_path, index=False)
print(f"\nSaved: {csv_path}")