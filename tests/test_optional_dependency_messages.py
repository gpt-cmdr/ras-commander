"""Missing optional packages name the extra to install.

The core install has only h5py, numpy, and pandas. A public export that needs
a package outside that set must fail with ``OptionalDependencyError`` (an
``ImportError``) naming the extra that provides it, not a bare
``ModuleNotFoundError``. psutil and pywin32 come from the ``compute`` extra;
everything else comes from ``full``.
"""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from ras_commander._optional_deps import (
    OptionalDependencyError,
    import_feature_module,
    missing_dependency_message,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

_BLOCK_PSUTIL_AND_GEOPANDAS = r'''
import importlib.abc
import json
import sys

forbidden = {"psutil", "geopandas"}

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in forbidden:
            raise ModuleNotFoundError(f"No module named {fullname!r}")
        return None

sys.meta_path.insert(0, Blocker())

import ras_commander
import ras_commander.hdf
from ras_commander import RasCmdr
from ras_commander._optional_deps import OptionalDependencyError

def capture(fn):
    try:
        fn()
    except OptionalDependencyError as exc:
        return str(exc)
    except Exception as exc:
        return f"WRONG TYPE {type(exc).__name__}: {exc}"
    return None

print(json.dumps({
    "RasControl": capture(lambda: ras_commander.RasControl),
    "RasTerrain": capture(lambda: ras_commander.RasTerrain),
    "HdfBndry": capture(lambda: ras_commander.hdf.HdfBndry),
    # The class imports without geopandas; building geometry names the extra.
    "HdfBndry geometry": capture(
        lambda: sys.modules["ras_commander.hdf.HdfBndry"].gpd.GeoDataFrame),
    "compute_plan": capture(lambda: RasCmdr.compute_plan("01")),
}))
'''


def test_missing_packages_name_the_extra():
    completed = subprocess.run(
        [sys.executable, "-c", _BLOCK_PSUTIL_AND_GEOPANDAS],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    messages = json.loads(completed.stdout.strip().splitlines()[-1])

    for label in ("RasControl", "RasTerrain", "compute_plan"):
        message = messages[label]
        assert message is not None, label
        assert not message.startswith("WRONG TYPE"), message
        assert "'psutil'" in message, message
        assert 'pip install "ras-commander[compute]"' in message, message

    assert messages["HdfBndry"] is None
    hdf_message = messages["HdfBndry geometry"]
    assert hdf_message is not None and not hdf_message.startswith("WRONG TYPE")
    assert "'geopandas'" in hdf_message
    assert 'pip install "ras-commander[full]"' in hdf_message


def test_pywin32_modules_map_to_compute_extra():
    message = missing_dependency_message("win32com.client", "RasControl")
    assert 'ras-commander[compute]' in message
    assert "pip install pywin32" in message


def test_missing_ras_commander_module_is_not_masked():
    with pytest.raises(ModuleNotFoundError) as info:
        import_feature_module(".DoesNotExist", "ras_commander", "probe")
    assert not isinstance(info.value, OptionalDependencyError)
