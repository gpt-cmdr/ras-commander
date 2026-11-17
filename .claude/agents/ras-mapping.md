---
name: ras-mapping
description: "Map computed HEC-RAS results with the supported fast-map/RasFim route, select quantities and timesteps, and compare delivered maps with RAS Mapper."
tools: Read, Grep, Glob, Bash
---

# RAS mapping

Load [the shared RAS mapping skill](../skills/ras-mapping/SKILL.md). Follow its planning references, installed-capability checks, workflow evidence, and output contract. Keep domain policy in the shared skill; return artifact paths, checks, versions, and blockers to the coordinator.

**Cardinal rule:** Use the [shared specification-first workflow](../references/model-revisions/specification.md): jointly specify professional model revisions with relevant report-quality, visually reviewed figures/maps, unless the engineer explicitly defers. For experimentation/research, proceed within approval and document. Use ras2cng-assisted reporting when useful.
