# HEC-RAS terrain-export version compatibility audit

**Date:** 2026-08-29
**Scope:** HEC-RAS 6.3 through the current 7.0.1 Classic release, every published intermediate release, locally installed 6.7 betas, and the requested 7.1 release-status check

## Decision

`RasTerrain.export_rasmapper_terrain()` accepts exactly HEC-RAS 6.4.1, 6.5,
6.6, and 7.0.1. It rejects every other version before output directories or native
processes are created. When an initialized `RasPrj` is supplied, both
`ras_version` and the identifiable release folder in `ras_exe_path` are
checked, and an explicit `hecras_version` must name the same exact release.

The earlier family-level decision to accept 6.6.x and 7.0.x was too broad.
HEC-RAS 7.0.0 has an official known terrain-modification export defect. The
officially signed 7.0.1 installer was downloaded, installed, independently
reflected, and run through the native semantic matrix before that exact patch
release was accepted. Other patch and beta terms cannot enter this private managed API on the
strength of a compatible major/minor family alone.

## Independent official changelog review

The official release notes and Mapper manuals document user-visible behavior,
not private managed method signatures. They are evidence about semantics and
known defects; reflection and real exports remain necessary for the callable
contract.

| Release | Official-source finding | Audit disposition |
|---|---|---|
| 6.3 | The [6.3 Terrain Layer manual](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/6.3/terrain-layer) documents separate resample/clip operations, not the later unified export options. The internal `6.3.0.2` spelling encountered in model/runtime provenance is treated as part of this unsupported line. | Unsupported; installed binary also lacks the required bounded modification-aware method. |
| 6.3.1 | The [6.3.1 release notes](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/6.3.1) describe a bug-fix release; its [resolved issues](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/6.3.1/resolved-issues) do not add the required export contract. | Unsupported; installed binary matches 6.3's old surface. |
| 6.4.0 | The [6.4 Terrain Layer manual](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/6.4/terrain-layer) still documents the older three export operations. The later 6.4.1 notes identify a terrain-creation elevation defect in 6.4. | Unsupported and not locally installed. |
| 6.4.1 | HEC's [6.4.1 resolved issues](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/6.4.1/resolved-issues) say that creating a new terrain in 6.4 could sometimes add 1.0 to elevations; 6.4.1 is the fixed release. | Supported after exact reflection and native semantic qualification. |
| 6.5 | The [6.5 resolved issues](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/6.5/resolved-issues) fix geometry-extent clipping and creation of encroachment terrains without the source terrain's modifications. The [6.5 Terrain Layer manual](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/6.5/terrain-layer) still presents the older UI. | Supported after exact reflection and native semantic qualification. |
| 6.6 | The [6.6 Terrain Layer manual](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/6.6/terrain-layer) explicitly documents Extent, Cell Size, Export to Single Raster, and Rasterize Terrain Modifications in one operation. | Supported; qualified on native Windows and under Wine. |
| 6.7 prereleases | HEC's [official download archive](https://www.hec.usace.army.mil/software/hec-ras/download.aspx) lists 6.7 Beta, Beta 2, Beta 3, Beta 4a, and Beta 5, followed by 7.0 rather than a final 6.7. The [7.0 new-features page](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/7.0/new-features) calls 7.0 the official release of the software previously titled 6.7 Beta. The [Beta terrain tutorial](https://www.hec.usace.army.mil/confluence/rasdocs/hecras/beta/tutorials/adding-terrain-mods-land-cover-and-n-values) uses Generate New RAS Terrain to rasterize vector pier modifications. | Local folders labeled Beta 4 and Beta 5 passed probes, but all 6.7 prereleases remain unsupported. The Beta 4 folder's identity cannot be equated silently with HEC's archived Beta 4a package; the earlier binaries were unavailable. |
| 7.0.0 | HEC's [7.0 known issues](https://www.hec.usace.army.mil/confluence/rasdocs/raski/7.0) say a new raster can omit the bottom, minimum-Y portion of a terrain modification, especially a triangular-nose pier; no workaround is given. | Unsupported even though the available bounded probes passed. Those fixtures do not disprove the documented defect. |
| 7.0.1 | HEC's [7.0.1 resolved issues](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/latest/resolved-issues) list the 7.0.0 terrain-modification export issue as fixed. | Supported after exact installed-binary reflection and native semantic qualification. The defect-specific triangular-nose/minimum-Y fixture was not available, so the official fix notice and broader modification checks are both recorded. |
| 7.1 | The official [HEC-RAS downloads page](https://www.hec.usace.army.mil/software/hec-ras/download.aspx) and [HEC download releases](https://github.com/HydrologicEngineeringCenter/hec-downloads/releases) publish no HEC-RAS Classic 7.1 installer or release. The latest Classic package is 7.0.1. | Unsupported because there is no official binary to install, reflect, or qualify. HEC-RAS 2025 is a different product and is not treated as 7.1. |

## Installed managed API matrix

The installed `RasMapperLib.dll` files were reflected and the relevant
`TerrainLayer` bodies were independently decompiled.

| Installed runtime | `GenerateNewRasTerrain` | Relevant result |
|---|---|---|
| 6.3 | Absent | Public `ExportResampleToSingleFile(string, double, TiffMetadata<float>, ProgressReporter)` is full-extent and has no `resampleVecMods` argument. |
| 6.3.1 | Absent | Same old surface as 6.3. |
| 6.4.1 | Present, non-public | Exact nine-parameter contract required by the helper. |
| 6.5 | Present, non-public | Exact nine-parameter contract required by the helper. |
| 6.6 | Present, non-public | Exact nine-parameter contract required by the helper. |
| 6.7 Beta 4 (local folder label) | Present, non-public | Exact nine-parameter contract required by the helper; archived Beta 4a package provenance not independently established. |
| 6.7 Beta 5 | Present, non-public | Exact nine-parameter contract required by the helper. |
| 7.0.0 | Present, non-public | Same invocation contract; body adds ground-line force-render handling. |
| 7.0.1 | Present, non-public | Same nine-parameter invocation contract; signed official installer reports `Ras.exe` 7.00.0001 and `RasMapperLib.dll` 2.0.0.0. |

For 6.4.1 through 7.0.1 the reflected signature is:

```text
GenerateNewRasTerrain(
    string,
    Extent,
    double,
    bool resampleTo1RFI,
    bool resampleVecMods,
    ProgressReporter,
    Action<SpatialIndex<int>>,
    List<string>,
    ref TiffMetadata<float>)
```

The checked bodies call the native resample path with `resampleVecMods`, write
a single TIFF when `resampleTo1RFI=True`, append exactly one filename to the
supplied `List<string>`, update the referenced metadata, and report completion
through the supplied `ProgressReporter`. `ExportRasterOptions` belongs to the
`ExportRaster` namespace; it is not a `RasMapperLib` type.

## Native semantic matrix

Each locally available candidate was tested through the packaged production
helper against the same bounded windows. The experimental harness bypassed
only the then-current version allow-list; selection, inspection, invocation,
partial promotion, receipt generation, and GeoTIFF validation remained the
production path.

For every checked runtime:

- UPGU3 2x modification-off and modification-on exports were 33 columns by 48 rows.
- UPGU3 4x modification-on exports were 17 columns by 24 rows.
- Exactly 73 valid cells changed when modifications were enabled and 1,511 valid control cells remained unchanged.
- Every changed cell was lower than the modification-off value.
- The bounded Muncie `TerrainWithChannel` export was 16 columns by 23 rows, loaded two source rasters, preserved one authoritative grid, and produced checksum 4221.
- Grid transforms and CRS were equal across all checked versions.

| Runtime | UPGU3 modification delta range, feet | Four export elapsed range | Total elapsed |
|---|---:|---:|---:|
| 6.4.1 | -26.90625 to -0.71875 | 1.540-3.302 s | 10.07 s |
| 6.5 | -26.90625 to -0.71875 | 1.531-3.100 s | 9.94 s |
| 6.6 | -27.0625 to -0.09375 | 1.477-3.479 s | 10.80 s |
| 6.7 Beta 4 (local label) | -27.0625 to -0.09375 | 1.521-3.168 s | 10.23 s |
| 6.7 Beta 5 | -27.0625 to -0.09375 | 1.493-3.225 s | 10.35 s |
| 7.0.0 | -27.0625 to -0.09375 | 1.452-4.775 s | 11.64 s |
| 7.0.1 | -27.0625 to -0.09375 | 1.490-3.874 s | 11.70 s |

The vendor outputs are not pixel-identical across all stable releases. The
6.5 modification-on 2x result differs from 6.4.1 at 10 cells, within -0.59375
to +0.34375 feet. The 6.6 results differ more broadly from 6.4.1, while the
6.6, Beta 4, Beta 5, 7.0.0, and 7.0.1 outputs are pixel-identical for these windows.
This is recorded as version-dependent vendor behavior, not normalized or
hidden by ras-commander.

## Final public contract and qualification gaps

- Accepted exact releases: 6.4.1, 6.5, 6.6, and 7.0.1.
- The existing public `6.4` alias is accepted only because `get_ras_exe()` maps it to the fixed 6.4.1 installation. An executable actually located in a `6.4` release folder is rejected.
- Compact/plan-file spellings normalize to the same exact accepted release: `6.41`/`641`, `6.50`/`65`, `6.60`/`66`, and `7.01`/`701`.
- Any patch/build version not explicitly qualified, including 6.4.1.1, 6.6.0.1, and 6.6.1, fails closed.
- Native Windows qualification covers all four accepted releases.
- Wine qualification covers the exact 6.6 runtime. Matching 6.4.1, 6.5, and 7.0.1 Wine runs remain a qualification gap, not an implied result.
- The local fixtures do not contain the exact triangular-nose/minimum-Y regression described in HEC's 7.0.0 known issue. HEC's explicit 7.0.1 fix notice plus the bounded 73-cell modification comparison and stitched export support acceptance, while this defect-specific fixture remains a documented qualification gap.
- HEC-RAS Classic 7.1 cannot be added until HEC publishes an exact release that can be independently reflected and qualified. HEC-RAS 2025 must be evaluated under its own product/version contract if support is later requested.
