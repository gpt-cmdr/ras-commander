# Plan: Dominant Precipitation Method Visualization

## Summary

Create a new visualization that shows **which precipitation method produces the highest maximum WSE** at each mesh cell. This is a categorical choropleth map where each polygon is colored by the "winning" method, not by the WSE value itself.

## User's Request

The user wants to:
1. Compare multiple HEC-RAS results (different temporal distributions) for the same AEP event
2. For each mesh cell, determine which method produced the highest max WSE
3. Visualize this as a map where polygons are colored by the dominant method
4. Create THREE SEPARATE FIGURES per AEP event (saved to disk, not panels)
5. Add this to notebook 721 (Hyetograph Comparison)
6. Handle ties as "No Difference" (2 plans) or "Ambiguous" (3+ plans)

## Data Structures

### Notebook 721 Structure
```python
storm_projects = {
    "10-year AEP": {
        'path': Path("example_projects/Davis_721_10yr"),
        'plans': {
            'Atlas14 First': {'plan_number': '03', 'hyeto_file': ..., 'total_depth': 6.94},
            'Atlas14 Second': {'plan_number': '04', ...},
            'FrequencyStorm SCS II': {'plan_number': '08', ...},
            'ScsTypeStorm Type I': {'plan_number': '09', ...},
            # ... more methods
        }
    },
    "50-year AEP": {...},
    "100-year AEP": {...}
}
```

### Key API Methods
- `HdfResultsMesh.get_mesh_max_ws(plan_hdf)` → GeoDataFrame with `cell_id`, `mesh_name`, `maximum_water_surface`
- `HdfMesh.get_mesh_cell_polygons(hdf_file)` → GeoDataFrame with `cell_id`, `mesh_name`, `geometry` (Polygon)

## Algorithm

```python
# For each AEP:
#   1. Extract max WSE from each plan's HDF
#   2. Stack WSE values into a DataFrame (columns = methods, rows = cells)
#   3. Find argmax across methods for each cell
#   4. Assign categorical labels (method names)
#   5. Create choropleth with categorical colormap
```

## Implementation Steps

### Step 1: Create helper function to extract max WSE from multiple plans

```python
def extract_multi_plan_max_wse(project_path, plan_methods):
    """
    Extract max WSE from multiple plans and determine dominant method per cell.

    Args:
        project_path: Path to HEC-RAS project
        plan_methods: dict of {method_name: plan_number}

    Returns:
        GeoDataFrame with columns: mesh_name, cell_id, geometry, dominant_method, max_wse
    """
    # For each method, get max WSE
    all_wse = {}
    for method_name, plan_num in plan_methods.items():
        hdf_path = find_plan_hdf(project_path, plan_num)
        max_ws_gdf = HdfResultsMesh.get_mesh_max_ws(hdf_path)
        all_wse[method_name] = max_ws_gdf

    # Create comparison DataFrame
    # Index by (mesh_name, cell_id)
    # Columns are method names
    # Values are max WSE

    # Find dominant method (argmax) for each cell
    # Return GeoDataFrame with categorical 'dominant_method' column
```

### Step 2: Create visualization function

```python
def plot_dominant_method_map(result_gdf, aep_name, method_names):
    """
    Create choropleth map colored by dominant method.

    Uses categorical colormap with legend showing method colors.
    """
    # Create figure with 2 subplots:
    # Left: Dominant method choropleth
    # Right: Summary statistics (pie chart or bar chart of cell counts by method)
```

### Step 3: Add to notebook 721

New cell after execution results validation:
```python
# =============================================================================
# 7.X Dominant Method Map (NEW)
# =============================================================================
# For each AEP, visualize which precipitation method produces the highest max WSE
# at each mesh cell location
```

## Files to Modify

1. **`examples/721_Precipitation_Hyetograph_Comparison.ipynb`** (PRIMARY)
   - Add new visualization cell at end showing dominant method map
   - One figure per AEP event

2. **`examples/722_gridded_precipitation_atlas14.ipynb`** (SECONDARY)
   - Fix existing max WSE visualization
   - Add similar dominant method map if multiple methods are compared

## Visualization Design (User Clarified)

**Output**: Three separate figures per AEP (NOT panels), saved to disk

### Figure 1: Dominant Method Map
- File: `{project_folder}/precip_analysis/{aep}_dominant_method.png`
- Each polygon colored by categorical value (method name)
- Use qualitative colormap (e.g., `Set3`, `Paired`, `tab10`)
- Legend shows method name → color mapping
- Title: "Dominant Precipitation Method - {AEP} Event"
- Include summary statistics as text annotation (cell counts per method)

### Figure 2: Maximum WSE Map (from dominant method)
- File: `{project_folder}/precip_analysis/{aep}_max_wse.png`
- Continuous colormap showing actual WSE values
- Each cell shows WSE from whichever method was dominant there
- Title: "Maximum WSE (from Dominant Method) - {AEP} Event"

### Figure 3: Sensitivity Magnitude Map
- File: `{project_folder}/precip_analysis/{aep}_sensitivity_delta.png`
- Shows difference between 1st and 2nd highest WSE at each cell
- Highlights areas most sensitive to precipitation method choice
- Title: "WSE Sensitivity to Precipitation Method - {AEP} Event"

## Tie Handling (User Clarified)

When multiple methods produce identical max WSE at a cell:
- **2 plans compared**: Label as "No Difference"
- **3+ plans compared**: Label as "Ambiguous"

Use tolerance of 0.001 ft (1/1000th of a foot) to detect ties (accounts for floating-point precision).

## Detailed Implementation Code

### Core Analysis Function

```python
def analyze_dominant_method(project_path, plan_methods, ras_object=None):
    """
    Analyze which precipitation method produces highest max WSE at each mesh cell.

    Args:
        project_path: Path to HEC-RAS project (or [Computed] folder)
        plan_methods: dict of {method_name: plan_number}
        ras_object: Optional RasPrj object

    Returns:
        GeoDataFrame with columns:
        - mesh_name, cell_id, geometry (Polygon)
        - dominant_method (str): Name of winning method or "No Difference"/"Ambiguous"
        - max_wse (float): Highest WSE value across all methods
        - delta_wse (float): Difference between 1st and 2nd highest
        - {method_name}_wse (float): WSE for each method
    """
    from ras_commander.hdf import HdfResultsMesh, HdfMesh
    import pandas as pd
    import numpy as np

    method_names = list(plan_methods.keys())
    n_methods = len(method_names)
    TIE_TOLERANCE = 0.001  # ft

    # Step 1: Extract max WSE from each plan
    wse_data = {}
    cell_polygons = None

    for method_name, plan_num in plan_methods.items():
        # Find HDF file
        hdf_files = list(project_path.glob(f"*.p{plan_num}.hdf"))
        if not hdf_files:
            print(f"  [!!] HDF not found for {method_name} (Plan {plan_num})")
            continue

        hdf_path = hdf_files[0]

        # Get max WSE
        max_ws_gdf = HdfResultsMesh.get_mesh_max_ws(hdf_path)
        wse_col = [c for c in max_ws_gdf.columns if 'water_surface' in c.lower()][0]
        wse_data[method_name] = max_ws_gdf.set_index(['mesh_name', 'cell_id'])[wse_col]

        # Get polygons from first HDF (they're all the same mesh)
        if cell_polygons is None:
            try:
                cell_polygons = HdfMesh.get_mesh_cell_polygons(hdf_path)
            except:
                pass

    if not wse_data:
        raise ValueError("No valid WSE data extracted from any plan")

    # Step 2: Create comparison DataFrame
    wse_df = pd.DataFrame(wse_data)
    wse_df.columns = [f"{m}_wse" for m in wse_df.columns]

    # Step 3: Compute dominant method for each cell
    wse_values = wse_df.values  # NumPy array for fast operations
    method_cols = [f"{m}_wse" for m in method_names]

    # Find max and argmax
    max_wse = np.nanmax(wse_values, axis=1)
    argmax_idx = np.nanargmax(wse_values, axis=1)
    dominant = np.array(method_names)[argmax_idx]

    # Find 2nd highest for delta calculation
    sorted_wse = np.sort(wse_values, axis=1)[:, ::-1]  # Descending
    second_highest = sorted_wse[:, 1] if wse_values.shape[1] > 1 else sorted_wse[:, 0]
    delta_wse = max_wse - second_highest

    # Detect ties (values within tolerance of max)
    is_tie = np.sum(np.abs(wse_values - max_wse[:, None]) < TIE_TOLERANCE, axis=1) > 1

    # Label ties based on number of methods
    tie_label = "No Difference" if n_methods == 2 else "Ambiguous"
    dominant = np.where(is_tie, tie_label, dominant)

    # Step 4: Build result DataFrame
    result_df = wse_df.copy()
    result_df['dominant_method'] = dominant
    result_df['max_wse'] = max_wse
    result_df['delta_wse'] = delta_wse
    result_df = result_df.reset_index()

    # Step 5: Merge with polygons
    if cell_polygons is not None:
        cell_polygons['cell_id'] = cell_polygons['cell_id'].astype(int)
        result_df['cell_id'] = result_df['cell_id'].astype(int)

        merged = cell_polygons.merge(
            result_df,
            on=['mesh_name', 'cell_id'],
            how='left'
        )
        return gpd.GeoDataFrame(merged, geometry='geometry')
    else:
        # Fallback: return without polygons (scatter plot mode)
        return result_df
```

### Figure Generation Functions

```python
def generate_dominant_method_figures(result_gdf, aep_name, output_folder, method_names):
    """
    Generate all three figures for a single AEP event.

    Saves to:
    - {output_folder}/{aep}_01_dominant_method.png
    - {output_folder}/{aep}_02_max_wse.png
    - {output_folder}/{aep}_03_sensitivity.png
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    import matplotlib.patches as mpatches

    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    # Sanitize AEP name for filename
    aep_safe = aep_name.replace(' ', '_').replace('-', '_').lower()

    # Define color palette for methods
    colors = plt.cm.Set3(np.linspace(0, 1, len(method_names) + 2))
    method_colors = {m: colors[i] for i, m in enumerate(method_names)}
    method_colors['No Difference'] = 'lightgray'
    method_colors['Ambiguous'] = 'darkgray'

    # ===== FIGURE 1: Dominant Method Map =====
    fig1, ax1 = plt.subplots(figsize=(12, 10))

    # Map categories to numeric for plotting
    categories = list(method_names) + ['No Difference', 'Ambiguous']
    cat_to_num = {c: i for i, c in enumerate(categories)}
    result_gdf['method_code'] = result_gdf['dominant_method'].map(cat_to_num)

    # Plot
    result_gdf.plot(
        column='method_code',
        ax=ax1,
        cmap=ListedColormap([method_colors[c] for c in categories]),
        edgecolor='none',
        legend=False
    )

    # Create legend
    patches = [mpatches.Patch(color=method_colors[m], label=m) for m in categories
               if m in result_gdf['dominant_method'].unique()]
    ax1.legend(handles=patches, loc='upper right', title='Dominant Method')

    # Add summary statistics
    counts = result_gdf['dominant_method'].value_counts()
    total = len(result_gdf)
    stats_text = "Cell Distribution:\n" + "\n".join(
        [f"  {m}: {c:,} ({100*c/total:.1f}%)" for m, c in counts.items()]
    )
    ax1.text(0.02, 0.02, stats_text, transform=ax1.transAxes,
             fontsize=9, verticalalignment='bottom',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    ax1.set_title(f'Dominant Precipitation Method - {aep_name}', fontsize=14, fontweight='bold')
    ax1.set_xlabel('X Coordinate')
    ax1.set_ylabel('Y Coordinate')
    ax1.set_aspect('equal')

    fig1.tight_layout()
    fig1.savefig(output_folder / f'{aep_safe}_01_dominant_method.png', dpi=150, bbox_inches='tight')
    plt.close(fig1)
    print(f"  [OK] Saved: {aep_safe}_01_dominant_method.png")

    # ===== FIGURE 2: Maximum WSE Map =====
    fig2, ax2 = plt.subplots(figsize=(12, 10))

    result_gdf.plot(
        column='max_wse',
        ax=ax2,
        cmap='viridis',
        legend=True,
        legend_kwds={'label': 'Max WSE (ft)', 'shrink': 0.8},
        edgecolor='none'
    )

    ax2.set_title(f'Maximum WSE (from Dominant Method) - {aep_name}', fontsize=14, fontweight='bold')
    ax2.set_xlabel('X Coordinate')
    ax2.set_ylabel('Y Coordinate')
    ax2.set_aspect('equal')

    # Add statistics
    wse_stats = f"WSE Range: {result_gdf['max_wse'].min():.2f} - {result_gdf['max_wse'].max():.2f} ft\n"
    wse_stats += f"Mean: {result_gdf['max_wse'].mean():.2f} ft"
    ax2.text(0.02, 0.98, wse_stats, transform=ax2.transAxes,
             fontsize=10, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    fig2.tight_layout()
    fig2.savefig(output_folder / f'{aep_safe}_02_max_wse.png', dpi=150, bbox_inches='tight')
    plt.close(fig2)
    print(f"  [OK] Saved: {aep_safe}_02_max_wse.png")

    # ===== FIGURE 3: Sensitivity (Delta) Map =====
    fig3, ax3 = plt.subplots(figsize=(12, 10))

    result_gdf.plot(
        column='delta_wse',
        ax=ax3,
        cmap='YlOrRd',  # Yellow to Red - highlights high sensitivity areas
        legend=True,
        legend_kwds={'label': 'WSE Difference (ft)', 'shrink': 0.8},
        edgecolor='none'
    )

    ax3.set_title(f'WSE Sensitivity to Precipitation Method - {aep_name}', fontsize=14, fontweight='bold')
    ax3.set_xlabel('X Coordinate')
    ax3.set_ylabel('Y Coordinate')
    ax3.set_aspect('equal')

    # Add statistics
    delta_stats = f"Sensitivity Range: {result_gdf['delta_wse'].min():.3f} - {result_gdf['delta_wse'].max():.3f} ft\n"
    delta_stats += f"Mean: {result_gdf['delta_wse'].mean():.3f} ft\n"
    delta_stats += f"Cells with >0.5 ft difference: {(result_gdf['delta_wse'] > 0.5).sum():,}"
    ax3.text(0.02, 0.98, delta_stats, transform=ax3.transAxes,
             fontsize=10, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    fig3.tight_layout()
    fig3.savefig(output_folder / f'{aep_safe}_03_sensitivity.png', dpi=150, bbox_inches='tight')
    plt.close(fig3)
    print(f"  [OK] Saved: {aep_safe}_03_sensitivity.png")

    return output_folder
```

## Notebook Cell to Add (721)

Add this cell after the execution results section (approximately cell 7.2):

```python
# =============================================================================
# 7.3 Dominant Method Comparison Maps
# =============================================================================
print("="*80)
print("DOMINANT PRECIPITATION METHOD ANALYSIS")
print("="*80)

if not EXECUTE_PLANS:
    print("\n[--] EXECUTE_PLANS is False - skipping analysis")
    print("\nThis visualization requires executed HEC-RAS results.")
    print("Set EXECUTE_PLANS = True and re-run the notebook.")

elif not PROJECT_AVAILABLE or not storm_projects:
    print("\n[--] No storm projects available")

else:
    print("\nAnalyzing which precipitation method produces highest max WSE at each cell...")
    print("Generating 3 figures per AEP event:\n")
    print("  1. Dominant Method Map (categorical)")
    print("  2. Maximum WSE Map (from dominant method)")
    print("  3. Sensitivity Map (delta between 1st and 2nd highest)")

    for aep_name, project_info in storm_projects.items():
        print(f"\n{'='*60}")
        print(f"Processing {aep_name}")
        print(f"{'='*60}")

        project_path = project_info['path']

        # Detect [Computed] folder if exists
        computed_folder = project_path.parent / f"{project_path.name} [Computed]"
        if computed_folder.exists():
            analysis_path = computed_folder
            print(f"  Using computed folder: {computed_folder.name}")
        else:
            analysis_path = project_path

        # Build plan_methods dict: {method_name: plan_number}
        plan_methods = {
            storm_name: plan_info['plan_number']
            for storm_name, plan_info in project_info['plans'].items()
        }
        method_names = list(plan_methods.keys())

        print(f"  Methods to compare: {len(method_names)}")
        for m, p in plan_methods.items():
            print(f"    - {m} (Plan {p})")

        try:
            # Analyze dominant method
            result_gdf = analyze_dominant_method(analysis_path, plan_methods)

            # Generate figures
            output_folder = project_path / "precip_analysis"
            generate_dominant_method_figures(result_gdf, aep_name, output_folder, method_names)

            print(f"\n  [OK] Analysis complete - figures saved to: {output_folder}")

            # Summary statistics
            counts = result_gdf['dominant_method'].value_counts()
            print(f"\n  Cell Distribution by Dominant Method:")
            for method, count in counts.items():
                pct = 100 * count / len(result_gdf)
                print(f"    {method}: {count:,} cells ({pct:.1f}%)")

        except Exception as e:
            print(f"\n  [!!] Error processing {aep_name}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)
```

## Files to Modify

| File | Changes |
|------|---------|
| `examples/721_Precipitation_Hyetograph_Comparison.ipynb` | Add new cell 7.3 with dominant method analysis (after current 7.2 WSE map) |
| `examples/722_gridded_precipitation_atlas14.ipynb` | Fix existing WSE visualization; optionally add similar comparison if multiple plans exist |

## Implementation Order

1. **First**: Add helper functions to notebook 721 (analyze_dominant_method, generate_dominant_method_figures)
2. **Second**: Add cell 7.3 with the analysis loop for each AEP
3. **Third**: Test with available storm_projects data
4. **Fourth**: Adapt similar pattern for 722 if needed
