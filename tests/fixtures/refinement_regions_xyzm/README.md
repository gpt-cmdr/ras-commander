# Fixture: four-ordinate refinement-region vertices

`12090106_MidCo_0601_A1.refinement_regions.hdf` reproduces a HEC-RAS geometry HDF whose
refinement-region vertices carry four ordinates, which every Shapely constructor rejects.

## Provenance

| | |
|---|---|
| Study | FEMA eBFE HUC8 **12090106** (Lower Colorado-Cummins, TX) |
| Delivery | `12090106_Models.zip`, 152,379,996,790 bytes, on the corpus NAS at `/mnt/pool_12tb/FEMA/eBFE/raw/12090106/` |
| Model | `12090106/RAS Model/12090106_Models_20241130/Hydraulic Models/RAS_Submittal/Input (Includes both Inputs and Outputs)/0601_A1/MidCo_0601_A1.prj` |
| Geometry HDF | `MidCo_0601_A1.g01.hdf` |
| Dataset | `/Geometry/2D Flow Area Refinement Regions` |
| Source CRS | EPSG:6578 (NAD83(2011) / Texas Central, ftUS) |

In the source HDF that group holds **41** regions and its `Polygon Points` is **`(21592, 4)`**.
The third and fourth columns are **entirely NaN**: they are padding, not Z and M. That
measurement is what decides the reduction rule — see `HdfBase.plan_vertex_ordinates`.

## What was reduced, and what was kept

Two of the 41 regions were kept, with their real names (`Region 41`, `Region 58`), their real
coordinates, and the group's real dtypes. Nothing was synthesised:

- the `Attributes` compound dtype keeps all nine real fields
  (`Name`, `Spacing dx`, `Spacing dy`, `Shift dx`, `Shift dy`, `Perimeter Spacing`,
  `Near Spacing Repeats`, `Far Spacing`, `Protection Radius`);
- `Polygon Points` keeps its real `float64` `(n, 4)` shape and its real NaN third and fourth
  columns;
- `Polygon Info` and `Polygon Parts` keep their real `int32` layout.

Two regions rather than one, because one record would exercise a single constructor call and
not the per-record loop or the GeoDataFrame assembly that follows it.

## It reproduces the failure

Against the code before the fix, `HdfBndry.get_refinement_regions()` on this file logs

```
Error reading refinement regions: The ordinate (last) dimension should be 2 or 3, got 4
```

and returns an **empty** GeoDataFrame — the blanket `except Exception` turns a read error into
an indistinguishable "this model has no refinement regions". `tests/test_hdf_xyzm_vertices.py`
asserts both the raise from the raw array and the recovered layer.
