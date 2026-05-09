# Manning's n Horizontal Variation Block Limit

Issue: CLB-663

Date: 2026-05-08

## Finding

HEC-RAS 6.6 accepts and computes a maximum of **20 Manning's n horizontal variation blocks per 1D cross-section**.

The first failing count is 21. For counts greater than 20, HEC-RAS writes/preserves the requested Manning's n values in the geometry HDF, but the compute path stops with a data error:

```text
cross section has <N> Manning's n values.  There is a limit of 20 per cross section.
```

This means the practical compute limit is 20 blocks per cross-section. Values above 20 are not silently truncated; they are preserved in the geometry HDF and rejected by the HEC-RAS data checker.

## Probe Method

The probe used only ras-commander APIs:

- `RasExamples.get_example_projects("6.6")` / `RasExamples.extract_project()`
- `init_ras_project()` and ras-commander DataFrames to locate plan geometry files
- `GeomCrossSection.get_mannings_n()` and `GeomCrossSection.set_mannings_n()`
- `RasCmdr.compute_plan()` with HEC-RAS 6.6
- HDF inspection of `/Geometry/Cross Sections/Manning's n Info`

Three 1D steady-state example projects were tested:

| model_key | Example project | Plan | Target cross-section |
|---|---|---:|---|
| `chanmod` | Example 16 - Channel Modification | 02 | Critical Cr. / Upper Reach / RS 7 |
| `beaver` | Example 2 - Beaver Creek | 01 | Beaver Creek / Kentwood / RS 5.39 |
| `wailupe` | Wailupe GeoRAS | 01 | Wailupe / lower / RS 0.06 |

The tested block counts were 20, 21, 25, 30, 40, 50, and 100. Count 20 was included to confirm the upper accepted value; 21 was included to identify the exact first failure.

## Result Summary

`accepted_blocks` is the count preserved in the geometry HDF. `ras_behavior` is the observed compute behavior.

| model_key | requested_blocks | accepted_blocks | ras_behavior |
|---|---:|---:|---|
| chanmod | 20 | 20 | accepted_preserved |
| chanmod | 21 | 21 | limit_error |
| chanmod | 25 | 25 | limit_error |
| chanmod | 30 | 30 | limit_error |
| chanmod | 40 | 40 | limit_error |
| chanmod | 50 | 50 | limit_error |
| chanmod | 100 | 100 | limit_error |
| beaver | 20 | 20 | accepted_preserved |
| beaver | 21 | 21 | limit_error |
| beaver | 25 | 25 | limit_error |
| beaver | 30 | 30 | limit_error |
| beaver | 40 | 40 | limit_error |
| beaver | 50 | 50 | limit_error |
| beaver | 100 | 100 | limit_error |
| wailupe | 20 | 20 | accepted_preserved |
| wailupe | 21 | 21 | limit_error |
| wailupe | 25 | 25 | limit_error |
| wailupe | 30 | 30 | limit_error |
| wailupe | 40 | 40 | limit_error |
| wailupe | 50 | 50 | limit_error |
| wailupe | 100 | 100 | limit_error |

The full CSV is `research/mannings_n_block_limit_results.csv`.

Durable proof artifacts are under `H:/Symphony/ras-commander/CLB-663/`:

- `mannings_n_block_limit_results.csv`
- `mannings_n_block_limit_results.json`
- `mannings_n_probe_runs/`
- `terminal-logs/20260508_164616_probe_full_mannings_matrix.terminal.log`

## Existing Example Catalog

The catalog pass parsed 3,030 cross-section records from HEC-RAS 6.6 example projects and found 2,931 cross-sections with parseable Manning's n values. The largest observed real-world Manning's n horizontal variation count in those examples was 8.

Top observed counts:

| Example project | Max existing blocks |
|---|---:|
| Example 18 - Advanced Inline Structure | 8 |
| Example 22 - Groundwater Interflow | 8 |
| Example 16 - Channel Modification | 8 |
| Example 2 - Beaver Creek | 6 |
| Example 5 - Multiple Openings | 6 |
| Example 6 - Floodway Determination | 6 |

The catalog artifacts are stored at:

- `H:/Symphony/ras-commander/CLB-663/example_mannings_catalog.csv`
- `H:/Symphony/ras-commander/CLB-663/example_mannings_summary.csv`

## Implementation Note

During probe setup, `GeomCrossSection.set_mannings_n()` needed a writer correction. Manning's n records are triplets, so fixed-width wrapping must use 9 scalar values per line (3 triplets), not the generic 10 values per line. The writer also now replaces the old Manning's n data block as a slice so expanding a block does not overwrite following cross-section records.
