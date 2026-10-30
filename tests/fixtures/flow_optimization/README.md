# HEC-RAS 7.0.1 Automated Flow Optimization fixture

Source: public USACE HEC-RAS 7.0 example project
`2D Unsteady Flow Hydraulics/Muncie` (plan `p03`, "Unsteady Run with 2D 50ft
Grid", geometry `g02`, flow `u01`, 02JAN1900 00:00-24:00).

Edits, all made by `make_fixture.py` through ras-commander:

1. `GeomReferenceFeatures.add_reference_points("Muncie.g02", ...)` adds reference
   point `FlowOptPt` at X 407550, Y 1804350 (a wet cell centre of
   `2D Interior Area`); the stale `Muncie.g02.hdf`/`Muncie.c02` are removed so
   HEC-RAS recompiles the geometry.
2. `RasFlowOptimization.copy_plan_with_optimization("03", ...)` clones `p03` to
   `p02` ("Flow Optimization") with mode stage, reference `Ref Point: FlowOptPt`,
   target 946.0 ft, tolerance 0.1, initial ratio 1.0, min 0.5, max 2.0, 5
   iterations, no user-selected hydrographs, and writes the constant observed
   stage target into `u01`.
3. `RasFlowOptimization.compute_plan_and_get_trials("02")` runs HEC-RAS 7.0.1
   (`Ras.exe -c`) through `RasCmdr.compute_plan`.

Command:

```
python make_fixture.py "<HEC-RAS 7.0 examples>/2D Unsteady Flow Hydraulics/Muncie" <work folder>
```

HEC-RAS ran five trials and converged on trial 5 (ratio 1.434). It wrote no
`.computeMsgs.txt`; the trials are in the plan HDF:

- `Results/Unsteady/Flow Optimization Hydro Scaling/Results`: float32 (5, 3),
  `Variable_Unit` = `Hydro Scale, dimensionless, Water Surface, ft, Error, ft`
  (Error = target - computed);
- `Plan Data/Flow Ratio Optimization`: setup attributes (`Target Mode` Stage,
  `Reference Type` Ref Point, `Reference Name` FlowOptPt, `Target Value` 946,
  tolerances, ratios) and an `Attributes` table of scaled hydrographs;
- `Results/Summary/Compute Messages (text)`: the `Optimization trial #` lines
  and `Hydro Flow Optimization Converged Trial #   5    Ratio  1.434`.

Files:

| File | Bytes | SHA-256 |
|---|---|---|
| `Muncie.p02` (plan text written by ras-commander and HEC-RAS) | 14513 | `911ef60092458bfd3374185758c35ad77165f14df0483fd9751cb4a012a79c5e` |
| `Muncie.p02.flowopt.hdf` (excerpt of the 20.6 MB plan HDF: root attributes and the three objects above, copied unchanged by `make_fixture.excerpt`) | 18392 | `35eb602b9c7ea53a50f7c1a9758554fd0865a96e4cd2b170eaa9c3e2530b4427` |
