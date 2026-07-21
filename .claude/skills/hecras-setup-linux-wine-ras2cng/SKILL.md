---
name: hecras-setup-linux-wine-ras2cng
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
description: Set up, audit, and qualify isolated headless Linux instances that use the official HEC-RAS Linux solvers where supported and Windows HEC-RAS RasProcess/RASMapper components through Wine for remaining geometry, terrain, and ras2cng map-export gaps. Use for Linux, Wine, Apptainer, Proxmox/LXC, Slurm/HPC, ras2cng, RasProcess.exe, RasStoreMapHelper, Wine-prefix isolation, CPU-topology crashes, TCU provisioning, or native-Windows parity qualification.
---

# Set Up Headless Linux/Wine/Ras2Cng

Use a two-lane runtime. Prefer vendor Linux executables for computations and any
preprocessing operation officially supported by the installed HEC-RAS version.
Use the same Windows HEC-RAS version under pinned Wine only for gaps such as
RasProcess geometry/terrain work and RASMapper-backed ras2cng stored maps.

## Workflow

1. Identify the exact HEC-RAS version and the requested operations.
2. Read [references/setup-runbook.md](references/setup-runbook.md) before changing
   a host, prefix, scheduler template, or container image.
3. Run the native-Linux preflight before launching Wine:

   ```bash
   python .claude/skills/hecras-setup-linux-wine-ras2cng/scripts/headless_wine_preflight.py \
     --wine-prefix "$WINEPREFIX" \
     --ras-install-dir "$RAS_INSTALL_DIR" \
     --require-safe-topology --require-runtime --require-python-packages
   ```

4. Fail closed when `wine_topology_safe` is false. Do not widen a scheduler
   allocation. Prefer a coherent zero-based visible CPU namespace plus a CPU
   quota. A single allowed CPU whose ID is below the reported processor count is
   the fallback, not the production default.
5. Create one writable prefix and one writable project copy per scheduler task.
   Never run concurrent RASMapper helpers in one prefix. Use `--map-workers 1`
   for a single ras2cng process and scale across isolated tasks/prefixes.
6. Configure ras-commander and verify content:

   ```python
   from ras_commander import RasProcess

   RasProcess.configure_wine(
       wine_prefix="/work/$JOB_ID/wine",
       wine_executable="/opt/wine-11.0/bin/wine",
       ras_install_dir="/work/$JOB_ID/wine/drive_c/HEC-RAS/7.0",
   )
   status = RasProcess.check_wine_environment()
   assert status["wine_found"] and status["rasprocess_found"]
   ```

7. Qualify a representative fixture against a native-Windows golden before
   production use. Read
   [references/qualification-and-troubleshooting.md](references/qualification-and-troubleshooting.md).

## Execution Routing

| Operation | Default route |
|---|---|
| Unsteady/steady compute | Official HEC-RAS Linux executable when supported |
| Geometry preprocessing | Official Linux `RasGeomPreprocess` when supported; otherwise qualified Wine `RasProcess.compute_geometry()` |
| RASMapper mesh, terrain, and property-table gaps | Qualified Windows components under Wine |
| Result raster generation | ras2cng `map`/`map-hdf` through the bundled RasStoreMapHelper under Wine |
| GeoParquet/COG/PMTiles conversion | Native-Linux Python/GDAL/ras2cng |

Do not call the Wine path "native." Use "vendor Linux executable," "native
Windows," or "Windows component under Wine" so provenance stays unambiguous.

## TCU Handling

Never use a generic dialog watchdog to click an unknown button. Check with
`RasTcu.status()`. If the operator has already accepted the same installed
HEC-RAS version and authorizes reuse, run Windows Python inside Wine and seed
the current Wine user with the audited donor-based `RasTcu.accept()` flow (or `init_ras_project(...,
accept_tcu=True)`). If no donor exists, report the blocker; do not fabricate
acceptance.

## Ras2Cng Headless Pattern

```bash
ras2cng map /work/$JOB_ID/project /work/$JOB_ID/maps \
  --ras-version 7.0 \
  --rasprocess "$RAS_INSTALL_DIR" \
  --map-workers 1 \
  --depth --wse --velocity --cog --fail-fast
```

For concurrent plans, submit separate jobs with distinct `WINEPREFIX`, project,
and output paths. Do not share an active HDF or writable prefix.

## Completion Standard

Do not declare the host ready from exit code alone. Record Wine and HEC-RAS
versions, prefix identity, CPU topology, project fingerprint, exact mesh
cell/face counts, property-table completeness, raster metadata and pixel hashes,
and hydraulic tolerances. Mark untested operations unqualified.
