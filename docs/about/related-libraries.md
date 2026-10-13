# Related hydraulic Python libraries

RAS Commander builds on a community of hydraulic modeling tools. This page
credits conceptual influences and shows where using a companion library can
help. Acknowledging an idea, adapting implementation code, and calling an
upstream dependency are different relationships; name the relationship when
citing related work.

## Choosing a companion

| Task | Useful starting point | Relationship to RAS Commander |
| --- | --- | --- |
| Spatial point/profile queries and hydraulic interpretation | [Gyan Basyal's Rivia](https://github.com/gyanz/rivia) | Conceptual basis for `HdfResultsQuery`; also offers mesh-face flux queries, sediment access, and raster rendering |
| Bounded HDF reads, batches, and reductions | RAS Commander `HdfResultView` and `HdfResultsMesh` | Source fingerprints, explicit memory budgets, xarray/pandas/Arrow conversion; compare Rivia's live lazy datasets |
| Native HEC-DSS records and metadata | [Gyan Basyal's pydsstools](https://github.com/gyanz/pydsstools) | Optional native precipitation-grid dependency; use upstream directly for its broader record and metadata APIs |
| ParaView/VTK analysis and HEC-RAS/SRH-2D comparison | [Xiaofeng Liu's pyHMT2D](https://github.com/psu-efd/pyHMT2D) | Earlier HDF extraction and spatial probing influence; offers a separate multi-solver workflow |

These are task-based starting points, not numerical-equivalence claims. Shared
names such as “velocity,” “maximum,” or “profile” can describe different spatial
locations, output intervals, reconstruction algorithms, or summary envelopes.

## Rivia: conceptual credit and query comparison

**Gyan Basyal (gyanz)** created Rivia; its license credits Gyan and
**WEST Consultants, Inc.** Rivia's query functions are the conceptual basis for
RAS Commander's spatial results query design. We also credit Rivia for the
StoreAllMaps approach used by `RasProcess`. Rivia remains a useful library in
its own right. See its [data access guide](https://rivia.readthedocs.io/en/latest/guide/readdata.html)
and [source](https://github.com/gyanz/rivia).

| Design choice | Rivia | RAS Commander |
| --- | --- | --- |
| Entry point | An HDF plan owns named flow-area and cross-section objects | Static `Hdf*` namespaces; optional source-backed `HdfResultView` |
| File lifetime | HDF reader keeps a handle open; use a context manager | A result view reopens the source and checks its fingerprint; iterators hold a handle during consumption |
| Selective values | Lazy `h5py.Dataset` slices and convenience methods returning arrays/Series | Direct selections, bounded iterators/reductions, and container conversion |
| Arbitrary coordinate samples | Geometry-aware query and reconstruction methods | `HdfResultsQuery.query_point()` / `query_points()` offer nearest-center or IDW sampling |
| Along-line hydraulics | WSE stations include cell crossings; discharge sums oriented fluxes across a connected mesh-face path | Dedicated polyline WSE/velocity/flow profiles and time-series methods; assess each method's semantics before comparison |

Nearest-center or IDW values are not automatically equivalent to RASMapper
interpolation. A WSE maximum envelope is not one instantaneous hydraulic state.
A line-discharge time series and a sampled velocity profile answer different
questions.

### Demonstrate mesh-face discharge and WSE profiles

This example reads an **already computed** unsteady plan with Rivia's HDF API.
It does not open or execute a HEC-RAS project. Install Rivia in a compatible
upstream-supported environment (the project documents Windows and Python 3.10+).
Choose an actual flow-area name and a transect in the model's projected CRS.
The coordinates below are placeholders to replace with your model coordinates.

```python
import numpy as np
from rivia.hdf import UnsteadyPlan

transect = np.array([[500.0, 200.0], [700.0, 300.0]])
with UnsteadyPlan("computed_model.p01.hdf") as plan:
    area = plan.flow_areas["Perimeter 1"]
    discharge = area.flow_across_line(transect)  # datetime-indexed Series
    profile = area.wse_along_line(transect, timestep=0, interval=10.0)
    snapshot = area.get_water_surface(timestep=0)
    cell_history = area.get_water_surface(cell=100)

# These results are materialized before the HDF context closes.
print(discharge.head())
print(profile[["station", "cell", "wse"]].head())
```

`flow_across_line()` uses a connected face path approximating the transect and
sums signed face fluxes over time. Line direction controls sign; consult the
[implementation and sign convention](https://github.com/gyanz/rivia/blob/32d795622928d18ce947e9d3b313657bdf0dbffb/src/rivia/hdf/unsteady_plan.py).
The default is `method="shortest_path"`; `method="walk"` is unimplemented in the
reviewed revision. Inspect the selected face path before treating it as a
measurement section. `wse_along_line()` adds cell-boundary crossings to regular
stations and marks outside/dry samples as missing. Units follow the model.

For a comparison using RAS Commander, query the same computed HDF at a
coordinate with `HdfResultsQuery.query_point(path, x=..., y=...,
variable="wse", time_index=0, method="nearest")`. This returns a value with
mesh/cell identity and distance to the selected center. Match output time,
units, dry-cell handling, and spatial location before comparing values.

### Other useful Rivia capabilities

- **Sediment output:** `plan.sediment.flow_areas()[name]` exposes bed change,
  grain-class transport, and separate bed/transport time axes. For example,
  `fa.get_transport_rate(face=200)` returns a DataFrame; only use it when the
  plan includes that output. See the [sediment examples](https://github.com/gyanz/rivia/blob/32d795622928d18ce947e9d3b313657bdf0dbffb/docs/guide/quickstart.md).
- **Raster rendering:** `area.export_raster("wse", timestep=0, ...)` offers
  horizontal, sloping, and hybrid modes following RASMapper's rendering
  approach. This is useful when rendering semantics matter. Upstream documents
  possible edge-case differences, so establish equivalence on your model
  rather than assuming every raster is identical to RASMapper output.
- **1D output blocks:** `plan.cross_sections("mapping")`, `"output"`,
  `"profile"`, and `"post_process"` distinguish interval/block semantics.
  Rivia's DSS reader is another option for 1D records spanning restart runs;
  see its data access guide.

## pydsstools: use native DSS features directly

Gyan's [pydsstools](https://github.com/gyanz/pydsstools) informed RAS Commander's
DSS architecture and supplies the optional native grid-writing backend.
[Our DSS guide](../user-guide/dss-operations.md) documents
`RasDss.write_precip_grid_arrays()` and its qualification limits.

Use pydsstools directly when the task centers on DSS paired data, irregular
series, quality flags/notes, location or vertical-datum metadata, text/array/
binary records, or file utilities. These are reasons to use the upstream
library, rather than assuming the RAS Commander wrapper exposes every DSS
feature. The [3.1.0 changelog](https://github.com/gyanz/pydsstools/blob/eb619317276c4ee00066c2404307019c9832bc4a/CHANGES.MD)
describes the expanded metadata and record APIs.

```python
from pydsstools.heclib.dss import HecDss

# Replace with an existing file and a pathname from its catalog.
with HecDss.Open("boundary.dss") as dss:
    series = dss.read_ts("/BASIN/GAUGE/FLOW//1HOUR/OBS/")
    print(series.data_units, series.data_type)
    values = series.values.copy()
    times = [time.datetime() for time in series.times]
```

This uses the 3.x snake_case API. See the upstream
[time-series guide](https://pydsstools.readthedocs.io/en/latest/topics/timeseries.html)
and [paired-data guide](https://pydsstools.readthedocs.io/en/latest/topics/paired_data.html).
Check upstream wheel/platform and DSS6/DSS7 restrictions for your environment;
our Monolith backend remains useful for existing Java-based workflows.

## pyHMT2D: recent release and complementary workflows

**Xiaofeng Liu and the pyHMT2D contributors** deserve credit for early HEC-RAS
HDF extraction work and the spatial probing, calibration, and uncertainty
workflows explored during RAS Commander's development. The internal April
2026 analysis explicitly identified point queries, transect profiles, and
flood-extent analysis as useful ideas. Its VTK probing pipeline helped motivate
our direct HDF/scipy spatial query approach.

As checked on **2026-10-13**, [PyPI](https://pypi.org/project/pyHMT2D/#history)
lists **2.0.0**, uploaded **2026-04-04**, as the latest published release.
The source repository has later development through **2026-08-09**. Its current
[README](https://github.com/psu-efd/pyHMT2D/blob/57645ff7af3321a54998f9acb29aa4281380f8e8/README.md)
documents calibration/Monte Carlo tools, MCP/agent workflows, multi-area VTK
export, and HEC-RAS/SRH-2D conversion. These source capabilities should not be
assumed to be identical to the April wheel. Post-release source fixes include timestep-specific VTK cache handling,
wet-cell/flood-extent calculations on NumPy 2.x, Monte Carlo exceedance indexing,
and export-file/unit reporting. See the [source history](https://github.com/psu-efd/pyHMT2D/commits/57645ff7af3321a54998f9acb29aa4281380f8e8/).
The repository's changelog still
only records older 1.x changes, so consult source history and examples too.

Useful workflows to explore:

1. **ParaView review:** export computed 2D results to VTK for interactive
   field inspection and probing. This serves a different audience from web maps.
2. **Solver comparison:** use the HEC-RAS-to-SRH-2D converter to investigate
   models sharing a mesh and material specification; separately qualify
   boundary conditions and solver settings.
3. **Calibration/uncertainty:** inspect the upstream observation sampling,
   optimization, and ensemble workflows alongside RAS Commander's calibration
   and Monte Carlo examples. Different interpolation can change the objective.

The following post-processing example follows the **August source API**,
whose result constructor takes a plan object. Use a matching source checkout;
it is not a qualification of the 2.0.0 wheel.

```python
from pyHMT2D.Hydraulic_Models_Data.RAS_2D.HEC_RAS_Model import HEC_RAS_Project

project = HEC_RAS_Project("computed_model.prj")
plan = project.get_plan("p01")
results = plan.load_results()
results.saveHEC_RAS2D_results_to_VTK(lastTimeStep=True, dir="vtk_review")
```

Provide an existing computed plan and its terrain dependencies. This writes
VTK review files; it does not run HEC-RAS. See the upstream
[comparison example](https://github.com/psu-efd/pyHMT2D/blob/57645ff7af3321a54998f9acb29aa4281380f8e8/examples/compare_SRH_2D_RAS_2D/Muncie2D/process_RAS_2D_Data.py).

## Evidence and acknowledgment practice

This comparison was checked against Rivia `32d7956`, pydsstools `eb61931`, and
pyHMT2D `57645ff` on 2026-10-13. Examples were checked against upstream source;
they have not been executed against a common HEC-RAS model here. They are
workflow demonstrations, not a benchmark or a hydraulic-equivalence report.

Internal research consulted: `feature_dev_notes/HdfResultsQuery/README.md`,
`feature_dev_notes/pyHMT2D_backports/00_MASTER_SYNTHESIS.md`, and
`feature_dev_notes/pyHMT2D_backports/04_unique_features_analysis.md`. These are
research notes, not published API contracts; historical proposals and rankings
were checked against current source before inclusion here.

When adding a feature informed by parallel work, credit the author/project in
the relevant guide, link the exact upstream API/example, describe the influence,
and identify useful upstream capabilities. Preserve applicable license notices
when adapting code; conceptual acknowledgment does not replace that obligation.
See [Acknowledgments](acknowledgments.md) for broader contributor credit.
