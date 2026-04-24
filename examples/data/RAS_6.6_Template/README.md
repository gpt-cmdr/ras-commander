# RAS 6.6 Template Scaffold

This folder is the starter HEC-RAS 6.6 project scaffold currently bundled with `ras-agent`.

Current contents:

- `TEMPLATE.prj`
- `TEMPLATE.rasmap`

Current status:

- This is a real seed project scaffold, not just a placeholder path.
- It is not yet a clone-ready 1D or 2D template.
- `template_clone` should not rely on this folder until it has at least the geometry, flow, and plan files needed for the intended template type.

Recommended next additions for a 2D seed template:

- `.g##` with a named 2D flow area
- `.p##` and `.u##` seed files
- terrain/regeneration workflow verified in HEC-RAS 6.6
- any `ras-commander` assumptions documented alongside the template

Recommended next additions for a 1D seed template:

- `.g##` with representative river/reach/cross section structure
- `.p##` and `.u##` seed files
- naming conventions that `ras-agent` and `ras-commander` can target consistently

Design rule:

- Treat the plain-text `.g##` file as authoritative for geometry-backed content.
- Let HEC-RAS regenerate derived HDF/preprocessor artifacts after edits.
