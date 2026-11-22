"""GeomMesh.generate keeps the geometry HDF seed tables exact.

Two defects left stale seeds after regenerating a 2D mesh with a different
seed count:

* RASGeometry.Save() rewrote the area mesh but not the collection-level
  ``Cell Info`` / ``Cell Points`` seed tables, so the previous seeds (and any
  rows beyond the new count) persisted.
* The cell-size and breakline-spacing syncs wrote whole compound tables back
  through h5py. That re-encodes the native NULLTERM ``Name`` field, which
  RASGeometry.Save() sizes exactly to the name, and drops its last character.
  The next generate then loaded an area named ``Perimeter`` instead of
  ``Perimeter 1`` and saved a second area group.
"""

import os
import platform
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander.geom.GeomMesh import (
    _format_seed_coordinate,
    _replace_hdf_area_seeds,
    _sync_breakline_spacing_text_to_hdf,
    _sync_cell_size_to_hdf,
)

AREA = "Geometry/2D Flow Areas"
HECRAS_INTEGRATION_ENV = "RAS_COMMANDER_RUN_HECRAS_INTEGRATION"


def _seed_hdf(path, blocks):
    names = list(blocks)
    counts = [len(blocks[name]) for name in names]
    starts = np.concatenate(([0], np.cumsum(counts)[:-1])).astype(np.int32)
    with h5py.File(path, "w") as hdf:
        group = hdf.create_group(AREA)
        group.create_dataset(
            "Attributes",
            data=np.array(
                [(name.encode(), count) for name, count in zip(names, counts)],
                dtype=[("Name", "S16"), ("Cell Count", "<i4")],
            ),
        )
        group.create_dataset(
            "Cell Info", data=np.column_stack((starts, counts)).astype(np.int32)
        )
        group.create_dataset(
            "Cell Points",
            data=np.concatenate([np.asarray(blocks[n], float) for n in names]),
            maxshape=(sum(counts), 2),
        )
    return path


def _read_blocks(path):
    with h5py.File(path, "r") as hdf:
        group = hdf[AREA]
        names = [n.decode().strip() for n in group["Attributes"][()]["Name"]]
        info = group["Cell Info"][()]
        points = group["Cell Points"][()]
        return {
            name: points[start : start + count]
            for name, (start, count) in zip(names, info)
        }, info, points


def _text_values(seeds):
    return np.array(
        [[float(_format_seed_coordinate(v)) for v in row] for row in seeds]
    )


def test_more_then_fewer_seeds_leave_exactly_the_new_seeds(tmp_path):
    rng = np.random.default_rng(7)
    other_before = rng.uniform(0, 1000, (4, 2))
    path = _seed_hdf(
        tmp_path / "Model.g01.hdf",
        {"Upper": rng.uniform(0, 1000, (5, 2)), "Lower": other_before},
    )

    more = rng.uniform(1_000_000, 2_000_000, (9, 2))
    assert _replace_hdf_area_seeds(path, "Upper", more) == 9
    blocks, info, points = _read_blocks(path)
    assert info.tolist() == [[0, 9], [9, 4]]
    assert points.shape == (13, 2)
    np.testing.assert_array_equal(blocks["Upper"], _text_values(more))
    np.testing.assert_array_equal(blocks["Lower"], other_before)

    fewer = rng.uniform(1_000_000, 2_000_000, (3, 2))
    assert _replace_hdf_area_seeds(path, "Upper", fewer) == 3
    blocks, info, points = _read_blocks(path)
    # No rows from the larger seed set survive beyond the new count.
    assert info.tolist() == [[0, 3], [3, 4]]
    assert points.shape == (7, 2)
    np.testing.assert_array_equal(blocks["Upper"], _text_values(fewer))
    np.testing.assert_array_equal(blocks["Lower"], other_before)
    with h5py.File(path, "r") as hdf:
        assert hdf[f"{AREA}/Cell Points"].dtype == np.float64
        assert hdf[f"{AREA}/Cell Points"].maxshape == (None, 2)


def test_missing_or_ambiguous_area_is_rejected(tmp_path):
    path = _seed_hdf(tmp_path / "Model.g01.hdf", {"Upper": [[0.0, 0.0]]})
    with pytest.raises(ValueError, match="exactly once"):
        _replace_hdf_area_seeds(path, "Missing", [[1.0, 1.0]])
    _, info, points = _read_blocks(path)
    assert info.tolist() == [[0, 1]] and points.tolist() == [[0.0, 0.0]]


def test_cell_info_outside_cell_points_is_rejected(tmp_path):
    path = _seed_hdf(tmp_path / "Model.g01.hdf", {"Upper": [[0.0, 0.0]]})
    with h5py.File(path, "r+") as hdf:
        hdf[f"{AREA}/Cell Info"][0] = [0, 5]
    with pytest.raises(ValueError, match="outside Cell Points"):
        _replace_hdf_area_seeds(path, "Upper", [[1.0, 1.0]])


def _native_name_table(path, dataset, name, numeric_fields):
    """Write a compound table whose Name is a NULLTERM string sized to the name.

    This is the layout RASGeometry.Save() writes, for example ``S11`` for
    ``Perimeter 1``. Raw bytes are written with the file type itself so no
    conversion trims the name during fixture creation.
    """
    width = len(name)
    string = h5py.h5t.C_S1.copy()
    string.set_size(width)
    string.set_strpad(h5py.h5t.STR_NULLTERM)
    fields = [("Name", f"S{width}")] + [(f, "<f4") for f in numeric_fields]
    layout = np.dtype(fields)
    ftype = h5py.h5t.create(h5py.h5t.COMPOUND, layout.itemsize)
    ftype.insert(b"Name", layout.fields["Name"][1], string)
    for field in numeric_fields:
        ftype.insert(field.encode(), layout.fields[field][1], h5py.h5t.IEEE_F32LE)
    with h5py.File(path, "a") as hdf:
        parent = hdf.require_group(str(Path(dataset).parent).replace("\\", "/"))
        space = h5py.h5s.create_simple((1,))
        dsid = h5py.h5d.create(parent.id, Path(dataset).name.encode(), ftype, space)
        row = np.zeros(1, dtype=layout)
        row["Name"] = name.encode()
        for field in numeric_fields:
            row[field] = 100.0
        dsid.write(h5py.h5s.ALL, h5py.h5s.ALL, row, mtype=ftype)


def _stored_name(path, dataset):
    with h5py.File(path, "r") as hdf:
        return bytes(hdf[dataset][()]["Name"][0]).rstrip(b"\x00").decode()


def test_cell_size_sync_keeps_native_full_width_area_name(tmp_path):
    path = tmp_path / "Model.g01.hdf"
    _native_name_table(path, f"{AREA}/Attributes", "Perimeter 1", ("Spacing dx", "Spacing dy"))
    _sync_cell_size_to_hdf(path, 200.0, mesh_name="Perimeter 1")
    assert _stored_name(path, f"{AREA}/Attributes") == "Perimeter 1"
    with h5py.File(path, "r") as hdf:
        row = hdf[f"{AREA}/Attributes"][0]
        assert row["Spacing dx"] == row["Spacing dy"] == 200.0


def test_breakline_spacing_sync_keeps_native_full_width_name(tmp_path):
    path = tmp_path / "Model.g01.hdf"
    key = "Geometry/2D Flow Area Break Lines/Attributes"
    _native_name_table(path, key, "Road 1", ("Cell Spacing Near", "Cell Spacing Far"))
    text = tmp_path / "Model.g01"
    text.write_text(
        "BreakLine Name=Road 1\nBreakLine CellSize Min=25\nBreakLine CellSize Max=75\n"
    )
    _sync_breakline_spacing_text_to_hdf(text, path)
    assert _stored_name(path, key) == "Road 1"
    with h5py.File(path, "r") as hdf:
        row = hdf[key][0]
        assert (row["Cell Spacing Near"], row["Cell Spacing Far"]) == (25.0, 75.0)


@pytest.mark.integration
@pytest.mark.destructive_copy
@pytest.mark.slow
@pytest.mark.skipif(
    platform.system() != "Windows" or os.environ.get(HECRAS_INTEGRATION_ENV) != "1",
    reason="Requires Windows, HEC-RAS, and explicit opt-in integration execution",
)
def test_generate_more_then_fewer_seeds_on_rasexamples_chippewa(tmp_path):
    from ras_commander import RasExamples, RasPrj, init_ras_project
    from ras_commander.geom import GeomMesh

    version = os.environ.get("RAS_COMMANDER_HECRAS_VERSION", "7.0.1")
    project = RasExamples.extract_project(
        "Chippewa_2D", output_path=tmp_path, suffix="pytest_seed_hdf"
    )
    ras = init_ras_project(project, version, ras_object=RasPrj())
    row = ras.geom_df.loc[ras.geom_df["geom_number"] == "01"].iloc[0]
    hdf_path = Path(row["hdf_path"])

    counts = []
    for cell_size in (50.0, 200.0):
        result = GeomMesh.generate(
            "01", mesh_name="Perimeter 1", cell_size=cell_size, ras_object=ras
        )
        assert result.ok, result.error_message
        with h5py.File(hdf_path, "r") as hdf:
            group = hdf[AREA]
            names = [bytes(n).rstrip(b"\x00").decode() for n in group["Attributes"][()]["Name"]]
            assert names == ["Perimeter 1"]
            assert sorted(k for k in group if isinstance(group[k], h5py.Group)) == ["Perimeter 1"]
            assert group["Cell Info"][()].tolist() == [[0, result.cell_count]]
            assert group["Cell Points"].shape == (result.cell_count, 2)
        counts.append(result.cell_count)
    assert counts[0] > counts[1] > 0
