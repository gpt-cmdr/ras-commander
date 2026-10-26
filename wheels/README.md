# Optional engine test wheels

Install the matching x86-64 wheel into the environment used for mapping:

```powershell
python -m pip install wheels/ras2fim_engine-0.7.1-py3-none-win_amd64.whl
```

```bash
python -m pip install wheels/ras2fim_engine-0.7.1-py3-none-manylinux_2_28_x86_64.whl
```

Run `ras2fim-batch method` to inspect capabilities. Pass the installed engine
path explicitly or activate its environment. Python/GIS dependencies are
installed separately. No Rust compiler or system GDAL is needed by the engine.
These are test builds; no PyPI publication is made.

Engine 0.7.1 supports Step05, horizontal method /2, plain sloping and unweighted
cell-corner/face sloping with optional shallow-to-horizontal selection. It shares
terrain and geometry across bounded in-flight profiles. File and streaming AOI
delivery are covered by installed-wheel smoke tests. Mapping scopes and measured
performance are documented in the
[performance report](../docs/development/fim-mapping-performance.md).

Verify `SHA256SUMS.txt` before installation. `BUILD.json` records the source
commit, source hashes, wheel/executable hashes and build environments. Linux is
built in the pinned official manylinux 2.28 container. Windows is cross-built
with a static GNU CRT and tested on Windows. CI MSVC builds are separate
artifacts. Hashes establish integrity, not a signature or independent trust.

The `Engine wheels` workflow regenerates artifacts and runs installed smoke.
Replace both retained wheels, source manifest, BUILD.json and SHA256SUMS.txt
together whenever engine source changes.
