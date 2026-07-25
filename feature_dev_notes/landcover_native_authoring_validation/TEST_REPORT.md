# Test Report

## Hydraulic qualification

- HEC-RAS 5.0.7 public native authoring: passed.
- HEC-RAS 5.0.7 native TIFF association: passed.
- HEC-RAS 5.0.7 public native property-table recompute: passed.
- HEC-RAS 5.0.7 `RasCmdr.compute_plan` completion: passed.
- HEC-RAS 5.0.7 completed plan HDF Manning audit: passed, 46,505 face
  profile rows and 10 material values.
- HEC-RAS 6.6 public native authoring: passed.
- HEC-RAS 6.6 native HDF association: passed.
- HEC-RAS 6.6 public native property-table recompute: passed.
- HEC-RAS 6.6 `RasCmdr.compute_plan` completion: passed.
- HEC-RAS 6.6 completed plan HDF Manning audit: passed, 5,765 cells and
  47,055 face profile rows with the same 10 material values.
- HEC-RAS 6.6 native parameter-table edit/save/reload: passed.

See the machine-readable result manifests for paths and SHA-256 hashes.

## Focused regression suite

Command:

```text
python -m pytest tests/test_landcover_native.py \
  tests/test_hdf_landcover_logging.py \
  tests/test_rasmap_land_classification.py \
  tests/test_spatial_extent.py \
  tests/test_geometry_association.py \
  tests/test_legacy_plan_execution_helpers.py -q
```

Result: 78 passed, 5 skipped. The three emitted warnings are intentional
deprecation warnings for the renamed non-authoritative Python raster estimate.

`ruff check` passed on every changed Python module and test.

## Repository-wide suite

The repository-wide single-process run reached 1,806 passed and 55 skipped,
with 20 failures and 8 errors outside this change's focused gate. Principal
causes included a test-injected `clr` module with `__spec__ = None` contaminating
later pythonnet integrations, missing/external fixture drift, citation/notebook
drift, and a native JVM/DSS access violation. The land-cover tests pass when
run in a fresh process, and the live HEC runs above provide the authoritative
integration gate for this change.
