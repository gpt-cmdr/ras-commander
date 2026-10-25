# ras_commander/subdomain

Hydraulic subdomains of a 2D parent model: normal-depth split lines found in the
parent's native face flow along TauDEM stream links, and the nested subdomains
upstream of them.

## Public API

- `RasSubdomain.find_split_lines(plan_hdf_paths, streams, catchments, *, mesh_name=None, growth_plan_hdf_path=None, criteria=None, link_ids=None) -> SplitLineSearch`
- `RasSubdomain.build_subdomains(search, *, split_line_ids=None) -> SubdomainPartition`
- `RasSubdomain.plan_breakouts(partition, plan_number, *, ras_object, perimeter_friction_slope=0.01, subdomain_ids=None) -> SubdomainBreakoutPlan`
- `RasSubdomain.apply_breakouts(breakout_plan, dest_folder, *, overwrite_dest=False, hecras_version=None, time_step="parent_minimum") -> SubdomainBreakoutSet`
- `RasSubdomain.validate_breakouts(breakout_set) -> DataFrame` (`subdomain_breakout_checks`)
- `RasSubdomain.compute_subdomains(breakout_set, *, max_workers=2, num_cores=2) -> DataFrame` (`subdomain_compute_runs`)
- `RasSubdomain.compare_to_parent(breakout_set, parent_plan_hdf_path, *, depth_threshold_ft=0.1) -> DataFrame` (`subdomain_parent_comparison`)
- `SplitLineCriteria`: frozen thresholds (feet, dimensionless); defaults are the
  project-engineer values of 2026-10-14.

Frames: `subdomain_split_lines`, `subdomain_split_candidates`,
`subdomain_partition`, `subdomain_cell_owner` (declared in `schemas.py`).

## Rules

- The parent project is never written. Search and partition are read only;
  authoring writes only inside `apply_breakouts(dest_folder=...)`.
- Children are held at the parent's minimum time step by default
  (`time_step="parent_minimum"`); do not let a child out-step its parent.
- Parent plan HDFs must carry native `Face Flow` output. Never estimate face
  flow from Face Velocity here; the method is defined on native face flow.
- Stream networks come in as TauDEM-shaped frames (`RasTauDem.delineate`).
  Pour points are link outlets (first vertex of each StreamNet LineString).
- Feet only in this release: SI parents raise `NotImplementedError`.
- Labels are information, not gates. `plan_breakouts` turns the ones the cut
  cannot build (`HOLES`, `MULTIPART`, `STRUCTURE_ON_SPLIT_LINE`) into blocking
  checks; `INTERIOR_SUBDOMAIN` stays information (such a band can be cut).
- Time series stream through `HdfResultsMesh.iter_mesh_timeseries`; never load
  a whole parent's face flow into memory.
- `_split_lines.py` is pure arrays (no file access); keep it that way so it
  stays unit-testable on synthetic grids.

Ported from fim-commander `fim_commander.methods.pic.split_lines` and
`fim_commander.step.rog_split_lines` (same owner).
