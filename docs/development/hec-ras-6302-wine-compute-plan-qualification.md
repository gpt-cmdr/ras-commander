# HEC-RAS 6.3.0.2 Wine `compute_plan` qualification

## Outcome

The lean `ras_commander.compute` facade is qualified for one real HEC-RAS
6.3.0.2 1D steady plan under Wine without RasControl or another Controller/COM
call. `RasCmdr.compute_plan()` launched the normal HEC-RAS command-line path,
HEC-RAS materialized its own steady run files, and ras-commander extracted the
completed result HDF directly.

This is a bounded integration qualification, not a claim that every HEC-RAS
6.3 model is qualified or that a downstream ras2fim container is production
ready. The downstream container still needs to pin this wheel, clone an
accepted task-local Wine prefix, preserve its supervisor and receipt gates, and
repeat the acceptance tests through its public runner interface.

## Qualified identities

| Component | Qualified identity |
|---|---|
| HEC-RAS release | `6.3.0.2` (`HEC-RAS 6.3 August 2022` in HDF provenance) |
| Installer SHA-256 | `869e5455de14f23abfba1c9b73e7ef15b7c1b5cca3af12e8b95cb61e69832e57` |
| `Ras.exe` SHA-256 | `3a8f683961dcad82cfb15bbb68ec3df62c6510711dd89c37e3e09f52c9d8b860` |
| `x64/RasSteady.exe` SHA-256 | `b3e110ad72e74901e40622379828d95188d646e79a6c96f206c64e996bbecf6b` |
| ras-commander source | `bbddd42c4966967ab6967de4fbc3c4079ab13d10` |
| Qualification wheel SHA-256 | `fb36090e14634dfd584b309bf649e8b0673fcac9d2f03121c8ba42defa89ef5d` |
| Wine | `wine-11.0` |
| Container image | `localhost/ras2fim-hecras:6.3.0.2-ras-commander-69871c81` |
| Guest | isolated CT217 on CLB01; network disabled for compute |
| CPU allocation | affinity set `{0, 2}`; one HEC-RAS plan core |

The existing container was reused to isolate the code-path question. The PR
wheel was force-installed without dependency resolution from the local
wheelhouse. A downstream image must rebuild from pinned inputs rather than
relying on this qualification image.

## Exact execution path

The probe imported only the narrow integration facade:

```python
from ras_commander.compute import RasCmdr, RasPrj, init_ras_project

project = RasPrj()
init_ras_project(
    r"Z:\work\project\MIXED.PRJ",
    r"C:\Program Files (x86)\HEC\HEC-RAS\6.3\Ras.exe",
    ras_object=project,
    load_results_summary=False,
    hide_intro=True,
    accept_tcu=False,
    load_hdf_metadata=True,
)
result = RasCmdr.compute_plan(
    "01",
    ras_object=project,
    force_rerun=True,
    num_cores=1,
    verify=True,
    dialog_watchdog=False,
)
```

ras-commander constructed the HEC-RAS-owned command:

```text
C:\Program Files (x86)\HEC\HEC-RAS\6.3\Ras.exe \
  -c Z:\work\project\MIXED.PRJ Z:\work\project\MIXED.p01
```

HEC-RAS then performed the full vendor workflow. Process and file-transition
capture showed it:

1. create the steady `.r01` input;
2. create the plan `.p01.tmp.hdf` skeleton;
3. run `RasProcess.exe CompleteGeometry` and promote the refreshed geometry
   HDF;
4. launch `x64/RasSteady.exe` with the absolute `.r01` path;
5. grow the temporary result HDF and promote it to `.p01.hdf`.

No ras-commander or ras2fim code authored `.r01` or `.tmp.hdf` content.

## Terms acceptance boundary

HEC-RAS `Ras.exe -c` displays the release-specific Terms and Conditions for
Use dialog when the exact Windows user and install path lack accepted state.
The original probe correctly blocked there. Earlier acceptance artifacts were
failed receipts and were not treated as authorization evidence.

After explicit authorization for exact HEC-RAS 6.3.0.2, the visible dialog was
accepted for the task-local `runner` prefix only. The application was closed
cleanly so its VB6 user settings were persisted, and `RasTcu.status()` then
reported `accepted=True`. The successful receipt pins the same `Ras.exe` hash
shown above. Acceptance was not inferred, copied from a different release, or
performed by `init_ras_project()`.

Production images must provision that already-authorized state into the
immutable base prefix and clone it per task. They must fail closed if the exact
release, executable hash, user, or acceptance state differs.

## Real-result parity

The immutable `MIXED` fixture contains two steady profiles and 19 cross
sections. The no-COM run completed in 5.421 seconds as measured around
initialization, `compute_plan()`, verification, and DataFrame refresh.

`HdfResultsPlan.get_steady_results()` returned 38 rows. Mapping its steady HDF
fields to the ras2fim contract produced:

```text
fid_xs, modelid, Xsection_name, wse, discharge, max_depth, channel_length
```

| Gate | Result |
|---|---|
| Rows | `38` |
| Profiles × cross sections | `2 × 19` |
| `max_depth` source | `Maximum Depth Total` |
| `channel_length` source | `Geometry/Cross Sections/Attributes/Len Channel` |
| Result HDF SHA-256 | `316fb01821d099c9043f4554b869f2dc4a2dea825a3a0a7bc647ea35bc2fc920` |
| Linux-hosted ras2fim CSV SHA-256 | `6453f93e6ff40eae7842f73de42b0a6b0ff0fe25689b4673636595f826a98d5f` |
| Windows Controller CSV SHA-256 | `6453f93e6ff40eae7842f73de42b0a6b0ff0fe25689b4673636595f826a98d5f` |
| Maximum numeric difference | `4.440892098500626e-16` (`max_depth`) |

WSE, discharge, and channel length were exact. Text identities and ordering
were exact. The sub-machine-precision depth difference passed the `1e-6`
absolute-tolerance gate, and the serialized result CSVs were byte-identical.

## Supervision gate

A separate run forced the container-level timeout while the compute worker was
still active. The named container was stopped and removed, the task-local Wine
server was terminated, and post-cleanup inspection found:

- no owned HEC-RAS or Wine survivor processes;
- no matching container;
- a machine-readable timeout receipt with `stop_reason="timed_out"` and
  `success=true`.

The fixture solves very quickly, so its HDF may already be complete before a
short outer timeout interrupts post-compute inventory refresh. The gate proves
owned-process cleanup; downstream runner tests should retain their synthetic
long-running timeout fixture to exercise termination during active work too.

## Preserved failed experiments

The following results constrain future implementations:

- Direct `RasSteady.exe MIXED.r01` without `.p01.tmp.hdf` exits with an HDF5
  diagnostic stating that the temporary result HDF is missing.
- Copying a completed `.p01.hdf` to `.p01.tmp.hdf` is invalid; the solver
  reports that the output must not already exist.
- Replaying captured `.r01`, temporary HDF, and geometry HDF artifacts through
  a separately launched Windows `RasSteady.exe` reached 10% progress and then
  failed in `READ_HDF`. Do not advertise direct Windows-engine replay as a
  supported path from this evidence.
- The first `compute_plan()` probes timed out before creating run artifacts
  because the TCU dialog was visible. After exact-version acceptance, the same
  `Ras.exe -c` path completed. Those timeouts are not evidence that
  `compute_plan()` is incompatible with Wine.

## Remaining downstream gates

Before calling the ras2fim lane production-ready:

1. merge the ras-commander integration PR and pin the resulting immutable
   wheel in ras2fim;
2. rebuild the lean batch image from pinned dependencies and record its digest
   and final size;
3. replace the ras2fim steady bridge's `RasControl.run_plan()` call with normal
   `RasCmdr.compute_plan()` while retaining task-local prefix/project cloning,
   CPU affinity, supervision, semantic HDF validation, and receipts;
4. rerun terrain, steady parity, concurrency, and forced-timeout smoke tests
   through the ras2fim public container command;
5. qualify additional immutable model families. The current steady-result HDF
   fixture matrix covers 6.0.0, 6.3.1, 6.4.1, 6.6, and 7.0; no computed steady
   HDF fixture was available for 6.1, 6.2, or 6.5.
