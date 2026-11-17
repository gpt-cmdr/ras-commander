---
name: precip_analyze_aorc
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
description: "Retrieve, inspect, and subset historical AORC rainfall or build an AORC storm catalog. Use for AORC source-data preparation; route design rainfall and RAS plan attachment to ras-gridded-precipitation."
---

# AORC source preparation

Keep this compatibility skill focused on AORC source data. Use `ras-gridded-precipitation` for precipitation method selection, Atlas 14/design storms, plan attachment and solver-consumption verification. Use `ras-meteorological-forcings` for format conversion or native DSS/Vortex processing when needed. HMS attachment follows canonical HMS guidance; do not infer equivalent RAS/HMS contracts.

1. Identify the historical event or catalog question, allowed data/output locations, model domain, time basis, quantity/units, requested spatial resolution and coverage. Missing coverage is not zero rainfall. Choose aggregation and storm-separation criteria explicitly; an example threshold is not a universal standard.
2. Discover installed `ras-commander` version and public `PrecipAorc` signatures. Source-acquisition methods include `download`, `check_availability`, `get_info`, and `get_storm_catalog`; inspect availability rather than copying historical `retrieve_aorc_data` or export signatures. Preserve user pins and report unavailable operations.
3. Select the relevant source in [AORC workflow references](references/aorc-workflow.md). Retrieve only the requested domain/time window; preserve original data and record transformation settings and source identity. Check units, interval totals, time alignment, finite/nodata coverage, and spatial footprint after reprojection or aggregation.
4. Return the source manifest, catalog or prepared file, actual checks and limitations. Hand off RAS plan attachment to `ras-gridded-precipitation`; acquiring AORC does not authorize creating plans, modifying inputs or running a model.

Performance depends on domain, interval, source store and cache; do not reuse historical seconds/storage estimates as service guarantees. Read only the applicable notebook sections rather than running a whole example to answer an inventory question.
