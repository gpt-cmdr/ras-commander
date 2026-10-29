"""Contracts for the lean RasCmdr command-line execution installation."""

from pathlib import Path
import inspect
import json
import runpy
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def _setup_metadata(monkeypatch):
    captured = {}

    def fake_setup(**kwargs):
        captured.update(kwargs)

    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setattr("setuptools.setup", fake_setup)
    runpy.run_path(str(REPO_ROOT / "setup.py"), run_name="__main__")
    return captured


def test_compute_extra_has_only_process_supervision_dependencies(monkeypatch):
    metadata = _setup_metadata(monkeypatch)

    assert metadata["install_requires"][:3] == ["h5py", "numpy", "pandas"]
    assert len(metadata["install_requires"]) == 4
    expected = [
        "psutil>=5.6.6",
        'pywin32>=227; sys_platform == "win32"',
    ]
    assert metadata["extras_require"]["compute"] == expected
    assert metadata["extras_require"]["execution"] == expected

    full = metadata["extras_require"]["full"]
    for dependency in (
        "geopandas",
        "rasterio",
        "matplotlib",
        "scipy",
        "xarray",
        "shapely>=2.0",
        "pyarrow>=14.0",
        "hms-commander>=0.3.1",
        *expected,
    ):
        assert dependency in full


def test_native_hdf_engine_is_a_core_dependency_on_wheel_platforms(monkeypatch):
    from packaging.requirements import Requirement

    metadata = _setup_metadata(monkeypatch)
    native = [Requirement(spec) for spec in metadata["install_requires"]
              if spec.startswith("ras-commander-fast-hdf")]
    assert len(native) == 1
    requirement = native[0]
    assert str(requirement.specifier) == "<0.3,>=0.2.4"
    assert requirement.marker is not None

    def environment(system, machine, implementation="CPython"):
        return {"platform_system": system, "platform_machine": machine,
                "platform_python_implementation": implementation}

    # Platforms with published wheels install the engine automatically.
    for system, machine in (("Windows", "AMD64"), ("Linux", "x86_64"),
                            ("Darwin", "arm64")):
        assert requirement.marker.evaluate(environment(system, machine))
    # Elsewhere pip must never be asked to build the Rust source distribution.
    for env in (environment("Windows", "ARM64"), environment("Linux", "aarch64"),
                environment("Darwin", "x86_64"),
                environment("Linux", "x86_64", "PyPy")):
        assert not requirement.marker.evaluate(env)

    # The former opt-in extras still resolve (no marker: they request a source
    # build on platforms without wheels).
    for extra in ("fast", "fast-hdf"):
        assert metadata["extras_require"][extra] == ["ras-commander-fast-hdf>=0.2.4,<0.3"]


def test_compute_facade_imports_without_full_feature_stack():
    script = r'''
import importlib.abc
import json
import sys

forbidden = {
    "geopandas", "rasterio", "matplotlib", "scipy", "xarray", "shapely",
    "pyarrow", "pyproj", "rasterstats", "rtree", "requests", "tqdm",
    "hms_commander",
}

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in forbidden:
            raise ModuleNotFoundError(fullname)
        return None

sys.meta_path.insert(0, Blocker())
from ras_commander.compute import (
    ComputeParallelResult,
    ComputeResult,
    GeometryPreprocessResult,
    HdfResultsPlan,
    PreprocessResult,
    RasCmdr,
    RasPlan,
    RasPreprocess,
    RasPrj,
    ResultsParser,
    ResultsSummary,
    init_ras_project,
    ras,
)

assert "ras_commander.RasControl" not in sys.modules
assert all(name not in globals() for name in ("RasControl", "RasControlResult"))
print(json.dumps({
    "exports": [
        RasCmdr.__name__, RasPlan.__name__, RasPrj.__name__,
        RasPreprocess.__name__, PreprocessResult.__name__,
        GeometryPreprocessResult.__name__,
        ComputeResult.__name__, ComputeParallelResult.__name__,
        HdfResultsPlan.__name__, ResultsParser.__name__, ResultsSummary.__name__,
    ],
    "project_initialized": getattr(ras, "project_folder", None) is not None,
    "initializer_callable": callable(init_ras_project),
}))
'''
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])

    assert payload["exports"] == [
        "RasCmdr",
        "RasPlan",
        "RasPrj",
        "RasPreprocess",
        "PreprocessResult",
        "GeometryPreprocessResult",
        "ComputeResult",
        "ComputeParallelResult",
        "HdfResultsPlan",
        "ResultsParser",
        "ResultsSummary",
    ]
    assert payload["initializer_callable"] is True


def test_representative_top_level_exports_remain_available():
    from ras_commander import (
        BenefitAreaConfig,
        HdfResultsPlan,
        RasCmdr,
        RasSteady,
        RasUnsteady,
        StoreMapPerformanceOptions,
    )
    from ras_commander.RasBenefits import BenefitAreaConfig as LegacyBenefitAreaConfig
    from ras_commander.RasterPerformance import (
        StoreMapPerformanceOptions as LegacyStoreMapPerformanceOptions,
    )
    from ras_commander.compute import RasCmdr as ComputeRasCmdr

    assert HdfResultsPlan.__name__ == "HdfResultsPlan"
    assert RasSteady.__name__ == "RasSteady"
    assert RasUnsteady.__name__ == "RasUnsteady"
    assert ComputeRasCmdr is RasCmdr
    assert BenefitAreaConfig is LegacyBenefitAreaConfig
    assert StoreMapPerformanceOptions is LegacyStoreMapPerformanceOptions
    assert BenefitAreaConfig.__module__ == "ras_commander.RasBenefits"
    assert (
        StoreMapPerformanceOptions.__module__
        == "ras_commander.RasterPerformance"
    )
    parameters = inspect.signature(RasCmdr.compute_plan).parameters
    assert "refresh_inventory" not in parameters
    assert "refresh_results" not in parameters


def test_lazy_class_exports_survive_same_named_submodule_imports():
    script = r'''
import importlib
from types import ModuleType

importlib.import_module("ras_commander.RasSteady")
importlib.import_module("ras_commander.hdf.HdfMesh")

from ras_commander import RasSteady
from ras_commander.hdf import HdfMesh

assert not isinstance(RasSteady, ModuleType)
assert not isinstance(HdfMesh, ModuleType)
assert RasSteady.__name__ == "RasSteady"
assert HdfMesh.__name__ == "HdfMesh"
'''
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
