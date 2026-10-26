# Optional engine test wheels

Install the wheel matching your operating system and CPU into the environment
used for mapping. These are x86-64 test builds; no PyPI release is made.

Linux (glibc 2.28 or newer):

```bash
python -m pip install wheels/ras2fim_engine-0.4.0-py3-none-manylinux_2_28_x86_64.whl
```

Windows x86-64:

```powershell
python -m pip install wheels/ras2fim_engine-0.4.0-py3-none-win_amd64.whl
```

Then run `ras2fim-batch method`. Installation places the engine in the virtual
environment's scripts directory. Activate that environment or pass the engine's
full path to the Python API. The application and GIS dependencies are installed
separately. The native engine needs neither a Rust compiler nor system GDAL.

Verify each wheel against `SHA256SUMS.txt` before installation (`sha256sum -c`
on Linux or `Get-FileHash -Algorithm SHA256` on Windows). `BUILD.json` records
the source revision, artifact/binary hashes and local build environments.
The retained 0.4.0 Linux wheel was built in the pinned official manylinux 2.28
container. The Windows wheel was cross-built for Windows GNU with a static
CRT and tested on Windows; it imports only Windows system DLLs. CI also builds
MSVC wheels as separate workflow artifacts. Both retained builds execute the installed
binary on synthetic terrain with shared profiles, bbox and polygon masks,
plus horizontal and plain-sloping file and streaming-pipe output. Version 0.4
adds `rasmapper-plain-sloping/1`, direct typed geometry arrays, shared terrain
and ownership across profiles, and bounded parallel reconstruction/painting.
It applies no additional depth cutoff. Version 0.3 introduced ownership
and polygon masks through native terrio, reusing ownership and terrain across
profiles while preserving Step05 arithmetic. Installed-wheel tests compare
the horizontal products with the explicit NumPy reference, including shared
boundaries, holes, multipart AOIs and bounded worker counts.
Both 0.4 installed wheels pass eight real-Davis sloping API checks, including
raw-bit Max/timestep comparisons with one/four workers and failure cleanup,
including metadata-only template delivery, and 69 engine-backed horizontal tests per platform. The Linux wheel also
passes the packaging smoke in a glibc 2.28 container. The
[sloping corpus/performance evidence](../docs/development/fim-mapping-performance.md#plain-sloping-development-qualification)
states full versus bounded comparison scopes separately. Step05 real-model
numerical qualification was performed on Linux; horizontal corpus checks
passed on both Linux and Windows. Wheel hashes establish
artifact integrity; they are not a signature or an independent trust anchor.

To regenerate, run the repository's `Engine wheels` workflow. It uploads wheels
and hashes as platform artifacts retained for 90 days. Only retain wheels whose
build and installed smoke test succeed. After changing engine source, replace
these test wheels and update `BUILD.json` and `SHA256SUMS.txt` together.
