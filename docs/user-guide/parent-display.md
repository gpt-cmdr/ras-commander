# Parent display: source geometry probe

`ras_commander.parent_display` provides read-only probes for stored geometry and forcing metadata.

`HdfStruc.get_structures` and `HdfMesh.get_mesh_areas` return an empty GeoDataFrame when a
feature is absent, when its tables are incomplete, and (for mesh areas) when reading failed.
A publisher cannot tell "this model has no structures" from "structures were not extracted".
`probe_geometry_features` inspects group and dataset presence and row counts only, never a
geometry array, and returns a `FeatureProbe` per feature.

```python
from ras_commander.parent_display import probe_geometry_features

probes = probe_geometry_features("UPGU1.g01.hdf")           # opened read-only
probes["structures"].reason_code, probes["structures"].confirmed_zero
```

| `reason_code` | Meaning | `confirmed_zero` |
|---|---|---|
| `FEATURE_PRESENT` | Feature-count table has rows; required supporting datasets have rows | no |
| `NOT_IN_SOURCE` | The HDF group is absent | yes |
| `EMPTY_IN_SOURCE` | Required datasets exist; feature-count table has zero rows | yes |
| `SOURCE_TABLE_INCOMPLETE` | Required datasets missing (`missing_datasets`), malformed, or empty despite declared features (`detail`) | no |
| `READ_ERROR` | One feature could not be read; the others are still reported | no |

Features: `mesh_areas`, `breaklines`, `refinement_regions`, `structures`. A file that cannot be
opened raises `OSError`. Parsing remains in `HdfMesh`, `HdfBndry` and `HdfStruc`.

Statuses describe the known HDF layout. `confirmed_zero` does not establish that
an unsupported layout or another source contains no features. `FEATURE_PRESENT`
is a metadata check: it does not validate coordinate values, index relationships,
or whether a geometry reader can construct usable features.

Run the probe on the source geometry HDF outside any container and pass
`dataclasses.asdict(probe)` to fim-commander's `build_catalog(source_probes=...)`.

Open gap, connections: `GeomLateral.get_connections` returns connection metadata (name, type,
from/to) from text geometry with no geometry column, and `HdfStruc.list_sa2d_connections`
reads plan results and names only connections that carry results. `HdfStruc.get_structures`
reads `Geometry/Structures` centerlines; whether that table also carries SA/2D connections for
a given model, and how to tell them apart, is not verified here. There is no dedicated,
typed connection-geometry reader, so `parent_connections` stays `LAYER_NOT_IN_EXTRACT`.

## Applied boundary-condition forcing probe

`probe_applied_forcing(plan_hdf)` describes `Results/Unsteady/Output/Output Blocks/Base Output/Unsteady
Time Series/Boundary Conditions` without reading a value array: series names, their `Columns`
attribute, step counts, an optional `Units` attribute, and whether per-face flow and stage tables
exist. `HdfResultsMesh.get_boundary_conditions_timeseries` returns an empty Dataset when the group is
missing, which cannot be told from "no boundary conditions". The probe returns
`AppliedForcingProbe(reason_code, boundaries, time_steps, time_units, detail)` with the same closed
codes as `FeatureProbe`; absent attributes stay `None`. This is what the solver *applied*; it is
neither the configured input (the unsteady flow file) nor a face flux.

A present forcing group requires a one-dimensional Time dataset and two-dimensional
boundary datasets with matching time-row counts. If `Columns` labels are supplied,
their count must match the series width. Violations return `SOURCE_TABLE_INCOMPLETE`
with a diagnostic in `detail`. These checks read shapes and attributes only; they do
not validate timestamp values, forcing values, units, or hydraulic suitability.
`NOT_IN_SOURCE` and `EMPTY_IN_SOURCE` describe this output group only; they do not
prove that the model was run without forcing.

## Configured boundary descriptors

`RasUnsteady.extract_boundary_and_tables` returns a DataFrame (`DSS File`, `Tables`, and the nine split
location columns). `normalize_configured_boundaries(frame)` reduces it, without re-parsing the text, to a list of
descriptors with exactly these keys: `location_fields` (non-empty location columns, verbatim, named by the parser's
labels, with no claim about what a column means), `table_types` (known table headers), `bc_type` (the table type
when exactly one, else `None`), `has_table` and `dss_linked` (a DSS file is named; its path is never copied).
Units, interval and BC-line geometry are not stated by the parser and are not invented. `None` or an empty
frame gives `[]`; a non-empty frame that is not parser output raises `ValueError`.
