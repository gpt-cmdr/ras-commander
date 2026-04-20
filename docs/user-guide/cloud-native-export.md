# Cloud-Native Export with ras2cng

[ras2cng](https://ras2cng.readthedocs.io) is a companion CLI and Python library from CLB Engineering Corporation that extends ras-commander with cloud-native export workflows. It builds on ras-commander's geometry and HDF parsing so you can move HEC-RAS projects into GeoParquet, DuckDB, PMTiles, and PostGIS-oriented workflows without rewriting the core model handling logic.

## Overview

ras2cng extends ras-commander rather than replacing it. Use ras-commander to initialize projects, extract example datasets, and work with HEC-RAS files; use ras2cng when you want those same project artifacts in cloud-native geospatial formats for analytics, web mapping, and archival workflows.

ras-commander uses a static class pattern, so the examples below follow the same approach: no helper objects need to be instantiated just to extract example projects or inspect files. The ras2cng CLI exposes 11 commands: `inspect`, `archive`, `geometry`, `results`, `query`, `pmtiles`, `sync`, `terrain`, `map`, `terrain-mod`, and `mannings`.

| Capability | What it enables |
|------------|-----------------|
| **Project inspection** | Discover plans, geometries, CRS, and terrain without exporting data |
| **GeoParquet export** | Write geometry and results layers to portable spatial parquet files |
| **DuckDB analytics** | Run SQL, including spatial functions, directly against exported parquet |
| **PMTiles generation** | Build vector or raster tiles for lightweight web delivery |
| **Archive packaging** | Write `manifest.json`, consolidated parquet outputs, and terrain COGs |
| **Database sync** | Push exported parquet into PostgreSQL/PostGIS when needed |

```python
from pathlib import Path

from ras_commander import RasExamples
from ras2cng import inspect_project

project_path = Path(RasExamples.extract_project("BaldEagleCrkMulti2D"))
info = inspect_project(project_path)

print(info.name)
print(f"Geometry files: {len(info.geom_files)}")
print(f"Plan files: {len(info.plan_files)}")
```

## Installation

ras2cng is distributed separately from ras-commander, so install it into the same environment where you already use ras-commander. Optional extras add DuckDB, PostGIS, and PMTiles support depending on the workflow you need.

| Install target | Command | Use when |
|----------------|---------|----------|
| **Core** | `pip install ras2cng` | Basic inspection, geometry export, results export |
| **DuckDB** | `pip install "ras2cng[duckdb]"` | SQL analytics against GeoParquet |
| **PostGIS** | `pip install "ras2cng[postgis]"` | Syncing outputs to PostgreSQL/PostGIS |
| **PMTiles** | `pip install "ras2cng[pmtiles]"` | Vector and raster tile generation |
| **Everything** | `pip install "ras2cng[all]"` | Full cloud-native workflow in one environment |

!!! note "Optional extras"
    The extras are additive. If you are not sure which workflow you need yet, `ras2cng[all]` is the simplest starting point for a dedicated analysis environment.

```bash
pip install ras2cng
pip install "ras2cng[duckdb]"
pip install "ras2cng[postgis]"
pip install "ras2cng[pmtiles]"
pip install "ras2cng[all]"
```

!!! info "External CLIs for PMTiles and Terrain"
    PMTiles generation and terrain conversion rely on external command-line tools. Install `tippecanoe`, `pmtiles`, and `gdal` with conda so they are available on your `PATH`.

```bash
conda install -c conda-forge tippecanoe pmtiles gdal
```

## Quick Start

The fastest way to understand ras2cng is to inspect a project first, then archive it. The `BaldEagleCrkMulti2D` example is a good 2D starting point because it contains multiple geometries, completed plans, and terrain content.

!!! tip "Example project"
    Use ras-commander's static `RasExamples` helper to extract the example project into a writable working folder before running the CLI or Python workflows below.

```python
from ras_commander import RasExamples

RasExamples.extract_project("BaldEagleCrkMulti2D")
```

=== "CLI"

    ```bash
    ras2cng inspect examples/example_projects/BaldEagleCrkMulti2D --json

    ras2cng archive \
      examples/example_projects/BaldEagleCrkMulti2D \
      working/cloud-native/bald_eagle \
      --results
    ```

=== "Python"

    ```python
    from pathlib import Path

    from ras_commander import RasExamples
    from ras2cng import archive_project, inspect_project

    project_path = Path(RasExamples.extract_project("BaldEagleCrkMulti2D"))

    info = inspect_project(project_path)
    print(info.name)
    print([g.geom_id for g in info.geom_files])
    print([p.plan_id for p in info.plan_files])

    manifest = archive_project(
        project_path,
        Path("working/cloud-native/bald_eagle"),
        include_results=True,
    )

    print(manifest.to_json())
    ```

## Geometry Export

Geometry export is the main entry point when you want HEC-RAS features in a GIS-friendly format. ras2cng writes GeoParquet directly from HEC-RAS geometry text files or geometry HDF files, which makes it practical to move model geometry into GeoPandas, DuckDB, or tile-generation workflows.

The most commonly used geometry layers are:

| Layer | Description |
|-------|-------------|
| mesh_cells | 2D mesh cell polygons |
| cross_sections | 1D cross-section cut lines |
| bc_lines | Boundary condition lines |
| breaklines | Mesh breaklines |
| refinement_regions | Mesh refinement polygons |
| reference_lines | Reference line transects |
| reference_points | Reference point locations |
| structures | Inline structures (bridges, culverts, weirs) |
| centerlines | River/reach centerlines |
| storage_areas | Storage area polygons |

=== "CLI"

    ```bash
    ras2cng geometry \
      examples/example_projects/BaldEagleCrkMulti2D/BaldEagleDamBrk.g09.hdf \
      working/cloud-native/mesh_cells.parquet \
      --layer mesh_cells

    # After extracting the Muncie example with RasExamples.extract_project("Muncie")
    ras2cng geometry \
      path/to/Muncie.g01 \
      working/cloud-native/cross_sections.parquet \
      --layer cross_sections
    ```

=== "Python"

    ```python
    from pathlib import Path

    from ras_commander import RasExamples
    from ras2cng import export_geometry_layers

    bald_eagle = Path(RasExamples.extract_project("BaldEagleCrkMulti2D"))
    muncie = Path(RasExamples.extract_project("Muncie"))

    export_geometry_layers(
        bald_eagle / "BaldEagleDamBrk.g09.hdf",
        Path("working/cloud-native/mesh_cells.parquet"),
        layer="mesh_cells",
    )

    export_geometry_layers(
        muncie / "Muncie.g01",
        Path("working/cloud-native/cross_sections.parquet"),
        layer="cross_sections",
    )
    ```

!!! info "GeoParquet output"
    The exported files are regular GeoParquet files, so you can read them directly with GeoPandas, DuckDB, or any other tool that supports the GeoParquet convention.

## Results Export

Results export is most useful for 2D summary outputs that you want to analyze outside HEC-RAS. A common pattern is to export mesh cell polygons first, then export a results variable and join those values onto the polygons so the output is immediately ready for mapping.

=== "CLI"

    ```bash
    ras2cng geometry \
      examples/example_projects/BaldEagleCrkMulti2D/BaldEagleDamBrk.g09.hdf \
      working/cloud-native/mesh_cells.parquet \
      --layer mesh_cells

    ras2cng results \
      examples/example_projects/BaldEagleCrkMulti2D/BaldEagleDamBrk.p03.hdf \
      working/cloud-native/maximum_depth.parquet \
      --var "Maximum Depth" \
      --geometry working/cloud-native/mesh_cells.parquet
    ```

=== "Python"

    ```python
    from pathlib import Path

    from ras_commander import RasExamples
    from ras2cng import export_geometry_layers, export_results_layer

    project_path = Path(RasExamples.extract_project("BaldEagleCrkMulti2D"))
    mesh_cells = Path("working/cloud-native/mesh_cells.parquet")

    export_geometry_layers(
        project_path / "BaldEagleDamBrk.g09.hdf",
        mesh_cells,
        layer="mesh_cells",
    )

    export_results_layer(
        project_path / "BaldEagleDamBrk.p03.hdf",
        Path("working/cloud-native/maximum_depth.parquet"),
        variable="Maximum Depth",
        geom_file=mesh_cells,
    )
    ```

!!! note "Joined output columns"
    ras2cng normalizes result variable names to snake case in the exported parquet. For example, `Maximum Depth` becomes `maximum_depth`.

## DuckDB Analytics

Once geometry or results are in GeoParquet, DuckDB is the quickest way to inspect them with SQL. This is especially useful for row counts, summary statistics, and lightweight spatial analysis without loading the full dataset into a desktop GIS.

!!! note "DuckDB table alias"
    In ras2cng queries, the registered table name is always `_`. Write SQL against `_` rather than inventing a custom table alias.

=== "CLI"

    ```bash
    ras2cng query \
      working/cloud-native/maximum_depth.parquet \
      "SELECT COUNT(*) AS wet_cells, AVG(maximum_depth) AS avg_depth FROM _ WHERE maximum_depth > 0"

    ras2cng query \
      working/cloud-native/mesh_cells.parquet \
      "SELECT COUNT(*) AS cell_count, SUM(ST_Area(geometry)) AS total_area FROM _"
    ```

=== "Python"

    ```python
    from pathlib import Path

    from ras2cng import query_parquet

    wet_cells = query_parquet(
        Path("working/cloud-native/maximum_depth.parquet"),
        """
        SELECT
            COUNT(*) AS wet_cells,
            AVG(maximum_depth) AS avg_depth
        FROM _
        WHERE maximum_depth > 0
        """,
    )

    mesh_stats = query_parquet(
        Path("working/cloud-native/mesh_cells.parquet"),
        "SELECT COUNT(*) AS cell_count, SUM(ST_Area(geometry)) AS total_area FROM _",
    )

    print(wet_cells)
    print(mesh_stats)
    ```

## PMTiles Generation

PMTiles lets you package vector or raster tiles into a single file for lightweight delivery. A common pattern is to generate vector PMTiles from GeoParquet for geometry or results polygons, then generate raster PMTiles from GeoTIFF outputs when you need image-based map layers.

!!! warning "CLI dependencies"
    Vector PMTiles require `tippecanoe`. Raster PMTiles require both `gdal_translate` and `pmtiles`. Install those CLIs before running the commands below.

=== "CLI"

    ```bash
    ras2cng pmtiles \
      working/cloud-native/mesh_cells.parquet \
      working/cloud-native/mesh_cells.pmtiles \
      --layer mesh_cells \
      --min-zoom 8 \
      --max-zoom 14

    ras2cng pmtiles \
      working/cloud-native/maximum_depth.tif \
      working/cloud-native/maximum_depth.pmtiles \
      --min-zoom 8 \
      --max-zoom 14
    ```

=== "Python"

    ```python
    from pathlib import Path

    from ras2cng import generate_pmtiles_from_input

    generate_pmtiles_from_input(
        Path("working/cloud-native/mesh_cells.parquet"),
        Path("working/cloud-native/mesh_cells.pmtiles"),
        layer_name="mesh_cells",
        min_zoom=8,
        max_zoom=14,
    )

    generate_pmtiles_from_input(
        Path("working/cloud-native/maximum_depth.tif"),
        Path("working/cloud-native/maximum_depth.pmtiles"),
        min_zoom=8,
        max_zoom=14,
    )
    ```

### MapLibre GL JS

Once you have a PMTiles file, you can serve it directly in a browser application with MapLibre GL JS and the PMTiles protocol handler.

```js
import maplibregl from "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js";
import * as pmtiles from "https://unpkg.com/pmtiles@3.0.7/dist/pmtiles.js";

const protocol = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

const map = new maplibregl.Map({
  container: "map",
  center: [-77.62, 40.92],
  zoom: 10,
  style: {
    version: 8,
    sources: {
      mesh: {
        type: "vector",
        url: "pmtiles://https://example.com/mesh_cells.pmtiles"
      }
    },
    layers: [
      {
        id: "mesh-fill",
        type: "fill",
        source: "mesh",
        "source-layer": "mesh_cells",
        paint: {
          "fill-color": "#2563eb",
          "fill-opacity": 0.2
        }
      },
      {
        id: "mesh-outline",
        type: "line",
        source: "mesh",
        "source-layer": "mesh_cells",
        paint: {
          "line-color": "#1e3a8a",
          "line-width": 1
        }
      }
    ]
  }
});
```

## Full Project Archive

For long-term storage or downstream pipelines, `archive` is the most complete ras2cng workflow. It writes a `manifest.json` catalog, consolidated parquet exports for discovered geometry and result layers, and optional terrain COGs so the entire project is easier to move between machines and services.

=== "CLI"

    ```bash
    ras2cng archive \
      examples/example_projects/BaldEagleCrkMulti2D \
      working/cloud-native/archive \
      --results \
      --terrain
    ```

=== "Python"

    ```python
    from pathlib import Path

    from ras_commander import RasExamples
    from ras2cng import archive_project

    project_path = Path(RasExamples.extract_project("BaldEagleCrkMulti2D"))

    manifest = archive_project(
        project_path,
        Path("working/cloud-native/archive"),
        include_results=True,
        include_terrain=True,
    )

    print(manifest.to_json())
    ```

An abbreviated `manifest.json` looks like this:

```json
{
  "schema_version": "2.1",
  "project": {
    "name": "BaldEagleDamBrk",
    "prj_file": "BaldEagleDamBrk.prj"
  },
  "geometry": [
    {
      "geom_id": "g09",
      "parquet": "BaldEagleDamBrk.g09.parquet"
    }
  ],
  "results": [
    {
      "plan_id": "p03",
      "parquet": "BaldEagleDamBrk.p03.parquet"
    }
  ],
  "terrain": [
    {
      "cog_file": "terrain/example_cog.tif"
    }
  ]
}
```

## Displaying in Jupyter Notebooks

GeoParquet outputs work well in notebooks because they can be loaded directly into GeoPandas for quick inspection or passed into web-map tools for interactive review. This is a practical way to validate cloud-native exports before moving them into a larger analytics or publishing pipeline.

!!! tip "Serve PMTiles over HTTP"
    Browsers do not reliably load local PMTiles files from `file://` paths. Start a lightweight local server from the output directory first.

```bash
python -m http.server 8000
```

### GeoParquet with GeoPandas

```python
import geopandas as gpd

gdf = gpd.read_parquet("working/cloud-native/maximum_depth.parquet")
gdf.explore(
    column="maximum_depth",
    cmap="Blues",
    tooltip=["mesh_name", "cell_id", "maximum_depth"],
)
```

### PMTiles with leafmap

```python
import leafmap.foliumap as leafmap

pmtiles_url = "http://localhost:8000/mesh_cells.pmtiles"
style = {
    "version": 8,
    "sources": {
        "mesh_source": {
            "type": "vector",
            "url": "pmtiles://" + pmtiles_url,
            "attribution": "PMTiles",
        }
    },
    "layers": [
        {
            "id": "mesh_cells",
            "source": "mesh_source",
            "source-layer": "mesh_cells",
            "type": "fill",
            "paint": {"fill-color": "#3388ff", "fill-opacity": 0.25},
        }
    ],
}

m = leafmap.Map(center=(40.92, -77.62), zoom=10)
m.add_pmtiles(pmtiles_url, name="Mesh Cells", style=style)
m
```

## See Also

The ras2cng project has its own documentation alongside the ras-commander notebooks that demonstrate these workflows in more detail. The links below are the best next stop when you want command reference details or larger worked examples.

```bash
python -m webbrowser https://ras2cng.readthedocs.io
python -m webbrowser https://gpt-cmdr.github.io/ras2cng/
```

- [ras2cng on Read the Docs](https://ras2cng.readthedocs.io)
- [ras2cng GitHub Pages documentation](https://gpt-cmdr.github.io/ras2cng/)
- [Example notebook 960: Cloud-Native Geometry Export](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/960_cloud_native_geometry_export.ipynb)
- [Example notebook 961: Cloud-Native Results Export](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/961_cloud_native_results_export.ipynb)
