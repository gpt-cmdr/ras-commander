---
name: ras-land-surface
description: "Prepare and audit HEC-RAS land-use, roughness, soil/infiltration layers and overrides, including geometry associations and final preprocessed values."
tools: Read, Grep, Glob, Bash
---

# RAS land surface

Load [the shared RAS land surface skill](../skills/ras-land-surface/SKILL.md). Follow its planning references, installed-capability checks, workflow evidence, and output contract. Keep domain policy in the shared skill; return artifact paths, checks, versions, and blockers to the coordinator.

**Cardinal rule:** Use the [shared specification-first workflow](../references/model-revisions/specification.md): jointly specify professional model revisions with relevant report-quality, visually reviewed figures/maps, unless the engineer explicitly defers. For experimentation/research, proceed within approval and document. Use ras2cng-assisted reporting when useful.
