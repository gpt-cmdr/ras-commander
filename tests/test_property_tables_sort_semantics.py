"""RasMapperLib property tables must use HEC-RAS's own .NET sort semantics.

.NET Framework 4.x selects compatibility quirks from the host process's target
framework. ``python.exe`` declares none, so a pythonnet host runs with pre-4.5
quirks and ``Array.Sort``/``List<T>.Sort`` use the legacy quicksort instead of
introsort. Face profile samples that share a station then come out in a
different order than in HEC-RAS plan compute (RasProcess/RasMapperLib target
4.7.2), and ``Faces Profile Values`` and the downstream face tables differ.
On Weise_2D with HEC-RAS 7.0.1 the legacy host changed 32 face profiles.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import h5py
import pytest

from ras_commander._native_worker_environment import (
    RASMAPPER_TARGET_FRAMEWORK,
    rasmapper_host_environment,
    worker_environment,
)

_PROBE = r"""
import clr
import System
from System.Collections.Generic import Comparer, List
from System.Reflection import BindingFlags

compatibility = System.Object().GetType().Assembly.GetType(
    "System.Runtime.Versioning.BinaryCompatibility"
)
flag = compatibility.GetProperty(
    "TargetsAtLeast_Desktop_V4_5", BindingFlags.NonPublic | BindingFlags.Static
)
by_tens = Comparer[System.Int32].Create(
    System.Comparison[System.Int32](lambda a, b: (a // 10 > b // 10) - (a // 10 < b // 10))
)
values = List[System.Int32]()
for value in (1, 2, 3):
    values.Add(value)
values.Sort(by_tens)
print(bool(flag.GetValue(None)), list(values))
"""


def _require_netfx_pythonnet():
    if os.name != "nt":
        pytest.skip(".NET Framework host semantics apply to Windows only")
    pytest.importorskip("clr_loader")
    pytest.importorskip("pythonnet")


def _probe(environment):
    result = subprocess.run(
        [sys.executable, "-I", "-c", _PROBE],
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return result.stdout.strip()


def _without_target_framework(environment):
    return {
        key: value
        for key, value in environment.items()
        if key.casefold() != "complus_targetframeworkmoniker"
    }


def test_rasmapper_host_environment_selects_net45_introsort():
    _require_netfx_pythonnet()
    # Three equal keys: introsort (insertion sort below 17 items) keeps input
    # order; the legacy quicksort reorders them. The control proves the probe
    # discriminates on this machine.
    assert _probe(rasmapper_host_environment(1)) == "True [1, 2, 3]"
    assert _probe(_without_target_framework(worker_environment(1))) == "False [3, 2, 1]"


def test_rasmapper_host_environment_replaces_inherited_target(monkeypatch):
    monkeypatch.setenv("complus_targetframeworkmoniker", ".NETFramework,Version=v4.0")
    environment = rasmapper_host_environment(1)
    matches = [k for k in environment if k.casefold() == "complus_targetframeworkmoniker"]
    assert matches == ["COMPlus_TargetFrameworkMoniker"]
    assert environment["COMPlus_TargetFrameworkMoniker"] == RASMAPPER_TARGET_FRAMEWORK
    assert environment["COMPlus_ThreadPool_ForceMaxWorkerThreads"] == "1"


def _hecras_701():
    from ras_commander.dotnet.clr_bootstrap import find_hecras_install

    try:
        install = find_hecras_install("7.0.1")
    except FileNotFoundError:
        pytest.skip("HEC-RAS 7.0.1 is not installed")
    if not (install / "Ras.exe").exists():
        pytest.skip("HEC-RAS 7.0.1 Ras.exe is not installed")
    return install


_AREA = "Geometry/2D Flow Areas/2DArea/"
_FACE_TABLES = (
    "Faces Profile Info",
    "Faces Profile Values",
    "FacePoints Elevation",
    "Faces Area Elevation Info",
    "Faces Area Elevation Values",
    "Faces Minimum Elevation",
    "Faces Low Elevation Centroid",
)


@pytest.mark.integration
@pytest.mark.real_ras
@pytest.mark.destructive_copy
def test_recompute_face_tables_match_native_plan_compute(tmp_path):
    """Weise_2D discriminates the sorts at equal-station face end points."""
    _require_netfx_pythonnet()
    _hecras_701()
    from ras_commander import RasExamples, RasMap, init_ras_project
    from ras_commander.geom import GeomPreprocessor

    try:
        source = RasExamples.extract_project("Weise_2D", output_path=tmp_path / "src")
    except Exception as exc:  # download or archive unavailable
        pytest.skip(f"Weise_2D example unavailable: {exc}")
    with h5py.File(source / "Weise.g08.hdf", "r") as hdf:
        # The 6.6 archive stores no face profiles, so their presence below
        # proves the native run produced them.
        assert _AREA + "Faces Profile Values" not in hdf

    native = tmp_path / "native" / "Weise_2D"
    shutil.copytree(source, native)
    project = init_ras_project(native, "7.0.1")
    # The geometry-only Ras.exe run is HEC-RAS's own producer. Its completion
    # contract is not asserted here: it reports land-cover attachment items
    # on this example that are unrelated to face profiles.
    GeomPreprocessor.run_geometry_preprocessor("01", ras_object=project, max_wait=900)
    native_hdf = native / "Weise.g08.hdf"
    with h5py.File(native_hdf, "r") as hdf:
        assert _AREA + "Faces Profile Values" in hdf

    mapper = tmp_path / "mapper" / "Weise_2D"
    shutil.copytree(native, mapper)
    RasMap.recompute_property_tables(mapper, mapper / "Weise.g08", hecras_version="7.0.1")

    with h5py.File(native_hdf, "r") as expected, h5py.File(
        mapper / "Weise.g08.hdf", "r"
    ) as actual:
        differing = [
            name
            for name in _FACE_TABLES
            if expected[_AREA + name][()].tobytes() != actual[_AREA + name][()].tobytes()
            or expected[_AREA + name].shape != actual[_AREA + name].shape
        ]
    assert differing == []
