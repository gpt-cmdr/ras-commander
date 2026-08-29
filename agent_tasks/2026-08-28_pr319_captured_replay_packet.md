# PR 319 captured-output offline replay packet

Date prepared: 2026-08-28

Mode: read-only archive validation and replay planning
HEC-RAS/COM execution: prohibited for this packet

## Scope and classification

This packet pins 13 outputs from the archived 2026-08-24 installed-version
matrix for read-only replay under the current PR 319 inspection logic. The
project copies and their results were produced in disposable stages by actual
installed HEC-RAS engines. Every replay artifact in this packet therefore has
the exact data-origin label:

`staged_execution_output`

The common shorthand “captured-real replay” describes how the output was
obtained; it does not change the artifact-origin label to `captured_real`.
The underlying immutable input projects remain `captured_real`.

No file in the old archive was changed. Validation used stable, streamed
SHA-256 reads with before/after size, `mtime_ns`, volume, and file-identity
checks. No HEC-RAS or COM API was called. Only this document was written.

## Canonical roots and destination naming

- Archived matrix root (`A`):
  `H:\CLB-Repos\ras-commander\working\structured_execution_evidence_2026-08-24\multiversion_fixtures`
- Durable replay audit root:
  `H:\CLB-Repos\ras-commander\working\pr319_execution_qualification_2026-08-28\captured_replay`
- Disposable local replay root:
  `C:\Users\billk_clb\AppData\Local\ras-commander\pr319_execution_qualification_2026-08-28\captured_replay`

Stable destination lane IDs are the archived lane ID plus `__replay`, for
example `steady_1d__4_0__replay`. Each attempt must use a fresh UUID and the
current harness layout:

`<disposable root>\<run_id>\<destination_lane_id>\<attempt_uuid>\stage`

The corresponding durable receipt directory is:

`<durable root>\<run_id>\attempts\<destination_lane_id>\<attempt_uuid>`

Neither a lane directory nor an attempt UUID may be reused.

## Archive index pins

| File under `A` | Size (bytes) | SHA-256 |
|---|---:|---|
| `manifest.json` | 6,736 | `bfbd4558a276d9ec2faf0bb0fb385fe3bb9a189e18b0cf4b09570a32daf0a3b8` |
| `matrix.parquet` | 24,428 | `555b7df52dce03103c6ba9d2b13e2c2321bca58de332a2bc0ab43b0ebbd34956` |
| `matrix.csv` | 20,852 | `81caf1901cc7928aabad5d36f984c794296927f18ea01e57dea289ef951ca9f8` |
| `matrix.json` | 68,752 | `5cfd3e4f9a0a245191f590cff2a0a523da59ee7fb72e7ccd0cf472b3b8368c56` |

`matrix.parquet` is the canonical old-matrix lookup. CSV and JSON are retained
only as historical archive companions; new qualification output remains
PyArrow/Parquet-first.

## Immutable input-source references

These are the immutable project bundles from which the disposable archived
lanes were staged. The source fingerprint is the value recorded equal before
and after staging in every selected lane record.

| Fixture | Exact source project / plan | Project SHA-256 / plan SHA-256 | Files / bytes | Source content fingerprint |
|---|---|---|---:|---|
| `steady_1d` | `C:\Users\billk_clb\Documents\HEC Data\HEC-RAS\Example Projects\1D Steady Flow Hydraulics\Chapter 4 Example Data\EX1.prj` / `EX1.P01` | `c5c99ea7ff1a3636a72247b72030387c78cc73c6ea7dbd2721e476c936b0dade` / `312fb0e636f681dfdf50175f3c005d5f35b0f7c71d00cf38a479d6a85ce53b66` | 7 / 18,647 | `b80648885d625fb7b035de00ad014cb05dd447513c4a8da9dd93e8791dd93530` |
| `unsteady_1d` | `A\sources\Example 20 - HagerLatWeir_e01_multiversion_source\HagerLatWeir.prj` / `HagerLatWeir.p06` | `b83b0e03fe98056891887fb12cabf6d58d1ab9687c803eea3e0827a7a59bcda2` / `a37bfd6744e2076ca56b6f6874b1d75bdbb5a363a89a7d94676695deeae2ca37` | 28 / 1,625,085 | `36ae1f21de0bdc3583839b3b9e339f07c3b374336c31489db54ce9060a6e7028` |
| `unsteady_2d` | `A\sources\BaldEagleCrkMulti2D_e01_multiversion_source\BaldEagleDamBrk.prj` / `BaldEagleDamBrk.p18` | `a112974c1216382971d60926aaf5f1d0324a4b3da0fe0309bd58e8d13f61a082` / `cfa4bb801bf957dd1b0ad81b03bf5714e8a92608c75e38eadf285b429675a833` | 98 / 354,028,433 | `09779010a48e6dfb34da3d4323cf444c6880b0e931a891c92f9f5ec189bebf46` |

`A` in an exact source path means the canonical absolute archive root defined
above, not an environment variable.

## The 13 anchors and current-PR expected outcomes

The project and plan shown below are the exact archived staged copies. Their
project hashes equal the source project hashes above. The archived selected
plan hashes are `c6f194276ac3aa9feff26b3cd25d590834eb2f4eef6071588bfb6448ce48afde`
for `EX1.P01`, `2f620b0ded657008eefe6178505d7ea380799305e4912fb27aa741f6a45b9992`
for `HagerLatWeir.p06`, and
`53da75f1e11eb18d9b80d486e775b6cb845aa9b2f44b607c49b19e5664be544d`
for `BaldEagleDamBrk.p18`.

| Archived lane | Exact lane directory; project / plan | Declared `Program Version` | Expected current-PR inspection | Destination lane ID |
|---|---|---|---|---|
| `steady_1d__4_0` | `A\lanes\steady_1d\4_0`; `EX1.prj` / `EX1.P01` | absent | pass; select sole legacy `.O01`; conflict `program_version_unresolved`; no ambiguity exception | `steady_1d__4_0__replay` |
| `steady_1d__4_1_0` | `A\lanes\steady_1d\4_1_0`; `EX1.prj` / `EX1.P01` | absent | pass; select sole legacy `.O01`; conflict `program_version_unresolved`; no ambiguity exception | `steady_1d__4_1_0__replay` |
| `unsteady_1d__4_0` | `A\lanes\unsteady_1d\4_0`; `HagerLatWeir.prj` / `HagerLatWeir.p06` | `4.00` | pass; select sole legacy `.O06`; no result-family conflict | `unsteady_1d__4_0__replay` |
| `unsteady_1d__4_1_0` | `A\lanes\unsteady_1d\4_1_0`; `HagerLatWeir.prj` / `HagerLatWeir.p06` | `4.00` | pass; select sole legacy `.O06`; no result-family conflict | `unsteady_1d__4_1_0__replay` |
| `steady_1d__6_1` | `A\lanes\steady_1d\6_1`; `EX1.prj` / `EX1.P01` | absent | expected `ResultArtifactAmbiguityError`; no selected family; reason `program_version_unresolved_multiple_formats` | `steady_1d__6_1__replay` |
| `steady_1d__6_6` | `A\lanes\steady_1d\6_6`; `EX1.prj` / `EX1.P01` | absent | expected `ResultArtifactAmbiguityError`; no selected family; reason `program_version_unresolved_multiple_formats` | `steady_1d__6_6__replay` |
| `steady_1d__7_0` | `A\lanes\steady_1d\7_0`; `EX1.prj` / `EX1.P01` | absent | expected `ResultArtifactAmbiguityError`; no selected family; reason `program_version_unresolved_multiple_formats` | `steady_1d__7_0__replay` |
| `unsteady_1d__6_1` | `A\lanes\unsteady_1d\6_1`; `HagerLatWeir.prj` / `HagerLatWeir.p06` | `4.00` | pass; select legacy `.O06`; conflict `multiple_result_formats_present`; warn that HDF is ignored because legacy is newer | `unsteady_1d__6_1__replay` |
| `unsteady_1d__6_6` | `A\lanes\unsteady_1d\6_6`; `HagerLatWeir.prj` / `HagerLatWeir.p06` | `4.00` | pass; select legacy `.O06`; conflict `multiple_result_formats_present`; warn that HDF is ignored because legacy is newer | `unsteady_1d__6_6__replay` |
| `unsteady_1d__7_0` | `A\lanes\unsteady_1d\7_0`; `HagerLatWeir.prj` / `HagerLatWeir.p06` | `4.00` | pass; select legacy `.O06`; conflict `multiple_result_formats_present`; warn that HDF is ignored because legacy is newer | `unsteady_1d__7_0__replay` |
| `unsteady_2d__6_1` | `A\lanes\unsteady_2d\6_1`; `BaldEagleDamBrk.prj` / `BaldEagleDamBrk.p18` | `5.00` | pass; select sole HDF `.p18.hdf`; no result-family conflict | `unsteady_2d__6_1__replay` |
| `unsteady_2d__6_6` | `A\lanes\unsteady_2d\6_6`; `BaldEagleDamBrk.prj` / `BaldEagleDamBrk.p18` | `5.00` | pass; select sole HDF `.p18.hdf`; no result-family conflict | `unsteady_2d__6_6__replay` |
| `unsteady_2d__7_0` | `A\lanes\unsteady_2d\7_0`; `BaldEagleDamBrk.prj` / `BaldEagleDamBrk.p18` | `5.00` | pass; select sole HDF `.p18.hdf`; no result-family conflict | `unsteady_2d__7_0__replay` |

Expected terminal totals are ten `passed` lanes and three
`expected_failure` lanes. The three expected failures must retain the exact
ambiguity reason code above; they are not worker crashes or failed invariants.

## Exact replay artifact allowlist

Every row below is an existing file beneath that lane's exact `source_root`
(`A\lanes\<plan_type>\<version_slug>`). Each file was rehashed on 2026-08-28.
These are the only archived execution outputs copied into the fresh stage.

| Lane | Relative replay file | Role | Size (bytes) | `mtime_ns` | SHA-256 |
|---|---|---|---:|---:|---|
| `steady_1d__4_0` | `EX1.O01` | legacy result | 32,000 | 1787629699920540500 | `8a954d8366d31647ee69657cd8ef1a1a87eb04bff297381ceeff8c828184f49c` |
| `steady_1d__4_0` | `EX1.p01.comp_msgs.txt` | stored messages | 124 | 1787629698966287500 | `633af6b576c1f392a196096438c887fbe0297aecb57625feae0ea1ddc89f50a1` |
| `steady_1d__4_1_0` | `EX1.O01` | legacy result | 32,000 | 1787634852496131800 | `bacfb38f203640e466b8c83ad77e6f963bb68b6fe5edef78fec89f9354ffe27a` |
| `steady_1d__4_1_0` | `EX1.p01.comp_msgs.txt` | stored messages | 122 | 1787634851616625500 | `c1ad1b929ea41f9b94ed1b006e30590bc728a93370e003d7149c6c393880a87b` |
| `unsteady_1d__4_0` | `HagerLatWeir.O06` | legacy result | 435,200 | 1787630560238384300 | `5587b6cc11555b80fde1a5d00f36076da0c5119b0e4a7d4370b9adf2c220d76e` |
| `unsteady_1d__4_0` | `HagerLatWeir.p06.comp_msgs.txt` | stored messages | 889 | 1787630559058797100 | `3448faff73067c7a491d65f01fcb336ea3990448c2603a095c2ad3d4cad69f4d` |
| `unsteady_1d__4_1_0` | `HagerLatWeir.O06` | legacy result | 435,200 | 1787634764570690700 | `951b0d5b4018911e04e79f75700315798bf51d26041f4b7bad655162c9531b83` |
| `unsteady_1d__4_1_0` | `HagerLatWeir.p06.comp_msgs.txt` | stored messages | 883 | 1787634763522496200 | `ff5be1a135822b0e1c21db7b364ba5491328a0610b9a248315e5d9ec566414c4` |
| `unsteady_1d__4_1_0` | `HagerLatWeir.bco06` | stored messages | 1,643,599 | 1787634762422420900 | `6c523ff171bdd9fee023788402843639b3f7d59a8a1b83274b06abcdaf70a4dc` |
| `steady_1d__6_1` | `EX1.p01.hdf` | HDF result | 336,655 | 1787633321559280100 | `d7b0a9a5b08c9d15679530e928c371692805afc4dd606c600bcd6a23376fa3c0` |
| `steady_1d__6_1` | `EX1.O01` | legacy result | 70,400 | 1787633323467738500 | `0b0ed8b32b160b463d85e87404c024296c5b257541bd5d952b85b086983b4e5b` |
| `steady_1d__6_6` | `EX1.p01.hdf` | HDF result | 352,613 | 1787633497334487200 | `ad40aa06d4848fbecd0d23e850d42a153c64f783787117d77123a54e48e12bb7` |
| `steady_1d__6_6` | `EX1.O01` | legacy result | 70,400 | 1787633499226854100 | `cae1b0bd424e5abd608e65c8d9b94b4da436d614e2a54e433d839972245d5fd3` |
| `steady_1d__7_0` | `EX1.p01.hdf` | HDF result | 352,597 | 1787630533940938400 | `a7e9490cf1a7d308ccc4c2b4f122c0150aa9b059658d209dfe788674fee36d7d` |
| `steady_1d__7_0` | `EX1.O01` | legacy result | 70,400 | 1787630535854448500 | `7b1fa0a697687f6d517a64d837ff3fa406dc94c5794329002c0a1a8e07bc5c2c` |
| `unsteady_1d__6_1` | `HagerLatWeir.p06.hdf` | HDF result | 616,520 | 1787633605209410100 | `2365e46b4543f1df2c84bb41142171c883f3effa74223511ee7864553779cc89` |
| `unsteady_1d__6_1` | `HagerLatWeir.O06` | legacy result | 435,200 | 1787633606518850700 | `384b8ab29097a8be30cbfee83cf8dc065eb4a3ccc1d738f91f83d23f5358d7a9` |
| `unsteady_1d__6_1` | `HagerLatWeir.bco06` | stored messages | 1,593,837 | 1787633603892086200 | `436fce789c2f20b1b4cfe36cf7c4416ebe159b11e4fcb5441f39f5b977331851` |
| `unsteady_1d__6_6` | `HagerLatWeir.p06.hdf` | HDF result | 890,950 | 1787633783497039700 | `2803bfbd1b0b9b9a23ebe39267fb1398622082a514b945bbdb1911f9479b56ef` |
| `unsteady_1d__6_6` | `HagerLatWeir.O06` | legacy result | 435,200 | 1787633784680297500 | `9831657892b75540513c592ae08ed5f00f7d912c6165917f329170f8a667ea76` |
| `unsteady_1d__6_6` | `HagerLatWeir.bco06` | stored messages | 1,593,837 | 1787633781949015800 | `e9f7d9bf030ce8703711c26e8091041cb2dae58c584553de1ae30c0119ad3645` |
| `unsteady_1d__7_0` | `HagerLatWeir.p06.hdf` | HDF result | 907,999 | 1787630669049256300 | `d8e1669fc841795b0d55dc0ee76cfa83efa183a2e15c9d83d02e1a3448c5360c` |
| `unsteady_1d__7_0` | `HagerLatWeir.O06` | legacy result | 435,200 | 1787630670199149500 | `57c95d02cdd5d3dbebf078b221067e54330372d31ca874abc3c9625a44b93677` |
| `unsteady_1d__7_0` | `HagerLatWeir.bco06` | stored messages | 1,593,837 | 1787630667861418600 | `771e9c16f83ca46c35c4c13c0a7cb80a7430fe7aab18a556b2f34a84fe570cb2` |
| `unsteady_2d__6_1` | `BaldEagleDamBrk.p18.hdf` | HDF result | 23,769,257 | 1787634021792134700 | `b906da8ec85652a67ad4401e25654a20c60733ab877b9db3377e5e5064b432e9` |
| `unsteady_2d__6_1` | `BaldEagleDamBrk.bco18` | stored messages | 3,375 | 1787634021589068500 | `311cb639758bd8607fdfcd312dffdeed368a7751d78a33d58517215f49e35df0` |
| `unsteady_2d__6_6` | `BaldEagleDamBrk.p18.hdf` | HDF result | 24,388,165 | 1787631030317931200 | `fd6a0d662a1e2c7f4988d4783fc2f46d43d3272d3951091cdf885af5e4c6a12b` |
| `unsteady_2d__6_6` | `BaldEagleDamBrk.bco18` | stored messages | 3,375 | 1787631030074521100 | `e2298b42a4e6a9a522f8c60bd83f32b96dd5ca6085921d6fc67dc1e30e5f56b4` |
| `unsteady_2d__7_0` | `BaldEagleDamBrk.p18.hdf` | HDF result | 24,422,446 | 1787631369236802400 | `1d0063a84fd131ac95ffaa2b3f6647f2ef51c7f38f23c43e8ae6c698bfc95f0b` |
| `unsteady_2d__7_0` | `BaldEagleDamBrk.bco18` | stored messages | 3,375 | 1787631369008821400 | `67d326a99a3f3e3b1988af6a2f09056d7833771e45c602e9e354342a0873e546` |

The replay copy must preserve each listed result/message file's bytes and
`mtime_ns`. It must not copy same-plan `.IC.O##` files as `.O##` results, nor
unrelated-plan messages such as `HagerLatWeir.bco02` or
`BaldEagleDamBrk.bco06`. `HagerLatWeir.bco` in the 4.0 lane is a useful legacy
archive companion, but it is not the exact `bco06` allowlist path and is not a
replay seed; the exact `.p06.comp_msgs.txt` is sufficient for that lane.

## Mixed-family timestamp deltas

All deltas are exact `legacy.mtime_ns - hdf.mtime_ns`. Positive means the
legacy result has the later filesystem timestamp.

| Lane | HDF `mtime_ns` | Legacy `mtime_ns` | Delta (ns) | Delta (s) |
|---|---:|---:|---:|---:|
| `steady_1d__6_1` | 1787633321559280100 | 1787633323467738500 | 1,908,458,400 | 1.9084584 |
| `steady_1d__6_6` | 1787633497334487200 | 1787633499226854100 | 1,892,366,900 | 1.8923669 |
| `steady_1d__7_0` | 1787630533940938400 | 1787630535854448500 | 1,913,510,100 | 1.9135101 |
| `unsteady_1d__6_1` | 1787633605209410100 | 1787633606518850700 | 1,309,440,600 | 1.3094406 |
| `unsteady_1d__6_6` | 1787633783497039700 | 1787633784680297500 | 1,183,257,800 | 1.1832578 |
| `unsteady_1d__7_0` | 1787630669049256300 | 1787630670199149500 | 1,149,893,200 | 1.1498932 |

## Current archived-lane tree pins

These fingerprints pin the complete archived lane tree as it exists now,
including inputs and staged execution outputs. Content fingerprints are based
on sorted relative path, size, and SHA-256. Metadata fingerprints additionally
include `mtime_ns`, volume ID, and file identity and are therefore host/archive
specific.

| Lane | Files | Content fingerprint | Metadata fingerprint |
|---|---:|---|---|
| `steady_1d__4_0` | 10 | `e8e06d8de68eba72376380789f2dc4c56e0da676c38d6842ded5664252c31170` | `1bf4f4681bdcc7bf5bc3d87c9ef9914182d633842f396e38be3d53763a8b3457` |
| `steady_1d__4_1_0` | 10 | `16db69270cba893ec1c99a40d10dbb1366a71f24b1e89dc5ac85cee32e9206aa` | `3087c15ce43ede496edcc5b5b4685976ffa7b3e98a47f82ccd865e773a35656d` |
| `unsteady_1d__4_0` | 36 | `f7250db5ab4940c8924b8e284c6686837e6df77a61a2b2ed427c8657c511b2cf` | `9e284d66ff08ec239a5bedb4a417cf8c38c2df6417cea462af4e509bee608bec` |
| `unsteady_1d__4_1_0` | 37 | `102b1f19ae3622130557639e54be50dcbbd0ef0cf635a690a1837afbc57a6cc1` | `a484030219b6723b7ca6426ad75104eef71a2bdb26a3705c2a513bf5dcc73337` |
| `steady_1d__6_1` | 12 | `f914d4fe9b31f6528c38321042840f27808d51350518f3aef6e72e447e1f8983` | `c35e3a95dc316a9c375d000c96efe77c723b6f2a15a7ba086840e335a5d288c1` |
| `steady_1d__6_6` | 12 | `8fb3ab6f80c316695633c839c684e07040244fa19c2e3d4f085f1a2c4649c03f` | `db99b93d3af2b572c88bf3f0ea10e87a9d3b8aac859511294976a103505ee6ae` |
| `steady_1d__7_0` | 12 | `663dde6bb170ec75b074fa6467d19b65d1382a0c90998c22df1d9df66d25c912` | `deacd651546ce42915bc73d873739dade0c662fd8e2962164f2fcc2ef16b4596` |
| `unsteady_1d__6_1` | 38 | `4281daa8470ffe2b9b1be6e2424b32553a5d2b9844e05272e0b205bdc98e4101` | `bcf241409de1a5113400995060b68ffdd3a6231180a7c9603650ac475a549f9e` |
| `unsteady_1d__6_6` | 38 | `c125f56cd3f976e7d555b139131d19d178a924140e80915f8153b2fd880ff69b` | `c0c1aed26ddb1ab120612099aea4c13e5fc709c0f6103bfb82e75524a712594d` |
| `unsteady_1d__7_0` | 38 | `2ec010ad3f6d9eef1f9234d1cb4f525ffb49d98c747f030e10dc2e3c550646b8` | `279230ddc6245cb1e49c1c15e0857e084cbe6da50ebe8bc8c1a868a663b821f9` |
| `unsteady_2d__6_1` | 105 | `2e9927601aa23e2faf38c4661aa3bb80de67b5c87e09af4e5781718a857ccdba` | `dc6a7a96245509690723dea25a926bd9a0af40da2cbdd295e7cb34ec159da12d` |
| `unsteady_2d__6_6` | 105 | `903879200771d3a4af517a779bdd657a81f586c00eff0c89ef65f3849febcf43` | `9c204dc211e49ae50bd9cedca097ffe1d8f2fa70721fd4ad0a514ad88c74e55b` |
| `unsteady_2d__7_0` | 105 | `c04fffd1a03020f601df36fbbcedf791afb95b937c6440d4a30896bfeb2c9f0f` | `a30cfa7b20b58abb586092fa71d2fbc0687155546d1cc8d519eda683f9030bc0` |

## Companion evidence records

Every anchor has an exact record directory at `A\records\<archived_lane_id>`.
Existence and hashes were revalidated for these common files:

- `record.json`
- `runner.log`
- `stage_assets.parquet`
- `execution_evidence.json`

The four legacy anchors also contain
`rascontrol_compute_messages.txt` and
`rascontrol_result_probe.parquet`; the steady probes have 30 rows and the
unsteady probes have 21 rows. The exact stored-message files copied into the
replay are already pinned in the replay-artifact table.

The archived `execution_evidence.json` files are provenance companions, not
the current-PR expected result. They were refreshed under an earlier inspector
state. The replay must generate new evidence from the copied bytes and compare
that evidence with the expected outcomes in this packet.

## Uncertainty and acceptance notes

- No artifact-selection outcome above is unresolved: the selected plan bytes,
  family population, and nanosecond timestamps were all read successfully.
- The three mixed steady lanes are deliberately expected failures because the
  plan has no `Program Version` declaration. Do not guess an HDF family from
  the engine that historically produced the file.
- The three mixed Hager lanes deliberately select legacy, even though their
  HDFs report modern producer versions. The plan still declares `4.00`, and the
  legacy `.O06` timestamp is later. This is the current conservative policy,
  not a producer-attribution claim.
- Filesystem times remain conservative ambiguity inputs. Their preservation in
  replay tests the current policy; it does not prove calculation chronology.
- The original extraction receipt/archive identity for the Hager and Bald
  Eagle source bundles remains unavailable. Their exact current source and
  archived-output bytes are pinned, but that upstream provenance gap is not
  silently upgraded to certainty.
- Read-only acceptance requires identical stage content and metadata
  fingerprints before and after inspection, ten passed lanes, three exact
  expected ambiguity failures, and no HEC-RAS/COM process launch.
