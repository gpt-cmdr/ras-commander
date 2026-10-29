"""Opt-in real-model prepared sloping lifecycle and exact-pixel checks."""

import json
import os
from pathlib import Path
import shutil

import numpy as np
import pytest


@pytest.fixture
def case():
    filename = os.environ.get("RAS_COMMANDER_SLOPING_CASE")
    if not filename:
        pytest.skip("set RAS_COMMANDER_SLOPING_CASE to a computed 2D model")
    return json.loads(Path(filename).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "options",
    [
        {"threads": 0},
        {"threads": 65},
        {"max_working_mib": False},
        {"max_prepared_mib": -1},
        {"profiles": {}},
        {"profiles": {"a": -1}},
        {"profiles": {"a": 1, "A": 2}},
        {"render_mode": "horizontal"},
        {"use_depth_weighted_faces": True},
    ],
)
def test_invalid_preparation_controls_fail_before_reading_inputs(tmp_path, options):
    from ras_commander import RasFim

    with pytest.raises(ValueError):
        RasFim.prepare_sloping_model(
            tmp_path / "absent.hdf", tmp_path / "absent.tif", **options
        )


def equal_products(left, right):
    import rasterio

    assert list(left.profile) == list(right.profile)
    for a, b in zip(left.itertuples(), right.itertuples(), strict=True):
        assert a.depth_finite_pixels == b.depth_finite_pixels
        assert a.flooded_pixels == b.flooded_pixels
        for band in ("depth_tif", "wse_tif"):
            with rasterio.open(getattr(a, band)) as actual, rasterio.open(
                getattr(b, band)
            ) as expected:
                assert actual.shape == expected.shape
                assert (
                    actual.transform == expected.transform
                    and actual.crs == expected.crs
                )
                x, y = actual.read(1, masked=True), expected.read(1, masked=True)
                np.testing.assert_array_equal(
                    np.ma.getmaskarray(x), np.ma.getmaskarray(y)
                )
                valid = ~np.ma.getmaskarray(x)
                np.testing.assert_array_equal(
                    x.data[valid].view("u4"), y.data[valid].view("u4")
                )


def test_new_caches_revisit_windows_and_invalidate_modified_wse(case, tmp_path):
    """Old/new and stream/native comparisons, including a return to an earlier AOI."""
    from shapely.geometry import Polygon
    from ras_commander import RasFim

    engine = os.environ.get("RAS_COMMANDER_RETAINED_FIM_ENGINE")
    if not engine:
        pytest.skip("set RAS_COMMANDER_RETAINED_FIM_ENGINE to the throughput candidate")
    profiles = dict(case["profiles"])
    with RasFim.prepare_sloping_model(
        case["hdf"], case["terrain"], engine_path=engine, profiles=profiles,
        threads=4, max_working_mib=4096, window_cache_mib=256, hydraulic_cache_mib=256,
    ) as model:
        if not model._method.get("native_geotiff_outputs"):
            pytest.skip("candidate lacks native GeoTIFF outputs")
        bounds = model._cells.total_bounds
        x0,y0,x1,y1 = bounds
        triangle = Polygon([(x0,y0),(x1,y0),((x0+x1)/2,y1)])
        selections = [dict(bbox=list(bounds)),dict(polygon=triangle, aoi_crs=model._cells.crs),dict(bbox=list(bounds))]
        for i, selection in enumerate(selections):
            actual = model.map_profiles(tmp_path / f"cached-{i}", product_writer="native", **selection)
            expected = RasFim.map_sloping_profiles(
                case["hdf"], case["terrain"], tmp_path / f"reference-{i}",
                engine_path=case["engine"], profiles=profiles, threads=4,
                max_working_mib=4096, **selection,
            )
            equal_products(actual, expected)
            report = actual.attrs["performance"]["engine_report"]
            if i:
                assert all(p["hydraulic_reused"] for p in report["profiles"])
            if i == 2:
                assert report["session"]["window_reused"]
                assert actual.attrs["performance"]["preparation"]["cell_validation_reused"]
            assert report["session"]["retained_window_bytes"] <= 256 << 20
            assert report["session"]["retained_hydraulic_bytes"] <= 256 << 20
        # Staged vectors are immutable by contract, but the native identity key
        # must also reject stale cache hits when a direct caller changes a vector.
        file = Path(model._units[next(iter(profiles))]["values_files"][0])
        data = np.fromfile(file, dtype="<f4")
        data += np.float32(1)
        data.tofile(file)
        result = model.map_profiles(tmp_path / "changed-values", profiles=[next(iter(profiles))], bbox=list(bounds))
        assert not result.attrs["performance"]["engine_report"]["profiles"][0]["hydraulic_reused"]


def test_later_native_writer_failure_cleans_delivery_and_context_recovers(case, tmp_path):
    from ras_commander import RasFim, FimEngineError

    engine = os.environ.get("RAS_COMMANDER_RETAINED_FIM_ENGINE")
    if not engine:
        pytest.skip("set RAS_COMMANDER_RETAINED_FIM_ENGINE to the throughput candidate")
    names = list(case["profiles"])
    if len(names) < 2 or len(set(case["profiles"].values())) < 2:
        pytest.skip("requires two distinct saved profiles")
    names = names[:2]
    with RasFim.prepare_sloping_model(case["hdf"], case["terrain"],
            profiles={name: case["profiles"][name] for name in names},
            engine_path=engine, threads=4, max_working_mib=4096) as model:
        values = Path(model._units[names[1]]["values_files"][0])
        data = np.fromfile(values, dtype="<f4")
        data[0] = np.float32(np.nan)
        data.tofile(values)  # Corrupt only this context's owned temporary staging.
        failed = tmp_path / "failed"
        with pytest.raises(FimEngineError):
            model.map_profiles(failed, product_writer="native")
        assert not list(failed.rglob("*.tif"))
        assert not model.closed
        assert model._native_session is None
        recovered = model.map_profiles(tmp_path / "recovered", profiles=[names[0]], product_writer="native")
        reference = RasFim.map_sloping_profiles(case["hdf"], case["terrain"], tmp_path / "reference",
            profiles={names[0]:case["profiles"][names[0]]}, engine_path=case["engine"], threads=4, max_working_mib=4096)
        equal_products(recovered, reference)


@pytest.mark.parametrize("enhanced", [False, True])
def test_repeated_aois_reuse_inputs_and_preserve_bits(
    case, enhanced, tmp_path, monkeypatch
):
    from shapely.geometry import Polygon
    from ras_commander import HdfMesh, RasFim, FimPreparedSlopingModel
    from ras_commander.fim import _sloping

    options = {}
    if enhanced:
        filename = os.environ.get("RAS_COMMANDER_SLOPING_OPTIONS_CASES")
        if not filename:
            pytest.skip("set RAS_COMMANDER_SLOPING_OPTIONS_CASES for enhanced geometry")
        cases = json.loads(Path(filename).read_text(encoding="utf-8"))
        case = next(
            c
            for c in cases
            if c["reduce_shallow_to_horizontal"]
            and c["use_depth_weighted_faces"]
            and any(isinstance(v, int) for v in c["profiles"].values())
        )
        options = dict(
            render_mode="slopingPretty",
            reduce_shallow_to_horizontal=True,
            use_depth_weighted_faces=True,
        )
    selected = dict(case["profiles"])
    name, selector = next(iter(selected.items()))
    selected["alias"] = selector
    common = dict(
        profiles=selected,
        engine_path=case["engine"],
        threads=4,
        max_working_mib=4096,
        **options,
    )
    counts = dict(polygons=0, mesh=0)
    original_polygons, original_mesh = (
        HdfMesh.get_mesh_cell_polygons,
        _sloping.write_binary_mesh_inputs,
    )

    def polygons(*args, **kwargs):
        counts["polygons"] += 1
        return original_polygons(*args, **kwargs)

    def mesh(*args, **kwargs):
        counts["mesh"] += 1
        return original_mesh(*args, **kwargs)

    monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", polygons)
    monkeypatch.setattr(_sloping, "write_binary_mesh_inputs", mesh)
    with RasFim.prepare_sloping_model(
        case["hdf"], case["terrain"], **common
    ) as prepared:
        assert isinstance(prepared, FimPreparedSlopingModel)
        root = Path(prepared._temporary.name)
        assert counts == dict(polygons=1, mesh=1)
        assert (
            prepared._units[name]["values_files"]
            == prepared._units["alias"]["values_files"]
        )
        assert prepared.info["unique_selectors"] == len(set(selected.values()))
        assert (
            prepared.info["planned_prepared_bytes"]
            <= prepared.info["max_prepared_bytes"]
        )
        metadata = prepared.info
        metadata["profiles"].clear()
        assert prepared.info["profiles"] == selected
        bounds = prepared._cells.total_bounds
        x, y = (bounds[:2] + bounds[2:]) / 2
        dx, dy = (bounds[2:] - bounds[:2]) / 4
        bbox = [x - dx, y - dy, x + dx, y + dy]
        polygon = Polygon([(x - dx, y - dy), (x + dx, y - dy), (x, y + dy)])
        results = []
        for index, aoi in enumerate(
            [dict(bbox=bbox), dict(polygon=polygon, aoi_crs=prepared._cells.crs)]
        ):
            result = prepared.map_profiles(
                tmp_path / f"prepared-{index}",
                profiles=["alias", name],
                max_inflight_profiles=2,
                **aoi,
            )
            results.append((result, aoi))
            assert result.attrs["performance"]["profile_views_prepared"] == 0
            assert result.attrs["performance"]["prepared_context"]["native_state_reused"] == bool(
                result.attrs["performance"]["engine_report"].get("session", {}).get("geometry_reused")
            )
        assert counts == dict(polygons=1, mesh=1)
        for index, (result, aoi) in enumerate(results):
            reference = RasFim.map_sloping_profiles(
                case["hdf"],
                case["terrain"],
                tmp_path / f"reference-{index}",
                **{**common, "profiles": {"alias": selector, name: selector}},
                max_inflight_profiles=2,
                **aoi,
            )
            equal_products(result, reference)
    assert prepared.closed and not root.exists()
    prepared.close()
    with pytest.raises(RuntimeError, match="closed"):
        prepared.map_profiles(tmp_path / "closed")


@pytest.mark.parametrize("source", ["hdf", "terrain", "engine"])
def test_changed_source_closes_before_delivery(case, tmp_path, source):
    from ras_commander import RasFim
    from ras_commander.fim import FimEngineError

    paths = {key: case[key] for key in ("hdf", "terrain", "engine")}
    copied = tmp_path / Path(paths[source]).name
    shutil.copy2(paths[source], copied)
    paths[source] = copied
    with RasFim.prepare_sloping_model(
        paths["hdf"], paths["terrain"], engine_path=paths["engine"]
    ) as prepared:
        root = Path(prepared._temporary.name)
        stat = copied.stat()
        os.utime(copied, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
        with pytest.raises(FimEngineError, match="sources changed"):
            prepared.map_profiles(tmp_path / "never-written")
        assert prepared.closed and not root.exists()
        assert not (tmp_path / "never-written").exists()


def test_source_change_during_delivery_aborts_products(case, tmp_path, monkeypatch):
    from ras_commander import RasFim
    from ras_commander.fim import FimEngineError

    copied = tmp_path / Path(case["hdf"]).name
    shutil.copy2(case["hdf"], copied)
    original = RasFim._write_products

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        stat = copied.stat()
        os.utime(copied, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
        return result

    with RasFim.prepare_sloping_model(
        copied, case["terrain"], engine_path=case["engine"]
    ) as prepared:
        monkeypatch.setattr(RasFim, "_write_products", changed)
        with pytest.raises(FimEngineError, match="sources changed"):
            prepared.map_profiles(tmp_path / "aborted")
        assert prepared.closed
    assert not list((tmp_path / "aborted").glob("*.tif"))
    receipt = json.loads(
        (tmp_path / "aborted/fim_manifest.json").read_text(encoding="utf-8")
    )
    assert receipt["status"] == "aborted"


def test_invalid_request_does_not_destroy_prepared_inputs(case, tmp_path):
    from ras_commander import RasFim

    with RasFim.prepare_sloping_model(
        case["hdf"], case["terrain"], engine_path=case["engine"]
    ) as prepared:
        for profiles in ([], ["Max", "Max"], ["unknown"], {"Max": "Max"}):
            with pytest.raises((ValueError, TypeError)):
                prepared.map_profiles(tmp_path / "invalid", profiles=profiles)
        with pytest.raises(ValueError):
            prepared.map_profiles(tmp_path / "invalid", bbox=[2, 3, 1, 4])
        assert not prepared.closed
        result = prepared.map_profiles(tmp_path / "valid")
        assert list(result.status) == ["complete"]


def test_delivery_failure_preserves_context_for_retry(case, tmp_path, monkeypatch):
    from ras_commander import RasFim

    original = RasFim._write_products

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("injected delivery failure")

    with RasFim.prepare_sloping_model(
        case["hdf"], case["terrain"], engine_path=case["engine"]
    ) as prepared:
        monkeypatch.setattr(RasFim, "_write_products", fail)
        with pytest.raises(OSError, match="injected"):
            prepared.map_profiles(tmp_path / "failed-write")
        assert not prepared.closed
        assert not list((tmp_path / "failed-write").glob("*.tif"))
        monkeypatch.setattr(RasFim, "_write_products", original)
        result = prepared.map_profiles(tmp_path / "retry")
        assert list(result.status) == ["complete"]


def test_source_geometry_change_invalidates_dimension_guard(case, tmp_path):
    from ras_commander import RasFim
    from ras_commander.fim import FimEngineError

    scope = RasFim.validate_2d_model(case["hdf"])
    if not scope.get("geometry_path"):
        pytest.skip("case has no resolved source geometry")
    hdf = tmp_path / Path(case["hdf"]).name
    geometry = tmp_path / Path(scope["geometry_path"]).name
    shutil.copy2(case["hdf"], hdf)
    shutil.copy2(scope["geometry_path"], geometry)
    with RasFim.prepare_sloping_model(
        hdf, case["terrain"], engine_path=case["engine"]
    ) as prepared:
        assert "geometry" in prepared._watched
        with geometry.open("a", encoding="utf-8") as stream:
            stream.write("\nRiver Reach=NewRiver,NewReach\n")
        with pytest.raises(FimEngineError, match="sources changed"):
            prepared.map_profiles(tmp_path / "never-written")
        assert prepared.closed


def test_calls_and_close_are_serialized(case, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from ras_commander import RasFim
    from ras_commander.fim import _sloping

    entered, release, closing = threading.Event(), threading.Event(), threading.Event()
    original = _sloping.map_profiles
    prepared = RasFim.prepare_sloping_model(
        case["hdf"], case["terrain"], engine_path=case["engine"]
    )
    root = Path(prepared._temporary.name)

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        assert root.exists()
        return original(*args, **kwargs)

    def close():
        closing.set()
        prepared.close()

    monkeypatch.setattr(_sloping, "map_profiles", blocked)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            mapping = pool.submit(prepared.map_profiles, tmp_path / "serialized")
            assert entered.wait(10)
            cleanup = pool.submit(close)
            assert closing.wait(10)
            assert not cleanup.done() and root.exists()
            release.set()
            assert list(mapping.result(timeout=30).status) == ["complete"]
            cleanup.result(timeout=30)
    finally:
        release.set()
        prepared.close()
    assert prepared.closed and not root.exists()


@pytest.mark.parametrize("add_1d", [False, True])
def test_new_source_geometry_requires_repreparation(case, tmp_path, add_1d):
    from ras_commander import RasFim
    from ras_commander.fim import FimError

    scope = RasFim.validate_2d_model(case["hdf"])
    if not scope.get("geometry_path"):
        pytest.skip("case has no resolved source geometry")
    hdf = tmp_path / Path(case["hdf"]).name
    geometry = tmp_path / Path(scope["geometry_path"]).name
    shutil.copy2(case["hdf"], hdf)
    with RasFim.prepare_sloping_model(
        hdf, case["terrain"], engine_path=case["engine"]
    ) as prepared:
        assert "geometry" not in prepared._watched
        shutil.copy2(scope["geometry_path"], geometry)
        if add_1d:
            with geometry.open("a", encoding="utf-8") as stream:
                stream.write("\nRiver Reach=NewRiver,NewReach\n")
        with pytest.raises(FimError):
            prepared.map_profiles(tmp_path / "never-written")
        assert prepared.closed and not (tmp_path / "never-written").exists()


@pytest.mark.parametrize("failure", ["budget", "staging-budget", "timestep"])
def test_failed_preparation_removes_staged_files(case, tmp_path, monkeypatch, failure):
    from ras_commander import RasFim
    from ras_commander.fim import _sloping_context
    from ras_commander.fim import _sloping

    original = _sloping_context.tempfile.TemporaryDirectory
    created = []

    def temporary(*args, **kwargs):
        result = original(*args, **kwargs, dir=tmp_path)
        created.append(Path(result.name))
        return result

    monkeypatch.setattr(_sloping_context.tempfile, "TemporaryDirectory", temporary)
    if failure == "staging-budget":
        original_mesh = _sloping.write_binary_mesh_inputs

        def constrained(*args, **kwargs):
            return original_mesh(*args, **{**kwargs, "max_staged_bytes": 1})

        monkeypatch.setattr(_sloping, "write_binary_mesh_inputs", constrained)
    options = (
        {"profiles": {"bad": 2**60}}
        if failure == "timestep"
        else {"max_prepared_mib": 1} if failure == "budget" else {}
    )
    with pytest.raises((ValueError, IndexError, RuntimeError)):
        RasFim.prepare_sloping_model(
            case["hdf"], case["terrain"], engine_path=case["engine"], **options
        )
    assert all(not path.exists() for path in created)
