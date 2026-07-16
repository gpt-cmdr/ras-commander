---
name: qa-rasmapper-web-parity
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
description: Create deterministic paired RASMapper and RAS Commander MapLibre evidence bundles from one review specification. Use when comparing a HEC-RAS model in RASMapper with its web viewer, validating map/tree/legend fidelity on desktop and mobile, checking nodata/extent/default layers, or establishing visual regression fixtures with fixed numeric COG probes.
---

# RASMapper Web Parity

Use one YAML/JSON review specification for both capture surfaces. Keep map, tree, legend,
semantic assertions, and numeric probes as separate evidence channels.

## Workflow

1. Read `references/review-spec.md` and validate project, manifest, CRS, layer IDs, profiles,
   viewport sizes, crop regions, and numeric probes.
2. Copy the source project to the review output. Never configure the original `.rasmap`.
3. Run `scripts/rasmapper_web_parity.py rasmapper SPEC OUTPUT` on a Windows HEC-RAS host.
4. Run `scripts/rasmapper_web_parity.py web SPEC OUTPUT` where Python Playwright and Chromium
   are installed, or use the in-app browser at the exact specified desktop/mobile viewports.
5. Run `scripts/rasmapper_web_parity.py compare SPEC OUTPUT` after all images exist.
6. Inspect `comparison.json`, `findings.md`, `contact-sheet.png`, and region images.

```powershell
uv run python .claude/skills/qa-rasmapper-web-parity/scripts/rasmapper_web_parity.py `
  rasmapper scripts/example_library/fixtures/muncie-parity.yml working/muncie-parity
```

## Capture Contract

- RASMapper: call `RasMap.create_spatial_review_package()` with fixed outer-window dimensions,
  selected plan/layer, terrain, range/ramp, RAS version, and matching web manifest metadata.
- Web: wait for `window.__rasCommanderViewerInstances`, apply WGS84 bounds and manifest layer
  state through that QA hook, wait for MapLibre and raster styling to become idle, then capture
  page, map, tree, and active legend separately at desktop and mobile sizes.
- Comparison: crop only declared RASMapper regions; normalize dimensions; report global SSIM,
  normalized mean absolute error, and a diff image. Do not use full desktop chrome as a golden.
- Numeric probes: sample authoritative numeric COGs with rasterio and compare to explicit
  expected values/tolerances. Never infer numeric correctness from image colors.

## Classification

- **Confirmed:** deterministic semantic assertion or numeric probe failure.
- **Likely:** repeatable image/extent/legend mismatch that needs targeted numerical review.
- **Uncertain:** missing capture, unstable external basemap, anti-aliasing, or an undeclared crop.

Always distinguish raw HDF computation-element values from RASMapper/RasProcess interpolated
rasters. A screenshot regression is presentation QA, not hydraulic validation.
