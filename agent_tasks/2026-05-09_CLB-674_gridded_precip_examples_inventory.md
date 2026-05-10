# CLB-674 Gridded Precipitation Example Inventory

Date: 2026-05-09

Issue: CLB-674, "Research: Find RasExamples and ScienceBase models using gridded precipitation"

Persistent artifacts: `H:/Symphony/ras-commander/CLB-674/research/`

## Method

- Added and ran `scripts/research/scan_gridded_precip_examples.py`.
- Queried official HEC release metadata from `https://api.github.com/repos/HydrologicEngineeringCenter/hec-downloads/releases`.
- Downloaded and scanned all available official HEC-RAS example archives for requested versions:
  - `Example_Projects_6_5.zip`
  - `Example_Projects_6_6.zip`
  - `Example_Projects_7_0.zip`
- Attempted `Example_Projects_6_3.zip` from the HEC GitHub release patterns and the HEC downloads path. All checked URLs returned 404, and no 6.3 example archive was present in the release asset inventory.
- Scanned each `.u##` file in-place from the ZIP archives for:
  - `Precipitation Mode`
  - `Met BC=Precipitation`
  - gridded DSS filename/pathname fields
  - precipitation/rain/met/radar/MRMS/QPE terms
- Queried USGS ScienceBase exact keyword searches and the `HEC-RAS` tag inventory.
- Checked public eBFE/FEMA/TWDB model URLs already referenced by ras-commander's eBFE registry.

## Artifact Index

| Artifact | Contents |
|---|---|
| `ras_examples_release_manifest.csv` | Release/archive availability, sizes, source URLs, and 6.3 failed URL probes. |
| `ras_examples_downloads.csv` | Downloaded archive byte counts and SHA-256 hashes. |
| `ras_examples_unsteady_scan.csv` | One row per scanned `.u##` file, including precipitation mode, Met BC mode, DSS references, and matched line samples. |
| `ras_examples_project_summary.csv` | Per-project summary by RAS example version. |
| `ras_examples_precip_candidate_details.json` | Expanded matched lines and file lists for files with met/precip signals. |
| `sciencebase_search_log.csv` | ScienceBase search terms, total hits, returned hits, and elapsed time. |
| `sciencebase_candidates.csv` | Thirteen ScienceBase HEC-RAS candidates evaluated with item IDs, file manifests, and precipitation metadata terms. |
| `sciencebase_raw_candidate_items.json` | Raw ScienceBase item metadata for the evaluated candidates. |
| `fema_twdb_url_checks.csv` | HEAD checks for public eBFE/FEMA/TWDB model URLs. |

## RasExamples Results

| Version | Archive status | Projects scanned | `.u##` files scanned | Active gridded precipitation found |
|---|---:|---:|---:|---|
| 6.3 | Not available from checked official release/download URLs | 0 | 0 | No archive found |
| 6.5 | Available, 427.9 MB | 39 | 68 | `BaldEagleCrkMulti2D`, `BaldEagleDamBrk.u03` |
| 6.6 | Available, 412.4 MB | 41 | 70 | `BaldEagleCrkMulti2D`, `BaldEagleDamBrk.u03` |
| 7.0 | Available, 407.5 MB | 41 | 70 | `BaldEagleCrkMulti2D`, `BaldEagleDamBrk.u03` |

### Active Gridded Precipitation Fixture

| Source | Version | Category | Project | `.u##` | Precip type | DSS reference |
|---|---|---|---|---|---|---|
| RasExamples | 6.5 | 2D Unsteady Flow Hydraulics | `BaldEagleCrkMulti2D` | `BaldEagleDamBrk.u03` | Gridded DSS, NEXRAD pathname | `.\Precipitation\precip.2018.09.dss` |
| RasExamples | 6.6 | 2D Unsteady Flow Hydraulics | `BaldEagleCrkMulti2D` | `BaldEagleDamBrk.u03` | Gridded DSS, NEXRAD pathname | `.\Precipitation\precip.2018.09.dss` |
| RasExamples | 7.0 | 2D Unsteady Flow Hydraulics | `BaldEagleCrkMulti2D` | `BaldEagleDamBrk.u03` | Gridded DSS, NEXRAD pathname | `.\Precipitation\precip.2018.09.dss` |

Relevant `.u##` lines:

```text
Flow Title=Gridded Precipitation
Precipitation Mode=Enable
Met BC=Precipitation|Mode=Gridded
Met BC=Precipitation|Gridded Source=DSS
Met BC=Precipitation|Gridded DSS Filename=.\Precipitation\precip.2018.09.dss
Met BC=Precipitation|Gridded DSS Pathname=/SHG/MARFC/PRECIP/01SEP2018:0200/01SEP2018:0300/NEXRAD/
```

### RasExamples Non-Fixtures To Avoid For Gridded API Tests

- `Muncie` has Met BC precipitation template lines, but `Precipitation Mode=Disable`.
- `Balde Eagle Creek` 1D has Met BC precipitation template lines, but `Precipitation Mode=Disable`.
- `DavisStormSystem.u01` in the 6.6 `Pipes (beta)` and 7.0 `Pipes` example has `Flow Title=Full System Rain w/ Pump` and `Precipitation Hydrograph= 21`, but the scanned file still reports `Precipitation Mode=Disable`; this is useful only as a possible pipe/rain metadata audit, not as a gridded precipitation fixture.
- Several other projects include default Met BC rows or DSS boundary files, but no enabled gridded precipitation.

## ScienceBase Results

Exact ScienceBase keyword searches returned no direct hits:

| Search | Total hits |
|---|---:|
| `"HEC-RAS" MRMS` | 0 |
| `"HEC-RAS" "gridded precipitation"` | 0 |
| `"HEC-RAS" "radar rainfall"` | 0 |
| `"HEC-RAS" QPE` | 0 |
| `"HEC-RAS" meteorological` | 0 |

The ScienceBase `tags=HEC-RAS` query returned 13 candidates. All were evaluated in `sciencebase_candidates.csv`.

| ScienceBase ID | Title short name | Downloadable model files | Precipitation evidence |
|---|---|---|---|
| `68307326d4be0269904c2372` | Millstone River Blackwells Mills 2D RAS | `RAS2D_BlackwellsMills.zip` (3251.2 MB) | No precip/radar/MRMS/QPE terms in metadata. |
| `66049bced34e64ff15492d45` | Siletz River, Oregon 1D/2D | `Siletz_2D_Model.zip` (245.7 MB), `Siletz_1D_Model.zip` (3.7 MB) | No precip/radar/MRMS/QPE terms in metadata. |
| `67a38201d34ee33d441d2f22` | Kalamazoo River Trowbridge 2D | `hec_ras_model.zip` (2976.7 MB), other archives | No precip/radar/MRMS/QPE terms in metadata. |
| `620e94dad34e6c7e83baa7ce` | Willamette River 2D reaches | five reach ZIPs, 2.2 GB to 6.6 GB each | No precip/radar/MRMS/QPE terms in metadata. |
| `6040f8f5d34eb120311874c3` | Little Blue River Grandview | `LittleBlueRiver_HEC-RAS_ModelArchive.zip` (163.3 MB) | Metadata includes `precipitation`, but not gridded/radar/MRMS/QPE. Best small ScienceBase follow-up if one is required. |
| `604a62b3d34eb120311b0e38` | Mohawk River hydraulic/temperature/nutrient | `MODEL_ARCHIVE_Final.zip` (99.4 GB) | No precip/radar/MRMS/QPE terms in metadata; very large. |
| `631405b1d34e36012efa2e6c` | Lago El Guineo HEC-HMS and HEC-RAS dam failure | `Model_files.zip` (783.6 MB) | Rainfall/PMP terms, but appears to be HEC-HMS plus HEC-RAS dam-failure modeling, not a known RAS gridded precipitation fixture. |
| `57585e4de4b04f417c2520da` | Lago El Guineo 6-hour PMP inundation shapefile | none on item | Shapefile result item, not model archive. |
| `57585f98e4b04f417c2520e4` | Lago El Guineo 24-hour 100-year inundation shapefile | none on item | Shapefile result item, not model archive. |
| `57586197e4b04f417c2520f3` | Lago El Guineo 24-hour PMP inundation shapefile | none on item | Shapefile result item, not model archive. |
| `57586143e4b04f417c2520f0` | Lago El Guineo sunny day inundation shapefile | none on item | Shapefile result item, not model archive. |
| `653c1eead34ee4b6e05bc49c` | Lower Sandusky FluEgg model archive | metadata XML only on item | Not a precipitation candidate from item metadata. |
| `682e30dbd4be020ae7e19f89` | Millstone HEC-RAS and FLOW-3D HYDRO metadata item | metadata XML only on item | Not a precipitation candidate from item metadata. |

Conclusion: ScienceBase did not yield a confirmed gridded/radar/MRMS/QPE HEC-RAS fixture from metadata-level review. The two closest follow-ups are Little Blue River (smallest model archive with a generic precipitation metadata term) and Lago El Guineo (rainfall/PMP dam-failure modeling), but neither should displace the RasExamples or Upper Guadalupe recommendations without downloading and scanning the model archives.

## FEMA Region 6 / TWDB / eBFE Check

The public eBFE URLs referenced by ras-commander are live. `fema_twdb_url_checks.csv` records the HEAD checks.

| Model | HUC8 | Public URL status | Size | Precipitation relevance |
|---|---|---:|---:|---|
| Upper Guadalupe | 12100201 | 200 | 55.9 GB | Strong candidate. Existing ras-commander docs/source state RAS 6.3.1 handles precipitation internally, with 10 DSS files and 10,248 pathnames, including 6,720 gridded precipitation pathnames. |
| Spring Creek | 12040102 | 200 | 9.9 GB | Existing eBFE fixture, but no explicit gridded precipitation evidence from this scan. |
| North Galveston Bay | 12040203 | 200 | 8.4 GB | Compound HMS plus RAS delivery; likely hydrology-driven, not confirmed RAS gridded precip. |
| Lower Brazos inventory | 12070104 | 200 | 0.1 MB inventory | Very large component model set; not confirmed gridded precip from this pass. |
| Tickfaw | 08070203 | 200 | 12.9 GB | Existing eBFE fixture, but no explicit gridded precipitation evidence from this scan. |
| Lake Maurepas | 08070204 | 200 | 752.6 MB | Existing eBFE fixture; source archive lacks full RAS result HDFs in prior repo docs and no gridded precip evidence from this pass. |

## HEC Training / Technical References

- HEC's `W - Meteorological Data` training PDF uses the same `precip.2018.09.dss` file name in a `Precipitation` project folder and instructs users to choose gridded precipitation mode with DSS source.
- HEC's `Gridded Precipitation and Infiltration` training material lists gridded precipitation data sources as HEC-DSS, GRIB, and NetCDF, and separately lists point gage data sources.
- HEC-RAS 2D User's Manual snippets found through official HEC search describe gridded precipitation from DSS and GDAL raster files, including NetCDF/GRIB import paths.

## Recommendations

1. Use `BaldEagleCrkMulti2D` from RasExamples 6.6 or 7.0 as the primary small reference fixture for ras-commander's gridded precipitation API. It is official, compact relative to eBFE models, and has enabled gridded DSS precipitation with a NEXRAD pathname in `.u03`.
2. Keep the 6.5 copy of `BaldEagleCrkMulti2D` as a cross-version regression fixture if compatibility with older RAS 6.x examples matters.
3. Use Upper Guadalupe eBFE HUC8 `12100201` as the large real-world stress fixture. It is too large for default tests, but it is the best known production-style gridded DSS precipitation model in the current ras-commander ecosystem.

Do not prioritize ScienceBase models for gridded precipitation API fixtures until at least Little Blue River and Lago El Guineo are downloaded and scanned. Metadata-level review did not confirm gridded/radar/MRMS/QPE precipitation in those archives.
