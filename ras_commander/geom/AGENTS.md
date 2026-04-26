# Geometry Subpackage Contract

This file is the canonical local instruction file for `ras_commander/geom/`.

## Scope

- Parent guidance from `ras_commander/AGENTS.md` and the repo root still applies.
- This directory handles plain-text HEC-RAS geometry parsing and modification.

## Core Modules

- Parsing utilities: `GeomParser`
- Cross sections: `GeomCrossSection`
- Storage and 2D areas: `GeomStorage`, `GeomLandCover`
- Structures: `GeomLateral`, `GeomInlineWeir`, `GeomBridge`, `GeomCulvert`
- HTAB logic: `GeomHtab`, `GeomHtabUtils`
- Metadata and reference features: `GeomMetadata`, `GeomReferenceFeatures`
- Preprocessor helpers: `GeomPreprocessor`

## Critical Geometry Rules

- HEC-RAS geometry files use fixed-width numeric formatting.
- Standard numeric formatting is 8-character fields with 10 values per line.
- Count declarations can describe pairs rather than raw scalar count. Interpret them carefully before reading or writing.
- Preserve exact river, reach, and river-station identifiers. They are case-sensitive and must match the source file.
- Respect the HEC-RAS cross-section point-count limit when modifying cross sections.
- Create or preserve `.bak` backups before destructive writes.

## Modification Rules

- Use existing parser and formatter helpers rather than hand-rolling string slicing.
- Keep bank stations explicit when writing cross-section geometry.
- When changing HTAB or geometry settings, preserve nearby formatting conventions and required terminators.
- Prefer geometry-specific helper classes over direct text surgery when an existing helper already handles the section.

## Common Use Cases

- Cross-section extraction and modification: `GeomCrossSection`
- 2D flow area settings and storage curves: `GeomStorage`
- SA/2D connections and laterals: `GeomLateral`
- Structure geometry and metadata: `GeomBridge`, `GeomInlineWeir`, `GeomCulvert`
- HTAB optimization from results: `GeomHtab`

## Testing

- Validate geometry changes against real `.g##` files.
- Re-run geometry preprocessing or model execution when a change can affect HEC-RAS interpretation.
