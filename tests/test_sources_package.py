import pytest
from setuptools import find_packages


def test_sources_package_exports_current_models():
    from ras_commander.sources import M3Model, RasEbfeModels

    assert M3Model.__name__ == "M3Model"
    assert RasEbfeModels.__name__ == "RasEbfeModels"


def test_sources_root_does_not_export_boundary_helpers():
    import ras_commander.sources as sources

    assert not hasattr(sources, "CoastalBoundary")


def test_boundary_package_exports_coastal_boundary():
    from ras_commander.boundaries import CoastalBoundary

    assert CoastalBoundary.__name__ == "CoastalBoundary"


def test_legacy_coastal_boundary_import_path_remains_available():
    with pytest.deprecated_call(match="ras_commander.boundaries"):
        from ras_commander.sources.federal import CoastalBoundary

    assert CoastalBoundary.__name__ == "CoastalBoundary"


def test_sources_subpackages_are_packaged():
    packages = set(find_packages())

    assert "ras_commander.boundaries" in packages
    assert "ras_commander.sources" in packages
    assert "ras_commander.sources.county" in packages
    assert "ras_commander.sources.federal" in packages
