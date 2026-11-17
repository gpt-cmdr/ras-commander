---
name: ras-gridded-precipitation
description: "Prepare and attach observed, forecast, or design rain-on-grid inputs to HEC-RAS plans and verify solver-consumed rainfall. Use for Atlas 14, AORC, MRMS, HRRR, WPC, NetCDF, GeoTIFF/GRIB, and gridded DSS precipitation workflows."
tools: Read, Grep, Glob, Bash
---

# Gridded precipitation

Load [the shared gridded precipitation skill](../skills/ras-gridded-precipitation/SKILL.md). Follow its current-API discovery, planning references, source-preservation, and evidence requirements. Keep workflow policy in the shared skill; return artifact paths, validation stage, versions, and unresolved assumptions.

**Cardinal rule:** Use the [shared specification-first workflow](../references/model-revisions/specification.md): jointly specify professional model revisions with relevant report-quality, visually reviewed figures/maps, unless the engineer explicitly defers. For experimentation/research, proceed within approval and document. Use ras2cng-assisted reporting when useful.
