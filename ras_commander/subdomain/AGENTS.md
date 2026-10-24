# ras_commander/subdomain

Hydraulic subdomains of a 2D parent model: normal-depth split lines found in the
parent's native face flow along TauDEM stream links, and the nested subdomains
upstream of them.

## Public API

- `RasSubdomain.find_split_lines(plan_hdf_paths, streams, catchments, *, mesh_name=None, growth_plan_hdf_path=None, criteria=None, link_ids=None) -> SplitLineSearch`
- `RasSubdomain.build_subdomains(search, *, split_line_ids=None) -> SubdomainPartition`
- `SplitLineCriteria`: frozen thresholds (feet, dimensionless); defaults are the
  project-engineer values of 2026-10-14.

Frames: `subdomain_split_lines`, `subdomain_split_candidates`,
`subdomain_partition`, `subdomain_cell_owner` (declared in `schemas.py`).

## Rules

- Read only. Nothing in this package writes to the parent project or its HDFs.
- Parent plan HDFs must carry native `Face Flow` output. Never estimate face
  flow from Face Velocity here; the method is defined on native face flow.
- Stream networks come in as TauDEM-shaped frames (`RasTauDem.delineate`).
  Pour points are link outlets (first vertex of each StreamNet LineString).
- Feet only in this release: SI parents raise `NotImplementedError`.
- Labels are information, not gates. Authoring steps that cannot build a
  labelled subdomain (for example `INTERIOR_SUBDOMAIN`, `HOLES`, `MULTIPART`)
  turn the label into a blocking check there, not here.
- Time series stream through `HdfResultsMesh.iter_mesh_timeseries`; never load
  a whole parent's face flow into memory.
- `_split_lines.py` is pure arrays (no file access); keep it that way so it
  stays unit-testable on synthetic grids.

Ported from fim-commander `fim_commander.methods.pic.split_lines` and
`fim_commander.step.rog_split_lines` (same owner).
