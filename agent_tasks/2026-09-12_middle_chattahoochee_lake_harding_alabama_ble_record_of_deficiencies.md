# Middle Chattahoochee–Lake Harding Alabama BLE Record of Deficiencies

- Date: 2026-09-12
- Study key: `AL03130002`
- HUC8: `03130002`
- Source watershed: Middle Chattahoochee-Lake Harding
- Scope: source acquisition, lossless organization, portable FIM intake, and
  geometry-only dashboard preparation

## Qualification result

The complete Alabama BLE HUC8 delivery was enumerated, verified, extracted,
and assembled as one portable corpus. It contains 197 source models in eight
publisher basins, 197 HEC-RAS projects, 197 registered 1D steady plans, 197
geometry HDFs, and 5,365 cross sections. The 197 source ZIP files total
159,192,389 bytes.

This is source and geometry qualification, not hydraulic validation. No plan
computation has been run, and no result viewer is claimed. The source files
were not edited during staging or organization.

| Evidence | Result |
|---|---:|
| Source archives | 197 |
| Source basins | 8 |
| Source ZIP bytes | 159,192,389 |
| Valid HEC-RAS projects | 197 |
| Registered steady plans | 197 |
| Geometry HDFs | 197 |
| Cross sections | 5,365 |
| Physical `*.p##` files | 198 |

The basin distribution is Halawakee Creek 20, Moores Creek 13, Osanippa
Creek 42, Oseligee Creek 46, Stroud Creek 21, Town Creek 5, Wacoochee Creek
15, and Wehadkee Creek 35.

## Acquisition and organization record

The Alabama public catalog separates model metadata from download links.
RAS Commander queries Hydraulic Models layer 2 and Model Links table 3 at the
Alabama Models ArcGIS FeatureServer, joins records by the publisher's opaque
`ModelID`, and accepts only the link table's public `WebPath`. All 197 resolved
archives returned HTTP 200 and matched their recorded byte length and ETag.

Bare object-store source prefixes return HTTP 404 and are not directory
listings. They are provenance fields only; scraping them or synthesizing child
URLs would make corpus discovery incomplete or brittle.

The immutable staged source is:

```text
F:\BLE_State\AL\raw\AL03130002_AlabamaBLEMiddleChattahoocheeLakeHarding
```

The movable organized delivery is:

```text
F:\BLE_State\AL\organized\AL03130002
├── Source Archives\
├── RAS Models\
├── Documentation\
└── Derived\
```

`Source Archives/` and `RAS Models/` retain basin grouping. The canonical FIM
intake is
`Documentation/watershed_delivery_inventory.json`; all of its model file paths
are relative to the delivery root, and every recorded file has a byte count
and SHA-256 digest. Its schema name is
`ras_commander.watershed_delivery_inventory`, contract version `1.0.0`. Its
SHA-256 at qualification was
`8e9edbfcf8b80e9a86532a2fce7eda78365ab162bd6d146b8025fde76e8933e0`.

Organization made no hydraulic-data correction. It performed verified copy,
safe extraction, deterministic basin grouping, and RAS Commander project/
plan/geometry/flow association. The raw corpus remains the immutable source
of record.

## Deficiencies and qualification gaps

### ROD-AL03130002-01: orphan physical plan file

The organized corpus contains 198 physical `*.p##` files but only 197 plans
registered by the 197 projects. The extra file is:

```text
RAS Models/Osanippa_Creek/OSANIPPA_CREEK_DS_BLE/OSANIPPA CREEK.p02
```

The project registers `p01`, not `p02`. RAS Commander's project DataFrame is
therefore authoritative for the FIM inventory; the orphan is preserved for
provenance but excluded from the runnable-plan count. The publisher should
either register the file or remove/document it.

### ROD-AL03130002-02: incomplete and mixed version metadata

Delivered plan metadata records 135 plans as HEC-RAS 6.20, two as 6.31, and
omits `Program Version` for 60. The watershed must not be described as a
uniform 6.20 corpus. Exact per-model values are retained in the portable
inventory; missing values require compute qualification with an explicitly
recorded installed RAS version.

### ROD-AL03130002-03: non-browsable source prefixes

The publisher's bare source prefixes return 404. This is an integration and
discoverability deficiency, not evidence that the archives are missing.
Repeatable intake depends on the ArcGIS layer/table join and public `WebPath`
values.

### ROD-AL03130002-04: hydraulic execution not yet qualified

No steady plan has been recomputed. The corpus is suitable for source catalog,
geometry inspection, and FIM intake development, but it is not yet a computed
example-project result set. Completion requires running the intended plan for
each project through RAS Commander and recording plan-level outcomes.

### ROD-AL03130002-05: dashboard geometry not yet publicly hosted

The combined geometry archive has passed local structure and count checks, but
it does not yet have a proven public HTTP byte-range URL. The Example Project
Library configuration intentionally leaves that URL empty. Publication must
use the private immutable release pipeline and validate HTTP 206 behavior plus
the exact layer/zoom contract before activation.

The ready-to-promote candidate tree and its checksum receipt are staged at:

```text
F:\BLE_State\AL\organized\AL03130002\Derived\publication-candidate-20260912\hec-ras-7.0
```

## Terrain applicability

There is no terrain deficiency for this geometry-only 1D corpus product. A
compiled `Terrain.hdf` is mandatory to reproduce terrain-dependent mapping or
2D hydraulics, but these delivered projects are pure 1D steady geometries and
the current derivative publishes only model extents, river centerlines, cross
sections, and bank lines. This statement does not waive terrain requirements
for any future terrain-backed result-mapping product.

## Combined display derivative

The local display derivative was freshly built from the organized corpus, not
from a legacy backfill. It is not the canonical FIM model inventory.

| Artifact | Local path | Evidence |
|---|---|---|
| Individual footprints | `F:\BLE_State\AL\organized\AL03130002\Derived\AL03130002_model_footprints.geojson` | 197 features; SHA-256 `79bd7d900f4b15257dfafb6661b83901a3456d61c62257572d5c7502a2aae7cf` |
| Combined PMTiles | `F:\BLE_State\AL\organized\AL03130002\Derived\AL03130002_1d_geometry.pmtiles` | 4,303,908 bytes; SHA-256 `d401385e58f954dccd9ea142afef4f77d48c2905cdf6c6d7b36a093dfca2d627` |
| Display audit | `F:\BLE_State\AL\organized\AL03130002\Derived\alabama_ble_corpus_display_audit.json` | status `passed` |

The combined PMTiles bounds are
`[-85.4565862, 32.5518499, -85.0498685, 33.3680201]`. Its exact layer/count
contract is:

| Layer | Features | Zooms |
|---|---:|---:|
| `ras_model_extent` | 197 | 7-11 |
| `ras_river_centerlines` | 197 | 8-14 |
| `ras_cross_sections` | 5,365 | 10-14 |
| `ras_bank_lines` | 394 | 10-14 |

Every combined feature retains `study_id`, publisher `model_id`, `model_key`,
`display_id`, `source_feature_id`, and `feature_key`. The landing map uses one
union outline for the watershed entry; selecting that one entry will reveal
the individual model geometry only after the PMTiles is publicly released.

## FIM Commander intake evidence

FIM Commander's read-only intake accepted the canonical delivery without an
inventory-path override. It checked 1,379 per-model references (seven for each
of 197 models, including the retained source sidecar) plus the inventory and
source manifest, for 1,381 checked files. It recorded 60 nonblocking warnings
for missing delivered HEC-RAS version declarations and detected no source
mutation.

The normalized inventory is
`H:\CLB-Repos\fim-commander\working\artifacts\AL03130002\00_intake\watershed_model_inventory.parquet`
(90,675 bytes; SHA-256
`cb95129979999aef923be654525b9e154781ae14a3ceb08140f7a6e98c06a049`).
The QA record beside it is 12,262 bytes with SHA-256
`bcfc7f4ee28cb5a9f503c4ac5c68685c83c258b1690f5df1752abebce290a734`.
It registers the combined PMTiles as the spatial review view.

This milestone provides validated full-corpus intake and a deterministic
197-node fan-out plan. `max_concurrent_models` is a planning constraint, not a
claim that FIM Commander has executed the models. A resumable, clone-before-run
executor remains a separate public-API and HEC-RAS execution milestone.

## Disposition

- Preserve the raw corpus unchanged.
- Use the relative-path JSON inventory as FIM Commander's authoritative model
  directory contract.
- Keep the orphan plan and version omissions visible in downstream QA.
- Admit one HUC8-level discovery outline and one table row, not 197 public
  dashboard entries.
- Do not claim plan or results qualification until the 197-plan execution
  record exists.
- Do not activate the combined PMTiles URL until immutable publication and
  public byte-range validation pass.
