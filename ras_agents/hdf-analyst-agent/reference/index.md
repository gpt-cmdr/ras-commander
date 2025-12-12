# RASMapper Interpolation - Quick Reference Index

## Start Here

1. **README.md** - Complete project overview, usage examples, and folder structure
2. **AGENTS.md** - Guidelines for AI agents and contributors
3. **RASMAPPER_DECOMPILATION_REPORT.md** - Technical decompilation findings

## Key Research Documents

### Algorithm Documentation
- `research/findings/COMPLETE_ALGORITHM_REFERENCE.md` - Complete algorithm specification
- `research/findings/THE_ANSWER.md` - Ben's Weights discovery narrative
- `research/findings/horizontal_2d.md` - Horizontal interpolation (VALIDATED)
- `research/findings/sloped_cell_corners.md` - Sloped interpolation (VALIDATED)

### Implementation Plans
- `planning/IMPLEMENTATION_PLAN.md` - Original implementation roadmap
- `planning/SIMPLIFIED_PLAN.md` - Simplified workflow
- `planning/SLOPED_INTERPOLATION_ALGORITHM.md` - Algorithm specification

## Key Scripts

### Main Tools
- `scripts/rasmap_interpolation.py` - CLI for interpolation testing
- `scripts/compare_mesh_vs_raster.py` - Validation tool
- `scripts/rasprocess_storemap.py` - RASProcess automation

### Validation
- `scripts/final_sloped_implementation.py` - Final validated algorithm
- `scripts/compare_horizontal_vs_sloped.py` - Method comparison

## Decompiled Sources

### Key Files
- `decompiled_sources/RasMapperLib.RASGeometryMapPoints.decompiled.cs` - Ben's Weights algorithm
- `decompiled_sources/RasMapperLib.Mapping.SlopingCellPoint.decompiled.cs` - Vertex interpolation
- `decompiled_sources/RasMapperLib/` - Full RasMapperLib.dll decompilation (947 files)

## Test Data

Located in `.old/archived_data/Test Data/`:
- **BaldEagleCrkMulti2D - Horizontal/** - Horizontal ground truth
- **BaldEagleCrkMulti2D - Sloped - Cell Corners/** - Sloped ground truth (9 plans)

Recommended test plan: **p03 (Single 2D)** - smallest, simplest geometry

## Quick Start

```bash
# Run horizontal interpolation
python scripts/rasmap_interpolation.py \
  --project ".old/archived_data/Test Data/BaldEagleCrkMulti2D - Horizontal" \
  --plan 03 --variables WSE --interpolation-method horizontal

# Run sloped interpolation
python scripts/rasmap_interpolation.py \
  --project ".old/archived_data/Test Data/BaldEagleCrkMulti2D - Sloped - Cell Corners" \
  --plan 03 --variables WSE --interpolation-method sloped
```

## Status Summary

| Component | Status | Validation |
|-----------|--------|------------|
| Horizontal interpolation | ✅ Complete | RMSE < 0.001 ft |
| Sloped interpolation | ✅ Complete | Median |diff| = 0.0001 ft |
| Decompilation | ✅ Complete | 947 C# files extracted |
| Documentation | ✅ Complete | Full algorithm reference |
| Implementation | ✅ Complete | `RasMap.map_ras_results()` |

---

**Last Updated**: 2025-12-11  
**See README.md for complete documentation**
