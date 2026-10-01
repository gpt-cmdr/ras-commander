# Automated 2D mesh generation

`GeomMesh` authors computation points and invokes the native RASMapper mesh
engine. Import it from `ras_commander.geom` (also exported at package root).
Use `HdfMesh` to inspect meshes; use `RasCmdr` to compute hydraulic plans.

| Stage | API | Input → output |
|---|---|---|
| Bootstrap points | `generate_computation_points` | Authored perimeter text and spacing -> regular-grid computation points in text; no existing HDF required |
| Compile geometry | [RasCmdr preprocessing](../core.md#rascmdr) | Referencing project/plan and authored geometry -> native compiled HDF workspace |
| Author controls | Breakline/refinement methods | Names, spacing and polygons/flowlines → updated text or compiled-HDF controls, as specified per method |
| Check domain | `audit_domain_containment` | Selected 2D area and cell spacing → `DomainContainmentResult` |
| Regenerate mesh | `generate`, `generate_all` | Current compiled HDF, domain, breaklines/refinements and spacing -> `MeshResult` records and updated computation points |
| Build properties | `compute_property_tables` | Mesh and terrain/classification associations → native property tables; Boolean result |
| Check boundary conflicts | `detect_bc_conflicts`, `fix_bc_conflicts` | Compiled perimeter faces and BC lines → conflicts or `BCFixResult`; repair can modify HDF |

```mermaid
flowchart LR
    A[Geometry text and spatial inputs] --> S[Bootstrap points if no mesh exists]
    S --> B[Native geometry preprocessing]
    B --> C[Author and audit mesh controls]
    C --> D[Generate computation points and mesh]
    D --> E[Review repairs and associations]
    E --> F[Build property tables]
    F --> G[Prepare and compute hydraulic plan]
```

`generate_computation_points()` creates a breakline-unaware regular grid from
the authored perimeter. HEC-RAS preprocessing then builds the full mesh.
`GeomMesh.compile_geometry()` is a disabled compatibility shim and never
returns successfully; it is documented below only for compatibility.
RASMapper completion of an existing HDF is not text-to-HDF compilation.

## Runtime and persisted changes

Native mesh generation uses Windows Python, pythonnet and the selected installed
HEC-RAS `RasMapperLib.dll`. The [existing version matrix and qualification notes](../geometry.md#hec-ras-version-support-for-headless-mesh-generation)
cover 6.0–7.0.1 and the specifically tested Windows-Python-under-Wine setup;
this does not make native Linux Python a supported CLR runtime. Select
`hecras_dir` explicitly for reproducibility: `generate()` otherwise discovers
the newest installation, which need not match the project's version. Use a
fresh process when changing the loaded DLL version.

`generate()` needs a content-current compiled HDF workspace. Its
`recompile_via_rasexe=True` option refreshes missing/stale HDF through the library's
preprocessor and requires an initialized project with a referencing plan.
Computation points are written into geometry text. Automatic perimeter repairs
can also change text and HDF: work on a disposable project copy and inspect
`MeshResult.perimeter_repairs`, backups, displacement and area changes.
See the [existing repair contract](../geometry.md#geommesh) for failure semantics.

The domain gate checks mesh-owned breaklines, refinements and structures against
the exact perimeter buffered inward by one base-cell spacing. BC lines are
excluded from that gate and need their separate association/overlap checks.
Property-table success does not prove that intended land-cover assignments were
used: validate associations and inspect final cell properties.

Refinement-region `spacing_dy` is stored for schema fidelity, not evidence of
independent anisotropic Y refinement. Retain the
[release-specific refinement caveats](../geometry.md#hec-ras-refinement-region-caveats)
and [flowline-refinement workflow](../../user-guide/flowline-refinement-regions.md)
when designing an authoring workflow. GUI mesh-refresh/import operations are
separate from computation-point generation.

## Examples with retained outputs

- [230 — mesh sensitivity](../../notebooks/230_mesh_sensitivity_analysis.md)
- [231 — pipe-network mesh generation](../../notebooks/231_pipe_network_mesh_generation.md)
- [232 — Weise sediment mesh sensitivity](../../notebooks/232_weise_2d_sediment_mesh_sensitivity.md)

These notebooks retain outputs for their demonstrated models and runtimes;
they do not qualify every geometry, release or hydraulic configuration.

## Mesh methods

::: ras_commander.geom.GeomMesh.GeomMesh
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - setup_gdal_bridge
        - audit_domain_containment
        - set_breakline_spacing
        - get_breakline_names
        - set_breakline_name
        - get_breakline_spacing
        - get_refinement_region_names
        - set_refinement_region_name
        - get_refinement_regions
        - set_refinement_region_spacing
        - replace_refinement_regions
        - add_refinement_region
        - add_flowline_refinement_regions
        - compile_geometry
        - get_geometry_association
        - set_geometry_association
        - compute_property_tables
        - generate_computation_points
        - generate
        - generate_all
        - detect_bc_conflicts
        - fix_bc_conflicts

## Result and audit records

For `generate()` and `generate_all()`, inspect `MeshResult.ok`/`status`, error
information and repair evidence rather than cell count alone.

`generate_computation_points()` currently reports successful bootstrap with
`status == "success"`, while `MeshResult.ok` and `bool(result)` recognize only
`"complete"`. For this method, check `status`, `cell_count` and `error_message`
explicitly; a false `ok` alone does not mean bootstrap failed. Its `cell_count`
counts generated points, not a compiled hydraulic mesh.

`DomainContainmentResult.ok` means no recorded containment
violations. `BCFixResult.ok` means no unresolved conflicts in that result; these
are operation-specific states, not hydraulic acceptance criteria.

::: ras_commander.geom.GeomMeshDataclasses.MeshResult
    options:
      heading_level: 3

::: ras_commander.geom.GeomMeshDataclasses.DomainContainmentResult
    options:
      heading_level: 3

::: ras_commander.geom.GeomMeshDataclasses.DomainContainmentViolation
    options:
      heading_level: 3

::: ras_commander.geom.GeomMeshDataclasses.BCConflict
    options:
      heading_level: 3

::: ras_commander.geom.GeomMeshDataclasses.BCFixResult
    options:
      heading_level: 3
