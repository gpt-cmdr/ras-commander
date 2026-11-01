"""Generated-software fixtures only; no real model, solve or hydraulic claim."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from affine import Affine

from ras_commander.fim import FimEngineError, FimUnsupportedError
from ras_commander.fim import _depth_groups as groups
from ras_commander.fim._native_products import deliver, validate_controls


def test_product_controls_fail_explicitly_without_changing_defaults():
    assert validate_controls() == (["depth", "wse"], "LZW", False)
    assert validate_controls(["depth"], "NONE") == (["depth"], "NONE", True)
    for products in ([], ["depth", "depth"], ["unknown"]):
        with pytest.raises(ValueError):
            validate_controls(products)
    with pytest.raises(FimUnsupportedError):
        validate_controls(["depth"], writer="rasterio")
    with pytest.raises(FimUnsupportedError):
        validate_controls(["depth"], "NONE", method={"native_geotiff_outputs": True})
    validate_controls(
        ["depth"],
        "NONE",
        method={
            "native_output_products": ["depth"],
            "native_output_compression": ["NONE"],
        },
    )


def test_depth_only_delivery_verifies_compression_and_rejects_extra_files(tmp_path):
    import rasterio

    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    transform = Affine(1, 0, 0, 0, -1, 4)
    with rasterio.open(
        source / "depth.tif",
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="float32",
        nodata=np.nan,
        crs="EPSG:3857",
        transform=transform,
    ) as ds:
        ds.write(np.ones((4, 4), dtype="float32"), 1)
    plan = SimpleNamespace(
        shape=(4, 4),
        transform=transform,
        crs=rasterio.crs.CRS.from_epsg(3857),
        window=SimpleNamespace(col_off=0, row_off=0),
    )
    header = dict(
        products="native-geotiff/1",
        selected_products=["depth"],
        compression="NONE",
        depth_finite_pixels=16,
        flooded_pixels=16,
        write_seconds=0.1,
    )
    (source / "wse.tif").write_bytes(b"unexpected")
    with pytest.raises(FimEngineError, match="unrequested"):
        deliver(
            source, output, "p0", header, plan, products=["depth"], compression="NONE"
        )
    (source / "wse.tif").unlink()
    row = deliver(
        source, output, "p0", header, plan, products=["depth"], compression="NONE"
    )
    assert Path(row["depth_tif"]).is_file() and row["wse_tif"] is None


@pytest.mark.parametrize("times", [[], [0, 0], [True], [-1], ["Max"], [2**64]])
def test_group_validation_precedes_model_reads(times):
    with pytest.raises((TypeError, ValueError)):
        groups._normalise(
            [
                dict(
                    job_id="j",
                    hdf_path="absent",
                    terrain_path="absent",
                    groups=[dict(group_id="g", timesteps=times)],
                )
            ]
        )


@pytest.mark.parametrize(
    "options",
    [
        dict(max_workers=2),
        dict(strategy="parallel"),
        dict(max_inflight_profiles=2),
        dict(sink="grouped-buffer"),
        dict(products=["depth"]),
        dict(compression="DEFLATE"),
        dict(depth_cutoff_ft=float("nan")),
        dict(depth_cutoff_ft=True),
    ],
)
def test_group_controls_precede_model_reads(tmp_path, options):
    from ras_commander import RasFim

    with pytest.raises((ValueError, TypeError, FimUnsupportedError)):
        RasFim.map_depth_groups([], tmp_path / "out", **options)
    assert not (tmp_path / "out").exists()


def receipt():
    from rasterio.crs import CRS
    from rasterio.windows import Window

    plan = SimpleNamespace(
        shape=(2, 3),
        transform=Affine(1, 0, 0, 0, -1, 2),
        crs=CRS.from_epsg(3857),
        window=Window(0, 0, 3, 2),
    )
    job = dict(job_id="j", groups=[dict(group_id="g", timesteps=[3, 1])])
    group = dict(
        group_id="g",
        status="complete",
        source_indices=[3, 1],
        frames=[
            dict(
                source_index=i, status="complete", native_wet_count=6, retained_count=4
            )
            for i in [3, 1]
        ],
        shape=[2, 3],
        affine=list(plan.transform.to_gdal()),
        strict_extent=[0, 0, 3, 2],
        crs_wkt=plan.crs.to_wkt(),
        epsg=3857,
        lattice=dict(source_window=[0, 0, 3, 2]),
        units="feet",
        nodata="NaN",
        dtype="<f4",
        byte_length=24,
        retained_count=4,
        all_dry=False,
        output=dict(path="j/g.tif", compression="NONE"),
    )
    return (
        [job],
        {"j": plan},
        dict(
            schema="ras-commander-depth-groups-report/1",
            status="complete",
            jobs=[dict(job_id="j", groups=[group])],
        ),
    )


@pytest.mark.parametrize(
    "change",
    ["status", "missing", "repeat", "unrequested", "order", "group", "extent", "path"],
)
def test_receipt_validation_rejects_incomplete_or_unrequested_samples(change):
    jobs, plans, report = receipt()
    groups.validate_receipt(report, jobs, plans, "feet", "NONE")
    group = report["jobs"][0]["groups"][0]
    if change == "status":
        group["frames"][0]["status"] = "failed"
    elif change == "missing":
        group["frames"].pop()
    elif change == "repeat":
        group["frames"][1] = deepcopy(group["frames"][0])
    elif change == "unrequested":
        group["frames"][1]["source_index"] = 999
    elif change == "order":
        group["frames"].reverse()
    elif change == "group":
        group["group_id"] = "extra"
    elif change == "extent":
        group["affine"][0] = 999
    else:
        group["output"]["path"] = "../escape.tif"
    with pytest.raises(FimEngineError):
        groups.validate_receipt(report, jobs, plans, "feet", "NONE")


@pytest.fixture
def native_case(tmp_path, monkeypatch):
    """A single physical square and four ghost cells, passed to the real engine."""
    import os
    import geopandas as gpd
    import rasterio
    from shapely.geometry import box
    from ras_commander import HdfBase, RasFim
    from ras_commander.fim import _sloping
    from ras_commander.fim._catalog import _write_json

    engine = os.environ.get("RAS_COMMANDER_GROUP_TEST_ENGINE")
    if not engine:
        pytest.skip(
            "set RAS_COMMANDER_GROUP_TEST_ENGINE for generated engine integration"
        )
    terrain = tmp_path / "terrain.tif"
    with rasterio.open(
        terrain,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="float32",
        nodata=-9999,
        crs="EPSG:3857",
        transform=Affine(1, 0, 0, 0, -1, 4),
    ) as ds:
        ds.write(np.zeros((4, 4), dtype="float32"), 1)
    tables = dict(
        centers=([[2, 2], [-1, 2], [2, 5], [5, 2], [2, -1]], "<f8"),
        cell_info=([[0, 4], [4, 1], [5, 1], [6, 1], [7, 1]], "<i4"),
        cell_faces=(
            [[0, 1], [1, 1], [2, 1], [3, 1], [0, -1], [1, -1], [2, -1], [3, -1]],
            "<i4",
        ),
        cell_minimum=([0] * 5, "<f4"),
        face_vertices=([[0, 1], [1, 2], [2, 3], [3, 0]], "<i4"),
        face_cells=([[0, 1], [0, 2], [0, 3], [0, 4]], "<i4"),
        face_info=([[0, 0]] * 4, "<i4"),
        face_points=(np.empty((0, 2)), "<f8"),
        face_minimum=([0] * 4, "<f4"),
        vertices=([[0, 0], [0, 4], [4, 4], [4, 0]], "<f8"),
        vertex_info=([[0, 2], [2, 2], [4, 2], [6, 2]], "<i4"),
        vertex_faces=(
            [[3, 1], [0, 1], [0, 1], [1, 1], [1, 1], [2, 1], [2, 1], [3, 1]],
            "<i4",
        ),
    )
    descriptors = {}
    for key, (values, dtype) in tables.items():
        array = np.asarray(values, dtype=dtype)
        array.tofile(tmp_path / f"{key}.bin")
        descriptors[key] = dict(path=f"{key}.bin", rows=len(array))
    _write_json(
        tmp_path / "mesh.json",
        dict(schema="ras-commander-sloping-mesh/1", arrays=descriptors),
    )
    cells = gpd.GeoDataFrame(
        dict(mesh_name=["mesh"], cell_id=[0]),
        geometry=[box(0, 0, 4, 4)],
        crs="EPSG:3857",
    )
    for i, depth in enumerate([0.5, 2, 0]):
        np.array([depth, 0, 0, 0, 0], dtype="<f4").tofile(tmp_path / f"profile-{i}.bin")
    hdf = tmp_path / "source.hdf"
    hdf.write_bytes(b"source identity only")
    calls = []

    class Prepared:
        def __init__(self, profiles):
            self._hdf = hdf
            self._terrain = terrain
            self._cells = cells
            self._meshes = [dict(mesh_name="mesh", cell_count=5)]
            self._mesh_files = [str(tmp_path / "mesh.json")]
            self._terrain_identity = dict(epsg=3857, crs_identity=dict(kind="epsg"))
            self._terrain_transform = [0, 1, 0, 4, 0, -1]
            self._invalid_records = []
            self._invalid_policy = "repair"
            self._units = {
                name: dict(id=name, values_files=[str(tmp_path / f"profile-{i}.bin")])
                for name, i in profiles.items()
            }
            self.info = dict(
                planned_prepared_bytes=4096, staged_bytes=1024, invalid_cells={}
            )

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def _check_sources(self):
            pass

        def _validate_grid(self, plan):
            pass

    def prepare(*args, profiles, **kwargs):
        calls.append(dict(profiles))
        return Prepared(profiles)

    def stage(hdf, root, meshes, maximum, selected, **kwargs):
        result = []
        for name, index in selected.items():
            filename = f"{name}.bin"
            (root / filename).write_bytes(
                (tmp_path / f"profile-{index}.bin").read_bytes()
            )
            result.append(dict(id=name, values_files=[filename]))
        return result, 1, len(result) * 20

    monkeypatch.setattr(RasFim, "prepare_sloping_model", prepare)
    monkeypatch.setattr(
        HdfBase,
        "get_result_unit_metadata",
        lambda *a, **k: dict(depth_units="ft", status="resolved"),
    )
    monkeypatch.setattr(_sloping, "_stage_profiles", stage)
    jobs = [
        dict(
            job_id=name,
            reach_id=name,
            hdf_path=str(hdf),
            terrain_path=str(terrain),
            options={},
            timesteps=[0, 1, 2],
            key="same",
            sources={},
            groups=[
                dict(group_id="max", timesteps=[1, 0]),
                dict(group_id="dry", timesteps=[2]),
            ],
            aoi=dict(
                kind="polygon",
                wkb=box(x, 0, x + 2, 4).wkb_hex,
                crs="EPSG:3857",
                source="fixture",
            ),
        )
        for name, x in [("left", 0), ("right", 2)]
    ]
    output = tmp_path / "delivered"
    output.mkdir()
    control = tmp_path / "control"
    control.mkdir()
    controls = dict(
        max_profiles_per_batch=1,
        max_working_mib=256,
        max_prepared_mib=16,
        window_cache_mib=0,
        compression="NONE",
        max_accumulator_mib=0,
        max_scratch_bytes=1024,
        depth_cutoff_ft=0.5,
    )
    config = dict(
        controls=controls, cpus=[0], engine=dict(engine_path=engine), output=str(output)
    )
    return jobs, config, control, output, calls


def test_real_engine_cohort_reuses_parent_and_stages_waves(native_case):
    import rasterio

    jobs, config, control, output, calls = native_case
    report = groups._cohort(jobs, config, control, 0)
    assert len(calls) == 1 and len(calls[0]) == 1
    assert report["commander_preparation"]["wave_count"] == 3
    assert (
        report["geometry_preparations"] == 1 and report["hydraulic_preparations"] == 3
    )
    for name, start in [("left", 0), ("right", 2)]:
        with rasterio.open(output / name / "max.tif") as ds:
            assert ds.shape == (4, 2) and ds.transform.c == start
            np.testing.assert_array_equal(
                ds.read(1), np.full((4, 2), 2, dtype="float32")
            )
        with rasterio.open(output / name / "dry.tif") as ds:
            assert np.isnan(ds.read(1)).all()
    assert report["jobs"][0]["groups"][0]["source_indices"] == [1, 0]


def test_native_group_budget_refusal_preserves_required_and_allowed_bytes(native_case):
    jobs, config, control, output, _ = native_case
    config["controls"]["max_working_mib"] = 68
    with pytest.raises(FimEngineError, match="required.*bytes, allowed.*bytes"):
        groups._cohort(jobs, config, control, 0)
    assert not list(output.rglob("*.tif"))


@pytest.mark.parametrize("state", ["complete", "failed", "missing", "cancelled"])
def test_public_supervisor_preserves_order_partial_receipts_and_owned_cleanup(
    tmp_path, monkeypatch, state
):
    import threading
    import psutil
    from ras_commander import RasFim

    from ras_commander.fim.RasFim import _file_identity

    source = tmp_path / "source.hdf"
    source.write_bytes(b"immutable source identity")
    source_binding = {"hdf": {"path": str(source), "identity": _file_identity(source)}}
    normal = [
        dict(
            job_id=name,
            reach_id=name,
            sources=source_binding,
            groups=[dict(group_id="g", timesteps=[0])],
        )
        for name in ("b", "a")
    ]
    monkeypatch.setattr(groups, "_normalise", lambda jobs: deepcopy(normal))
    engine = dict(
        engine_path="unused",
        method=dict(
            sloping=dict(persistent_session=True),
            depth_groups=dict(
                request_schema="ras-commander-depth-groups-request/1",
                sinks=["grouped-geotiff"],
                compression=["NONE"],
                aoi_mask="global-terrain-lattice/1",
            ),
        ),
    )
    monkeypatch.setattr(RasFim, "get_engine_info", lambda path: engine)
    event = threading.Event()
    if state == "cancelled":
        event.set()
    actors = []

    class Actor:
        def __init__(self, args, **kwargs):
            config = json.loads(Path(args[-1]).read_text())
            self.pid = psutil.Process().pid
            self.returncode = None
            self.polls = 0
            actors.append(self)
            jobs = [
                dict(job_id=j["job_id"], groups=[dict(group_id="g", status="complete")])
                for j in reversed(normal)
            ]
            if state == "missing":
                jobs.pop()
            for job in normal:
                folder = Path(config["output"]) / job["job_id"]
                folder.mkdir()
                (folder / "g.tif").write_bytes(b"owned test output")
            groups._write_json(
                Path(config["control"]) / "result.json",
                dict(
                    status="complete" if state != "failed" else "aborted",
                    cohorts=[dict(jobs=jobs)],
                    error="injected worker failure",
                ),
            )

        def poll(self):
            self.polls += 1
            if self.polls > 1:
                self.returncode = 0
            return self.returncode

    monkeypatch.setattr(groups.subprocess, "Popen", Actor)

    def terminate(actor):
        actor.returncode = -9

    monkeypatch.setattr(groups, "_terminate", terminate)
    receipt = RasFim.map_depth_groups(
        [],
        tmp_path / "output",
        scratch_folder=tmp_path,
        threads=1,
        max_working_mib=64,
        max_prepared_mib=64,
        max_memory_mib=8192,
        cancel_event=event,
        raise_on_failure=False,
    )
    assert receipt["status"] == ("complete" if state == "complete" else "aborted")
    saved = json.loads((tmp_path / "output/depth_groups_receipt.json").read_text())
    assert saved["status"] == receipt["status"]
    expected_sources = json.loads(
        json.dumps({job["job_id"]: source_binding for job in normal})
    )
    assert saved["sources"] == expected_sources
    if state == "complete":
        assert list(receipt["by_job"]) == ["b", "a"]
        assert [j["job_id"] for j in receipt["jobs"]] == ["b", "a"]
    else:
        assert not list((tmp_path / "output").rglob("*.tif"))
        assert all(
            g["status"] == "failed" for j in receipt["jobs"] for g in j["groups"]
        )
