---
name: dss_read_boundary-data
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
description: "Inspect DSS catalogs and read selected non-gridded boundary time series through RasDss, preserving pathname, units and time metadata. Use for bounded file reads; route boundary assignment and meteorological grid processing to their domain skills."
---

# Read DSS boundary data

Own bounded DSS catalog and non-gridded time-series extraction. Use `ras-boundary-conditions` for boundary selection, assignment or initial-condition changes; use `ras-meteorological-forcings` for gridded DSS conversion/processing. A DSS read does not itself authorize model edits, data repair, or execution.

1. Record the DSS file, requested pathnames/time window, expected record kind, output limits and installed Commander version. Resolve files from project DataFrames or the supplied allowed location; do not search an entire share for a bounded read.
2. Inspect `RasDss.get_capabilities()` and `RasDss.get_backend()` before configuring dependencies. The environment may override `RasDss.backend`; do not assume the selected backend equals the class attribute. Native reads use optional fast-dss without JVM/Monolith; Java reads use pyjnius and HEC Monolith. Shadow behavior depends on operation, so it is a comparison mode rather than a universal third implementation. Read [backend details](references/backend-and-extraction.md) only when choosing or troubleshooting a backend.
3. Inspect the catalog, select the needed ordinary time-series paths, and read them through installed public methods. Use `read_multiple_timeseries` or `extract_boundary_timeseries` only when the requested scope calls for a batch or complete boundary inventory. Keep missing/invalid records visible rather than presenting empty data as a valid boundary.
4. Preserve pathname, record type, units, interval/time basis, source file and DataFrame metadata. Check simulation-window coverage when applicable, missing values, finite values and expected quantity. Flow, stage, and rainfall require different interpretations; do not label every plot as flow.
5. Return a bounded summary or authorized artifact with checks and unresolved issues. Binary DSS reads and raw arrays belong in the Python path, not informational project MCP tools.

DSS pathnames have six parts, written `/A/B/C/D/E/F/`. B usually identifies location, C quantity, D date/block, E interval, and F version/scenario, but inspect actual record metadata rather than deriving all semantics from a pathname. See [workflow and backend references](references/backend-and-extraction.md) for the real-project extraction example and current contracts.
