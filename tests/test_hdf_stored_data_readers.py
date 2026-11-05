"""Stored observations, IC points, steady XS variables and obstruction contracts."""

import h5py
import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from ras_commander import HdfBndry, HdfResultsPlan, HdfXsec, fast_hdf
from ras_commander import _fast_hdf_typed as typed


@pytest.fixture
def data_file(tmp_path):
    path = tmp_path / "stored.hdf"
    with h5py.File(path, "w") as h:
        h["Geometry/IC Points/Attributes"] = np.array(
            [(b"Initial", b"Area", 0), (b"Initial", b"Area", 1)],
            dtype=[("Name", "S16"), ("SA/2D", "S16"), ("Cell Index", "<i4")],
        )
        h["Geometry/IC Points/Points"] = np.array(
            [[0.0, -0.0], [1.0, 2.0]], dtype="<f8"
        )
        h["Geometry/2D Flow Areas/Area/Cells Center Coordinate"] = np.zeros((2, 2))
        xs = np.array(
            [
                (b"River", b"Reach", b"2", b"", 0.0, 1.0),
                (b"River", b"Reach", b"1", b"", 0.0, 1.0),
            ],
            dtype=[
                ("River", "S16"),
                ("Reach", "S16"),
                ("RS", "S8"),
                ("Name", "S16"),
                ("Left Bank", "<f4"),
                ("Right Bank", "<f4"),
            ],
        )
        h["Geometry/Cross Sections/Attributes"] = xs
        h["Geometry/Cross Sections/Obstruction Info"] = np.array(
            [[0, 1], [1, 1]], dtype="<i4"
        )
        h["Geometry/Cross Sections/Obstruction Blocks"] = np.array(
            [(0.0, 1.0, -0.0), (2.0, 3.0, np.nan)],
            dtype=[("Left Sta", "<f4"), ("Right Sta", "<f4"), ("Elevation", "<f4")],
        )
        for kind, site, n in [
            ("Flow", "Ref Line: Gauge", 3),
            ("Stage", "Ref Point: Gauge", 2),
        ]:
            values = np.array(
                [
                    (b"01JAN2020 2400", 0.0, -0.0),
                    (b"01JAN2020 2400", 0.0, np.nan),
                    (b"01JAN2020 23:00:00", -1.0, 5.0),
                ],
                dtype=[("Date", "S18"), ("Simulation Time", "<f8"), ("Value", "<f4")],
            )[:n]
            ds = h.create_dataset(
                f"Event Conditions/Observed Data/{kind}/{site}", data=values
            )
            ds.attrs["Data Units"] = np.bytes_("cfs" if kind == "Flow" else "ft")
        sp = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"
        h[sp + "/Profile Names"] = np.array([b"P1", b"P2"], dtype="S16")
        h["Results/Steady/Output/Geometry Info/Cross Section Attributes"] = np.array(
            [(b"River", b"Reach", b"2", b""), (b"River", b"Reach", b"1", b"")],
            dtype=[
                ("River", "S16"),
                ("Reach", "S16"),
                ("Station", "S8"),
                ("Name", "S16"),
            ],
        )
        for name in ["Velocity Total", "Area including Ineffective Total"]:
            ds = h.create_dataset(
                sp + "/Cross Sections/Additional Variables/" + name,
                data=np.array([[1.0, -0.0], [np.nan, 4.0]], dtype="<f4"),
            )
            ds.attrs["Units"] = np.bytes_("literal-unit")
    return path


@pytest.fixture(params=["h5py", "auto"])
def mode(request, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", request.param)
    typed.clear_cache()
    return request.param


def test_observations_keep_duplicate_and_irregular_clock(data_file, mode):
    frame = HdfResultsPlan.get_observed_timeseries(str(data_file))
    assert len(frame) == 5
    flow = frame[frame.variable == "Flow"]
    assert flow.sample_index.tolist() == [0, 1, 2]
    assert flow.time.iloc[0] == pd.Timestamp("2020-01-02")
    assert flow.time.iloc[0] == flow.time.iloc[1]
    assert flow.time.iloc[2] == pd.Timestamp("2020-01-01 23:00:00")
    assert flow.value.dtype == np.dtype("<f4")
    assert np.signbit(flow.value.iloc[0]) and np.isnan(flow.value.iloc[1])
    assert len(frame.attrs["sites"]) == 2
    assert next(iter(frame.attrs["sites"].values()))["Data Units"] == b"cfs"
    selected = HdfResultsPlan.get_observed_timeseries(
        data_file, "Stage", "Ref Point: Gauge"
    )
    assert len(selected) == 2
    with pytest.raises(KeyError):
        HdfResultsPlan.get_observed_timeseries(data_file, site_name="unknown")
    with pytest.raises(ValueError):
        HdfResultsPlan.get_observed_timeseries(data_file, "Unknown")


def test_stored_points_and_blocks(data_file, mode):
    points = HdfBndry.get_initial_condition_points(hdf_path=data_file)
    assert points.point_id.tolist() == [0, 1]
    assert points.Name.tolist() == ["Initial", "Initial"]
    assert points["Cell Index"].tolist() == [0, 1]
    assert points.crs is None
    blocks = HdfXsec.get_blocked_obstructions(data_file)
    assert blocks.block_id.tolist() == [0, 1]
    assert blocks.xs_id.tolist() == [0, 1]
    assert "geometry" not in blocks and "Permanent" not in blocks
    assert blocks.Elevation.dtype == np.dtype("<f4")
    assert np.signbit(blocks.Elevation.iloc[0])


@pytest.mark.parametrize(
    "variable", ["Velocity Total", "Area including Ineffective Total"]
)
def test_steady_exact_variable_and_selectors(data_file, mode, variable):
    literal = "Additional Variables/" + variable
    result = HdfResultsPlan.get_steady_cross_section_results(data_file, literal)
    assert result.profile_index.tolist() == [0, 0, 1, 1]
    assert result.xs_id.tolist() == [0, 1, 0, 1]
    assert result.value.dtype == np.dtype("<f4")
    assert np.signbit(result.value.iloc[1])
    one = HdfResultsPlan.get_steady_cross_section_results(
        hdf_path=str(data_file), variable=literal, profile_name="P2"
    )
    assert_frame_equal(one, result.iloc[2:].reset_index(drop=True))
    with pytest.raises(ValueError):
        HdfResultsPlan.get_steady_cross_section_results(
            data_file, literal, profile_index=-1
        )
    with pytest.raises(ValueError):
        HdfResultsPlan.get_steady_cross_section_results(
            data_file, literal, profile_index=0, profile_name="P2"
        )
    with pytest.raises(ValueError):
        HdfResultsPlan.get_steady_cross_section_results(data_file, "../Flow")
    with pytest.raises(KeyError):
        HdfResultsPlan.get_steady_cross_section_results(data_file, "Missing")


def test_absent_optional_and_malformed_pairs(tmp_path, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "h5py")
    path = tmp_path / "empty.hdf"
    with h5py.File(path, "w"):
        pass
    assert HdfResultsPlan.get_observed_timeseries(path).empty
    assert HdfBndry.get_initial_condition_points(path).empty
    assert HdfXsec.get_blocked_obstructions(path).empty
    with h5py.File(path, "a") as h:
        h["Geometry/IC Points/Points"] = np.zeros((1, 2))
    with pytest.raises(ValueError):
        HdfBndry.get_initial_condition_points(path)
    with h5py.File(path, "a") as h:
        h["Geometry/Cross Sections/Obstruction Info"] = np.array([[0, 1]], dtype="i4")
    with pytest.raises(ValueError):
        HdfXsec.get_blocked_obstructions(path)


@pytest.mark.parametrize(
    "damage", ["date", "points", "cell", "range", "profile", "shape"]
)
def test_malformed_present_data(data_file, monkeypatch, damage):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "h5py")
    with h5py.File(data_file, "a") as h:
        if damage == "date":
            path = "Event Conditions/Observed Data/Flow/Ref Line: Gauge"
            data = h[path][()]
            data["Date"][0] = b"bad"
            h[path][...] = data
        elif damage == "points":
            del h["Geometry/IC Points/Points"]
            h["Geometry/IC Points/Points"] = np.zeros((1, 2))
        elif damage == "cell":
            ds = h["Geometry/IC Points/Attributes"]
            v = ds[()]
            v["Cell Index"][0] = 99
            ds[...] = v
        elif damage == "range":
            h["Geometry/Cross Sections/Obstruction Info"][0] = [0, 99]
        elif damage == "profile":
            path = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names"
            del h[path]
            h[path] = np.array([b"P1"], dtype="S16")
        else:
            path = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections/Additional Variables/Velocity Total"
            del h[path]
            h[path] = np.zeros((2, 3))
    with pytest.raises(ValueError):
        if damage == "date":
            HdfResultsPlan.get_observed_timeseries(data_file)
        elif damage in ["points", "cell"]:
            HdfBndry.get_initial_condition_points(data_file)
        elif damage == "range":
            HdfXsec.get_blocked_obstructions(data_file)
        else:
            HdfResultsPlan.get_steady_cross_section_results(
                data_file, "Additional Variables/Velocity Total"
            )


@pytest.mark.parametrize(
    "method", [HdfBndry.get_initial_condition_points, HdfXsec.get_blocked_obstructions]
)
def test_required_new_capability_or_explicit_refusal(data_file, monkeypatch, method):
    import ras_commander_fast_hdf as native

    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "h5py")
    expected = method(data_file)
    typed.clear_cache()
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "native")
    if not hasattr(native, "initial_condition_point_geometry"):
        with pytest.raises(fast_hdf.FastHdfError):
            method(data_file)
        return
    with typed.trace_reads() as trace:
        actual = method(data_file)
    assert_frame_equal(actual, expected)
    assert any(row["backend"] == "native-typed" for row in trace)
    assert not any(row["backend"] == "h5py-fallback" for row in trace)


def test_required_existing_observation_and_steady_routes(data_file, monkeypatch):
    for method, args in [
        (HdfResultsPlan.get_observed_timeseries, ()),
        (
            HdfResultsPlan.get_steady_cross_section_results,
            ("Additional Variables/Velocity Total",),
        ),
    ]:
        monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "h5py")
        expected = method(data_file, *args)
        monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "native")
        typed.clear_cache()
        with typed.trace_reads() as trace:
            actual = method(data_file, *args)
        assert_frame_equal(actual, expected)
        assert any(row["backend"] == "native-typed" for row in trace)
        assert not any(row["backend"] == "h5py-fallback" for row in trace)


def test_injected_native_failure_preserves_policy(data_file, monkeypatch):
    original = typed._engine

    def refuse(module, path, name, *args, **kwargs):
        if name == "initial_condition_point_geometry":
            raise RuntimeError("injected refusal")
        return original(module, path, name, *args, **kwargs)

    monkeypatch.setattr(typed, "_engine", refuse)
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    typed.clear_cache()
    assert len(HdfBndry.get_initial_condition_points(data_file)) == 2
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "native")
    typed.clear_cache()
    with pytest.raises(fast_hdf.FastHdfError):
        HdfBndry.get_initial_condition_points(data_file)


@pytest.mark.parametrize("clock", ["2400", "24:00", "24:00:00"])
def test_end_of_day_formats(clock):
    from ras_commander.hdf._stored_data import _observation_datetime

    assert _observation_datetime("01JAN2020 " + clock) == pd.Timestamp("2020-01-02")


def test_empty_dtypes(tmp_path, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "h5py")
    path = tmp_path / "empty.hdf"
    with h5py.File(path, "w"):
        pass
    frame = HdfXsec.get_blocked_obstructions(path)
    assert frame.xs_id.dtype == np.dtype("int64")
    assert frame.block_id.dtype == np.dtype("int64")
    assert frame["Left Sta"].dtype == np.dtype("float64")


@pytest.mark.parametrize(
    "damage", ["profile_type", "profile_rank", "name_type", "nan_point"]
)
def test_identity_and_coordinate_contract(data_file, damage, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "h5py")
    with h5py.File(data_file, "a") as h:
        if damage.startswith("profile"):
            path = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names"
            del h[path]
            h[path] = (
                np.array([1, 2])
                if damage == "profile_type"
                else np.array([[b"P1", b"P2"]], dtype="S2")
            )
        elif damage == "name_type":
            path = "Geometry/IC Points/Attributes"
            del h[path]
            h[path] = np.array(
                [(1, b"Area", 0), (2, b"Area", 1)],
                dtype=[("Name", "i4"), ("SA/2D", "S8"), ("Cell Index", "i4")],
            )
        else:
            h["Geometry/IC Points/Points"][0] = [np.nan, 1.0]
    with pytest.raises(ValueError):
        if damage.startswith("profile"):
            HdfResultsPlan.get_steady_cross_section_results(
                data_file, "Additional Variables/Velocity Total"
            )
        else:
            HdfBndry.get_initial_condition_points(data_file)


@pytest.mark.parametrize(
    "damage",
    [
        "ic_child_group",
        "centers_group",
        "xs_scalar",
        "xs_child_group",
        "xs_group_dataset",
    ],
)
def test_malformed_object_kinds(data_file, damage, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "h5py")
    with h5py.File(data_file, "a") as h:
        path = {
            "ic_child_group": "Geometry/IC Points/Points",
            "centers_group": "Geometry/2D Flow Areas/Area/Cells Center Coordinate",
            "xs_scalar": "Geometry/Cross Sections/Attributes",
            "xs_child_group": "Geometry/Cross Sections/Obstruction Blocks",
            "xs_group_dataset": "Geometry/Cross Sections",
        }[damage]
        del h[path]
        if damage in ["xs_scalar", "xs_group_dataset"]:
            h[path] = 1
        else:
            h.create_group(path)
    with pytest.raises(ValueError):
        if damage.startswith("ic") or damage == "centers_group":
            HdfBndry.get_initial_condition_points(data_file)
        else:
            HdfXsec.get_blocked_obstructions(data_file)


def test_present_empty_obstruction_fields(data_file, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "h5py")
    with h5py.File(data_file, "a") as h:
        group = h["Geometry/Cross Sections"]
        del group["Attributes"]
        group["Attributes"] = np.empty(
            0, dtype=[("River", "S8"), ("Reach", "S8"), ("RS", "S8")]
        )
        del group["Obstruction Info"]
        group["Obstruction Info"] = np.empty((0, 2), dtype="i4")
        del group["Obstruction Blocks"]
        group["Obstruction Blocks"] = np.empty(
            0,
            dtype=[
                ("Left Sta", "f4"),
                ("Right Sta", "f4"),
                ("Elevation", "f4"),
                ("Permanent", "u1"),
            ],
        )
    frame = HdfXsec.get_blocked_obstructions(data_file)
    assert frame.empty and frame.xs_id.dtype == np.dtype("int64")
    assert frame.Elevation.dtype == np.dtype("float32")
    assert frame.Permanent.dtype == np.dtype("uint8")


@pytest.mark.parametrize("selector", ["01", 1])
def test_project_context_resolution(data_file, selector, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "h5py")
    geom = data_file.with_suffix("")
    geom.touch()
    context = SimpleNamespace(
        check_initialized=lambda: None,
        plan_df=pd.DataFrame(
            {
                "plan_number": ["01"],
                "geometry_number": ["01"],
                "HDF_Results_Path": [str(data_file)],
            }
        ),
        geom_df=pd.DataFrame(
            {
                "geom_number": ["01"],
                "full_path": [str(geom)],
                "hdf_path": [str(data_file)],
            }
        ),
    )
    context.get_prj_entries = lambda component: context.geom_df
    assert (
        len(
            HdfResultsPlan.get_observed_timeseries(
                hdf_path=selector, ras_object=context
            )
        )
        == 5
    )
    assert (
        len(
            HdfResultsPlan.get_steady_cross_section_results(
                selector, "Additional Variables/Velocity Total", ras_object=context
            )
        )
        == 4
    )
    assert len(HdfBndry.get_initial_condition_points(selector, ras_object=context)) == 2
    assert (
        len(HdfXsec.get_blocked_obstructions(hdf_path=selector, ras_object=context))
        == 2
    )


def test_zero_profile_schema(data_file, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "h5py")
    base = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"
    with h5py.File(data_file, "a") as h:
        del h[base + "/Profile Names"]
        h[base + "/Profile Names"] = np.empty(0, dtype="S16")
        path = base + "/Cross Sections/Additional Variables/Velocity Total"
        del h[path]
        h[path] = np.empty((0, 2), dtype="f4")
    frame = HdfResultsPlan.get_steady_cross_section_results(
        data_file, "Additional Variables/Velocity Total"
    )
    assert frame.empty and frame.xs_id.dtype == np.dtype("int64")
    assert frame.profile_index.dtype == np.dtype("int64")
    assert frame.value.dtype == np.dtype("float32")
