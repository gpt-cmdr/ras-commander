# Qualification and Troubleshooting

## Minimum qualification matrix

Run the same fixture on native Windows and under Wine with the exact HEC-RAS
version. Include project open/save/clone, geometry completion, terrain creation,
mesh/property tables where applicable, unsteady compute through the vendor Linux
solver, stored-map export, restart/recovery, long paths, failure diagnostics,
and isolated concurrency.

Inspect content, not only exit status:

- exact 2D cell/face counts, boundary assignments, and topology fingerprints;
- property-table completeness and invalid-cell count;
- geometry and terrain fingerprints;
- volume-accounting error and hydrograph/WSE tolerances;
- raster CRS, transform, dimensions, nodata, overlap, values, and pixel hashes;
- no critical skips on the private integration runner.

Muncie is the preferred small Windows/Wine parity fixture. BaldEagleCrkMulti2D
is appropriate for mesh and projection-dependent mapper operations.

## Known-good operating rules

- A coherent zero-based CPU namespace passed Wine 11.0 and 11.13; upgrading Wine
  alone did not repair sparse-cpuset failures.
- Single-CPU pinning passed as a conservative fallback. `GDAL_NUM_THREADS=1`,
  NTSYNC, and CLR GC knobs did not repair the topology defect.
- One prefix shared by concurrent helpers stalled. Separate prefixes passed with
  exact raster hashes. Keep one helper per prefix.
- Wine map processing remains serialized. Do not describe it as native.

## Failure signatures

| Symptom | Likely cause | Action |
|---|---|---|
| CLR `0x80131506`, `0xc0000005`, nondeterministic seed hang | Sparse CPU namespace | Run preflight; expose coherent CPU IDs or pin entire Wine tree to safe fallback |
| One of two helpers stalls | Shared writable Wine prefix | Give every helper its own copied prefix and project |
| `HDF.PInvoke.H5F` initializer fails | Missing/mixed native HDF DLLs | Copy the complete same-version install tree including architecture subfolders |
| RasMapper assembly load error | Incomplete HEC-RAS payload | Restore all same-version managed assemblies and GDAL tree |
| TCU modal blocks headless launch | Prefix lacks accepted state | Check `RasTcu.status()` and use authorized donor-based `RasTcu.accept()` |
| Stored-map command exits but raster differs | Wrong render/interpolation path or version mix | Use bundled RasStoreMapHelper, match render mode, compare content to Windows golden |
| Terrain build cannot locate HEC-RAS | Portable install not discoverable | Configure `RasProcess` explicitly and verify the terrain command's version lookup |

## Stop conditions

Stop and report the instance as unqualified when the preflight is unsafe, the
TCU donor is absent, binaries are mixed or incomplete, a critical test is
skipped, a helper shares writable state, or output content exceeds tolerance.
