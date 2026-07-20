"""Tests for deterministic RasMapperLib managed-assembly loading."""

from pathlib import Path

import pytest

from ras_commander._rasmapper_runtime import (
    RAS_MAPPER_MANAGED_DEPENDENCIES,
    load_rasmapper_assemblies,
)


def _create_assemblies(root: Path, dependencies: tuple[str, ...]) -> None:
    for dependency in dependencies:
        (root / f"{dependency}.dll").touch()


def test_rasmapper_dependency_order_loads_rasmapper_last(tmp_path):
    _create_assemblies(tmp_path, RAS_MAPPER_MANAGED_DEPENDENCIES)
    observed: list[str] = []

    loaded = load_rasmapper_assemblies(tmp_path, observed.append)

    expected = [
        str(tmp_path / f"{dependency}.dll")
        for dependency in RAS_MAPPER_MANAGED_DEPENDENCIES
    ]
    assert observed == expected
    assert [str(path) for path in loaded] == expected
    assert RAS_MAPPER_MANAGED_DEPENDENCIES[-1] == "RasMapperLib"


def test_rasmapper_dependency_loader_skips_absent_version_specific_dlls(tmp_path):
    core = ("Utility.Core", "Geospatial.Core", "H5Assist", "RasMapperLib")
    _create_assemblies(tmp_path, core)
    observed: list[str] = []

    loaded = load_rasmapper_assemblies(tmp_path, observed.append)

    assert [path.stem for path in loaded] == list(core)
    assert Path(observed[-1]).stem == "RasMapperLib"


def test_rasmapper_dependency_loader_rejects_missing_required_dll(tmp_path):
    _create_assemblies(tmp_path, ("Utility.Core", "Geospatial.Core", "H5Assist"))

    with pytest.raises(FileNotFoundError, match="RasMapperLib.dll"):
        load_rasmapper_assemblies(tmp_path, lambda _path: None)


def test_rasmapper_dependency_loader_fails_before_partial_binding(tmp_path):
    _create_assemblies(tmp_path, RAS_MAPPER_MANAGED_DEPENDENCIES)

    def fail_on_geospatial_io(path: str) -> None:
        if Path(path).stem == "Geospatial.IO":
            raise OSError("bad image")

    with pytest.raises(RuntimeError, match=r"Geospatial\.IO\.dll.*bad image"):
        load_rasmapper_assemblies(tmp_path, fail_on_geospatial_io)
