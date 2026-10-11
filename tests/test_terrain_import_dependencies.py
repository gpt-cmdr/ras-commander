"""Terrain creation/replay must work without the unrelated HTTP downloader."""

import subprocess
import sys


def test_core_terrain_import_without_requests():
    script = """
import importlib.abc
import sys

class NoRequests(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'requests' or fullname.startswith('requests.'):
            raise ModuleNotFoundError('blocked HTTP dependency', name='requests')

sys.meta_path.insert(0, NoRequests())
from ras_commander.terrain import RasTerrain, RasTerrainModWriter
assert callable(RasTerrain.create_terrain_hdf)
assert callable(RasTerrainModWriter.get_modification_features)
assert 'ras_commander.terrain.Usgs3depAws' not in sys.modules
try:
    from ras_commander.terrain import Usgs3depAws
except ImportError as exc:
    assert 'install requests' in str(exc), str(exc)
else:
    raise AssertionError('downloader unexpectedly loaded without requests')
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_downloader_public_exports_are_classes():
    script = """
from ras_commander.terrain import TerrainBuildError, Usgs3depAws
from ras_commander.terrain import Usgs3depAws as again
assert isinstance(Usgs3depAws, type)
assert issubclass(TerrainBuildError, RuntimeError)
assert again is Usgs3depAws
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
