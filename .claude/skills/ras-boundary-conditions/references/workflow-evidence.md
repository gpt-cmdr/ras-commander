# Boundary workflow evidence

Read only the sources needed for the task; inspect notebook source cells without rerunning outputs wholesale.

| Source | Use during planning and implementation |
|---|---|
| [Boundary guide](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/user-guide/boundary-conditions.md) | Boundary inventory, exact selection, guarded deletion, and the distinction between read-only `boundaries_df` and public editing APIs. |
| [Coastal guide](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/user-guide/coastal-boundaries.md) | Coastal stage acquisition and datum/time assumptions; do not equate an ocean-model reference level to the project datum. |
| [Notebook 312](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/312_boundary_df_qmult_dss_paths.ipynb) | QMult/QMin and A–F metadata, inline→DSS→inline round trips, stage/flow pairs, and compute comparisons. Its station updater changes the A-part (project/basin), not the B-part location. |
| [Notebook 313](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/313_hms_to_ras_boundary_matching.ipynb) | Candidate HMS series matching and correlation review; confirm physical location and scenario separately. |
| [Notebook 318](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/318_validating_dss_paths.ipynb) | Check that each referenced file/pathname exists and is the intended record; existence is only one readiness check. |
| [Notebook 322](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/322_native_dss_records_and_recovery.ipynb) | Real DSS6/7 series and paired-data read/write, location metadata, backend comparisons and copy-out recovery. Distinguish authentic examples from unavailable record-type fixtures. |
| [Notebook 320](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/320_1d_boundary_condition_visualization.ipynb) | Review boundary hydrographs in spatial/model context rather than relying only on file-level metadata. |
| [Notebook 923](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/923_stofs3d_coastal_boundary.ipynb) | STOFS-3D coastal-boundary acquisition and datum-aware inspection; its illustrative +1 ft offset is not an established datum transformation or proof of solver attachment. |

The current source contract is [DSS AGENTS](https://github.com/gpt-cmdr/ras-commander/blob/main/ras_commander/dss/AGENTS.md). `RasDss.backend` selection and native feature gates depend on installed versions; Java is the documented default in the inspected source. Native refusals must not silently change backends. Use `RasDss.get_capabilities()` and actual readback instead of assuming all DSS record types have equivalent support.
