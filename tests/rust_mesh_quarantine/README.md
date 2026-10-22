# Native mesh quarantine qualification

The direct native assemble_cells binding preserves its original positional arrays,
optional threads argument, default strict failure, and three-array return value.
New keyword-only strict=False quarantines geometric ring invalidity only;
return_diagnostics=True adds a fourth list of (cell_id, reason_code, reason).
Structural errors remain TopologyError and carry mesh_structure_error=True;
strict geometric failures carry False. Adapter code uses this typed marker,
never message matching, to prevent corruption fallback. Bounds are preflighted
for every cell before geometry. No repair, snapping, or source mutation occurs.

The high-level adapter checks the binding signature for both new keywords before
requesting quarantine. Older API_VERSION 1 binaries cannot claim support:
required Rust fails with a rebuild instruction; auto may use Python. No shared
registration/Cargo/API_VERSION edit is needed for this compatible capability gate.

Diagnostics preserve mesh_name, original cell_id, face_count, polygon_count,
status, reason_code, face_ids and missing_face_ids. Invalid rings use status
omitted and the canonical reason_code no_polygon. Records keep the Python
reference schema exactly (main #572 parity contract); the native failure kind
and message are logged at debug level instead of added to the record. Ghosts
remain boundary_only/insufficient_faces. Zero-face records retain zero_faces.
Metadata construction uses one cell mask and omission-only per-face slices;
there is no per-cell copying of whole topology arrays.

Run the new binding/adapter regressions with:

    .venv/Scripts/python.exe -m pytest tests/rust_mesh_quarantine/test_quarantine.py -q

Run the full immutable corpus (paths/hashes declared in qualification.py) with:

    .venv/Scripts/python.exe tests/rust_mesh_quarantine/qualification.py --output working/qualification.json

Full comparisons retain all forward collinear vertices, removing only exact
consecutive duplicate samples for comparison, and normalize orientation/start
with GEOS. Every composite ID and every normalized coordinate is compared.
Native read/assembly calls are counted and Python polygonize is forbidden.
The second strict5.x probe modifies only a detached array's first-invalid count,
retaining original ID339176; the source HDF is never changed.

The older test_hdf_mesh_cell_polygon_diagnostics.py suite contains assertions
for Python/native diagnostic equality and fallback over corrupt references.
Those expectations conflict with this packet's explicit native safety policy.
They remain unchanged for coordinator review; the Python-only suite still passes.
The new tests enforce the revised native contract independently.

Timing scope is mesh extraction only. Read, assembly, adapter/output residual and
10ms sampled absolute process RSS are reported separately. These are single warm
process observations with retained reference geometries, not isolated-memory,
cold-cache, statistical, export-pipeline, wetness, peak-result or solver claims.

For another host, pass `--fixture-root <local-directory>` to qualification.py. The declared model filenames, stored versions, expected counts and SHA256 values remain pinned; no project search or source mutation is performed.
