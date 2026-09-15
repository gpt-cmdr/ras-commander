# PR 319 qualification fixture inventory

Date inventoried: 2026-08-28

Prior archive created: 2026-08-25
Inventory mode: read-only; no HEC-RAS process was started and no project or result file was changed.

## Executive finding

The prior qualification archive is intact and reusable, but it predates the
result-family cleanup in PR 319. It is therefore evidence about actual HEC-RAS
behavior and an excellent source for offline selection/ambiguity tests; it is
not, by itself, qualification evidence that the new cleanup works.

The canonical 58-lane matrix contains:

| Status | Count | Meaning |
|---|---:|---|
| `completed` | 34 | A real installed HEC-RAS engine produced a fresh result and completion was verified. |
| `blocked` | 15 | The project was staged, but no execution was attempted because an exact 5.x or 6.0 engine gate had already been established. |
| `failed` | 9 | A real attempt failed, chiefly at COM `Project_Open`; one 5.0.6 command-line attempt returned no fresh result. |

The 34 completed lanes break down into four clean legacy-only captures, ten
clean HDF-only 2D captures, and twenty mixed-format modern 1D captures. In all
twenty mixed captures, the legacy `.O##` modification time is later than the
plan HDF by 1.065 to 1.929 seconds. This is direct evidence that the modern
1D executions in the old harness left both families behind, with the legacy
file written last. Those lanes are especially valuable for testing the new
read-only ambiguity policy, but they must not be called clean modern-output
baselines.

Canonical archive files:

- `H:\CLB-Repos\ras-commander\working\structured_execution_evidence_2026-08-24\multiversion_fixtures\manifest.json`
- `H:\CLB-Repos\ras-commander\working\structured_execution_evidence_2026-08-24\multiversion_fixtures\matrix.parquet`
- `H:\CLB-Repos\ras-commander\working\structured_execution_evidence_2026-08-24\multiversion_fixtures\matrix.csv`
- `H:\CLB-Repos\ras-commander\working\structured_execution_evidence_2026-08-24\multiversion_fixtures\matrix.json`
- Harness: `H:\CLB-Repos\ras-commander\working\structured_execution_evidence_2026-08-24\run_multiversion_matrix.py`

The archive records harness commit `c9311e381232784eba65858000ee3126125af082`
and then-main commit `0a7ceac02220d8572f7b7242e728f1483869b0c7`.
The evidence was later refreshed offline while the inspector implementation
was modified in that worktree. Preserve the raw records, but record the PR 319
commit and a clean worktree in every new qualification lane.

## P0 quiescence audit addendum

The 2026-08-28 deterministic audit found a real fail-open path in
`RasControl.run_plan`: an exception from asynchronous `Compute_Complete()` was
logged and ignored, and the outer finalizer could then delete the opposing
result family while solver state remained unknown. A compute-dispatch exception
after pre-cleanup had the same finalization risk. The focused fix requires a
valid blocking Controller return or `Compute_Complete() == True` before final
opposing-family cleanup; otherwise the call fails and preserves the ambiguous
artifacts. No HEC-RAS process was used. The affected deterministic suite passed
53 tests across `test_execution_artifact_cleanup.py`,
`test_rascontrol_blocking.py`, `test_rascontrol_logging.py`, and
`test_compute_extra.py`.

## Provenance classifications

This inventory uses the agreed dataset language:

| Classification | Contents in this archive |
|---|---|
| `captured_real` | The three immutable source projects and their actual input assets. They are real HEC-RAS examples, not synthetic fixtures. |
| `staged_execution_output` | Disposable project copies and outputs produced by actual installed HEC-RAS engines during the 58-lane run. |
| `archived_failed_execution` | Staged projects, logs, and records from blocked or failed real-engine attempts. |
| `generated_edge_case` | None in the prior archive. Timestamp permutations and deliberately corrupt/incomplete files for PR 319 must be generated separately and labeled as such. |

The JSON, CSV, Parquet, log, and extracted compute-message files are generated
qualification metadata. They describe real sources or real executions, but are
not themselves HEC-RAS result files.

## Exact source projects and plans

### Steady 1D

- Project: `C:\Users\billk_clb\Documents\HEC Data\HEC-RAS\Example Projects\1D Steady Flow Hydraulics\Chapter 4 Example Data\EX1.prj`
- Plan: `C:\Users\billk_clb\Documents\HEC Data\HEC-RAS\Example Projects\1D Steady Flow Hydraulics\Chapter 4 Example Data\EX1.P01`
- Plan 01 title: `Existing Conditions Run`
- Classification: steady 1D; geometry `g01`; steady flow `f01`
- Declared plan version: absent
- Source tree captured by `stage_project`: 7 files, 18,647 bytes
- Source tree fingerprint: `b80648885d625fb7b035de00ad014cb05dd447513c4a8da9dd93e8791dd93530`
- Project SHA-256: `c5c99ea7ff1a3636a72247b72030387c78cc73c6ea7dbd2721e476c936b0dade`
- Plan SHA-256: `312fb0e636f681dfdf50175f3c005d5f35b0f7c71d00cf38a479d6a85ce53b66`
- Classification: `captured_real`

This is the installed HEC-RAS Chapter 4 example and is the strongest source
provenance of the three. Do not use
`multiversion_fixtures\sources\EX1_chapter4_steady_source`: it is itself a
previously staged copy containing reserved `.ras-commander` metadata.

### Unsteady 1D

- Project: `H:\CLB-Repos\ras-commander\working\structured_execution_evidence_2026-08-24\multiversion_fixtures\sources\Example 20 - HagerLatWeir_e01_multiversion_source\HagerLatWeir.prj`
- Plan: `H:\CLB-Repos\ras-commander\working\structured_execution_evidence_2026-08-24\multiversion_fixtures\sources\Example 20 - HagerLatWeir_e01_multiversion_source\HagerLatWeir.p06`
- Plan 06 title: `Unsteady Broad Crest S=10ft/mi`
- Classification: unsteady 1D; geometry `g02`; unsteady flow `u01`
- Declared plan version: `4.00`
- Source tree: 28 files, 1,625,085 bytes
- Source tree fingerprint: `36ae1f21de0bdc3583839b3b9e339f07c3b374336c31489db54ce9060a6e7028`
- Project SHA-256: `b83b0e03fe98056891887fb12cabf6d58d1ab9687c803eea3e0827a7a59bcda2`
- Plan SHA-256: `a37bfd6744e2076ca56b6f6874b1d75bdbb5a363a89a7d94676695deeae2ca37`
- Classification: `captured_real`

The folder name and project contents identify the HEC-RAS Example 20 Hager
lateral-weir project. The exact upstream example archive/version and the
original `RasExamples.extract_project()` transaction were not preserved. That
provenance gap should be closed before promoting this to a long-lived fixture.

### Unsteady 2D

- Project: `H:\CLB-Repos\ras-commander\working\structured_execution_evidence_2026-08-24\multiversion_fixtures\sources\BaldEagleCrkMulti2D_e01_multiversion_source\BaldEagleDamBrk.prj`
- Plan: `H:\CLB-Repos\ras-commander\working\structured_execution_evidence_2026-08-24\multiversion_fixtures\sources\BaldEagleCrkMulti2D_e01_multiversion_source\BaldEagleDamBrk.p18`
- Plan 18 title: `2D to 2D Run`
- Classification: unsteady 2D; geometry `g11`; unsteady flow `u10`
- Declared plan version: `5.00`
- Source tree: 98 files, 354,028,433 bytes
- Source tree fingerprint: `09779010a48e6dfb34da3d4323cf444c6880b0e931a891c92f9f5ec189bebf46`
- Project SHA-256: `a112974c1216382971d60926aaf5f1d0324a4b3da0fe0309bd58e8d13f61a082`
- Plan SHA-256: `cfa4bb801bf957dd1b0ad81b03bf5714e8a92608c75e38eadf285b429675a833`
- Classification: `captured_real`

The source is the official `BaldEagleCrkMulti2D` example as extracted for the
prior matrix. As with Hager, the exact source archive/version and extraction
receipt are absent. The source includes geometry and unsteady HDF sidecars,
terrain, DSS, land-classification, soil, and precipitation assets; it does not
contain a plan-18 result HDF or `.O18`.

Rejected source candidates retained in `multiversion_fixtures\sources`:

- `Balde Eagle Creek_steady_candidate`: not selected for the final matrix.
- `Wailupe GeoRAS_steady_candidate`: produced incomplete-input evidence in an early attempt.
- `EX1_chapter4_steady_source`: valid model bytes but invalid as a source to `stage_project` because it contains reserved staging metadata.

## Installed HEC-RAS engines

All twenty executable paths still exist on 2026-08-28. Their current SHA-256
hashes match the 2026-08-25 manifest exactly.

| Requested label | File product version | Exact executable | SHA-256 |
|---|---|---|---|
| 4.0 | 4.00 | `C:\Program Files (x86)\HEC\HEC-RAS\4.0\Ras.exe` | `29f22cd3330ca14e7b92a5e8ca0293cb46a582156ae2bd03bbb1b83f1701300b` |
| 4.1.0 | 4.01 | `C:\Program Files (x86)\HEC\HEC-RAS\4.1.0\Ras.exe` | `b9b1cb9376ccfe63dcca8969c518e095059ea7aba7340b04eabb7a5dd2c9dc17` |
| 5.0 | 5.00 | `C:\Program Files (x86)\HEC\HEC-RAS\5.0\Ras.exe` | `f1913cfee5655c59ad63bae1ae9545ed1063fa5408ce84bde1a56566d7c99aea` |
| 5.0.1 | 5.00.0001 | `C:\Program Files (x86)\HEC\HEC-RAS\5.0.1\Ras.exe` | `3ecf4d03f6054d085745ffc2ed673292f462a5b82c2e99f6fb58092a083724e6` |
| 5.0.3 | 5.00.0003 | `C:\Program Files (x86)\HEC\HEC-RAS\5.0.3\Ras.exe` | `794e3dc4c9f2b2820b6056ee2aa6c2bf7712b8879f4b13163bf4c44156e68b37` |
| 5.0.4 | 5.00.0004 | `C:\Program Files (x86)\HEC\HEC-RAS\5.0.4\Ras.exe` | `4b260e8a010d6d7eaa4cfa74b998603136d6d692bec29838c91313fd8e711d5b` |
| 5.0.5 | 5.00.0005 | `C:\Program Files (x86)\HEC\HEC-RAS\5.0.5\Ras.exe` | `eb973b70aa718e1f48bac2e4dc3c2ffc5b4409ace19b2ca747e4e2b5b7e9cc86` |
| 5.0.6 | 5.00.0006 | `C:\Program Files (x86)\HEC\HEC-RAS\5.0.6\Ras.exe` | `0af2521be71574c893c606f9fb4229df91e2464ebf6c04507957b80e0be1766f` |
| 5.0.7 | 5.00.0007 | `C:\Program Files (x86)\HEC\HEC-RAS\5.0.7\Ras.exe` | `940dbdc1869e8672402821a0df091d905406b9b0ff7f44d521a8681ca917e88e` |
| 6.0 | 6.00 | `C:\Program Files (x86)\HEC\HEC-RAS\6.0\Ras.exe` | `2126b0307f7b77e1885f7a0dba4ddd590d0c08d1ac63e425c8a7b7fed54e7473` |
| 6.1 | 6.01 | `C:\Program Files (x86)\HEC\HEC-RAS\6.1\Ras.exe` | `58423df21f7115340a9d41f5d93039a786c91f0ffc944f7b23c77846bcc9e330` |
| 6.2 | 6.02 | `C:\Program Files (x86)\HEC\HEC-RAS\6.2\Ras.exe` | `826082cb45384ec6c05150eb71a8ab26bb5183a8e2603f717cf8ee9832e7a92e` |
| 6.3 | 6.03 | `C:\Program Files (x86)\HEC\HEC-RAS\6.3\Ras.exe` | `3a8f683961dcad82cfb15bbb68ec3df62c6510711dd89c37e3e09f52c9d8b860` |
| 6.3.1 | 6.03.0001 | `C:\Program Files (x86)\HEC\HEC-RAS\6.3.1\Ras.exe` | `7b40237b2ef0a90a32b673affe7f5de7114410527d17e755d0c62a44e2c39a9e` |
| 6.4.1 | 6.04.0001 | `C:\Program Files (x86)\HEC\HEC-RAS\6.4.1\Ras.exe` | `0fd3bcef58db429bc2faa0c926d5da4ca64918d398ce9db349f138aee1d533f6` |
| 6.5 | 6.05 | `C:\Program Files (x86)\HEC\HEC-RAS\6.5\Ras.exe` | `b23bd359f47e2a869a5b931a98b461c43978d86c6250894e88a09b21f8aae99d` |
| 6.6 | 6.06 | `C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe` | `a34e56a172ba06cde2d546f4d7282801c2b67040969d4ed23b41dfc755772134` |
| 6.7 Beta 4 | 6.07 | `C:\Program Files (x86)\HEC\HEC-RAS\6.7 Beta 4\Ras.exe` | `b3c8df2e68ed51da64a29c277b9ff558bba217817b017df577a6dba9064e260a` |
| 6.7 Beta 5 | 6.07 | `C:\Program Files (x86)\HEC\HEC-RAS\6.7 Beta 5\Ras.exe` | `80e708b51e68f342359817b1dc54559da0f8b57021a0b42cf9f64b61c32b6524` |
| 7.0 | 7.00 | `C:\Program Files (x86)\HEC\HEC-RAS\7.0\Ras.exe` | `9990c10531221469bf51a9a62ae91f36ec01e651bed83aadf632e678130ae797` |

The 6.7 Beta 4 and Beta 5 executables report the same file product version, so
the path and executable hash are required to distinguish them. The prior
harness also recorded that `RAS506` resolved to the 5.0.5 executable and that
the generic `RAS67` controller resolved to Beta 5; exact executable/controller
identity must remain a qualification invariant.

## Disposable destinations and record archive

Network lane root:

`H:\CLB-Repos\ras-commander\working\structured_execution_evidence_2026-08-24\multiversion_fixtures\lanes\<plan_type>\<version_slug>`

Local lane root used to distinguish old-controller failures from network-path
failures:

`C:\Users\billk_clb\AppData\Local\ras-commander\structured_execution_evidence_2026-08-24\lanes\<plan_type>\<version_slug>`

The local root was canonical for versions 5.0, 5.0.1, 5.0.3, and 5.0.7 in the
final harness. Some earlier H-drive attempt copies for those versions also
remain and must not be mistaken for the final lane. The 5.0.4, 5.0.5, 5.0.6,
and 6.0 staged lanes remained under the network root.

Record root:

`H:\CLB-Repos\ras-commander\working\structured_execution_evidence_2026-08-24\multiversion_fixtures\records\<lane_id>`

Each final lane has `record.json`, `runner.log`, and normally
`stage_assets.parquet`. Completed lanes also have `execution_evidence.json`.
The four legacy completions additionally have a successful real
`rascontrol_result_probe.parquet`; legacy Controller messages are retained in
`rascontrol_compute_messages.txt` and beside the project as
`<project>.p##.comp_msgs.txt`.

Archive size snapshot:

| Root | Files | Bytes |
|---|---:|---:|
| Network `sources` | 159 | 363,267,813 |
| Network `lanes` | 2,398 | 5,659,445,969 |
| Network `records` | 283 | 11,824,857 |
| Local old-controller `lanes` | 544 | 1,422,811,092 |

There are 77 record directories: 58 canonical final-lane records and 19
retained diagnostic attempts. The `matrix.*` files intentionally summarize
only the 58 canonical records.

## Reusable captured outputs

All paths below are `staged_execution_output`: they were generated by actual
HEC-RAS executions in disposable copies. `matrix.parquet` is the canonical
lookup for the exact result path and SHA-256 of every completed lane.

### Legacy-only captures

| Lane | Result | SHA-256 | Companion evidence |
|---|---|---|---|
| `steady_1d__4_0` | `...\lanes\steady_1d\4_0\EX1.O01` | `8a954d8366d31647ee69657cd8ef1a1a87eb04bff297381ceeff8c828184f49c` | `EX1.p01.comp_msgs.txt`; 30-row Parquet probe |
| `steady_1d__4_1_0` | `...\lanes\steady_1d\4_1_0\EX1.O01` | `bacfb38f203640e466b8c83ad77e6f963bb68b6fe5edef78fec89f9354ffe27a` | `EX1.p01.comp_msgs.txt`; 30-row Parquet probe |
| `unsteady_1d__4_0` | `...\lanes\unsteady_1d\4_0\HagerLatWeir.O06` | `5587b6cc11555b80fde1a5d00f36076da0c5119b0e4a7d4370b9adf2c220d76e` | `HagerLatWeir.p06.comp_msgs.txt`; 21-row Parquet probe |
| `unsteady_1d__4_1_0` | `...\lanes\unsteady_1d\4_1_0\HagerLatWeir.O06` | `951b0d5b4018911e04e79f75700315798bf51d26041f4b7bad655162c9531b83` | `HagerLatWeir.p06.comp_msgs.txt`; 21-row Parquet probe |

These four are suitable offline references for legacy completion messages,
producer-version parsing, result-path selection, and real RASControl result
access. They still need fresh-copy reruns to qualify PR 319 cleanup.

### Modern 1D mixed-format captures

Each directory contains both the listed plan HDF and the same-plan `.O##`.
The `.O##` is newer by roughly one to two seconds in every lane.

| Project/result name | Version directories |
|---|---|
| `...\lanes\steady_1d\<version_slug>\EX1.p01.hdf` plus `EX1.O01` | `6_1`, `6_2`, `6_3`, `6_3_1`, `6_4_1`, `6_5`, `6_6`, `6_7_beta_4`, `6_7_beta_5`, `7_0` |
| `...\lanes\unsteady_1d\<version_slug>\HagerLatWeir.p06.hdf` plus `HagerLatWeir.O06` | `6_1`, `6_2`, `6_3`, `6_3_1`, `6_4_1`, `6_5`, `6_6`, `6_7_beta_4`, `6_7_beta_5`, `7_0` |

These twenty lanes are the strongest real-world regression fixtures for mixed
result-family inspection. Use copies for any timestamp permutation; do not
touch the archive. They are not clean baselines for the invariant “a modern
ras-commander execution leaves HDF only.”

### Modern 2D HDF-only captures

The exact result pattern is:

`H:\CLB-Repos\ras-commander\working\structured_execution_evidence_2026-08-24\multiversion_fixtures\lanes\unsteady_2d\<version_slug>\BaldEagleDamBrk.p18.hdf`

Available version directories are `6_1`, `6_2`, `6_3`, `6_3_1`, `6_4_1`,
`6_5`, `6_6`, `6_7_beta_4`, `6_7_beta_5`, and `7_0`. No `.O18` is present in
any of these ten completed lanes. The exact SHA-256 for each HDF is retained in
`matrix.parquet`/`matrix.csv`.

### Archived failure and gate evidence

- 5.0 through 5.0.6 unsteady 1D and 2D were staged and then deliberately
  blocked without execution; 6.0 unsteady 1D and 2D were handled the same way.
- 5.x exact controllers blocked or failed in `Project_Open` before plan
  dispatch on this host; moving projects to the local lane root did not resolve
  the 5.0 failure.
- 5.0.6 steady command-line execution returned `success=False` and produced no
  fresh `EX1.p01.hdf`.
- Early attempt records preserve useful failure modes: symbolic/reparse-point
  rejection, missing staging parent, reserved staging metadata, first-launch
  dialog race, unsupported command-line automation, network versus local COM
  open failure, and a shallow-DSS readiness gate.

Treat these as `archived_failed_execution`. They can be asserted offline and
used to design controlled failure injection, but they are not successful
result fixtures.

## Gaps to close

1. **The archive predates PR 319 cleanup.** Re-run representative engines from
   fresh source copies and prove the opposing result family is absent after
   confirmed solver quiescence.
2. **Hager and Bald Eagle lack extraction receipts.** Record RasExamples key,
   HEC-RAS examples archive/version, archive hash, extraction timestamp, and
   source-tree fingerprint in the new manifest.
3. **The old evidence refresh used a dirty inspector worktree.** New records
   must include a clean git commit and source-file hash. Old outputs remain
   valid real artifacts, but old interpretation records should be regenerated
   read-only under PR 319.
4. **5.x and 6.0 do not have exact successful execution lanes.** Keep these as
   explicit automation-boundary tests until a reliable, version-specific
   Controller path is established; do not silently substitute another engine.
5. **No 5.x 2D output was produced in this matrix.** The 2D fixture matrix starts
   at 5.0, but all 5.x rows are blocked.
6. **No 6.3.0.2 installation appears in the manifest.** If that maintenance
   build is required, locate/install it and hash it explicitly rather than
   treating 6.3 as equivalent.
7. **Local failed/staged projects are machine-specific.** Preserve them until
   their evidence is normalized into the central record store; do not rely on
   them as portable fixtures.
8. **The archive has no generated edge-case corpus.** Timestamp equality,
   copied-folder timestamp rewrites, corrupt/incomplete HDF, locked deletion,
   active writer, and interrupted promotion still need clearly labeled
   `generated_edge_case` fixtures.
9. **The old 58-lane report lacks a complete before/after artifact inventory.**
   The new harness should inventory every allowlisted result/message path before
   cleanup, after pre-launch cleanup, after execution, and after post-quiescence
   cleanup.

## Proposed representative first packet

Use a new destination root; do not reuse or mutate the 2026-08-24 archive. A
suitable root is:

`H:\CLB-Repos\ras-commander\working\pr319_qualification_2026-08-28\lanes`

Run every live lane in a separate Python process through public ras-commander
APIs, with the exact executable path and hash recorded. The first packet should
have two parts.

### Packet A: read-only captured-artifact regression

Copy, then inspect, these 13 archived lanes without invoking HEC-RAS:

- legacy anchors: steady 1D and unsteady 1D at 4.0 and 4.1.0;
- modern anchors: all three plan types at 6.1, 6.6, and 7.0.

This gives four legacy-only, six mixed-modern-1D, and three HDF-only-2D cases.
For every copied lane, fingerprint watched files before and after inspection and
require byte and timestamp identity. This immediately exercises missing plan
declarations, old plan declarations, mixed result families, and HDF-only 2D
results using actual engine outputs.

### Packet B: fresh real-engine execution

Stage fresh copies of the three exact sources above and execute these 13 lanes:

| Engine | Steady 1D plan 01 | Unsteady 1D plan 06 | Unsteady 2D plan 18 | Purpose |
|---|:---:|:---:|:---:|---|
| 4.0 | yes | yes | no | Earliest legacy engine; require `.O##` plus stored messages and no plan HDF. |
| 4.1.0 | yes | yes | no | Second legacy implementation and Controller mapping. |
| 6.1 | yes | yes | yes | Earliest modern engine that completed all applicable lanes in the old matrix. |
| 6.6 | yes | yes | yes | Stable modern 6.x anchor. |
| 7.0 | yes | yes | yes | Latest installed engine anchor. |

For each modern lane, seed a copied opposing `.O##` before execution so the
pre-launch cleanup is exercised, then verify that any `.O##` recreated by
HEC-RAS is removed only after solver quiescence. Final state must be one complete
plan HDF and no same-plan `.O##`. For each legacy lane, seed a copied plan HDF,
then require one fresh `.O##`, stored compute messages, and no plan HDF. In all
cases, prove source-tree immutability and no surviving owned HEC-RAS process.

Do not include live 5.x or 6.0 execution in this first packet. First replay their
archived gate records offline and validate that exact engine identity fails
closed without mutation. A separately approved packet can then investigate
version-specific Controller behavior without weakening the exact-version rule.

If Packet A and Packet B pass twice from new copies, extend to 6.2, 6.3, 6.3.1,
6.4.1, 6.5, and both 6.7 beta executable hashes, then revisit the 5.x/6.0
automation boundary and the full 58-lane matrix.
