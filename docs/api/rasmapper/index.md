# RASMapper API

Use this section to configure spatial layers, inspect a model in RASMapper,
complete geometry, generate 2D meshes, and export stored maps. These operations
span several static namespaces; there is no single RASMapper object to create.

| Task | Primary API | Inputs | Outputs and effects |
|---|---|---|---|
| Discover or author spatial layers | [RasMap: layers and associations](layers.md) | Project, `.rasmap`, terrain/classification sources | Layer inventories, registrations, classification HDFs, compiled-HDF associations |
| Configure a spatial review | [RasMap: display and review](display.md) | Registered layers, geometry selectors, view bounds | Saved `.rasmap` display state; optional native-window screenshots and review bundles |
| Plot profiles and reference hydrographs | [Profiles and reference results](profiles.md) | Saved plan results, line geometry, and route-specific terrain/runtime | Station profiles, time series, batch plots; explicit extraction provenance |
| Export hydraulic result maps | [Stored maps](stored-maps.md) | Computed plan HDF, associated terrain, map types and profiles | Raster paths, batch tables, or an orchestration report |
| Complete geometry-derived layers | [Geometry completion](geometry-completion.md) | Existing compiled geometry HDF and spatial associations | Native edge lines, interpolation surfaces, property tables, validation diagnostics |
| Author and generate 2D meshes | [Automated mesh generation](mesh-generation.md) | Geometry text, current compiled HDF, domain, spacing and refinements | Computation points, mesh evidence, optional property tables |
| Create or export terrain | [Terrain API](../terrain.md) | Elevation rasters or registered native terrain | Terrain HDF, GeoTIFFs and export evidence |
| Read mesh and hydraulic results | [HDF API](../hdf.md) | Geometry or computed plan HDF | Geometry, arrays, time series and derived products |

## Configuration, native processing, and computation

For many-line plotting, start with [2D profiles and reference workflows](../../user-guide/2d-profile-and-reference-workflows.md).
Solver-recorded reference results are also stored in HDF: choosing a file format
does not identify whether a quantity was computed during the run or reconstructed
afterwards. The guide explains that distinction and when a new run is needed.

Editing `.rasmap` visibility does not change hydraulic results. Registering a
terrain in `.rasmap` does not prove the compiled geometry references it.
Generating computation points does not compute a hydraulic solution. Use
[RasCmdr](../core.md#rascmdr) to execute plans after geometry and boundary inputs
are prepared; then inspect results before generating stored maps.

File readers and XML editors do not all require HEC-RAS. Native authoring,
geometry completion, mesh generation, and map export have operation-specific
runtime requirements described on the child pages. GUI screenshots additionally
require a visible desktop. A successful native operation is evidence for that
operation, not a hydraulic or regulatory acceptance determination.

For task-oriented walkthroughs, see [Spatial data and RASMapper](../../user-guide/spatial-data.md)
and the [example catalog](../../examples/index.md). The signatures below each
child page come from the library source, including optional parameters and
method-specific return contracts.
