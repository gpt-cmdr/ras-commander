# Native inline precipitation controls

Six externally retained controls pin HEC-RAS 6.6 and 7.0.1 results: Davis US units
with simulation-start and five-minute-offset fixed origins, and Weise SI units.
The manifest contains identities and SHA-256 hashes, not model data.

Set `RAS_PRECIP_NATIVE_FIXTURE_ROOT` to the retained corpus and run
`python -m pytest tests/test_precip_native_contract.py -q`.
Absent fixtures skip explicitly; configured missing or changed files fail.
These tests read retained evidence and never launch HEC-RAS.

## Source, serialized records, and native results

The tests independently parse fixed-width source records and compare their
interval depths and absolute clocks with the source CSV and every physical
native precipitation cell. They also check eager, view and stream readers,
units, cell identity, ghost exclusion and the owning native output timestamps.
Native US units are inches and inches/hour; SI units are millimeters and
millimeters/hour. Initial cumulative depth is zero even when the native initial
rate is positive. Integrating right-end rates starts with the next output row.
All six cases use regular five-minute output intervals. Fixed-origin controls
use a dry prestart interval and do not qualify nonzero prestart accumulation. This is forcing and
reader conformance, not hydraulic acceptance or general temporal interpolation.

## Creating an absent boundary

```python
from ras_commander import RasUnsteady

RasUnsteady.ensure_2d_precipitation_boundary(
    "model.u01", "model.g01", area_2d="2DArea"
)
# Then call set_precipitation_hyetograph with explicit interval depths.
```

The new helper validates the exact geometry-backed 2D area and existing inline
state before replacement. It creates zero precipitation only when absent;
existing valid inline records remain byte-identical. Traditional Storage Areas,
DSS and conflicting area-wide records are refused. Perimeter boundaries remain
separate. Preserve source projects and author a working copy.

Use `RasUnsteady.disable_meteorology` when replacing meteorological precipitation
with inline forcing: changing only the text mode leaves inherited HDF-sidecar
state active. Four such dual-source attempts were rejected by native prechecks
and remain retained as negative evidence. The SI successes preserve the original
Weise sediment configuration and 0.2-second computation step. An altered setup
crashed and is retained separately; it establishes no cause or hydraulic claim.
The new helper was accepted by both SI runtimes; a separate US Ether Hollow
7.0.1 run also completed and matched source depth, outside this six-case matrix.

Storage Area precipitation, additional intervals, irregular clocks, alternate
native versions and physical model acceptance remain unqualified. Issue #398
remains open for its broader notebook and authoring scope.
