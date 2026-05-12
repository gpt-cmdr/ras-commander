# USGS Integration Contract

This file is the canonical local instruction file for `ras_commander/usgs/`.

## Scope

- Parent guidance from `ras_commander/AGENTS.md` and the repo root still applies.
- This directory handles USGS NWIS retrieval, gauge matching, boundary generation, validation metrics, and real-time monitoring.

## Workflow Stages

1. Discover gauges spatially.
2. Retrieve data and metadata.
3. Match gauges to model features.
4. Resample or align time series to model intervals.
5. Generate boundary-condition inputs or validation comparisons.
6. Produce metrics, plots, or a reusable gauge catalog.

## Core Modules

- Retrieval and metadata: `core.py`
- Spatial discovery: `spatial.py`
- Matching: `gauge_matching.py`
- Time series handling: `time_series.py`
- Boundary generation: `boundary_generation.py`
- Initial conditions: `initial_conditions.py` (`generate_ic_from_usgs()`: auto-discover gauges, match to XS, retrieve USGS values, assemble IC table)
- Real-time workflows: `real_time.py`
- Catalogs and persistence: `catalog.py`, `file_io.py`
- Validation and plotting: `metrics.py`, `visualization.py`
- Rate limiting and study helpers: `rate_limiter.py`, `study.py`

## Critical Rules

- Respect USGS service limits. Keep rate limiting intact.
- Preserve GeoDataFrame-based spatial workflows where they already exist.
- Keep parameter-code handling explicit and correct for flow vs stage.
- Match gauges to model features using the established spatial and metadata heuristics rather than ad hoc nearest-point shortcuts.
- When generating boundary conditions, preserve HEC-RAS formatting expectations.

## Validation Rules

- Use observed-vs-modeled alignment helpers before calculating metrics.
- Keep model-validation outputs reviewable: tables, plots, and explicit metric summaries.
- Prefer real historical events and actual gauges over synthetic validation examples.

## Reference Notebooks

- `examples/420_usgs_gauge_catalog.ipynb`
- `examples/421_usgs_gauge_data_integration.ipynb`
- `examples/422_usgs_real_time_monitoring.ipynb`
- `examples/423_bc_generation_from_live_gauge.ipynb`
- `examples/424_model_validation_with_usgs.ipynb`
- `examples/911a_usgs_study_package_from_primitives.ipynb`
