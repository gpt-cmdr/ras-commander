# Optional engine test wheels

Install the matching x86-64 wheel into the environment used for mapping:

```powershell
python -m pip install wheels/ras2fim_engine-0.8.0-py3-none-win_amd64.whl
```

```bash
python -m pip install wheels/ras2fim_engine-0.8.0-py3-none-manylinux_2_28_x86_64.whl
```

Run `ras2fim-batch method` to inspect capabilities. Pass the installed engine
path explicitly or activate its environment. Python/GIS dependencies are
installed separately. No Rust compiler or system GDAL is needed by the engine.
These are test builds; no PyPI publication is made.

Engine 0.8.0 supports Step05, horizontal method /2, plain sloping and
cell-corner/face sloping with optional depth weighting and shallow-to-horizontal
selection. Cell-face requests require `native_donation_history`; weighted
requests also require `depth_weighted_faces` and stored corner elevations. It shares
terrain and geometry across bounded in-flight profiles. File and streaming AOI
delivery are covered by installed-wheel smoke tests. Mapping scopes and measured
performance are documented in the
[performance report](../docs/development/fim-mapping-performance.md).

Depth-weighted FIM requires fast-HDF's native `mesh_corner_elevations` entry point,
added after published 0.2.2. Qualification used CI run 40351630621 from commit
`6920fd8efb36831c32161156eee6c7635eee0229`; these development wheels also report
0.2.2. `BUILD.json` records dependency hashes. Check capabilities rather than the
version string. Missing corner inputs can be prepared explicitly through
`RasFim.prepare_corner_elevations()` on Windows/HEC-RAS 7.0.1; subsequent mapping
is runtime independent on Windows/Linux. Preserve the native source terrain grid
and tile layout for cell-face matching.

Verify `SHA256SUMS.txt` before installation. `BUILD.json` records the source
commit, source hashes, wheel/executable hashes and build environments. Linux is
built in the pinned official manylinux 2.28 container. Windows is cross-built
with a static GNU CRT and tested on Windows. CI MSVC builds are separate
artifacts. Hashes establish integrity, not a signature or independent trust.

The `Engine wheels` workflow regenerates artifacts and runs installed smoke.
Replace both retained wheels, source manifest, BUILD.json and SHA256SUMS.txt
together whenever engine source changes.
