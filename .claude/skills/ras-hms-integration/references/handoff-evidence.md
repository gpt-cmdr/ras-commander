# HMS-to-RAS handoff evidence

| Source | Use and scope |
|---|---|
| [HMS contract](https://github.com/gpt-cmdr/hms-commander/blob/main/AGENTS.md) | Project identity, immutable-source practice, explicit project objects and independent HMS/RAS APIs. HMS requires `.hms` discovery, not a RAS `.prj` parser. |
| [HMS DSS guide](https://github.com/gpt-cmdr/hms-commander/blob/main/docs/user_guide/dss_operations.md) | Catalog, series and result workflows. HMS DSS operations use RAS Commander DSS infrastructure; inspect installed signatures and actual return schemas. |
| [HMS run configuration](https://github.com/gpt-cmdr/hms-commander/blob/main/docs/user_guide/run_configuration.md) and [execution](https://github.com/gpt-cmdr/hms-commander/blob/main/docs/user_guide/execution.md) | Resolve the selected run's component references and execution prerequisites before changing dates or running HMS. |
| [HMS results analysis](https://github.com/gpt-cmdr/hms-commander/blob/main/docs/user_guide/results_analysis.md) | Discover element/run results in the current public package. Do not infer an outlet pathname from an illustrative string. |
| [HMS notebook 06](https://github.com/gpt-cmdr/hms-commander/blob/main/examples/06_results_dss.ipynb) | Supporting results/DSS workflow; inspect current cells and installed APIs before adapting it. |
| [RAS notebook 313](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/313_hms_to_ras_boundary_matching.ipynb) | Real Bald Eagle DSS-linked boundary inventory, FLOW catalog extraction, exact link checks, `RasHydroCompare` comparisons, inline candidate matching and cross-plan comparison. Existing-link validation differs from discovering an unknown physical pairing. |
| [RAS notebook 312](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/312_boundary_df_qmult_dss_paths.ipynb) | Boundary scaling, pathname parts, inline/DSS state transitions and model checks; an A-part grouping update does not rename the B-part outlet. |
| [RAS notebook 918](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/918_hms_ras_coupled_forecast.ipynb) | Conceptual coupling sequence and time alignment. Its HMS configuration/compute/extraction cells are commented examples and print statements; it is not executed end-to-end coupled qualification. Validate current signatures independently. |

Qualification of a new coupling needs a real HMS run and identified RAS target, a reviewed spatial assignment, exact DSS readback, units/time/volume checks and authorized RAS consumption evidence. Notebook presence alone does not supply those checks for a user's watershed.
