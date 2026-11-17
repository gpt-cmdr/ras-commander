# DSS extraction and backend details

Read the section relevant to the chosen operation. These links describe current source; installed capability discovery remains authoritative for the active environment.

## Bounded real-project extraction

[Notebook 310](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/310_dss_boundary_extraction.ipynb) demonstrates Bald Eagle DSS catalog inspection, individual time-series reads, boundary-DataFrame extraction, plots and optional CSV artifacts. Start with a catalog and selected record instead of reading every boundary for one question. Use `RasDss.get_catalog`, `read_timeseries`, `read_multiple_timeseries`, and `extract_boundary_timeseries` as available in the installed release; inspect signatures and metadata instead of copying fixed paths, field names or HEC runtime versions from a historical notebook.

Preserve `df.attrs` together with time-index/value data. Check interval, quantity, units, source file and pathname before plotting or handing the series to boundary assignment. Reading existing DSS does not require a hydraulic solve. Catalogs can include grid, paired-data and other record kinds; a time-series reader is not a universal record decoder.

## Select and troubleshoot the actual backend

The [DSS package contract](https://github.com/gpt-cmdr/ras-commander/blob/main/ras_commander/dss/AGENTS.md), [native backend guide](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/user-guide/dss-native-backend.md), and installed [RasDss signatures](https://github.com/gpt-cmdr/ras-commander/blob/main/ras_commander/dss/RasDss.py) explain dispatch and limits. Source currently defaults `RasDss` to Java; `RAS_COMMANDER_DSS_BACKEND` can override the configured attribute. Native availability does not imply native selection.

- **Native:** selected time-series, catalog, paired-data and metadata operations use optional `ras-commander-fast-dss`. This path does not initialize JVM or download Monolith. A missing wheel/capability is reported; explicitly selected native operations must not silently switch to Java. Grid reads have a separate qualification gate. Native writers require installed write capabilities; neither support is implied by successful catalog extraction.
- **Java:** configure its optional Java/pyjnius prerequisites only when this path is selected. Monolith loading is lazy and may fetch missing libraries on demand; preserve offline constraints and existing environment pins. Consult current package dependency guidance before adding extras or runtimes. Java setup is not a prerequisite for native reads.
- **Shadow:** supported ordinary reads return native values and cross-check Java, but grid reads return Java and compare native. Writes return Java and may repeat natively on a temporary copy under documented limits. Missing native support can resolve shadow to Java with a warning. Confirm effective backend and operation support; do not claim all shadow work ran twice.

When Java fails, check missing pyjnius, Java discovery/`JAVA_HOME`, and classpath configuration. Configure the JVM before importing Java classes; a running JVM cannot be reconfigured in the same process, so a notebook/kernel restart can be necessary after a configuration change. These are Java-specific diagnostics, not a reason to recommend Java installation for every exception. Preserve the actual missing-file, record-type, lock or capability error.

DSS V6/V7 and operation support remain backend/record-specific. Return actual file version and selected backend when relevant; do not extrapolate time-series support to every DSS record family. Source conversion, gridded forcing and precipitation attachment use their dedicated shared skills; this reference does not authorize writes or repair.
