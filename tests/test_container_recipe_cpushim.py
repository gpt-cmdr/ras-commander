"""Offline checks of the Wine CPU-numbering shim recipe.

Ported from ras2fim-2d ``tests/test_cpu_shim.py``. The compile-and-preload test
needs a C compiler and two non-zero CPUs in the affinity mask; it is skipped
otherwise. No Docker, Apptainer, or Wine is required.
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RECIPE = REPO_ROOT / "containers" / "hecras-wine-precompute"
SHIM_SOURCE = RECIPE / "cpushim.c"
SHIM_PATH = "/opt/hecras-prepare/cpushim.so"


def _compiler():
    return shutil.which("cc") or shutil.which("gcc")


@pytest.mark.skipif(sys.platform != "linux", reason="Linux preload shim")
def test_cpu_shim_maps_restricted_affinity_with_concurrent_first_use(tmp_path):
    compiler = _compiler()
    if compiler is None:
        pytest.skip("C compiler required")
    cpus = sorted(os.sched_getaffinity(0))
    selected = [cpu for cpu in cpus if cpu > 0][:2]
    if len(selected) < 2:
        pytest.skip("Two nonzero host CPUs required")
    library = tmp_path / "cpushim.so"
    subprocess.run([compiler, "-shared", "-fPIC", "-O2", "-Wall", "-Wextra",
                    "-Werror", "-o", str(library), str(SHIM_SOURCE), "-ldl", "-pthread"],
                   check=True)
    script = '''
import concurrent.futures, ctypes, os, threading
cpus = sorted(os.sched_getaffinity(0))
getcpu = ctypes.CDLL(None).sched_getcpu
barrier = threading.Barrier(32)
def check(i):
    barrier.wait()
    # Initialize while every thread still has the process CPU set.
    assert 0 <= getcpu() < len(cpus)
    index = i % len(cpus)
    os.sched_setaffinity(0, {cpus[index]})
    for _ in range(1000):
        assert getcpu() == index
with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
    list(pool.map(check, range(32)))
'''
    environment = dict(os.environ, LD_PRELOAD=str(library))
    # Repeat fresh process initialization; setting affinity on Python threads
    # in the child avoids unsafe preexec_fn use in a threaded test runner.
    script = "import os\nos.sched_setaffinity(0, " + repr(set(selected)) + ")\n" + script
    for _ in range(5):
        subprocess.run([sys.executable, "-c", script], env=environment,
                       check=True, timeout=30)


def test_cpu_shim_source_overrides_sched_getcpu_with_thread_safe_map():
    source = SHIM_SOURCE.read_text(encoding="utf-8")
    assert re.search(r"^int sched_getcpu\(void\)$", source, re.MULTILINE)
    assert "pthread_once(&map_once, build_map)" in source
    assert 'dlsym(RTLD_NEXT, "sched_getcpu")' in source
    assert "sched_getaffinity(0" in source


def test_dockerfile_builds_shim_outside_the_image_and_names_it():
    dockerfile = (RECIPE / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM ${PYTHON_IMAGE} AS cpushim" in dockerfile
    assert "COPY containers/hecras-wine-precompute/cpushim.c /src/cpushim.c" in dockerfile
    assert "grep -qw sched_getcpu" in dockerfile
    assert "FROM scratch AS cpushim-artifact" in dockerfile
    assert "COPY --from=cpushim /out/cpushim.so ./cpushim.so" in dockerfile
    assert "WORKDIR /opt/hecras-prepare" in dockerfile
    assert "RAS_COMMANDER_WINE_CPU_SHIM=" + SHIM_PATH in dockerfile
    # The compiler stage is pinned and never the base of the runtime image.
    assert '"gcc=${GCC_VERSION}"' in dockerfile
    assert "FROM cpushim" not in dockerfile
    stages = re.findall(r"^FROM (\S+) AS (\S+)$", dockerfile, re.MULTILINE)
    assert ("base", "bundled") in stages
    assert dockerfile.rstrip().splitlines()[-1] == "USER rasworker"


def test_executor_build_installs_the_shim_at_a_fixed_path():
    script = (REPO_ROOT / "containers" / "hecras-wine-executor"
              / "build_executor_image.sh").read_text(encoding="utf-8")
    assert "SHIM=/opt/ras-commander-executor/cpushim.so" in script
    assert 'ENV RAS_COMMANDER_WINE_CPU_SHIM=$SHIM' in script
    assert "test -f /opt/hecras-prepare/cpushim.so" in script
    assert "--target cpushim-artifact" in script
