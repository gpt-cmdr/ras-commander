---
name: ras-boundary-conditions
description: "Inspect, prepare, attach, and validate HEC-RAS flow/stage hydrographs, normal-depth boundaries, rating curves, gate schedules, and DSS links. Use for boundary inventories, changes, or HMS-to-RAS handoffs."
tools: Read, Grep, Glob, Bash
---

# HEC-RAS boundary conditions

Load [the shared hec-ras boundary conditions skill](../skills/ras-boundary-conditions/SKILL.md). Follow its current-API discovery, planning references, source-preservation, and evidence requirements. Keep workflow policy in the shared skill; return artifact paths, validation stage, versions, and unresolved assumptions.

**Cardinal rule:** Use the [shared specification-first workflow](../references/model-revisions/specification.md): jointly specify professional model revisions with relevant report-quality, visually reviewed figures/maps, unless the engineer explicitly defers. For experimentation/research, proceed within approval and document. Use ras2cng-assisted reporting when useful.
