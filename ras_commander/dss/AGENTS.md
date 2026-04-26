# DSS Subpackage Contract

This file is the canonical local instruction file for `ras_commander/dss/`.

## Scope

- Parent guidance from `ras_commander/AGENTS.md` and the repo root still applies.
- This directory handles HEC-DSS access through the Java-based monolith bridge.

## Architecture

- Public API: `RasDss`
- Private support: `_hec_monolith.py`
- Loading is intentionally staged:
  1. parent package lazy-import
  2. lightweight subpackage import
  3. JVM and pyjnius initialization on first real DSS call

## Critical Rules

- Configure the JVM before importing Java classes with `jnius`.
- Resolve DSS paths to absolute paths before opening files.
- Close DSS handles in `finally` blocks.
- Remember that the JVM can only be started once per process.
- Keep Part D blank when writing standard DSS pathnames unless the method explicitly requires otherwise.

## Dependency Rules

- `pyjnius` and Java are optional runtime prerequisites and should fail with clear installation guidance when missing.
- Keep the monolith download flow lazy and on-demand.

## Common API Surface

- Catalog reads and metadata: `get_catalog()`, `get_info()`
- Time series reads and writes: `read_timeseries()`, `write_timeseries()`
- Path validation: `check_pathname()`, `is_valid_pathname()`, `is_pathname_available()`

## Testing

- Validate against real DSS files and pathnames whenever possible.
- Be careful with notebook or REPL sessions that already started a JVM.
