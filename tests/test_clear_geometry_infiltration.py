"""Clearing infiltration on clone geometries preserves unrelated associations."""

import h5py
import pytest

from ras_commander import RasMap
from ras_commander._geometry_association import (
    clear_geometry_infiltration,
    read_geometry_association,
)


def test_clear_geometry_infiltration_is_selective_and_idempotent(tmp_path):
    path = tmp_path / "child.g02.hdf"
    with h5py.File(path, "w") as h:
        g = h.create_group("Geometry")
        for k, v in {
            "Terrain Filename": "terrain.hdf",
            "Land Cover Filename": "cover.hdf",
            "Infiltration Filename": "infiltration.hdf",
            "Infiltration Layername": "SCS",
            "Infiltration File Date": "old",
            "Other": "untouched",
        }.items():
            g.attrs[k] = v
    assert clear_geometry_infiltration(path) == path.resolve()
    assert not read_geometry_association(path).get("infiltration_hdf_path")
    with h5py.File(path) as h:
        assert dict(h["Geometry"].attrs) == {
            "Terrain Filename": "terrain.hdf",
            "Land Cover Filename": "cover.hdf",
            "Other": "untouched",
        }
    assert RasMap.clear_geometry_infiltration(str(path)) == path.resolve()


@pytest.mark.parametrize("name", ["parent.p01.hdf", "parent.u01.hdf", "terrain.hdf", "project.g01"])
def test_clear_geometry_infiltration_rejects_non_geometry_before_open(name, tmp_path):
    with pytest.raises(ValueError, match="gNN"):
        clear_geometry_infiltration(tmp_path / name)
