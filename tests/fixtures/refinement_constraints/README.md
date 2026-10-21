# Refinement constraint patch

`local_patch.json` contains 26 computation points, one trimmed breakline and
one trimmed refinement polygon from a delivered eBFE geometry. Coordinates
are translated to a local origin; names and the geographic origin are omitted.
The 800-by-800-foot window is a test boundary, not a delivered model boundary.
No terrain, hydraulic results, full model, or project metadata is included.

HEC-RAS 6.6 RasMapperLib reconstructs the target cell with nine faces using
breakline constraints and seven faces when the region edge is also constrained.
The corresponding states are `MaxFacesPerCellExceeded` and `Complete`.
This fixture tests mesh classification, not hydraulic results.
