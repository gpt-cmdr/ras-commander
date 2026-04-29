---
name: qa_rasmapper_spatial-review
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
description: |
  Use RASMapper layer and view automation for spatial QA/QC, contextual model
  review, and documentation screenshots. Launches standalone RasMapper.exe,
  toggles reference maps, basemaps, terrain, results, and geometry elements,
  zooms to HDF-derived extents, enables Update Legend with View, and captures
  snapshots for agent review.
---

# RASMapper Spatial Review

Use this skill when a task needs agent-readable RASMapper context: visual QA/QC,
spatial documentation, layer-state review, reference map verification, or a
snapshot-driven inspection of 2D flow areas, structures, breaklines, and terrain.

This is a shared workflow skill. Keep it as a lightweight navigator that points
agents to ras-commander APIs and tests instead of duplicating implementation.

## Primary Sources

Read these first when exact behavior matters:

- `ras_commander/RasMap.py` - public API surface
- `ras_commander/_rasmap_control_helper.py` - RASMapper view, layer, launch, and snapshot helpers
- `ras_commander/_rasmap_layer_helper.py` - reference map, basemap, and GeoJSON validation helpers
- `docs/user-guide/spatial-data.md` - user-facing workflow examples
- `tests/test_rasmap_map_layers.py` - expected XML/HDF behavior

## When To Use

Use for:

- Capturing RASMapper screenshots for documentation or agent review
- Toggling geometry child elements such as `RASD2FlowArea`, `LateralStructureLayer`,
  `StructureLayer`, `RASXS`, and mesh perimeter layers
- Reviewing terrain context with "Update Legend with View" enabled
- Verifying reference map layers, shapefile layers, GeoJSON layers, and standard basemaps
- Setting result and map-layer visibility state for deterministic figures
- Checking whether a project is visually configured for spatial QA/QC
- Preparing evidence for future numerical mesh/breakline alignment review

Do not use this skill for:

- Running HEC-RAS computations
- Mutating hydraulic geometry or results
- Treating a screenshot as a substitute for numerical QA where numerical APIs exist

## Safety Notes

- These workflows edit `.rasmap` layer, terrain, legend, and viewport state.
  Prefer a copied project in `working/` when the user has not asked to mutate the
  original project presentation state.
- RASMapper screenshots require Windows and a visible standalone `RasMapper.exe`
  window.
- GeoJSON reference layers must be WGS84/EPSG:4326. `RasMap.add_reference_map_layer`
  validates this and raises `ValueError` for incompatible GeoJSON sources.
- Always close RASMapper by PID after capture when the workflow launched it.

## Standard Review Workflow

### Preferred: Review Package API

Use the high-level review package API when the user asks for a repeatable
agentic QA/QC artifact. It records the configured view and writes evidence files
that another agent or engineer can audit.

```python
from ras_commander import init_ras_project, ras, RasMap

init_ras_project(r"C:\Projects\MyModel", "6.6")

review = RasMap.create_spatial_review_package(
    ras.project_folder,
    output_dir=ras.project_folder / "working" / "rasmapper_spatial_review",
    geometry_number="04",
    layer_type=["RASD2FlowArea", "LateralStructureLayer"],
    feature_name="Lateral Structure 1",
    terrain_name="TerrainWithChannel",
    result_plan_name="Existing Conditions",
    result_layer_name="Depth",
    map_layer_category="land_classification",
    capture_snapshot=True,
    snapshot_timeout_seconds=1800,
    ras_version="6.6",
)

print(review["artifacts"])
print(review["preflight"])
```

Use `capture_snapshot=False` for headless preflight/state bundles and
`capture_snapshot=True` on Windows review machines with HEC-RAS installed. The
snapshot timeout is configurable with `snapshot_timeout_seconds`; the default is
1800 seconds because large projects can take a long time to open in RASMapper.
When `output_dir` is omitted, ras-commander writes the review bundle and
screenshots to the project's `RASMapper Screenshots` folder.

RASMapper toggles full layers, but ras-commander can center the viewport on a
selected HDF-backed feature. The full layer remains visible; the selected
feature only controls the centered viewport. By default, feature-focused views
expand the selected feature extent by 50% overall so the screenshot includes the
mesh, terrain, land-cover, and profile context around it. Discover selectors with:

```python
features = RasMap.list_geometry_features(
    ras.project_folder / "MyModel.g04.hdf",
    layer_type="LateralStructureLayer",
)
```

Then pass `feature_id`, `feature_name`, or `feature_index` to
`create_spatial_review_package()` or `zoom_to_geometry_layer()`.

### Lower-Level Steps

Use lower-level calls when you need custom control over each operation.

1. Initialize or inspect the project with ras-commander.

```python
from ras_commander import init_ras_project, ras, RasMap

init_ras_project(r"C:\Projects\MyModel", "6.6")
print(ras.rasmap_df)
print(RasMap.list_geometry_layers(ras.project_folder))
print(RasMap.list_map_layers(ras.project_folder))
```

2. Configure the spatial QA view.

Use terrain plus target geometry elements for the clearest RASMapper review.
The legend checkbox is stored as `RegenerateForScreen="True"` on `SurfaceFill`
entries. Result and map layers are hidden by default in review packages unless
they are explicitly included or selected.

```python
RasMap.set_geometry_layer_visibility(
    ras.project_folder,
    geometry_number="04",
    layer_type=["RASD2FlowArea", "LateralStructureLayer"],
    checked=True,
    exclusive=True,
)

RasMap.set_terrain_layer_visibility(
    ras.project_folder,
    terrain_name="TerrainWithChannel",
    checked=True,
    exclusive=True,
)

RasMap.set_result_layer_visibility(ras.project_folder, checked=False)

RasMap.set_map_layer_visibility(
    ras.project_folder,
    category="land_classification",
    checked=True,
    exclusive=True,
)

RasMap.set_update_legend_with_view(ras.project_folder)
```

3. Set a deterministic viewport.

Prefer HDF-derived extents over hand-entered coordinates when reviewing a known
geometry element.

```python
view = RasMap.zoom_to_geometry_layer(
    ras.project_folder,
    geometry_number="04",
    layer_type="LateralStructureLayer",
    feature_name="Lateral Structure 1",
)
print(view)
```

4. Launch standalone RASMapper and capture evidence.

```python
process = RasMap.open_rasmapper(ras.project_folder, ras_version="6.6")
snapshot = RasMap.capture_rasmapper_snapshot(
    pid=process.pid,
    output_path=ras.project_folder / "qa" / "rasmapper_spatial_review.png",
    delay_seconds=5,
    timeout_seconds=1800,
)
RasMap.close_rasmapper(pid=process.pid)
print(snapshot)
```

## Agent Output Contract

When this skill is used for QA/QC, report:

- Project path and `.rasmap` path inspected
- Geometry number/name and layer types toggled
- Feature selector and selected feature metadata, when used
- Terrain layer and whether `Update Legend with View` was enabled
- Result and map-layer visibility state used for the figure
- Current view bounds and whether they came from HDF-derived extents
- Snapshot file paths
- Visual findings, with uncertainty separated from confirmed defects
- Any follow-up numerical checks needed

## Review Heuristics

For spatial review, look for:

- Target layer is actually visible in the RASMapper tree
- Terrain is checked and visually informative
- Results or terrain legends are view-updated when raster interpretation matters
- 2D flow area context remains visible when inspecting lateral structures
- Reference layers align with model geometry and terrain
- Structures, levees, roads, or breaklines appear misaligned with mesh faces
- The screenshot view includes enough surrounding context to explain the finding

The future mesh face and breakline alignment score should convert these visual
signals into quantitative diagnostics. Until that API exists, treat screenshots
as evidence for human or agent review, not as the final engineering determination.

## Cross-References

Related agents:

- `rasmapper-spatial-reviewer` - primary agent for spatial screenshot QA/QC
- `quality-assurance` - RasCheck/RasFixit validation and repair
- `hdf-analyst` - HDF extraction and numerical result context
- `hecras-project-inspector` - project and DataFrame intelligence

Related skills:

- `qa_repair_geometry`
- `hecras_extract_results`
- `hecras_parse_geometry`
- `hecras_screenshot`
