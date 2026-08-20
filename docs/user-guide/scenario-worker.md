# Scenario Worker

`ras-scenario-worker` is the package-owned process boundary for one isolated
HEC-RAS scenario. It lets an orchestrator invoke RAS Commander from a dedicated
RAS environment without importing RAS Commander into the orchestrator.

The versioned request binds the scenario to:

- the source project checksum, full model-manifest identity, and exact template
  plan;
- the HMS result DSS and hydrologic product-manifest identities;
- every exact DSS boundary selector;
- the run-local gridded `EXCESS` DSS and provenance identity;
- the local model window, RAS executable, core count, and timeout; and
- new workspace and hydraulic-product destinations.

Run a request with either entry point:

```powershell
ras-scenario-worker --request request.json --result result.json

python -m ras_commander.RasScenarioWorker `
  --request request.json `
  --result result.json
```

The worker calls `RasScenario.prepare_workspace()`, `RasScenario.execute()`,
and `HdfResultsProducts.export()`. The original model is not mutated. A
successful result includes current-plan, simulation-window, newline,
geometry-crosswalk, DSS-link, HDF-completion, time-axis, product, numerical
QA/QC, and timing evidence.

Newline evidence covers authored project, plan, geometry, and flow text files;
generated `.b##`, `.c##`, `.o##`, `.r##`, and `.x##` compute artifacts are
excluded because they may be binary.

Scenario clones omit source-project generated outputs: the project-named DSS,
plan and temporary plan HDF files, and RAS Mapper `PostProcessing.hdf` caches.
Geometry HDF inputs remain in the clone. The preparation result records every
excluded path and byte count so the reduced clone is auditable.

Mechanical execution and hydraulic acceptance remain separate. Compute-message
findings such as ignored boundaries, precipitation coverage, maximum
iterations, water-surface error, and volume accounting are returned under
`conditional_findings`; their presence does not rewrite a mechanically
successful execution as a failure.

## Repeat and failure behavior

A verified successful result for the identical normalized request is returned
without rerunning RAS. The worker refuses an existing workspace, product
directory, conflicting result, or changed completed output. Timeout and failed
attempt workspaces are retained for diagnosis and GUI review, and failure
results are written atomically when possible.

## Shared linked-asset cache and preparation retry

Large immutable linked directories such as `Terrain`, `Land Cover`, and
`Hydrologic Input` do not need a private copy for every scenario. Set
`source_model.linked_asset_mode` to `shared-cache` and place scenario workspace
directories directly below one stable cache root. The first request copies or
adopts the linked directories beside the workspace, content-compares them with
their declared sources, records an identity manifest, and marks cached files
read-only. Later sibling workspaces verify the cache metadata and reuse it
without copying the large assets again.

```json
{
  "source_model": {
    "linked_asset_mode": "shared-cache",
    "linked_asset_directories": [
      "C:/models/release/Terrain",
      "C:/models/release/Land Cover"
    ]
  },
  "workspace": "C:/ras-cache/model-manifest-sha/scenario-001"
}
```

The cache key is the request's verified RAS model-manifest SHA-256. A different
key, source path, file population, size, or modification time fails closed.
Cache adoption may read both large trees once to establish their content
identity, but it does not allocate another copy.

A corrected retry after a preparation-only failure may reference the preserved
prior request and result:

```json
{
  "retry": {
    "prior_request": "C:/evidence/failed-request.json",
    "prior_result": "C:/evidence/failed-result.json"
  }
}
```

The worker authenticates the prior request/result binding, requires execution
to remain `not_started`, preserves the failed workspace, and requires the new
workspace to be a sibling under the same cache root. Scenario, source-model,
hydrology, forcing-excess, and model-window identities cannot change; corrected
boundary selectors and execution options may change.

The packaged contracts are:

- `ras-commander/scenario-worker-request/1.0`
- `ras-commander/scenario-worker-result/1.0`

## Configure the installed-engine test

The installed-engine test is opt-in through the `integration` pytest marker.
Configure its inputs with environment variables in the shell that launches
pytest:

| Variable | Required | Value |
| --- | --- | --- |
| `RAS_WORKER_TEST_SOURCE_PROJECT` | Yes | Source `.prj` file or directory containing one project |
| `RAS_WORKER_TEST_SOURCE_PLAN` | Yes | Template plan number, such as `01` |
| `RAS_WORKER_TEST_MODEL_MANIFEST` | Yes | JSON model manifest whose `stage` is `ras` |
| `RAS_WORKER_TEST_HYDROLOGY_DSS` | Yes | HMS result DSS used by the boundary links |
| `RAS_WORKER_TEST_HYDROLOGY_MANIFEST` | Yes | `hms-commander/hydrologic-product-manifest/1.0` JSON that identifies the HMS DSS checksum |
| `RAS_WORKER_TEST_BOUNDARY_LINKS_JSON` | Yes | JSON array of worker boundary-link objects |
| `RAS_WORKER_TEST_EXCESS_DSS` | Yes | Run-local gridded excess DSS |
| `RAS_WORKER_TEST_EXCESS_MANIFEST` | Yes | JSON provenance manifest for the excess DSS |
| `RAS_WORKER_TEST_EXCESS_PATHNAME` | Yes | Six-part DSS pathname family, ending with `/` |
| `RAS_WORKER_TEST_EXECUTABLE` | Yes | Installed `Ras.exe` path |
| `RAS_WORKER_TEST_START` / `RAS_WORKER_TEST_END` | No | Naive local model timestamps; defaults cover the DeLoutre canary window |
| `RAS_WORKER_TEST_TIME_ZONE` | No | IANA time-zone identity; default `America/Chicago` |
| `RAS_WORKER_TEST_TIMEOUT_SECONDS` | No | Positive worker timeout; default `7200` |
| `RAS_WORKER_TEST_CORES` | No | Positive RAS core count; default `2` |
| `RAS_WORKER_TEST_WORKSPACE` | No | New, nonexistent workspace path |
| `RAS_WORKER_TEST_LINKED_ASSETS_JSON` | No | JSON array of immutable linked-asset directories |
| `RAS_WORKER_TEST_LINKED_ASSET_MODE` | No | `copy` or `shared-cache`; default `copy` |
| `RAS_WORKER_TEST_RETRY_REQUEST` / `RAS_WORKER_TEST_RETRY_RESULT` | No | Authenticated preparation-only retry evidence; configure both or neither |

For example:

```powershell
$env:RAS_WORKER_TEST_SOURCE_PROJECT = 'C:\models\release\Model.prj'
$env:RAS_WORKER_TEST_SOURCE_PLAN = '01'
$env:RAS_WORKER_TEST_MODEL_MANIFEST = 'C:\evidence\ras-model.json'
$env:RAS_WORKER_TEST_HYDROLOGY_DSS = 'C:\inputs\hms-output.dss'
$env:RAS_WORKER_TEST_HYDROLOGY_MANIFEST = 'C:\inputs\hydrologic-products.json'
$env:RAS_WORKER_TEST_BOUNDARY_LINKS_JSON = Get-Content -Raw '.\boundary-links.json'
$env:RAS_WORKER_TEST_EXCESS_DSS = 'C:\inputs\ras-excess.dss'
$env:RAS_WORKER_TEST_EXCESS_MANIFEST = 'C:\inputs\ras-excess.json'
$env:RAS_WORKER_TEST_EXCESS_PATHNAME = '/SHG/BASIN/PRECIPITATION///EXCESS/'
$env:RAS_WORKER_TEST_EXECUTABLE = 'C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe'
$env:RAS_WORKER_TEST_WORKSPACE = 'C:\ras-cache\model-hash\canary-001'
$env:RAS_WORKER_TEST_LINKED_ASSETS_JSON = '["C:/models/release/Terrain"]'
$env:RAS_WORKER_TEST_LINKED_ASSET_MODE = 'shared-cache'

python -m pytest tests\test_scenario_worker.py `
  -m integration `
  -k installed_engine_executes_one_scenario `
  --basetemp .\working\pytest-scenario-worker-installed
```

Use a fresh `--basetemp` and workspace for each new attempt. A shared cache
can adopt an existing directory only when its content matches the declared
canonical source; otherwise the worker fails closed before RAS execution.
