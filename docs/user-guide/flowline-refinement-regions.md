# Flowline Refinement Regions

Aligning 2D cell faces along channels is one of the most effective ways to
improve conveyance accuracy in HEC-RAS. The HEC-RAS guide *"Aligning Cell Faces
in Channels with Refinement Regions"* describes the manual RAS Mapper workflow:
draw a polygon along the channel, set a tighter cell spacing inside it, and
regenerate the mesh so cell faces line up with the flow direction.

`GeomMesh.add_flowline_refinement_regions()` is the programmatic equivalent. It
takes channel flowlines (a GeoDataFrame, GeoSeries, or shapely line geometries),
buffers each into a refinement-region polygon, sets the region's X/Y cell
spacing, and writes the regions into an existing compiled geometry HDF through
`GeomMesh.add_refinement_region()`. It returns a list of FID / name / spacing
mappings so you can audit exactly what was written.

> **Prerequisite:** a current compiled `.g##.hdf` workspace must exist for the
> target geometry (the same precondition as `add_refinement_region()` and
> `generate()`). The helper does not regenerate the mesh itself — call
> `GeomMesh.generate()` afterward to rebuild with the new regions.

## Quick start

```python
import geopandas as gpd
from ras_commander import init_ras_project, GeomMesh

init_ras_project(r"path\to\BaldEagleCrkMulti2D", "6.6")

# Channel centerlines in any known CRS; reprojected to the project CRS
# automatically when both CRS values are known.
flowlines = gpd.read_file(r"path\to\bald_eagle_channels.shp")

mappings = GeomMesh.add_flowline_refinement_regions(
    geom_number="01",
    flowlines=flowlines,
    buffer_width=60.0,        # project units; also becomes the default cell spacing
    name_column="Name",       # optional: name regions from a GeoDataFrame column
)

for m in mappings:
    print(m["fid"], m["name"], m["spacing_dx"], round(m["area"], 1))
```

Each returned dictionary contains `fid`, `name`, `source_index`, `part_index`,
`spacing_dx`, `spacing_dy`, `buffer_width`, and `area`.

## Controlling spacing

`buffer_width` doubles as the default cell spacing. Decouple them when you want a
wide refinement corridor but tighter cells (or vice versa):

```python
GeomMesh.add_flowline_refinement_regions(
    geom_number="01",
    flowlines=flowlines,
    buffer_width=80.0,   # corridor half-width
    spacing_dx=20.0,     # cell size inside the corridor
    spacing_dy=20.0,
)
```

## Smoothing sinuous centerlines

Digitized centerlines often carry more vertices than the mesh needs. Pass
`simplify_tolerance` to apply a shapely `simplify()` before buffering, which
yields cleaner corridors and fewer near-duplicate faces:

```python
GeomMesh.add_flowline_refinement_regions(
    geom_number="01",
    flowlines=flowlines,
    buffer_width=60.0,
    simplify_tolerance=5.0,       # project units
    preserve_topology=True,
)
```

Buffering is performed with shapely (`LineString.buffer`), so bends and
confluences are joined robustly without the self-intersections a naive
segment-offset would produce. Tune the corner treatment with `cap_style`
(`"flat"`, `"round"`, `"square"`), `join_style` (`"round"`, `"mitre"`,
`"bevel"`), and `mitre_limit`.

## Avoiding bridges and confluences

Refinement corridors should not overlap structures or merge across confluences.
Three mechanisms are available:

- **`trim_geometries`** — a GeoDataFrame / geometry / iterable of geometries to
  subtract from every buffer. Use it for bridge decks, levee footprints, or
  storage-area perimeters. `trim_distance` dilates these zones before
  subtraction.
- **`trim_overlaps=True`** — subtract previously-created flowline regions from
  later ones (order-dependent), a quick way to remove confluence overlaps.
- **`trim_hook`** — a callable `f(polygon, line, source)` returning a custom
  polygon / MultiPolygon, or `None` to skip a flowline entirely.

```python
bridges = gpd.read_file(r"path\to\bridge_footprints.shp")

GeomMesh.add_flowline_refinement_regions(
    geom_number="01",
    flowlines=flowlines,
    buffer_width=60.0,
    trim_geometries=bridges,
    trim_distance=10.0,      # keep cells clear of the deck
    trim_overlaps=True,      # de-overlap at confluences
    min_area=500.0,          # drop slivers left after trimming
)
```

When a trim splits a buffer into several pieces, each part is written as its own
region (`<name>_1`, `<name>_2`, …). If a trim leaves an interior hole, the helper
logs a warning: `add_refinement_region()` writes the exterior ring only, so use a
`trim_hook` that returns split, hole-free polygons when a hole must be preserved.

## Verifying face alignment

After writing the regions, regenerate the mesh and compare cell-face angles
inside the channel against the flow direction. A typical check buffers the
centerline, selects the faces that fall inside the corridor, and reports the mean
absolute deviation between each face normal and the local flow azimuth before and
after refinement:

```python
GeomMesh.generate(geom_number="01")   # rebuild the mesh with the new regions

# Pull 2D face geometry from the results/geometry HDF and compare the
# angle between each in-channel face and the flowline tangent. A lower mean
# deviation after refinement confirms the faces now align with the channel.
```

Well-aligned faces reduce numerical diffusion of momentum across the channel and
improve the stability of the conveyance solution — the goal of the source guide.

## See also

- [Geometry Operations](geometry-operations.md) — broader `GeomMesh` workflow
- [`230_mesh_sensitivity_analysis.ipynb`](../examples/index.md) — refinement-region
  spacing sensitivity
- API reference: [`GeomMesh`](../api/geometry.md#geommesh)
