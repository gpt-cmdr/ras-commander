# Design note: CRS evidence that differs only by datum realization

Status: proposal, not implemented. Needs a maintainer decision.

## Problem

`HdfUtils.resolve_crs_evidence` resolves a CRS only when every found piece of
evidence is strictly equivalent (`pyproj.CRS.equals(..., ignore_axis_order=True)`).
It reports `conflict` with `crs=None` otherwise. `HdfBase.get_projection`,
`RasPrj.refresh_project_crs` (`project_crs_status == "conflict"`) and the
mapping paths built on them then return geometry without a CRS, and a later
pyproj step fails.

A real 2D model hit this case. Its plan HDF, geometry HDF and `.rasmap`
projection file use EPSG:6479, NAD83(2011) / Louisiana South (ftUS). The
terrain HDF named in the `.rasmap` uses EPSG:3452, NAD83 / Louisiana South (ftUS).
On current `main` (0.118.0, pyproj 3.x), the two definitions compare as follows:

| Property | EPSG:6479 | EPSG:3452 |
|---|---|---|
| Datum | NAD83 (National Spatial Reference System 2011) | North American Datum 1983 |
| Ellipsoid | GRS 1980 | GRS 1980 (equal) |
| Projection method and parameters | Lambert Conic Conformal (2SP), Louisiana South | identical |
| Linear unit | US survey foot | US survey foot |
| `CRS.equals` | false | |

`resolve_crs_evidence([plan 6479, .prj 6479, terrain 3452])` returns
`status="conflict"`, `crs=None` and two candidates. The pinning test
`tests/test_crs_datum_realization_conflict.py` records this.

HEC-RAS uses the terrain coordinates as stored; it does not transform between
the two labels. RAS Mapper's export of that terrain carries the `.rasmap`
projection (EPSG:6479), and the model's hydraulics were computed in those
coordinates.

## Why this is not changed by default

- The strict rule is a documented contract. Since 0.106.1, the resolver has
  deliberately stopped guessing; before that, `RasPrj` returned the first CRS
  found. Relaxing it changes `project_crs` for every caller, which is about a
  dozen call sites.
- NAD83 and NAD83(2011) are different datums. Positions in the two realizations
  can differ by roughly a metre or more, depending on location. A label
  difference often reflects metadata hygiene, with identical coordinates in
  practice. It can also mean that data were collected in one realization and
  never transformed. The library cannot tell these apart from the files.
- Choosing a winner is a precedence policy (plan/geometry/`.prj` over terrain)
  that affects georeferencing of published outputs. It should be explicit.

## Proposed behavior

1. **Diagnose:** add `HdfUtils.compare_crs(a, b)`, which returns `equivalent`,
   `datum_realization` or `different`. `datum_realization` requires all of the
   following to be equal:
   - CRS type (projected or geographic), coordinate operation method and every
     parameter value, to a tight tolerance;
   - axis units and order (ignoring order flips that `equals` already ignores);
   - ellipsoid.

   In addition, both datums must belong to one datum ensemble or family, by an
   explicit allowlist: NAD83, NAD83(HARN), NAD83(CORS96), NAD83(2007),
   NAD83(2011), NAD83(MA11)/(PA11). WGS 84 realizations would be a separate
   decision.
2. **Report, but do not resolve, by default:** `CrsResolution` gains
   `conflict_kind: Optional[str]` (`"datum_realization"` or `"different"`) and
   `warnings: tuple[str, ...]`. `status` stays `conflict` and `crs` stays
   `None`. Log messages name both datums and state that the projection
   parameters are identical, so the user sees the actual reason.
3. **Opt in to a precedence rule:** `resolve_crs_evidence(evidence,
   datum_realization="conflict" | "prefer_primary")`, also exposed through
   `RasPrj` (for example `init_ras_project(..., crs_datum_realization=...)`)
   and the mapping entry points that resolve CRS.
   - With `prefer_primary`, a conflict whose every candidate pair is
     `datum_realization` resolves to the highest-precedence evidence. The
     precedence order is already `hdf_attribute`, then `rasmap_projection`,
     then `terrain_hdf`, which puts the plan, geometry and `.prj` first.
     `status` becomes a new value, `"resolved_with_warning"`, so strict
     `status == "resolved"` checks do not silently accept it.
   - `warnings` records the losing source, its datum and the statement "labels
     differ by datum realization; coordinates are used as stored, with no
     transformation".
   - No reprojection ever happens. The coordinates are assigned the primary
     label, which is what HEC-RAS and RAS Mapper already do.
4. **Receipts:** result objects and receipts that record a CRS (terrain export,
   mapping manifests) copy `warnings`, so a published product shows the
   decision.

## Open questions for the maintainer

- Should `prefer_primary` be allowed only when the primary source is the
  `.rasmap` projection (the CRS RAS Mapper itself uses), or for any
  highest-precedence source?
- Is a new status value acceptable, or should `resolved` plus a non-empty
  `warnings` be used?
- Should the allowlist cover only the NAD83 family at first?

## Workaround until then

Callers that already know the model's CRS can resolve from the
higher-precedence evidence only. For example, read the plan HDF in an isolated
copy outside the project folder, so the `.rasmap` terrain is not consulted.
They can also pass an explicit CRS where the API accepts one, and record the
datum-realization difference in their own receipt.
