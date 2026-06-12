# Geometry Subpackage Contract

This file is the canonical local instruction file for `ras_commander/geom/`.

## Scope

- Parent guidance from `ras_commander/AGENTS.md` and the repo root still applies.
- This directory handles plain-text HEC-RAS geometry parsing and modification.

## Core Modules

- Parsing utilities: `GeomParser`
- Cross sections: `GeomCrossSection`
- Storage and 2D areas: `GeomStorage`, `GeomLandCover`
- Structures: `GeomLateral`, `GeomInlineWeir`, `GeomBridge`, `GeomCulvert`, `GeomCulvertGIS`
- HTAB logic: `GeomHtab`, `GeomHtabUtils`
- Metadata and reference features: `GeomMetadata`, `GeomReferenceFeatures`
- Preprocessor helpers: `GeomPreprocessor`

## Critical Geometry Rules

- HEC-RAS geometry files use fixed-width numeric formatting.
- Standard numeric formatting is 8-character fields with 10 values per line.
- Count declarations can describe pairs rather than raw scalar count. Interpret them carefully before reading or writing.
- Preserve exact river, reach, and river-station identifiers. They are case-sensitive and must match the source file.
- Respect the HEC-RAS cross-section point-count limit (500) when modifying cross sections.
- Respect the Manning's n block limit of 20 per cross section (`GeomCrossSection.MAX_MANNINGS_N_BLOCKS`). HEC-RAS 6.6 rejects 21+ blocks at compute time.
- Create or preserve `.bak` backups before destructive writes.

## Modification Rules

- Use existing parser and formatter helpers rather than hand-rolling string slicing.
- Keep bank stations explicit when writing cross-section geometry.
- When changing HTAB or geometry settings, preserve nearby formatting conventions and required terminators.
- Prefer geometry-specific helper classes over direct text surgery when an existing helper already handles the section.

## Common Use Cases

- Cross-section extraction and modification: `GeomCrossSection`
- 2D flow area settings and storage curves: `GeomStorage`
- SA/2D connections and laterals: `GeomLateral`
- Structure geometry and metadata: `GeomBridge`, `GeomInlineWeir`, `GeomCulvert`
- Culvert GIS reconstruction / hydraulic-validity checks: `GeomCulvertGIS`
- HTAB optimization from results: `GeomHtab`

## Culvert GIS Validation (`GeomCulvertGIS`)

Reconstruct and validate culvert placement from geometry; complements `GeomCulvert`
(plain-text record authoring). All static.

- **1D inline culverts** (`reconstruct_barrels`, `validate_placement`): a 1D culvert has
  no stored GIS line; the barrel is *reconstructed* from the bounding XS GIS cut lines +
  culvert US/DS stations + `US Distance` + reach lengths (one per-barrel reach-length
  basis). Accuracy ~mean 2.6% vs HEC-RAS, so the length check is an informational
  `REVIEW`. `validate_placement` runs: invert vs the **local bed under the opening**
  (not a far-off XS minimum), HDS-5 entrance/exit-loss guidance, and the length indicator.
- **2D connection culverts** (`mesh_cell_min_from_terrain`, `validate_2d_inverts`): for a
  culvert/structure end on a SA/2D connection, the relevant streambed is the minimum
  terrain elevation of the nearest 2D mesh cell. Computed **directly from the terrain
  raster** (rasterio zonal-min over the `HdfMesh` cell polygon), so it needs no 2D
  hydraulic-table preprocessor (a generated mesh is still required). `all_touched=False`
  by default (pixel-center; `True` understates a minimum). Off-mesh points (beyond
  `max_dist_to_cell`) report `OFF_MESH`. Requires `rasterio`.
- 2D SA/2D connection culverts DO store explicit per-barrel GIS endpoint coordinates
  (`Connection Culv=` + `Conn Culvert Barrel=` + a packed `US_x US_y DS_x DS_y` line), so
  for 2D the +/-1% GIS-length rule is exact. 1D inline culverts do not store a GIS line.

## SA/2D Connection Culvert Authoring (`GeomLateral`)

- `get_connection_culverts(geom, connection_name)` reads the `Connection Culv=` group(s)
  on a connection -> one row per barrel (shape/dims/inverts/loss + per-barrel US/DS
  stations and GIS endpoint coordinates). `set_connection_culverts(geom, connection_name,
  culverts)` authors/replaces them (list of group dicts, each with a `barrels` list of
  `us_xy`/`ds_xy`); stations default to the connection-line projection of the barrel
  midpoint. Format verified against production LA LWI 2D models and the authored output
  confirmed to compute in HEC-RAS.
- Record layout: per group `Connection Culv=Shape,Span,Rise,Length,n,Ke,Kex,Chart,Scale,
  USinv,DSinv,NumBarrels,Name, 0 ,` then an 8-char fixed-width station line (one US/DS pair
  per barrel), then per barrel `Conn Culvert Barrel=<id>,<name>,2` + a 16-char fixed-width
  `US_x US_y DS_x DS_y` line, then `Conn Culv Bottom n=`. The 3 `Conn HTab` lines appear
  ONCE after the last group. Coordinate lines may be fixed-width *packed* (no delimiter) ->
  parse by column (`_parse_fw_floats`).
- `set_connection_culverts` warns when a barrel's GIS endpoint distance differs from the
  entered `Length` by > 1% (HEC-RAS may reject it).

## Land Cover Manning's n Override Architecture

HEC-RAS resolves per-cell Manning's n through a layered override hierarchy:

1. **Sidecar HDF Variables** — authoritative base n-values per class
2. **LCMann Table= (plain text .g##)** — optional base overrides
3. **LCMann Region Table=** — optional per-region calibration overrides
4. **Geometry HDF Calibration Table** — final preprocessed values (NaN = use sidecar)

`LCMann Table=0` means no overrides defined (empty table). NaN in the calibration table is normal — HEC-RAS reads the sidecar directly. There is no 16-class limit.

See `.claude/rules/hec-ras/land-cover-mannings-n.md` for full documentation.

## Testing

- Validate geometry changes against real `.g##` files.
- Re-run geometry preprocessing or model execution when a change can affect HEC-RAS interpretation.
