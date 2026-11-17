# Study examples and interpretation limits

Read only the notebook relevant to the investigation; inspect code and retained evidence without rerunning output-heavy cells by default. Paths below are repository sources, not promises that a portable host has the files.

| Source | Reusable research mechanics | Limit to retain |
|---|---|---|
| [117 Monte Carlo](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/117_monte_carlo_uncertainty.ipynb) | Inspect real roughness classes, bounded LHS samples, shipped parameter-application factory, ensemble recipe | Saved evidence covers preparation/sampling, not a completed hydraulic ensemble or uncertainty estimate |
| [220 calibration](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/220_calibration_workflow.ipynb) | Kalamazoo WSE/ADCP observations, delivered-run scoring, grid-search and multi-event design | New execution is guarded; distinguish delivered outputs from newly computed scenarios |
| [230 mesh sensitivity](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/230_mesh_sensitivity_analysis.ipynb) | Controlled mesh-size changes and bed-change/gradation comparisons | Structure-free, breakline-free sediment example; remeshing can alter structure connections and elevations |
| [710 bulk roughness](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/710_mannings_sensitivity_bulk_analysis.ipynb) | Baseline/min/max scenarios, sidecar associations, preprocessed roughness and full-mesh response checks | Bulk bounds do not isolate individual class effects |
| [711 OAT roughness](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/711_mannings_sensitivity_multi_interval.ipynb) | Per-class parameter sweeps, cloned geometry, sensitivity curves | One-at-a-time results do not measure parameter interactions |
| [914 historical event](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/914_historical_event_validation.ipynb) | Trace rainfall from NetCDF to completed plan HDF and inspect event diagnostics | Retained synthetic boundary/control histories make gauge comparison diagnostic, not calibration validation |
| [922 gauge comparison](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/922_model_validation_with_usgs.ipynb) | Matched Kalamazoo delivered results and gauge observations, file identities and comparison metrics | Reads delivered results; does not demonstrate a new HEC-RAS run |

Use domain preparation skills to establish valid boundaries, forcing, land-surface inputs, and map semantics before attributing differences to the experimental variable. A fast backend changes runtime; equivalence still requires quantity-specific evidence.
