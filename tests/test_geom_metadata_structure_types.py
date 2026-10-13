"""Regression tests for geometry HDF structure Type decoding in GeomMetadata."""

from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander.geom.GeomMetadata import GeomMetadata


def _write_structures_hdf(path: Path, types, gate_groups: int = 0) -> None:
    dtype = np.dtype([("Type", "S16"), ("River", "S16")])
    attrs = np.array([(t, b"River A") for t in types], dtype=dtype)
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset("Geometry/Structures/Attributes", data=attrs)
        if gate_groups:
            gate_attrs = np.array(
                [(b"Gate",)] * gate_groups, dtype=np.dtype([("Name", "S16")])
            )
            hdf.create_dataset(
                "Geometry/Structures/Gate Groups/Attributes", data=gate_attrs
            )


def test_hdf_structure_type_byte_strings_are_counted(tmp_path):
    hdf_path = tmp_path / "Model.g01.hdf"
    _write_structures_hdf(
        hdf_path,
        [
            b"Bridge", b"Bridge", b"Culvert", b"Inline",
            b"Lateral", b"Lateral", b"Lateral", b"Connection",
        ],
        gate_groups=1,
    )

    counts = GeomMetadata.get_geometry_counts(tmp_path / "missing.g01", hdf_path)

    assert counts["geometry_metadata_source"] == "hdf"
    assert counts["num_bridges"] == 2
    assert counts["num_culverts"] == 1
    assert counts["num_weirs"] == 1
    assert counts["num_inline_structures"] == 4
    assert counts["num_lateral_structures"] == 3
    assert counts["num_sa_2d_connections"] == 1
    assert counts["num_gates"] == 1
    assert "_hdf_structure_types" not in counts


def test_hdf_structure_types_are_not_double_counted_with_text(tmp_path):
    # A text geometry with a connection record must not add to the HDF
    # inventory, which already supplies lateral and connection counts.
    geom_path = tmp_path / "Model.g01"
    geom_path.write_text(
        "Geom Title=Synthetic\n"
        "Connection=Conn A          ,0,0\n"
        "Connection=Conn B          ,0,0\n",
        encoding="utf-8",
    )
    hdf_path = tmp_path / "Model.g01.hdf"
    _write_structures_hdf(hdf_path, [b"Connection", b"Lateral"])

    counts = GeomMetadata.get_geometry_counts(geom_path, hdf_path)

    assert counts["num_sa_2d_connections"] == 1
    assert counts["num_lateral_structures"] == 1


def test_hdf_structure_type_padding_and_case_are_tolerated(tmp_path):
    hdf_path = tmp_path / "Model.g01.hdf"
    _write_structures_hdf(hdf_path, [b" Bridge ", b"INLINE", b"Unknown"])

    counts = GeomMetadata.get_geometry_counts(None, hdf_path)

    assert counts["num_bridges"] == 1
    assert counts["num_weirs"] == 1
    assert counts["num_culverts"] == 0


def test_hdf_structure_legacy_integer_codes_are_counted(tmp_path):
    hdf_path = tmp_path / "Model.g01.hdf"
    attrs = np.array([(2,), (2,), (3,), (4,), (9,)], dtype=np.dtype([("Type", "i4")]))
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_dataset("Geometry/Structures/Attributes", data=attrs)

    counts = GeomMetadata.get_geometry_counts(None, hdf_path)

    assert counts["num_bridges"] == 2
    assert counts["num_culverts"] == 1
    assert counts["num_weirs"] == 1
    assert counts["num_inline_structures"] == 4


@pytest.fixture(scope="module")
def bald_eagle_project(tmp_path_factory):
    from ras_commander.RasExamples import RasExamples

    output = tmp_path_factory.mktemp("ras_examples")
    return RasExamples.extract_project("Balde Eagle Creek", output_path=output)


def test_bald_eagle_geom_df_counts_bridges_and_inline_structure(bald_eagle_project):
    from ras_commander import init_ras_project
    from ras_commander.RasPrj import RasPrj

    ras = init_ras_project(bald_eagle_project, ras_object=RasPrj())
    row = ras.geom_df.set_index("geom_number").loc["01"]

    assert row["geometry_metadata_source"] == "hdf"
    assert row["num_bridges"] == 10
    assert row["num_weirs"] == 1
    assert row["num_culverts"] == 0
    assert row["num_inline_structures"] == 11
    assert row["num_gates"] == 1
