"""Sanitized format fixtures; these are schema controls, not native qualification.

No solver, private model, geometry mock, or network access is needed. The public
APIs read actual temporary HDF files with deliberately distinguishable values.
"""

from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander.hdf import HdfStruc1D


BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
FAMILIES = [
    ("Inline Structures", "Inline", "Structure Variables"),
    ("Bridges", "Bridge", "Bridge Variables"),
    ("Culverts", "Culvert", "Culvert Variables"),
    ("Pumping Stations", "Pump", "Structure Variables"),
]


def _write_direct(path, family, *, tailwater="finite"):
    group, kind, variable = family
    # Spaces and a starred station prohibit splitting names or numeric proximity.
    identity = ("", "", "Pump station A") if kind == "Pump" else (
        "River with spaces", "Reach with spaces", "100*",
    )
    name = identity[2] if kind == "Pump" else " ".join(identity)
    primary = f"/{BASE}/{group}/{name}/{variable}"
    labels = [b"Total Flow" if kind == "Inline" else b"Flow", b"Ignored", b"Stage HW"]
    values = [[-3., 999., 11.], [4., 888., 12.], [2., 777., 10.]]
    if tailwater != "absent":
        labels.append(b"Stage TW")
        for row, tw in zip(values, [6., 8., 7.]):
            row.append(np.nan if tailwater == "nan" else tw)
    with h5py.File(path, "w") as hdf:
        if kind == "Pump":
            hdf.create_dataset("Geometry/Pump Stations/Attributes", data=np.array(
                [(name.encode(),)], dtype=[("Name", "S64")],
            ))
        else:
            # Geometry row order is deliberately unrelated to result group order.
            rows = [(kind.encode(), b"Other", b"Reach", b"100"),
                    (kind.encode(), *(part.encode() for part in identity))]
            hdf.create_dataset("Geometry/Structures/Attributes", data=np.array(
                rows, dtype=[("Type", "S16"), ("River", "S64"), ("Reach", "S64"), ("RS", "S16")],
            ))
        hdf.create_dataset(f"{BASE}/Time", data=[0., 1., 2.])
        dataset = hdf.create_dataset(primary, data=values)
        dataset.attrs["Variable_Unit"] = np.array([[label, b"unit"] for label in labels])
        # Components cannot replace or contaminate the family's primary result.
        hdf.create_dataset(f"{BASE}/{group}/{name}/Components/Flow", data=[1.e6] * 3)
    return path, identity, primary


@pytest.mark.parametrize("family", FAMILIES, ids=[row[1] for row in FAMILIES])
@pytest.mark.parametrize("tailwater", ["finite", "absent", "nan"])
@pytest.mark.parametrize("input_form", ["path", "string", "01", "p01"])
def test_direct_family_identity_labels_maxima_and_flexible_inputs(tmp_path, family, tailwater, input_form):
    path, identity, primary = _write_direct(tmp_path / "direct.p01.hdf", family, tailwater=tailwater)
    # Only project resolution is supplied; no global project is initialized.
    project = SimpleNamespace(
        plan_df=pd.DataFrame([{"plan_number": "01", "HDF_Results_Path": str(path)}]),
        check_initialized=lambda: None,
    )
    value = {"path": path, "string": str(path), "01": "01", "p01": "p01"}[input_form]
    before = path.read_bytes()
    result = HdfStruc1D.get_structure_max_values(value, *identity, ras_object=project)
    assert result["found"]
    assert result["max_hw"] == 12.
    assert result["max_flow"] == 4.
    assert result["hw_source"] == f"{primary} [Stage HW]"
    flow_label = "Total Flow" if family[1] == "Inline" else "Flow"
    assert result["flow_source"] == f"{primary} [{flow_label}]"
    assert result["max_tw"] == (8. if tailwater == "finite" else None)
    assert result["tw_source"] == (f"{primary} [Stage TW]" if tailwater == "finite" else None)
    inventory = HdfStruc1D.list_1d_structures(value, ras_object=project)
    assert inventory.columns.tolist() == ["River", "Reach", "RS", "Name", "Type"]
    assert inventory[["River", "Reach", "RS"]].to_records(index=False).tolist() == [identity]
    assert inventory["Type"].tolist() == [family[1]]
    assert path.read_bytes() == before


def _corrupt(path, primary, case):
    with h5py.File(path, "r+") as hdf:
        dataset = hdf[primary]
        if case == "labels-shape":
            dataset.attrs["Variable_Unit"] = [[b"Flow", b"unit"]]
        elif case == "labels-missing":
            del dataset.attrs["Variable_Unit"]
        elif case == "labels-numeric":
            dataset.attrs["Variable_Unit"] = np.ones((4, 2), dtype="i4")
        elif case == "time-missing":
            del hdf[f"{BASE}/Time"]
        elif case == "time-rank":
            del hdf[f"{BASE}/Time"]
            hdf.create_dataset(f"{BASE}/Time", data=[[0., 1., 2.]])
        elif case == "time-inconsistent":
            hdf.create_dataset(f"{BASE}/Time Date Stamp", data=[b"a", b"b"])
        elif case in ("primary-rank", "primary-rows", "primary-text"):
            labels = dataset.attrs["Variable_Unit"]
            del hdf[primary]
            values = {"primary-rank": [1., 2., 3.],
                      "primary-rows": np.zeros((2, 4)),
                      "primary-text": np.full((3, 4), b"bad")}[case]
            hdf.create_dataset(primary, data=values).attrs["Variable_Unit"] = labels
        elif case == "primary-missing":
            del hdf[primary]
        elif case == "identity-mismatch":
            table = hdf["Geometry/Structures/Attributes"]
            rows = table[()]
            rows[1]["RS"] = b"101*"
            table[...] = rows
        elif case == "identity-duplicate":
            table = hdf["Geometry/Structures/Attributes"]
            rows = table[()]
            rows[0] = rows[1]
            table[...] = rows
        elif case == "identity-wrong-type":
            table = hdf["Geometry/Structures/Attributes"]
            rows = table[()]
            rows[1]["Type"] = b"Culvert"
            table[...] = rows
        else:
            raise AssertionError(case)


@pytest.mark.synthetic_hdf_layout(
    "labels-shape-Variable_Unit-inventory",
    "labels-shape-Variable_Unit-maxima",
)
@pytest.mark.parametrize("api", ["inventory", "maxima"])
@pytest.mark.parametrize("case,match", [
    ("labels-shape", "Variable_Unit"), ("labels-missing", "Variable_Unit"),
    ("labels-numeric", "text"), ("time-missing", "time axes"),
    ("time-rank", "one-dimensional time axis"), ("time-inconsistent", "time axes"),
    ("primary-rank", "numeric time/column layout"),
    ("primary-rows", "numeric time/column layout"),
    ("primary-text", "numeric time/column layout"),
    ("primary-missing", "missing primary dataset"),
    ("identity-mismatch", "no unique geometry identity"),
    ("identity-duplicate", "non-unique structure identity"),
    ("identity-wrong-type", "no unique geometry identity"),
])
def test_malformed_direct_layout_propagates_from_both_public_apis(tmp_path, api, case, match):
    path, identity, primary = _write_direct(tmp_path / "invalid.p01.hdf", FAMILIES[1])
    _corrupt(path, primary, case)
    with pytest.raises(ValueError, match=match):
        if api == "inventory":
            HdfStruc1D.list_1d_structures(path)
        else:
            HdfStruc1D.get_structure_max_values(path, *identity)


def test_explicit_project_resolution_does_not_reuse_another_project(tmp_path):
    first, identity, _ = _write_direct(tmp_path / "first.p01.hdf", FAMILIES[1])
    second, _, primary = _write_direct(tmp_path / "second.p01.hdf", FAMILIES[1])
    with h5py.File(second, "r+") as hdf:
        hdf[primary][:, 2] = [21., 22., 20.]
    for path, expected in [(first, 12.), (second, 22.), (first, 12.)]:
        project = SimpleNamespace(
            plan_df=pd.DataFrame([{"plan_number": "01", "HDF_Results_Path": path}]),
            check_initialized=lambda: None,
        )
        assert HdfStruc1D.get_structure_max_values("01", *identity, ras_object=project)["max_hw"] == expected


@pytest.mark.synthetic_hdf_layout
def test_two_direct_structures_join_exact_geometry_not_group_or_row_order(tmp_path):
    path, identity, primary = _write_direct(tmp_path / "multiple.p01.hdf", FAMILIES[1])
    other = ("Other", "Reach", "100")
    with h5py.File(path, "r+") as hdf:
        dataset = hdf.create_dataset(f"{BASE}/Bridges/Other Reach 100/Bridge Variables",
                                    data=[[40., 31., 25.], [50., 32., 26.], [45., 30., 24.]])
        dataset.attrs["Variable_Unit"] = [[b"Flow", b"cfs"], [b"Stage HW", b"ft"], [b"Stage TW", b"ft"]]
    inventory = HdfStruc1D.list_1d_structures(path)
    assert set(inventory[["River", "Reach", "RS"]].itertuples(index=False, name=None)) == {identity, other}
    assert HdfStruc1D.get_structure_max_values(path, *identity)["max_hw"] == 12.
    assert HdfStruc1D.get_structure_max_values(path, *other)["max_hw"] == 32.


def test_direct_values_precede_legacy_estimates_even_when_tailwater_missing(tmp_path):
    path, identity, _ = _write_direct(tmp_path / "precedence.p01.hdf", FAMILIES[1], tailwater="absent")
    with h5py.File(path, "r+") as hdf:
        generic = hdf.create_group(f"{BASE}/Structures")
        generic.create_dataset("Structure Attributes", data=np.array(
            [tuple(value.encode() for value in identity)],
            dtype=[("River", "S64"), ("Reach", "S64"), ("RS", "S16")],
        ))
        for name in ("Headwater", "Tailwater", "Flow"):
            generic.create_dataset(name, data=[[999.], [999.], [999.]])
    result = HdfStruc1D.get_structure_max_values(path, *identity)
    assert (result["max_hw"], result["max_flow"], result["max_tw"], result["tw_source"]) == (12., 4., None, None)


@pytest.mark.parametrize("family", FAMILIES, ids=[row[1] for row in FAMILIES])
def test_duplicate_quantity_labels_are_rejected(tmp_path, family):
    path, identity, primary = _write_direct(tmp_path / "duplicate.p01.hdf", family)
    with h5py.File(path, "r+") as hdf:
        labels = hdf[primary].attrs["Variable_Unit"]
        labels[1] = labels[0]
        hdf[primary].attrs["Variable_Unit"] = labels
    with pytest.raises(ValueError, match="ambiguous .* columns"):
        HdfStruc1D.get_structure_max_values(path, *identity)
