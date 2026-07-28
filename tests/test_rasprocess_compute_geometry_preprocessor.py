"""Integration test for native ``RasProcess.compute_geometry()``.

Verifies the real RasProcess.exe path that ``force_geompre`` relies on without
selectively deleting solver-owned geometry-HDF datasets.

Opt-in (marked ``integration``) because it needs an installed HEC-RAS: RasProcess.exe
plus a real 2D land-cover project. Skips cleanly when either is unavailable.

Guards the empirical findings behind compute_geometry:
  - CompleteGeometry is the working verb (ComputePropertyTables is a stub on 7.0)
  - the CLI key is GeomFilename (GeometryFilename is rejected)
so a regression in the argument form is caught rather than silently ignored.
"""

from pathlib import Path

import pytest

from ras_commander.RasExamples import RasExamples
from ras_commander.RasProcess import RasProcess
h5py = pytest.importorskip("h5py")
import numpy as np

pytestmark = pytest.mark.integration

PROJECT = "BaldEagleCrkMulti2D"
CELLS_CENTER_N = "Cells Center Manning's n"


@pytest.fixture(scope="module")
def geom_hdf(tmp_path_factory):
    """Extract the 2D land-cover project and return its first geometry HDF."""
    if RasProcess.find_rasprocess() is None:
        pytest.skip("RasProcess.exe not found (HEC-RAS not installed)")

    output_path = tmp_path_factory.mktemp("ras_examples")
    try:
        project = Path(
            RasExamples.extract_project(
                PROJECT, output_path=output_path, suffix="cgp_integration"
            )
        )
    except Exception as exc:
        pytest.skip(f"{PROJECT} example project unavailable: {exc}")

    geoms = sorted(project.glob("*.g??.hdf"))
    if not geoms:
        pytest.skip(f"{PROJECT} extracted without a geometry HDF")
    return geoms[0]


def _per_cell_n(hdf_path):
    """Return {mesh_dataset_path: (n_cells, min, max)} for every per-cell n table."""
    found = {}
    with h5py.File(hdf_path, "r") as f:
        def visit(name, obj):
            if isinstance(obj, h5py.Dataset) and name.endswith(CELLS_CENTER_N):
                found[name] = (obj.shape[0], float(np.min(obj[:])), float(np.max(obj[:])))

        f.visititems(visit)
    return found


def _land_cover_filename(hdf_path):
    with h5py.File(hdf_path, "r") as f:
        if "Geometry" not in f:
            return None
        return f["Geometry"].attrs.get("Land Cover Filename")


def test_compute_geometry_preserves_per_cell_n_and_land_cover_association(geom_hdf):
    """Native complete-geometry processing preserves required model content."""
    RasProcess.compute_geometry(geom_hdf)
    seeded = _per_cell_n(geom_hdf)
    assert seeded, "expected per-cell Manning's n after native geometry processing"
    lc_before = _land_cover_filename(geom_hdf)
    assert lc_before is not None, "land cover association missing before rerun"

    result = RasProcess.compute_geometry(geom_hdf)
    assert result["return_code"] == 0
    assert not (result["stderr"] or "").strip().startswith("Error:"), (
        f"CompleteGeometry reported an argument error: {result['stderr']!r}"
    )

    recomputed = _per_cell_n(geom_hdf)
    assert recomputed, "compute_geometry removed per-cell n"
    assert set(recomputed) == set(seeded), "recomputed mesh set differs from the seeded set"
    for name, (cells, lo, hi) in recomputed.items():
        assert (cells, lo, hi) == seeded[name], (
            f"recomputed per-cell n for {name} differs from seeded values"
        )
    assert _land_cover_filename(geom_hdf) == lc_before, (
        "land cover association changed across native geometry processing"
    )


def test_compute_geometry_missing_hdf_raises():
    """A missing geometry HDF is a caller error, not a silent no-op."""
    with pytest.raises(FileNotFoundError):
        RasProcess.compute_geometry("does_not_exist.g01.hdf")
