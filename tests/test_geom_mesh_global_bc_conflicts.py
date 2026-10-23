"""Unsupported global BC tables must not be reported as conflict-free."""

import hashlib

import h5py
import numpy as np
import pytest

from ras_commander.geom import GeomMesh


@pytest.fixture
def global_bc_conflict_hdf(tmp_path):
    """Build the saved compact global-table regression fixture."""
    hdf_path = tmp_path / "global.g01.hdf"
    with h5py.File(str(hdf_path), "w") as hf:
        fa_group = hf.create_group("Geometry/2D Flow Areas")
        area_grp = fa_group.create_group("MainArea")
        area_grp.create_dataset(
            "FacePoints Coordinate",
            data=np.array(
                [[90.0, 0.0], [95.0, 0.0], [20.0, 0.0], [25.0, 0.0]],
                dtype=np.float64,
            ),
        )
        area_grp.create_dataset(
            "Faces FacePoint Indexes",
            data=np.array([[0, 1], [2, 3]], dtype=np.int32),
        )
        area_grp.create_dataset(
            "Faces Perimeter Info",
            data=np.array([[1, 1], [1, 1]], dtype=np.int32),
        )
        bc_group = hf.create_group("Geometry/Boundary Condition Lines")
        attributes = np.zeros(
            2,
            dtype=np.dtype([("Name", "S32"), ("SA-2D", "S16"), ("Type", "S8")]),
        )
        attributes[0] = (b"NormDepth1", b"MainArea", b"External")
        attributes[1] = (b"USInflow1", b"MainArea", b"External")
        bc_group.create_dataset("Attributes", data=attributes)
        bc_group.create_dataset(
            "Polyline Info",
            data=np.array([[0, 3, 0, 1], [3, 3, 1, 1]], dtype=np.int32),
        )
        bc_group.create_dataset(
            "Polyline Parts",
            data=np.array([[0, 3], [0, 3]], dtype=np.int32),
        )
        bc_group.create_dataset(
            "Polyline Points",
            data=np.array(
                [
                    [0.0, 0.0],
                    [50.0, 0.0],
                    [100.0, 0.0],
                    [80.0, 0.0],
                    [150.0, 0.0],
                    [200.0, 0.0],
                ],
                dtype=np.float64,
            ),
        )
    return hdf_path


@pytest.mark.parametrize("include_legacy_area", [False, True])
@pytest.mark.parametrize("as_string", [False, True])
@pytest.mark.parametrize("operation", ["detect", "repair", "dry_run"])
def test_global_bc_conflicts_fail_before_modification(
    global_bc_conflict_hdf, include_legacy_area, as_string, operation
):
    path = global_bc_conflict_hdf
    if include_legacy_area:
        with h5py.File(path, "r+") as hdf:
            area = hdf["Geometry/2D Flow Areas/MainArea"]
            # Even a supported legacy group must not hide the global layout.
            bcs = area.create_group("BC Lines")
            for name, coords in (
                ("LegacyNormal", [[0.0, 0.0], [50.0, 0.0], [100.0, 0.0]]),
                ("LegacyFlow", [[80.0, 0.0], [150.0, 0.0], [200.0, 0.0]]),
            ):
                feature = bcs.create_group(name)
                feature.create_dataset("Coordinates", data=coords)
                feature.attrs["Type"] = "Normal Depth" if name == "LegacyNormal" else "Flow"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    argument = str(path) if as_string else path
    with pytest.raises(NotImplementedError, match="global boundary-condition tables"):
        if operation == "detect":
            GeomMesh.detect_bc_conflicts(argument, cell_size=50.0)
        else:
            GeomMesh.fix_bc_conflicts(
                argument, cell_size=50.0, dry_run=operation == "dry_run"
            )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]
