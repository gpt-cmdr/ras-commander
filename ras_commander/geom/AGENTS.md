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
- Respect the HEC-RAS cross-section point-count limit (500) when modifying cross sections.
- Respect the Manning's n block limit of 20 per cross section (`GeomCrossSection.MAX_MANNINGS_N_BLOCKS`). HEC-RAS 6.6 rejects 21+ blocks at compute time.
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

## Land Cover Manning's n Override Architecture

HEC-RAS resolves per-cell Manning's n through a layered override hierarchy:

1. **Sidecar HDF Variables** — authoritative base n-values per class
2. **LCMann Table= (plain text .g##)** — optional base overrides
3. **LCMann Region Table=** — optional per-region calibration overrides
4. **Geometry HDF Calibration Table** — final preprocessed values (NaN = use sidecar)

`LCMann Table=0` means no overrides defined (empty table). NaN in the calibration table is normal — HEC-RAS reads the sidecar directly. There is no 16-class limit.

See `.claude/rules/hec-ras/land-cover-mannings-n.md` for full documentation.

## Testing

- Validate geometry changes against real `.g##` files.
- Re-run geometry preprocessing or model execution when a change can affect HEC-RAS interpretation.
