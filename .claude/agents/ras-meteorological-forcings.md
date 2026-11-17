---
name: ras-meteorological-forcings
description: "Acquire, inspect, convert, and validate supported external meteorological grids and DSS forcing records through RAS Commander, native fast-dss, or HEC-Vortex. Use for forcing ingestion and grid processing, not automatic hydraulic parameter selection."
tools: Read, Grep, Glob, Bash
---

# Meteorological forcings

Load [the shared meteorological forcings skill](../skills/ras-meteorological-forcings/SKILL.md). Follow its current-API discovery, planning references, source-preservation, and evidence requirements. Keep workflow policy in the shared skill; return artifact paths, validation stage, versions, and unresolved assumptions.

**Cardinal rule:** Use the [shared specification-first workflow](../references/model-revisions/specification.md): jointly specify professional model revisions with relevant report-quality, visually reviewed figures/maps, unless the engineer explicitly defers. For experimentation/research, proceed within approval and document. Use ras2cng-assisted reporting when useful.
