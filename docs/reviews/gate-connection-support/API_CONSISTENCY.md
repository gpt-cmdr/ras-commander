# API consistency review: gate connection support and area mapping

Date: 2026-10-10. Agent: Codex API consistency auditor (`/root/api_consistency_auditor`). Review of the public upstream working diff from ras-commander main commit `8359f17fe9dc8aae78cc870c8b4ee5c641f99e58`. Source code was not edited by this reviewer.

Scope: `GeomLateral.get_connection_gate_lines`, `classify_connections`, `remap_connection_areas`, RasBreakout2D gate-group inventory equality, public DataFrame schemas, API documentation, and focused regression tests. Criteria: canonical root/library/geometry/docs AGENTS guidance and the repository auditor's static namespace, logging, naming and path conventions.

| ID | Severity | Where | Finding | Disposition |
|---|---|---|---|---|
| UP-01 | note | New GeomLateral methods | Public methods use the existing static namespace and both `@staticmethod` and `@log_call`. Path parameters accept `str` or `Path`; implementations use pathlib or existing public readers. Return types and read-only behavior are explicit. | Conforms to the five critical API convention rules. |
| UP-02 | note | Gate GIS reader | The return frame contains explicit one-based consecutive opening indexes, names and complete valid lines in model coordinates without an inferred CRS. Missing GIS inventory yields an empty frame; malformed counts, duplicate indexes, nonfinite/invalid coordinates and undeclared extra coordinate payload fail closed. The reader now consumes the full coordinate payload up to the next labeled record before checking its exact count. | Initial short-read concern resolved; final extra-coordinate regression passes. No station-derived footprint is invented. |
| UP-03 | note | Connection classification | Gate GIS line support is buffered by half the delivered finite positive width and combined with conservative crest/culvert supports. Unknown additional support and unsupported physical parameters continue to block. `gate_group_count` reports verified gate GIS groups irrespective of the overall action; it is not independent approval of the connection. | Initial count-description inconsistency resolved in schemas. Stable existing action/reason vocabulary remains intact. |
| UP-04 | note | RasBreakout2D / schemas | Existing native gate-group count must equal the summed verified group inventory, and every connection still needs a unique verified keep/drop decision. `gate_group_count` is declared on both classification and breakout feature actions; nonconnection feature rows are filled with integer zero. Global schema contract version is incremented to 1.23. | Initial missing public feature-action column declaration resolved. Count mismatch blocks; no blanket gate waiver. |
| UP-05 | note | `remap_connection_areas` | An explicit old-to-new area-name map produces source-ordered `Name`/authoritative `RawBlock` pairs without changing the source. Only recognized upstream/downstream endpoint names change, preserving all other native records. Invalid names and ambiguous endpoint records raise. Callers write only to clones and must separately verify preprocessing, native attachments and hydraulic equivalence. | Small public primitive; no duplicate parser or hidden project state. |
| UP-06 | note | Documentation / schemas | Geometry API docs list and expose new methods, units/CRS, mutation boundaries, supported GIS evidence and mapping limitations. New DataFrame surfaces have canonical schemas; existing classification gains the additive gate-group field. | Public interfaces are discoverable and consistent with implementation. |
| UP-07 | note | Native qualification | Focused tests exercise real parser/writer APIs on synthetic geometry. The retained Austin real-source test is skipped unless its explicit project/boundary environment inputs are available. No HEC-RAS preprocessing or compute was run in this audit. | Native compile, production-model format coverage, and hydraulic equivalence remain separate evidence requirements. |

## Verification

Executed from the fresh upstream clone with its root explicitly assigned to `PYTHONPATH`:

- `C:\Users\bill\AppData\Local\clb-gen3\venv-py311\Scripts\python.exe -m pytest -q tests/test_gate_connection_support.py tests/test_breakout_outside_connections.py -p no:cacheprovider`: **37 passed, 1 skipped** after the final parser/schema/test updates. The skipped test requires explicitly configured Austin source and boundary paths.
- AST inspection confirms `remap_connection_areas`, `classify_connections`, and `get_connection_gate_lines` each carry `@staticmethod`, `@log_call`, and annotated returns.
- Inspected public schema declarations, feature-action count normalization, full-payload coordinate validation, unchanged source bytes and RawBlock round-trip tests, endpoint ambiguity rejection, gate-inventory mismatch tests, and docs diff.
- `git diff --check`: passed during review.

This report does not claim the upstream full suite, all supported Python versions, docs strict build, native 6.6 compile, or hydraulic acceptance. Those checks belong to the implementing task's retained evidence.

## Simplest design that meets the need

Keep gate GIS extraction and endpoint-name remapping as small read-only GeomLateral primitives. Reuse the existing complete-support classifier and RasBreakout2D inventory gate rather than adding a parallel gate execution path. Return authoritative native blocks for clone-only writing, then require actual native attachment evidence from the resulting compiled geometry. Consumers must explicitly adopt a runtime containing this upstream change.

## Summary

Outstanding blockers 0, fixes 0, simplifications 0. Verdict: **ready** for API consistency. Runtime/native qualification and engineering acceptance are not established by this review.
