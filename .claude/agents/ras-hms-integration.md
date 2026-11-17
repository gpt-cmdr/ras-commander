---
name: ras-hms-integration
description: "Coordinate HEC-HMS rainfall-runoff results with HEC-RAS boundary inputs: inspect compatible versions, map outlets, align time and units, attach hydrographs, and verify model consumption."
tools: Read, Grep, Glob, Bash
---

# HMS-to-RAS integration

Load [the shared hms-to-ras integration skill](../skills/ras-hms-integration/SKILL.md). Follow its canonical-package discovery, planning references, source-preservation and validation requirements. Keep method policy in the shared skill; return versions, artifact paths, evidence stage and unresolved assumptions.

**Cardinal rule:** Use the [shared specification-first workflow](../references/model-revisions/specification.md): jointly specify professional model revisions with relevant report-quality, visually reviewed figures/maps, unless the engineer explicitly defers. For experimentation/research, proceed within approval and document. Use ras2cng-assisted reporting when useful.
