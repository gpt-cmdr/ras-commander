# Native mesh quarantine qualification

Covers native cell-polygon assembly for bridge `API_VERSION` 11 (engine API
10). The qualification originally ran on engine
`0b024adc7857e9fb2d364997ad002e01a939cec1`; `qualification.py` accepts the
engine commits listed in `tests/native_engine_provenance.py`, or exactly
`RAS_EXPECTED_ENGINE_COMMIT` when it is set.

## Direct binding

`ras_commander_fast_hdf.assemble_cells(face_points, face_endpoints,
face_perimeter_info, face_perimeter_values, cell_face_info, cell_face_values,
threads=None, *, strict=True, return_diagnostics=False)`

- Default call returns three arrays: `(coordinates (N, 2), ring offsets (C+1),
  original cell ids (C))`. Rings are closed and retain every face perimeter
  sample (curved and reversed faces included).
- `strict=False` quarantines geometric ring invalidity only;
  `return_diagnostics=True` adds a fourth element, a list of dicts with at
  least `cell_id`, `kind` (`"invalid_geometry"`) and `message`.
- Structural damage (offsets, counts, face/endpoint/perimeter indices, NaN
  coordinates, missing columns, disconnected rings) always raises
  `TopologyError` with `mesh_structure_error=True`, in strict and quarantine
  mode alike. Strict geometric failures raise `TopologyError` with
  `mesh_structure_error=False`, naming the first original cell (`cell N:`).
- Ghost/empty cells are expected non-polygons, never diagnostics. Results are
  identical for every thread count; inputs are never mutated.

## Release contract (`HdfMesh.get_mesh_cell_polygons`)

| Mode | Behaviour |
|------|-----------|
| auto (`RAS_COMMANDER_FAST_HDF` unset/`auto`, `engine="auto"`) | Exactly the Python reference outcome: same frame, CRS and `cell_polygon_diagnostics`, or the same exception. Any native refusal, corruption or invalid geometry falls back to h5py/Python. |
| native (`=native`/`required`, or `engine="native"`) | Never falls back to Python polygonize. Valid and quarantined meshes return the reference frame and diagnostics. Structural corruption raises `FastHdfError` (non-strict); with `strict=True` every native `TopologyError`, structural included, raises the documented strict `MeshCellPolygonError`. A missing/incompatible extension raises `FastHdfError`. |
| h5py (`=h5py`/`0`, or `engine="h5py"`) | Never imports or calls the extension. |

Native diagnostics records keep the Python reference schema exactly:
`mesh_name, cell_id, face_count, polygon_count, status, reason_code, face_ids,
missing_face_ids`. Invalid rings are `status="omitted"`,
`reason_code="no_polygon"`; ghosts are `boundary_only`/`insufficient_faces`;
zero-face records are `zero_faces`. The native failure kind and message are
logged at debug level only, never added to the record.

## Running

The regression suite needs no fixtures and passes in all three modes; tests
that need the extension skip cleanly when it is not importable:

    python -m pytest tests/rust_mesh_quarantine/test_quarantine.py -q
    RAS_COMMANDER_FAST_HDF=h5py python -m pytest tests/rust_mesh_quarantine/test_quarantine.py -q
    RAS_COMMANDER_FAST_HDF=native python -m pytest tests/rust_mesh_quarantine/test_quarantine.py -q

Synthetic fixtures store `Projection` as a fixed-length ASCII string, as
HEC-RAS does; the native attribute reader refuses vlen/non-ASCII metadata
(a legitimate refusal that required mode would surface).

The full immutable corpus (file names, stored versions, polygon counts and
SHA256 values pinned in `qualification.py`) runs as a script against an
installed extension:

    python tests/rust_mesh_quarantine/qualification.py \
        --fixture-root <dir with the pinned HDFs> --output <ignored>/qualification.json

(`RAS_QUAL_FIXTURES` may replace `--fixture-root`.) For each fixture it
compares required native at 1 and 4 threads and auto mode against the Python
reference: every composite ID, every normalized coordinate (exact consecutive
duplicate samples removed, orientation/start normalized with GEOS), and the
diagnostic records exactly. Python polygonize is forbidden during required
native runs. The public fixtures (the FEMA eBFE `AustinOyster.p03` 5.0.7 plan,
`BaldEagleDamBrk.p07`, `BaldEagleDamBrk.p18`) have no invalid cells, so a derived
copy of the public `AustinOyster.p01` with two invalid cells
(`tests/mesh_invalid_cells.py`, written to a temporary folder) covers that case:
strict native must fail on original cell 1420, auto strict must raise the same
exception as Python, and a detached-array probe (changing only the first invalid
cell's count in a copy) must expose cell 1479. Source: FEMA estimated Base Flood
Elevation (eBFE) program. The source HDF hash is checked before and after.

Timing scope is mesh extraction only. Assembly, adapter dataset reads and the
adapter/output residual, and 10 ms sampled absolute process RSS are reported
separately. These are single warm-process observations, not isolated-memory,
cold-cache, statistical, export-pipeline or solver claims.
