# Native property tables: scoped writing review

Date: 2026-10-11. Disposition: **pass** for the changed prose.

Reviewed surfaces: `docs/api/geometry.md`, the new public
`GeomLandCover.restore_mannings_region_mappings` docstring, the changed
`RasMap.recompute_property_tables` docstring, the standalone worker's comments
and dependency diagnostic, and the recovery helper's diagnostics. Audience:
Python users authoring disposable HEC-RAS geometries. Generated documentation,
unrelated library prose, and model artifacts are excluded.

The review applies the repository Technical Writing Auditor protocol and
writing guides. Evidence inspected comprises the implementation, synthetic
regression tests, native HEC-RAS 6.6 Windows/Wine computation records, and a
native mapping-recovery integrity record. This is project API and observed
runtime behavior, not a statement of a HEC-endorsed hydraulic method. No HEC
affiliation, hydraulic approval, cross-version qualification, or terrain
equivalence is asserted.

Two consequential ambiguities were corrected before submission:

| Rule | Correction | Evidence |
|---|---|---|
| TW-CLAIM-01 / TW-PROC-01 | State Windows Python, Windows/Wine execution, the mesh extra, and the qualified 6.6 scope. | Worker imports/DLL calls; native runs. |
| TW-FACT-01 | Distinguish byte-identical input regions from preserved output attribute values; disclose native string-width normalization and an added empty area-name field. | Native integrity record and postwrite region guard. |

The source is read-only, target mutation and backup/rollback are explicit,
Manning's n is dimensionless, and source CRS/units are preserved without
conversion. The example uses the public APIs and ordinary synthetic paths.
Existing completion/table gates and required later hydraulic QA remain
explicit. Protected API identifiers and units were preserved. No material
writing findings remain for this diff. Other releases and full/cropped terrain
equivalence require separate qualification.

API consistency was reviewed separately by the delegated auditor. Its scoped
verdict is ready with no open fixes: static namespace, decorators, flexible
paths, drive-preserving handling, explicit result provenance, upstream native
execution, and reusable recovery scope. No DataFrame or FIM stage schema is
changed. The existing method export remains the `GeomLandCover` namespace.
