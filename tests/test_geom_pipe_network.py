from pathlib import Path

import h5py
import numpy as np

from ras_commander import GeomPipeNetwork


def _write_geometry_fixture(tmp_path: Path) -> Path:
    geom = tmp_path / "Scenario.g01"
    geom.write_text(
        """Geom Title=Pipe and Pump Scenario
Pump Station=Station 1 ,0,0,,,,
Pump Station Group=Primary ,False,5,,5
Pump Station Group Pump=Pump 1,26.6,25
Pump Station Group HQ= 3
       2      70       8      50      16      25

LCMann Table=0
""",
        encoding="utf-8",
    )

    conduit_dtype = np.dtype(
        [("Name", "S3"), ("System Name", "S8"), ("Rise", "<f4"), ("Span", "<f4")]
    )
    conduits = np.array(
        [(b"101", b"System A", 5.0, 5.0), (b"102", b"System A", 6.0, 6.0)],
        dtype=conduit_dtype,
    )
    group_dtype = np.dtype([("Name", "S16"), ("Pumps", "<i4")])

    with h5py.File(f"{geom}.hdf", "w") as hdf:
        hdf.create_dataset("Geometry/Pipe Conduits/Attributes", data=conduits)
        groups = hdf.require_group("Geometry/Pump Stations/Pump Groups")
        groups.create_dataset(
            "Attributes", data=np.array([(b"Primary", 1)], dtype=group_dtype)
        )
        groups.create_dataset("Efficiency Curves Info", data=np.array([[0, 3]], dtype=np.int32))
        groups.create_dataset(
            "Efficiency Curves Values",
            data=np.array([[2.0, 70.0], [8.0, 50.0], [16.0, 25.0]], dtype=np.float32),
        )
        networks = hdf.require_group("Geometry/Pipe Networks")
        networks.create_dataset(
            "Attributes", data=np.array([(b"System A",)], dtype=[("Name", "S8")])
        )
        compiled = networks.require_group("System A")
        compiled.create_dataset("Cell Property Table Values", data=np.ones((2, 2)))
    return geom


def test_set_conduit_dimensions_preserves_compound_strings_and_is_idempotent(tmp_path):
    geom = _write_geometry_fixture(tmp_path)

    first = GeomPipeNetwork.set_conduit_dimensions(
        geom, {"101": (7.5, 7.5), "102": (9.0, 9.0)}
    )
    second = GeomPipeNetwork.set_conduit_dimensions(
        geom, {"101": (7.5, 7.5), "102": (9.0, 9.0)}
    )

    assert first["changed"].tolist() == [True, True]
    assert second["changed"].tolist() == [False, False]
    with h5py.File(f"{geom}.hdf", "r") as hdf:
        attributes = hdf["Geometry/Pipe Conduits/Attributes"][()]
        assert "Geometry/Pipe Networks" in hdf
        assert "Geometry/Pipe Networks/Attributes" in hdf
        assert "Geometry/Pipe Networks/System A" not in hdf
    assert attributes["Name"].tolist() == [b"101", b"102"]
    assert attributes["System Name"].tolist() == [b"System A", b"System A"]
    np.testing.assert_allclose(attributes["Rise"], [7.5, 9.0])
    np.testing.assert_allclose(attributes["Span"], [7.5, 9.0])


def test_set_conduit_dimensions_keeps_compiled_tables_for_noop(tmp_path):
    geom = _write_geometry_fixture(tmp_path)

    result = GeomPipeNetwork.set_conduit_dimensions(
        geom, {"101": (5.0, 5.0), "102": (6.0, 6.0)}
    )

    assert not result["changed"].any()
    with h5py.File(f"{geom}.hdf", "r") as hdf:
        assert "Geometry/Pipe Networks" in hdf


def test_set_pump_group_hq_curve_updates_text_and_hdf_idempotently(tmp_path):
    geom = _write_geometry_fixture(tmp_path)
    target = [(2.0, 140.0), (8.0, 100.0), (16.0, 50.0)]

    first = GeomPipeNetwork.set_pump_group_hq_curve(geom, "Primary", target)
    second = GeomPipeNetwork.set_pump_group_hq_curve(geom, "Primary", target)

    assert first["changed"].all()
    assert not second["changed"].any()
    text = geom.read_text(encoding="utf-8")
    assert "140.00" in text
    assert "100.00" in text
    with h5py.File(f"{geom}.hdf", "r") as hdf:
        curve = hdf[
            "Geometry/Pump Stations/Pump Groups/Efficiency Curves Values"
        ][()]
    np.testing.assert_allclose(curve, target)
