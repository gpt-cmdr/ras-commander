# Horizontal Interpolation Clipping - Validated Findings

**Status:** COMPLETE
**Date:** 2025-12-05

## Summary

The horizontal interpolation method produces **bitwise-identical values** to RASMapper where both have data. The key implementation details are:

### Validation Results

| Metric | Result |
|--------|--------|
| Value accuracy (RMSE) | 0.000000 ft |
| Pixel count match | 99.93% (1,058 edge pixels differ) |
| Wet cell filtering | Depth > 0 matches RASMapper output |

### Required Filtering Steps

To match RASMapper output extent:

1. **Depth filter**: `depth = WSE - terrain > 0` excludes dry areas
2. **Mesh cell clipping**: Restrict output to cells within computational mesh

### Implementation in RasMap.map_ras_results()

The validated horizontal method is now implemented in `ras_commander.RasMap`:

```python
from ras_commander import init_ras_project, RasMap

init_ras_project("path/to/project", "6.6")

outputs = RasMap.map_ras_results(
    plan_number="01",
    variables=["WSE", "Depth", "Velocity"],
    terrain_path="Terrain/Terrain.tif",
    output_dir="outputs",
    interpolation_method="horizontal"  # Default
)
```

### Edge Pixel Difference (38 pixels / 0.003%)

RASMapper includes ~38 pixels outside mesh cell boundaries through edge interpolation. These cannot be replicated geometrically but represent negligible difference for practical use.

## Clipping Methods

| Method | Use Case | Match |
|--------|----------|-------|
| Mesh cell clipping | Production (default) | 99.93% |
| Wet cell filtering | Remove dry areas | Required |
| RASMapper mask | Validation only | 99.997% |

## RASMapper Settings

Identified in `.rasmap` XML:
- **Horizontal**: `<RenderMode>horizontal</RenderMode>`
- **Sloped**: `<RenderMode>slopingPretty</RenderMode>` + depth-weighted faces

---

*See `.old/investigation_docs/` for detailed investigation scripts and analysis.*
