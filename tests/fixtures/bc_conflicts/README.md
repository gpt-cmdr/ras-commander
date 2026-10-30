# BC-conflict excerpt

`BaldEagleDamBrk.p18.bclines.hdf` (191,743 bytes, SHA-256 `43f6e954727c51cfaaa5f2af67c0a3522057d970567905ab2864159b16a4bcb5`) holds, unchanged,
only the tables `GeomMesh.detect_bc_conflicts` reads from corpus fixture
`hec701/BaldEagleDamBrk.p18.all2d.hdf` (`gpt-cmdr/ras-hdf-test-corpus`, SHA-256
`b86eff07059ba49f507d36c6f9bed85b8b5e553ad56ae1ffb7ae7547ce53c32a`):

- `Geometry/Boundary Condition Lines` (Attributes, Polyline Info/Parts/Points, External Faces);
- `Geometry/2D Flow Areas/Attributes` and, per area, `Cells Center Coordinate`,
  `Faces Cell Indexes`, `Faces FacePoint Indexes`, `FacePoints Coordinate`,
  `Faces Perimeter Info`, `Faces Perimeter Values`;
- `Event Conditions/Unsteady/Boundary Conditions` (Normal Depth and Flow Hydrograph entries).

`make_excerpt.py <source> <output>` regenerates it with h5py `copy`.

Source: US Army Corps of Engineers, Hydrologic Engineering Center (HEC), HEC-RAS
example projects (BaldEagleCrkMulti2D, plan 18); computed with HEC-RAS 7.0.1 by CLB
Engineering Corporation. Read by `tests/test_geom_mesh_bc_conflicts_real.py`.
