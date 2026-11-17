# Method and compatibility references

## Canonical engine and RAS evidence

- [USACE go-consequences](https://github.com/USACE/go-consequences) is the public engine source. Inspect the selected version's hazard-provider, receptor-provider, vulnerability and writer contracts. A public upstream revision and an authorized downstream image can have different formats, samplers and writer behavior.
- [Stored-map API guide](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/api/rasmapper/stored-maps.md) and [native mapping engine guide](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/native-mapping-engine.md) describe supported mapping routes. Use current `RasMap`/HDF public documentation and installed signatures to establish the actual hazard export route.
- [RAS notebook 727](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/727_atlas14_gridded_rain_on_grid_hecras.ipynb) extracts complete-series maximum cell hydraulic depth and maximum WSE as distinct quantities and compares controlled hydraulic scenarios. It is hydraulic evidence, not an economic-damage demonstration.
- [RAS notebook 924](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/924_mrms_netcdf_rain_on_grid.ipynb) closes source-to-solver rainfall and hydraulic-response checks. It does not establish exposure, occupancy functions, valuations or flood-frequency assignments.

No consequences notebook in the inspected RAS examples qualified an end-to-end economic analysis. Preserve that evidence gap; use the selected consequences engine's examples and a real-project comparison before claiming a qualified integration.

If an authorized private downstream is present, read its own `AGENTS.md`, RAS integration skill and relevant provider/production qualification documentation locally. Do not copy its operational paths, private datasets, image identifiers or implementation into this public skill. Specialized sampler availability and behavior must be observed on that build. In particular, accepted compression, CRS handling, depth units and multiparameter support can differ by provider; do not silently fall back after a refusal. Reusable sampled-hazard caches must match event, condition, raster bytes, units, receptor IDs/locations and their required ordering.

## HEC planning links

These are passive planning references, checked November 17, 2026. They explain method concepts; they do not claim go-consequences implements HEC-FIA/FDA identically or that a method is approved for a particular project.

| Reference | Planning decision |
|---|---|
| [HEC-FIA 3.2 structure occupancy types](https://www.hec.usace.army.mil/confluence/fiadocs/fiaum/v3.2/inventory-data/structure-occupancy-types) | Select and review occupancy classes, structure/content damage functions, value ratios and uncertainty. Confirm the reference version matches the method being applied. |
| [HEC-FDA methodology](https://www.hec.usace.army.mil/software/hec-fda/methodology.aspx) | Distinguish event damage from frequency-based risk analysis; review hydraulic/economic inputs and uncertainty before annualizing results. |
| [HEC planning cross-references](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/development/hec-planning-references.md) | Select the relevant hydraulic result/mapping and version references before preparing the hazard. |

Neither an economic curve nor a model-produced flood map removes uncertainty in the other. Report the analysis scope and assumptions alongside totals; preserve project-specific review requirements without silently importing historical fallback parameters.
