import h5py
import numpy as np
import pandas as pd

from ras_commander.check import _utils as check_utils
from ras_commander.hdf.HdfChannelCapacity import HdfChannelCapacity
from ras_commander.hdf.HdfHydraulicTables import HdfHydraulicTables


def test_check_utils_decodes_profile_names_and_structure_locations(tmp_path):
    hdf_path = tmp_path / "geom.hdf"
    structure_dtype = np.dtype(
        [
            ("River", "S16"),
            ("Reach", "S16"),
            ("RS", "S16"),
            ("BR US Left Bank", "f8"),
            ("BR US Right Bank", "f8"),
        ]
    )
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_dataset(
            "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names",
            data=np.array([b"  10P  ", b"  01P  "]),
        )
        hdf.create_dataset(
            "Geometry/Structures/Attributes",
            data=np.array(
                [(b"  River A  ", b"  Reach B  ", b"  123.4  ", 10.0, 20.0)],
                dtype=structure_dtype,
            ),
        )

    assert check_utils.get_available_profiles(hdf_path) == ["10P", "01P"]

    locations = check_utils.get_structure_locations(hdf_path)
    assert locations.to_dict("records") == [
        {
            "river": "River A",
            "reach": "Reach B",
            "station": "123.4",
            "abut_left": 10.0,
            "abut_right": 20.0,
        }
    ]


def test_channel_capacity_decodes_steady_profile_metadata(tmp_path):
    hdf_path = tmp_path / "plan.p01.hdf"
    attrs_dtype = np.dtype(
        [("River", "S16"), ("Reach", "S16"), ("Station", "S16")]
    )
    base = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_dataset(
            f"{base}/Cross Sections/Water Surface",
            data=np.array([[101.0, 102.0], [103.0, 104.0]]),
        )
        hdf.create_dataset(
            f"{base}/Profile Names",
            data=np.array([b"  10P  ", b"  01P  "]),
        )
        hdf.create_dataset(
            f"{base}/Cross Sections/Cross Section Attributes",
            data=np.array(
                [
                    (b"  River A  ", b"  Reach B  ", b"  100  "),
                    (b"  River A  ", b"  Reach B  ", b"  200  "),
                ],
                dtype=attrs_dtype,
            ),
        )

    profiles = HdfChannelCapacity.extract_steady_profile_wse(hdf_path)

    assert profiles["River"].tolist() == ["River A", "River A"]
    assert profiles["Reach"].tolist() == ["Reach B", "Reach B"]
    assert profiles["RS"].tolist() == ["100", "200"]
    assert profiles["10P"].tolist() == [101.0, 102.0]
    assert profiles["01P"].tolist() == [103.0, 104.0]


def test_hydraulic_tables_decode_cross_section_attrs_and_variable_names(tmp_path):
    hdf_path = tmp_path / "geom.g01.hdf"
    attrs_dtype = np.dtype([("River", "S16"), ("Reach", "S16"), ("RS", "S16")])
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_dataset(
            "/Geometry/Cross Sections/Attributes",
            data=np.array([(b"  River A  ", b"  Reach B  ", b"  123.4  ")], dtype=attrs_dtype),
        )
        group = hdf.create_group("/Geometry/Cross Sections/Property Tables")
        group.create_dataset("XSEC Info", data=np.array([[0, 1, 0]], dtype="i4"))
        value = group.create_dataset("XSEC Value", data=np.array([[10.0, 20.0]], dtype="f8"))
        value.attrs["Variables"] = np.array(
            [[b"  Elevation  ", b"ft"], [b"  Area Chan  ", b"sqft"]]
        )

        table = HdfHydraulicTables._extract_property_table(hdf, 0)
        xs_index = HdfHydraulicTables._get_xs_index(hdf, "River A", "Reach B", "123.4")

    assert xs_index == 0
    assert table.columns.tolist() == ["Elevation", "Area_Chan"]
    pd.testing.assert_frame_equal(
        table,
        pd.DataFrame({"Elevation": [10.0], "Area_Chan": [20.0]}),
    )
