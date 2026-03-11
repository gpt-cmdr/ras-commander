---
name: hecras_export_cloud-native
description: |
  Export HEC-RAS geometry and simulation results to cloud-native formats:
  GeoParquet, PMTiles (vector and raster), and PostGIS. Uses ras2cng
  as a CLI wrapper over ras-commander parsers. Use when exporting HEC-RAS mesh
  geometry to GeoParquet, publishing results as PMTiles for web maps, querying
  HEC-RAS outputs with DuckDB SQL, syncing flood results to PostGIS, converting
  HEC-RAS to cloud-native geospatial formats, or generating vector tiles from
  simulation outputs. Keywords: GeoParquet, PMTiles, DuckDB, PostGIS, cloud-native,
  vector tiles, geometry export, mesh cells, cross sections, ras2cng.
---

# Exporting HEC-RAS to Cloud-Native Formats

**Tool**: `ras2cng` (RAS to Cloud Native GIS) — CLI wrapper over ras-commander that exports HEC-RAS
geometry and results to GeoParquet, vector/raster PMTiles, and PostGIS.

**Repo**: `C:\GH\ras2cng`

---

## Quick Start

### 1. Export Geometry to GeoParquet

```bash
# HDF geometry (*.g??.hdf) — exports mesh cell polygons by default
ras2cng geometry model.g01.hdf mesh_cells.parquet

# Text geometry (*.g01) — exports cross section cut lines by default
ras2cng geometry model.g01 cross_sections.parquet

# Select a specific layer
ras2cng geometry model.g01.hdf mesh_cells.parquet --layer mesh_cells
ras2cng geometry model.g01.hdf xs.parquet --layer cross_sections
ras2cng geometry model.g01.hdf cl.parquet --layer centerlines
```

### 2. Export Results to GeoParquet

```bash
# Single variable (default: Maximum Depth)
ras2cng results model.p01.hdf max_depth.parquet

# Specific variable
ras2cng results model.p01.hdf max_wse.parquet --var "Maximum Water Surface"

# Join results onto polygon geometry (results become spatial polygons, not points)
ras2cng results model.p01.hdf max_depth.parquet \
  --geometry mesh_cells.parquet \
  --var "Maximum Depth"

# Export ALL available summary variables to a directory
ras2cng results model.p01.hdf ./results_dir/ --all \
  --geometry mesh_cells.parquet
```

### 3. Query with DuckDB

```bash
# SQL query — table alias is always `_`
ras2cng query max_depth.parquet "SELECT mesh_name, AVG(maximum_depth) FROM _ GROUP BY mesh_name"

# Save results
ras2cng query max_depth.parquet "SELECT * FROM _ WHERE maximum_depth > 5" --output deep.csv
ras2cng query max_depth.parquet "SELECT * FROM _ WHERE maximum_depth > 5" --output deep.parquet
```

### 4. Generate PMTiles

```bash
# Vector PMTiles from GeoParquet (requires tippecanoe and pmtiles CLI)
ras2cng pmtiles mesh_cells.parquet mesh_cells.pmtiles --layer mesh_cells

# With zoom range
ras2cng pmtiles mesh_cells.parquet mesh_cells.pmtiles \
  --layer mesh_cells --min-zoom 8 --max-zoom 14

# Raster PMTiles from GeoTIFF (requires gdal_translate and pmtiles CLI)
ras2cng pmtiles results.tif results.pmtiles
```

### 5. Sync to PostGIS

```bash
ras2cng sync mesh_cells.parquet "postgresql://user:pass@localhost/mydb" mesh_cells
ras2cng sync mesh_cells.parquet "postgresql://user:pass@localhost/mydb" mesh_cells \
  --schema hydraulics --if-exists append
```

---

## Python API

All CLI commands have equivalent Python functions importable from `ras2cng`:

```python
from ras2cng import (
    export_geometry_layers,
    export_results_layer,
    export_all_variables,
    DuckSession,
    query_parquet,
    spatial_join,
    generate_pmtiles_from_input,
    sync_to_postgres,
)
from pathlib import Path

# Export geometry
export_geometry_layers(
    Path("model.g01.hdf"),
    Path("mesh_cells.parquet"),
    layer="mesh_cells",          # None = auto-select best layer
)

# Export results and join to polygon geometry
export_results_layer(
    plan_hdf=Path("model.p01.hdf"),
    output=Path("max_depth.parquet"),
    variable="Maximum Depth",
    geom_file=Path("mesh_cells.parquet"),  # Optional: join to polygons
)

# Export all variables
exported_vars = export_all_variables(
    plan_hdf=Path("model.p01.hdf"),
    output_dir=Path("./results/"),
    geom_file=Path("mesh_cells.parquet"),
)

# DuckDB query
df = query_parquet(Path("max_depth.parquet"), "SELECT * FROM _ WHERE maximum_depth > 3")

# Advanced DuckDB session
with DuckSession() as duck:
    duck.register_parquet("max_depth.parquet")     # auto-detects WKB geometry
    df = duck.sql("SELECT mesh_name, MAX(maximum_depth) FROM _ GROUP BY mesh_name")
```

---

## File Type Detection

Detection is suffix-based — no file inspection needed:

| Suffix Pattern | Type | Parser Used |
|---|---|---|
| `*.g01.hdf`, `*.g02.hdf`, ... | HDF geometry | `HdfMesh`, `HdfXsec` |
| `*.g01`, `*.g02`, ... | Text geometry | `GeomParser` |
| `*.p01.hdf`, `*.p02.hdf`, ... | Plan results | `HdfResultsMesh` |

---

## Geometry Layers

| Layer Name | Available In | Contents |
|---|---|---|
| `mesh_cells` | HDF geometry (`.g??.hdf`) | 2D mesh cell polygons (falls back to points if polygons unavailable) |
| `cross_sections` | HDF geometry + text geometry | 1D cross section cut lines |
| `centerlines` | HDF geometry + text geometry | River/reach centerlines |

**Default behavior** (no `--layer`):
- HDF geometry → exports `mesh_cells` first (falls back to first available)
- Text geometry → exports `cross_sections` first (falls back to first available)

---

## Results Variables

Column names in output GeoParquet use **snake_case** (ras-commander normalization):

| HEC-RAS Variable Name | Output Column |
|---|---|
| `Maximum Depth` | `maximum_depth` |
| `Maximum Water Surface` | `maximum_water_surface` |
| `Maximum Velocity` | `maximum_velocity` |

**Join behavior**: When `geom_file` is provided and results are points, the function merges
on `(mesh_name, cell_id)` — results columns are attached to the polygon GeoDataFrame.
Result: each row is a mesh cell polygon with hydraulic attributes.

---

## Full Typical Workflow

```bash
# Step 1: Export mesh geometry (the polygon base layer)
ras2cng geometry MyModel.g01.hdf mesh_cells.parquet --layer mesh_cells

# Step 2: Export max depth results joined to polygon geometry
ras2cng results MyModel.p01.hdf max_depth_polygons.parquet \
  --geometry mesh_cells.parquet \
  --var "Maximum Depth"

# Step 3: Query to filter deep areas
ras2cng query max_depth_polygons.parquet \
  "SELECT * FROM _ WHERE maximum_depth > 3.0 ORDER BY maximum_depth DESC LIMIT 100" \
  --output deep_areas.parquet

# Step 4: Generate PMTiles for web map
ras2cng pmtiles max_depth_polygons.parquet flood_depth.pmtiles \
  --layer flood --min-zoom 8 --max-zoom 14

# Step 5: Push to PostGIS
ras2cng sync max_depth_polygons.parquet \
  "postgresql://gis:pass@localhost/flood_db" max_depth \
  --schema hydraulics
```

---

## Installation

```bash
# From ras2cng repo root
pip install -e ".[all]"

# Or install specific extras
pip install -e ".[duckdb,postgis,pmtiles]"
```

**External CLI dependencies for PMTiles** (install separately):
- `tippecanoe` — GeoJSON → vector PMTiles
- `pmtiles` — go-pmtiles CLI for archive operations
- `gdal_translate` — raster conversion (part of GDAL)

---

## DuckDB Session Details

`DuckSession` auto-loads the `spatial` extension. `register_parquet()` detects WKB geometry
columns and wraps them with `ST_GeomFromWKB()` so spatial queries work directly:

```python
with DuckSession() as duck:
    duck.register_parquet("mesh_cells.parquet")
    # _ is the table alias; geometry column is auto-converted to GEOMETRY type
    result = duck.sql("""
        SELECT mesh_name, ST_Area(geometry) as cell_area_m2
        FROM _
        WHERE ST_Within(geometry, ST_GeomFromText('POLYGON((x1 y1, ...))', 4326))
    """)
```

---

## Error Patterns

| Error | Cause | Fix |
|---|---|---|
| `Unsupported geometry file format` | Suffix not `.g??` or `.g??.hdf` | Check file path and extension |
| `No geometry layers could be extracted` | Empty or malformed file | Verify HEC-RAS file is valid |
| `No results found for variable` | Variable name typo or not in plan | Check variable name; use `list_available_summary_variables()` |
| `tippecanoe: command not found` | PMTiles CLI not installed | Install tippecanoe separately |

---

## Source Files

| File | Purpose |
|---|---|
| `C:\GH\ras2cng\ras2cng\cli.py` | Typer CLI entrypoint (5 commands) |
| `C:\GH\ras2cng\ras2cng\geometry.py` | HDF + text geometry export |
| `C:\GH\ras2cng\ras2cng\results.py` | Plan results + polygon join |
| `C:\GH\ras2cng\ras2cng\duckdb_session.py` | DuckDB wrapper with spatial |
| `C:\GH\ras2cng\ras2cng\pmtiles.py` | Vector/raster PMTiles pipeline |
| `C:\GH\ras2cng\ras2cng\postgis_sync.py` | GeoParquet → PostGIS |
| `C:\GH\ras2cng\pyproject.toml` | Package metadata + entrypoints |

---

## See Also

- **hecras_extract_results**: Extract raw ras-commander HDF results (lower-level, no cloud-native output)
- **hecras_parse_geometry**: Parse text geometry files with ras-commander directly
