"""Suite-wide isolation for process state that real HEC-RAS interop changes."""

import os
import sys

import pytest

# Loading RasMapperLib (clr_bootstrap.load_clr) points GDAL_DATA, PROJ_LIB and
# PROJ_DATA at HEC-RAS's bundled GDAL for the rest of the process. Its proj.db
# is from another PROJ release, so GDAL-backed packages that read these
# variables later in the same worker (rasterio, fiona, pyogrio) fail every
# EPSG lookup. Restore the session's starting values after each test so test
# order cannot matter; RasMapperLib is often loaded by a module-scoped fixture,
# so a per-test snapshot would already include the change.
_GDAL_ENVIRONMENT = ("GDAL_DATA", "PROJ_LIB", "PROJ_DATA")
_SESSION_GDAL_ENVIRONMENT = {name: os.environ.get(name) for name in _GDAL_ENVIRONMENT}


def _detach_dotnet_console():
    """Point .NET Console output at a null writer once the CLR is loaded.

    .NET binds Console.Out/Error to the standard handles on first use. Under
    pytest's fd capture those are the capture file of the running test, which
    is closed afterwards, so RasMapperLib progress output in any later test of
    the same worker fails with "IOException: The handle is invalid".
    """
    bootstrap = sys.modules.get("ras_commander.dotnet.clr_bootstrap")
    if bootstrap is None or not bootstrap._CLR_LOADED:
        return
    import System  # type: ignore

    System.Console.SetOut(System.IO.TextWriter.Null)
    System.Console.SetError(System.IO.TextWriter.Null)


@pytest.fixture(scope="session", autouse=True)
def _worker_example_projects_dir(tmp_path_factory):
    """Extract example projects under this worker's basetemp, not the cwd.

    RasExamples.projects_dir defaults to ``<cwd>/example_projects``, and many
    tests extract the same project names there with delete-and-replace, so
    pytest-xdist workers (and runs sharing a cwd) raced on the same folders.
    """
    from ras_commander import RasExamples

    RasExamples.projects_dir = tmp_path_factory.getbasetemp() / "example_projects"


@pytest.fixture(autouse=True)
def _restore_interop_process_state():
    yield
    for name, value in _SESSION_GDAL_ENVIRONMENT.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    _detach_dotnet_console()
