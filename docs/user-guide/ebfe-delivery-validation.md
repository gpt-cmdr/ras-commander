# eBFE Delivery Validation

Use this checklist before considering an organized eBFE or BLE model ready for
handoff, notebooks, or downstream automation. A project that only initializes in
ras-commander is not fully validated; it must also pass a preprocessor run and
compute-message review.

Track canonical project-by-project readiness in the repository-level
`VALIDATION_MATRIX.md`; generated reports belong under the shared eBFE data
workspace, currently `H:\Testing\eBFE Model Organization\Validation`.

## Validation Status Levels

- `organized`: Files were copied into the delivery folder structure.
- `hms_validated`: Delivered HMS projects are present under `HMS Model/`, internal HMS file references resolve, and hms-commander can load the project; RAS-only studies document the absence of HMS instead of receiving this status.
- `path_validated`: Project dataframes and `.rasmap` references resolve to local files.
- `preprocessor_validated`: A geometry preprocessor run completed and compute messages were reviewed.
- `results_validated`: Existing HDF result files are present, loadable, and mapped to the project plans.
- `notebook_validated`: Example notebooks run against the organized delivery without stale paths.

## Standard Delivery Layout

```text
{StudyArea}_{HUC8}/
├── HMS Model/
├── RAS Model/
│   └── {Watershed or Project Group}/
│       └── {ProjectName}/
│           ├── *.prj, *.g##, *.p##, *.u##, *.f##, *.hdf
│           ├── DSS Inputs/
│           ├── Projection/
│           ├── Terrain/
│           └── Land Cover/
├── Spatial Data/
├── Documentation/
└── agent/
    ├── model_log.md
    └── validation_report.md
```

For a single RAS project, the files may live directly under `RAS Model/`.
For many reach models, preserve the source watershed/reach grouping so the
organized folder remains traceable to the original delivery.

## Organization Checklist

- Every HEC-RAS project folder opens directly from the folder containing the `.prj` file.
- Pre-computed `.p##.hdf` result files are inside the same project folder as the matching `.p##` files.
- DSS files are copied into `DSS Inputs/` for each RAS project that needs them.
- All `DSS File=` and `DSS Filename=` references point to existing local DSS files.
- `.rasmap` points to a local projection file under `Projection/`.
- Terrain files are inside `Terrain/`, and `.rasmap` terrain references point there.
- Land cover files are inside `Land Cover/`, and `.rasmap` land cover references point there.
- Terrain and land cover CRS match the project CRS where those layers exist.
- Delivered HEC-HMS projects are copied into `HMS Model/`, preserving the source project folder.
- If no HMS project is delivered, `HMS Model/README.md` documents how hydrology is supplied instead.
- Original source grouping and names are preserved enough for engineering review.
- `agent/model_log.md` records source paths, organization decisions, fixes, and known limitations.

## HMS Checklist

For combined hms-commander plus ras-commander workflows, treat HMS as a separate
delivery gate rather than a side effect of RAS organization.

- `HMS Model/` exists in every organized study folder.
- If `.hms` files are delivered, each HMS project folder is copied intact under `HMS Model/`.
- `.hms`, `.basin`, `.met`, `.control`, `.grid`, and `.pdata` file references resolve to files inside the organized HMS folder or another approved local delivery subfolder.
- HMS DSS files referenced by `DSS File Name:`, `Filename:`, or similar HMS project fields are present locally.
- If hms-commander is available for the workflow, the project can be discovered and loaded without path repair.
- If no HMS project was delivered, a README explains whether hydrology is supplied by RAS steady flow files, RAS DSS inputs, gridded precipitation, or another documented source.
- The validation matrix records `✓` only for studies with an actual validated HMS project; RAS-only deliveries use `-` and document the reason in notes.

## Dataframe Checks

Initialize each RAS project with `init_ras_project()` and verify:

- `plan_df` has all expected plans.
- `plan_df["HDF_Results_Path"]` resolves to local HDF files where pre-computed results are expected.
- `boundaries_df["DSS File"]` has no broken `.dss` paths.
- `rasmap_df["projection_path"]` resolves inside the project folder or an approved delivery subfolder.
- `rasmap_df["terrain_hdf_path"]` resolves inside `Terrain/` for 2D projects.
- Land cover layers in `.rasmap` resolve inside `Land Cover/` for 2D projects.

## Preprocessor Checklist

Run a geometry preprocessor validation for at least one representative plan in
every RAS project folder. For projects with multiple geometries, run one plan
per unique geometry. Use detailed logging and compute-message review as the
acceptance gate; do not require full unsteady calculations or floodplain
mapping/post-processing for delivery-format validation.

For end-to-end model-library testing, prefer the repository harness so the
same workflow performs download/cache lookup, extraction, organization, path
audit, and optional preprocessor validation:

```powershell
.\.venv\Scripts\python scripts\ebfe_end_to_end_validation.py `
  --models rio-hondo north-galveston-bay `
  --download-root "H:\Testing\eBFE Model Organization\Downloads" `
  --output-root "H:\Testing\eBFE Model Organization\Organized" `
  --report-root "H:\Testing\eBFE Model Organization\Validation\ebfe_delivery" `
  --run-preprocessor `
  --max-wait 7200
```

Use `GeomPreprocessor.run_geometry_preprocessor()` for 1D steady, 1D/2D
unsteady, and 2D projects:

```python
from pathlib import Path
from ras_commander import GeomPreprocessor, RasPrj, init_ras_project

ras_obj = RasPrj()
init_ras_project(Path("path/to/RAS Project"), "6.5", ras_object=ras_obj)

result = GeomPreprocessor.run_geometry_preprocessor(
    "01",
    ras_object=ras_obj,
    max_wait=7200,
    force=True,
)

assert result.success, result.error
```

Required evidence:

- Preprocessor result succeeds.
- `.bco##`, `.comp_msgs.txt`, `.computeMsgs.txt`, or HDF compute messages are available where HEC-RAS writes them.
- `.c##`, `.g##.hdf`, `.x##`, or `.b##` geometry/preprocessor artifacts are present where applicable.
- Compute messages contain no `ERROR`, `FATAL`, `DSS path needs correction`,
  missing terrain, missing land cover, missing projection, or file-not-found messages.
- For 2D projects, terrain and land cover load during preprocessing.
- For large 2D projects, use a 7200-second timeout before treating a
  preprocessor run as inconclusive.
- For 1D steady projects, manually verify terrain and land cover only if the
  project includes mapper layers; most 1D BLE reach models will not.

## Results Checklist

- Existing HDF files are loadable with ras-commander HDF readers.
- `results_df` is populated for projects with pre-computed HDF results.
- Results belong to the organized project folder, not an external source path.
- If a project is preprocessor-only and has no existing result HDF, document that
  result files are intentionally absent.
- For 1D steady collections where result HDFs are absent, run the steady plans
  with `RasCmdr.compute_plan(..., verify=True)`, then parse detailed compute
  messages. Mark results resolved only when all selected plans produce local
  `.p##.hdf` files, contain `Complete Process`, and contain no blocking errors.

Rio Hondo-style 1D steady batch validation:

```powershell
.\.venv\Scripts\python scripts\ebfe_steady_plan_batch.py `
  --root "H:\Testing\eBFE Model Organization\Organized\RioHondo_13060008\RAS Model" `
  --ras-version 6.6 `
  --output-dir "H:\Testing\eBFE Model Organization\Validation\ebfe_delivery\steady_plan_validation"
```

## Notebook Checklist

- Example notebooks use the organized delivery format paths.
- Notebooks use dataframe-derived paths for plans, DSS files, terrain, land cover,
  and result HDF files.
- Notebooks demonstrate preprocessor validation instead of full unsteady
  computation when the goal is delivery verification.
- Notebook text and file trees match `DSS Inputs/`, `Projection/`, `Terrain/`,
  and `Land Cover/`.
- Stored outputs are refreshed after path or delivery-format changes.

## Acceptance Criteria

An organized eBFE project is delivery-ready only when:

- It passes the organization checklist.
- It passes HMS validation when a separate HMS project is delivered, or clearly documents that no HMS project was delivered.
- It passes dataframe path validation.
- It passes preprocessor validation with reviewed compute messages.
- If pre-computed result HDFs were absent but the model is a 1D steady
  collection, all selected steady plans run successfully and their generated HDF
  compute messages are reviewed.
- It has an `agent/validation_report.md` with the exact plans/geometries checked.
- Any missing archives, manual checks, or unsupported steady preprocessor gaps are
  explicitly documented.
