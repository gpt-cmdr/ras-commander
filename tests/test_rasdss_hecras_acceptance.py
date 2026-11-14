"""HEC-RAS acceptance of DSS files written by RasDss on the java and native backends.

HEC-RAS runs only through ``RasCmdr.compute_plan(dest_folder=...)`` on copies of
RasExamples projects. Results are read back through ``Hdf*`` APIs.

1. Gridded precipitation: BaldEagleCrkMulti2D plan 06, a one-hour burst built like an
   AORC frame (WGS84 source, reprojected to SHG), hour-ending stamps, D = period start,
   E = period end, crossing midnight so E is spelled ``2400``.
2. Boundary time series: Dam Breaching plan 04, seven DSS inflows rewritten by each
   backend, with a scaled control that proves HEC-RAS reads the rewritten file.
3. Reads under native: the example plans' DSS boundaries resolve with Java blocked.

Tests 1 and 2 skip without the selected HEC-RAS version, its cached example archive, an
accepted TCU, or the backend under test. Nothing is downloaded. Test 3 needs no HEC-RAS.

``RAS_DSS_ACCEPTANCE_VERSION`` selects the version (default: first usable of 7.0, 6.6).
``RAS_DSS_ACCEPTANCE_EVIDENCE`` names a folder for a JSON record of each run.
"""

from __future__ import annotations

import json
import os
import pickle
import shutil
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import (
    RasCmdr,
    RasDss,
    RasExamples,
    RasPlan,
    RasTcu,
    RasUnsteady,
    get_ras_exe,
    init_ras_project,
)
from ras_commander.dss import _backend
from ras_commander.dss._hec_monolith import HecMonolithDownloader
from ras_commander.hdf import HdfMesh, HdfPlan, HdfResultsMesh, HdfResultsPlan, HdfResultsXsec

JAVA_WORKER = Path(__file__).with_name("_rasdss_native_writes_java_worker.py")
NATIVE_WORKER = Path(__file__).with_name("_rasdss_native_boundary_worker.py")

GRID_PROJECT, GRID_PLAN, GRID_UNSTEADY = "BaldEagleCrkMulti2D", "06", "03"
BOUNDARY_PROJECT, BOUNDARY_PLAN = "Dam Breaching", "04"

EVENT_START = pd.Timestamp("2018-09-09 21:00")
EVENT_END = pd.Timestamp("2018-09-10 04:00")
HOUR = pd.Timedelta(hours=1)
#: AORC-style hour-ending stamps. The stamp T covers (T - 1h, T].
LABELS = pd.date_range("2018-09-09 22:00", periods=6, freq="1h")
#: Period 09SEP2018:2300 to 09SEP2018:2400.
WET_LABEL = pd.Timestamp("2018-09-10 00:00")
SHIFTED_WET_LABEL = WET_LABEL + HOUR
ZERO_LENGTH_MIDDAY_WET_LABEL = pd.Timestamp("2018-09-09 23:00")

#: Source depths: west of the split, east of the split.
WEST_MM, EAST_MM = 25.4, 50.8
MM_PER_INCH = 25.4
AORC_RESOLUTION_DEG = 1.0 / 120.0
SHG_CELL_M = 2000.0
#: Mesh cells this far from the depth split lie wholly inside one zone of the 2 km grid.
ZONE_MARGIN_M = 6000.0
GRID_PATHNAME = "/SHG/BURST/PRECIP///AORC/"
CUMULATIVE = "Cell Cumulative Precipitation Depth"
SOLVER_CORES = 2
JAVA_MISSING = -3.4028234663852886e38
#: Largest depth difference (ft) accepted between runs with identical forcing. Two runs of
#: one file on HEC-RAS 6.6 differed in 36 of 1.5 million values, by at most 3e-8 ft; pairs of
#: different files differed by at most 2.4e-7 ft. HEC-RAS 7.0 runs were exactly equal.
DEPTH_NOISE_FT = 1e-6


def _plan_hdf(folder: Path, project_name: str, plan: str) -> Path:
    return folder / f"{project_name}.p{plan}.hdf"


def _usable_version(version: str) -> Optional[str]:
    """Return why ``version`` cannot run, or None. Never downloads anything."""
    exe = Path(str(get_ras_exe(version)))
    if not exe.is_file():
        return f"HEC-RAS {version} is not installed"
    archive = RasExamples.examples_dir / f"Example_Projects_{version.replace('.', '_')}.zip"
    if not archive.is_file():
        return f"example archive for {version} is not cached"
    return None


def _select_version() -> str:
    requested = os.environ.get("RAS_DSS_ACCEPTANCE_VERSION")
    candidates = [requested] if requested else ["7.0", "6.6"]
    reasons = []
    for version in candidates:
        reason = _usable_version(version)
        if reason is None:
            return version
        reasons.append(reason)
    pytest.skip("; ".join(reasons))


def _extract(version: str, project: str, output: Path) -> Path:
    previous = RasExamples._zip_file_path, RasExamples._folder_df
    try:
        RasExamples.get_example_projects(version)
        return Path(RasExamples.extract_project(project, output_path=output))
    finally:
        RasExamples._zip_file_path, RasExamples._folder_df = previous


def _require_tcu(ras) -> None:
    status = RasTcu.status(ras_object=ras)
    if not status.accepted:
        pytest.skip(
            f"HEC-RAS {status.version} TCU is not accepted ({status.reason}). Acceptance "
            "changes the registry, so this test leaves it to the qualification operator."
        )


def _record(name: str, payload: Dict[str, Any]) -> None:
    folder = os.environ.get("RAS_DSS_ACCEPTANCE_EVIDENCE")
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, indent=1, default=str)
        (Path(folder) / f"{name}.json").write_text(text, encoding="utf-8")


@contextmanager
def _native_backend():
    """Native backend whatever RAS_COMMANDER_DSS_BACKEND says, restored afterwards."""
    previous_env = os.environ.pop(_backend.ENV_VAR, None)
    previous_attr = RasDss.backend
    RasDss.backend = "native"
    try:
        yield
    finally:
        RasDss.backend = previous_attr
        if previous_env is not None:
            os.environ[_backend.ENV_VAR] = previous_env


def _require_backend(backend: str) -> None:
    if backend == "native":
        if not _backend.native_writes_available():
            pytest.skip("ras-commander-fast-dss with writers is not installed")
    elif not HecMonolithDownloader().is_installed():
        pytest.skip("HEC Monolith is not cached; the Java path would download it")


def _java(work: Path, requests: List[Dict[str, Any]]) -> List[Any]:
    """Run RasDss requests on the Java backend in a separate process."""
    work.mkdir(parents=True, exist_ok=True)
    req_path, out_path = work / "java_requests.pkl", work / "java_results.pkl"
    with open(req_path, "wb") as fh:
        pickle.dump(requests, fh)
    proc = subprocess.run(
        [sys.executable, str(JAVA_WORKER), str(req_path), str(out_path)],
        capture_output=True,
        text=True,
        timeout=1800,
        env={k: v for k, v in os.environ.items() if k != _backend.ENV_VAR},
    )
    if proc.returncode == 77 or "R1_BRIDGE_UNAVAILABLE" in proc.stdout:
        pytest.skip("Java bridge unavailable: " + proc.stdout.strip()[-300:])
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    with open(out_path, "rb") as fh:
        results = pickle.load(fh)
    errors = [item["error"] for item in results if "error" in item]
    assert not errors, errors
    return [item["result"] for item in results]


def _write(work: Path, backend: str, requests: List[Dict[str, Any]]) -> List[Any]:
    """Run write requests in order on ``backend``; returns each request's result."""
    if backend == "java":
        return _java(work, requests)
    with _native_backend():
        return [getattr(RasDss, req["op"])(**req["kwargs"]) for req in requests]


def _aorc_burst_frame(mesh_areas):
    """A WGS84 hourly depth field, reprojected to SHG like an AORC import.

    Returns the south-up SHG frame, its origin, and the longitude of the depth split.
    """
    warp = pytest.importorskip("rasterio.warp")
    transform = pytest.importorskip("rasterio.transform")

    west, south, east, north = (float(v) for v in mesh_areas.to_crs(4326).total_bounds)
    res = AORC_RESOLUTION_DEG
    lon0 = np.floor((west - 0.1) / res) * res
    lat1 = np.ceil((north + 0.1) / res) * res
    columns = int(np.ceil((east + 0.1 - lon0) / res))
    rows = int(np.ceil((lat1 - (south - 0.1)) / res))
    longitudes = lon0 + (np.arange(columns) + 0.5) * res
    split_lon = (west + east) / 2.0
    source = np.where(longitudes < split_lon, WEST_MM, EAST_MM).astype(np.float32)
    source = np.repeat(source[None, :], rows, axis=0)

    left, bottom, right, top = (float(v) for v in mesh_areas.to_crs(5070).total_bounds)
    x0 = np.floor((left - 4000.0) / SHG_CELL_M) * SHG_CELL_M
    y0 = np.floor((bottom - 4000.0) / SHG_CELL_M) * SHG_CELL_M
    nx = int(np.ceil((right + 4000.0 - x0) / SHG_CELL_M))
    ny = int(np.ceil((top + 4000.0 - y0) / SHG_CELL_M))
    north_up = np.zeros((ny, nx), dtype=np.float32)
    warp.reproject(
        source,
        north_up,
        src_transform=transform.from_origin(lon0, lat1, res, res),
        src_crs="EPSG:4326",
        dst_transform=transform.from_origin(x0, y0 + ny * SHG_CELL_M, SHG_CELL_M, SHG_CELL_M),
        dst_crs="EPSG:5070",
        resampling=warp.Resampling.nearest,
    )
    assert set(np.unique(north_up)) == {np.float32(WEST_MM), np.float32(EAST_MM)}
    return north_up[::-1].copy(), (float(x0), float(y0)), split_lon


@dataclass
class GridRun:
    label: str
    success: bool
    pathnames: List[str]
    messages: str
    forcing_times: List[pd.Timestamp] = field(default_factory=list)
    forcing_values: Optional[np.ndarray] = None
    forcing_attrs: Dict[str, Any] = field(default_factory=dict)
    times: Optional[pd.DatetimeIndex] = None
    cumulative: Optional[np.ndarray] = None
    depth: Optional[np.ndarray] = None


class GridBench:
    """One staged project; each scenario computes into its own dest_folder, once."""

    def __init__(self, root: Path, version: str):
        self.root, self.version = root, version
        self.project = _extract(version, GRID_PROJECT, root / "src")
        self.ras = init_ras_project(
            self.project, version, load_results_summary=False, hide_intro=True
        )
        _require_tcu(self.ras)
        (self.project / "Precipitation" / "precip.2018.09.dss").unlink()
        name = self.ras.project_name
        self.name = name
        geometry = str(
            self.ras.plan_df.set_index("plan_number").loc[GRID_PLAN, "geometry_number"]
        ).zfill(2)
        geometry_hdf = self.project / f"{name}.g{geometry}.hdf"
        mesh_areas = HdfMesh.get_mesh_areas(geometry_hdf)
        self.frame, self.origin, split_lon = _aorc_burst_frame(mesh_areas)
        cell_points = HdfMesh.get_mesh_cell_points(geometry_hdf).set_index("cell_id")
        west_of_split = cell_points.geometry.to_crs(4326).x.to_numpy() < split_lon
        # Distance to the split, measured in the source CRS's own terms: metres east.
        metres_per_degree = 111_320.0 * np.cos(
            np.radians(cell_points.geometry.to_crs(4326).y.to_numpy())
        )
        self.split_distance = (
            np.abs(cell_points.geometry.to_crs(4326).x.to_numpy() - split_lon)
            * metres_per_degree
        )
        self.west_of_split = west_of_split
        RasPlan.update_simulation_date(
            GRID_PLAN, EVENT_START.to_pydatetime(), EVENT_END.to_pydatetime(), ras_object=self.ras
        )
        RasPlan.update_plan_intervals(
            GRID_PLAN,
            output_interval="5MIN",
            instantaneous_interval="1HOUR",
            mapping_interval="5MIN",
            ras_object=self.ras,
        )
        self._runs: Dict[str, GridRun] = {}

    def frames(self, wet_label: pd.Timestamp) -> np.ndarray:
        stack = np.zeros((len(LABELS),) + self.frame.shape, dtype=np.float32)
        stack[list(LABELS).index(wet_label)] = self.frame
        return stack

    def grid_info(self) -> Dict[str, Any]:
        return {
            "cellsize": SHG_CELL_M,
            "origin": self.origin,
            "crs": "SHG",
            "units": "mm",
            "data_type": "PER-CUM",
            "interval_minutes": 60,
        }

    def _requests(self, dss_file, wet_label, dss_version, zero_length) -> List[Dict[str, Any]]:
        stack = self.frames(wet_label)
        common = dict(
            dss_file=str(dss_file),
            pathname=GRID_PATHNAME,
            grid_info=self.grid_info(),
            dss_version=dss_version,
        )
        if not zero_length:
            return [dict(op="write_grid_timeseries",
                         kwargs=dict(common, data=stack, times=LABELS))]
        # n + 1 boundaries with equal ends: D and E name the same instant.
        return [
            dict(op="write_grid_timeseries",
                 kwargs=dict(common, data=stack[index:index + 1], times=[label, label]))
            for index, label in enumerate(LABELS)
        ]

    def run(self, label, backend, *, wet_label=WET_LABEL, dss_version=7,
            zero_length=False) -> GridRun:
        if label in self._runs:
            return self._runs[label]
        _require_backend(backend)
        dss_file = self.project / "Precipitation" / f"{label}.dss"
        requests = self._requests(dss_file, wet_label, dss_version, zero_length)
        results = _write(self.root / "java" / label, backend, requests)
        pathnames = [path for result in results for path in result]
        RasUnsteady.configure_gridded_dss_precipitation(
            GRID_UNSTEADY,
            f"Precipitation/{dss_file.name}",
            pathnames[0],
            historic=True,
            ras_object=self.ras,
        )
        dest = self.root / label
        result = RasCmdr.compute_plan(
            GRID_PLAN,
            dest_folder=dest,
            overwrite_dest=True,
            force_rerun=True,
            num_cores=SOLVER_CORES,
            ras_object=self.ras,
            hdf_output_variables=[CUMULATIVE, "Cell Hydraulic Depth"],
        )
        run = self._read(label, bool(result), pathnames, _plan_hdf(dest, self.name, GRID_PLAN))
        shutil.rmtree(dest, ignore_errors=True)
        dss_file.unlink(missing_ok=True)
        self._runs[label] = run
        _record(f"grid_{self.version}_{label}", _grid_evidence(run, self))
        return run

    @staticmethod
    def _read(label, success, pathnames, plan_hdf: Path) -> GridRun:
        messages = HdfResultsPlan.get_compute_messages_hdf_only(plan_hdf)
        run = GridRun(label, success, pathnames, messages)
        try:
            forcing = HdfPlan.get_plan_met_precip_values(plan_hdf)
        except KeyError:
            return run
        run.forcing_values = np.asarray(forcing["values"])
        run.forcing_attrs = HdfPlan.get_plan_met_precip(plan_hdf)
        run.forcing_times = [
            pd.to_datetime(stamp.decode().rstrip("0").rstrip("."), format="%d%b%Y %H:%M:%S")
            for stamp in forcing["timestamps"]
        ]
        datasets = HdfResultsMesh.get_mesh_cells_timeseries(plan_hdf, var=CUMULATIVE)
        hydraulic = HdfResultsMesh.get_mesh_cells_timeseries(plan_hdf, var="Cell Hydraulic Depth")
        (dataset,) = datasets.values()
        (hydraulic_dataset,) = hydraulic.values()
        run.times = pd.DatetimeIndex(dataset["time"].values)
        run.cumulative = dataset[CUMULATIVE].values
        run.depth = hydraulic_dataset["Cell Hydraulic Depth"].values
        return run


def _grid_evidence(run: GridRun, bench: GridBench) -> Dict[str, Any]:
    evidence: Dict[str, Any] = {
        "label": run.label,
        "success": run.success,
        "pathnames": run.pathnames,
        "messages_tail": run.messages[-1500:],
        "message_lines_about_precipitation": [
            line for line in run.messages.splitlines() if "precip" in line.lower()
        ],
        "forcing_attrs": {
            key: value for key, value in run.forcing_attrs.items() if key != "Projection"
        },
    }
    if run.forcing_values is not None:
        evidence["forcing"] = [
            {"time": str(stamp), "max_in": float(np.nanmax(row)), "min_in": float(np.nanmin(row))}
            for stamp, row in zip(run.forcing_times, run.forcing_values)
        ]
    if run.cumulative is not None:
        evidence["cumulative_mean_in"] = {
            str(stamp): float(value)
            for stamp, value in zip(run.times, np.nanmean(run.cumulative, axis=1))
        }
        evidence["final_cumulative_in"] = {
            "min": float(np.nanmin(run.cumulative[-1])),
            "max": float(np.nanmax(run.cumulative[-1])),
            "mean": float(np.nanmean(run.cumulative[-1])),
        }
    return evidence


@pytest.fixture(scope="module")
def version():
    return _select_version()


@pytest.fixture(scope="module")
def grid(version, tmp_path_factory):
    return GridBench(tmp_path_factory.mktemp("grid", numbered=True), version)


real_ras = [pytest.mark.integration, pytest.mark.real_ras, pytest.mark.destructive_copy,
            pytest.mark.slow]


def _zone_mask(run: GridRun, bench: GridBench):
    """Interior cells of each depth zone, on the result's cell axis."""
    count = run.cumulative.shape[1]
    distance = bench.split_distance[:count]
    west = bench.west_of_split[:count]
    far = distance > ZONE_MARGIN_M
    return west & far, ~west & far


def _assert_burst(run: GridRun, bench: GridBench, wet_label: pd.Timestamp) -> None:
    """The known depth reaches the mesh, accumulating across (wet_label - 1h, wet_label]."""
    assert run.success, run.messages[-2000:]
    assert run.forcing_values is not None, run.messages[-2000:]
    start = wet_label - HOUR

    # What the solver was given: hour-ending stamps, the burst at its own stamp, in inches.
    assert run.forcing_times == list(LABELS)
    row_maxima = np.nanmax(run.forcing_values, axis=1)
    wet_index = list(LABELS).index(wet_label)
    assert row_maxima[wet_index] == pytest.approx(EAST_MM / MM_PER_INCH, abs=1e-4)
    assert np.all(np.delete(row_maxima, wet_index) == 0.0)
    assert sorted(np.unique(np.round(run.forcing_values[wet_index], 4))) == pytest.approx(
        [WEST_MM / MM_PER_INCH, EAST_MM / MM_PER_INCH], abs=1e-3
    )

    # What the mesh received.
    west, east = _zone_mask(run, bench)
    assert west.sum() > 100 and east.sum() > 100
    final = run.cumulative[-1]
    assert final[west] == pytest.approx(WEST_MM / MM_PER_INCH, abs=1e-3)
    assert final[east] == pytest.approx(EAST_MM / MM_PER_INCH, abs=1e-3)
    fraction = np.clip((run.times - start) / HOUR, 0.0, 1.0)
    assert np.nanmean(run.cumulative[:, west], axis=1) == pytest.approx(
        fraction * WEST_MM / MM_PER_INCH, abs=2e-3
    )
    assert np.nanmean(run.cumulative[:, east], axis=1) == pytest.approx(
        fraction * EAST_MM / MM_PER_INCH, abs=2e-3
    )


def _assert_depths_match(bench: GridBench, name: str, left: GridRun, right: GridRun) -> None:
    differs = left.depth != right.depth
    largest = float(np.nanmax(np.abs(left.depth - right.depth)))
    _record(f"depth_{bench.version}_{name}", dict(
        cells_differing=int(differs.sum()), values=int(differs.size), max_abs_ft=largest,
    ))
    assert largest <= DEPTH_NOISE_FT


@pytest.mark.parametrize("dss_version", [7, 6])
@pytest.mark.parametrize("backend", ["native", "java"])
@pytest.mark.integration
@pytest.mark.real_ras
@pytest.mark.destructive_copy
@pytest.mark.slow
def test_period_grid_burst_reaches_mesh(grid, backend, dss_version):
    run = grid.run(f"{backend}{dss_version}", backend, dss_version=dss_version)
    assert run.pathnames[list(LABELS).index(WET_LABEL)] == (
        "/SHG/BURST/PRECIP/09SEP2018:2300/09SEP2018:2400/AORC/"
    )
    _assert_burst(run, grid, WET_LABEL)
    assert np.nanmax(run.depth) > 0.0


@pytest.mark.parametrize("dss_version", [7, 6])
@pytest.mark.integration
@pytest.mark.real_ras
@pytest.mark.destructive_copy
@pytest.mark.slow
def test_java_and_native_grids_give_identical_results(grid, dss_version):
    native = grid.run(f"native{dss_version}", "native", dss_version=dss_version)
    java = grid.run(f"java{dss_version}", "java", dss_version=dss_version)
    np.testing.assert_array_equal(native.forcing_values, java.forcing_values)
    np.testing.assert_array_equal(native.cumulative, java.cumulative)
    _assert_depths_match(grid, f"java_native_{dss_version}", native, java)


@pytest.mark.integration
@pytest.mark.real_ras
@pytest.mark.destructive_copy
@pytest.mark.slow
def test_repeat_run_of_one_file_measures_solver_noise(grid):
    """The same file computed twice sets how close two backends can be expected to be."""
    first = grid.run("native7", "native")
    repeat = grid.run("native7_repeat", "native")
    np.testing.assert_array_equal(first.forcing_values, repeat.forcing_values)
    np.testing.assert_array_equal(first.cumulative, repeat.cumulative)
    _assert_depths_match(grid, "repeat", first, repeat)


@pytest.mark.parametrize("backend", ["native", "java"])
@pytest.mark.integration
@pytest.mark.real_ras
@pytest.mark.destructive_copy
@pytest.mark.slow
def test_one_hour_period_shift_moves_results_one_hour(grid, backend):
    base = grid.run(f"{backend}7", backend)
    shifted = grid.run(f"{backend}7_shift", backend, wet_label=SHIFTED_WET_LABEL)
    _assert_burst(shifted, grid, SHIFTED_WET_LABEL)
    steps_per_hour = int(HOUR / (base.times[1] - base.times[0]))
    assert steps_per_hour == 12
    # Cumulative rain at t in the shifted run equals rain at t - 1h in the base run.
    np.testing.assert_allclose(
        shifted.cumulative[steps_per_hour:], base.cumulative[:-steps_per_hour],
        rtol=0.0, atol=1e-5,
    )
    assert np.all(shifted.cumulative[:steps_per_hour + 24] == 0.0)


def test_native_writer_refuses_zero_length_period_grid(tmp_path):
    """Only the Java path can create D = E period grids."""
    _require_backend("native")
    frame = np.ones((1, 3, 4), dtype=np.float32)
    info = {"cellsize": SHG_CELL_M, "origin": (0.0, 0.0), "crs": "SHG", "units": "mm",
            "data_type": "PER-CUM"}
    with _native_backend():
        with pytest.raises(ValueError, match="must be later than its start"):
            RasDss.write_grid_timeseries(
                tmp_path / "zero.dss", GRID_PATHNAME, frame, [WET_LABEL, WET_LABEL], info,
                dss_version=7,
            )


@pytest.mark.parametrize(
    "wet_label",
    [LABELS[0], ZERO_LENGTH_MIDDAY_WET_LABEL, WET_LABEL],
    ids=["first-frame", "midday", "midnight"],
)
@pytest.mark.integration
@pytest.mark.real_ras
@pytest.mark.destructive_copy
@pytest.mark.slow
def test_zero_length_period_grids_act_as_hour_ending_stamps(grid, wet_label):
    """Pins observed HEC-RAS behaviour for D = E PER-CUM grids; not a recommendation.

    HEC-RAS applies each record's depth over the period ending at its stamp. Unlike the
    HEC-HMS result that prompted this test, no rain is lost and results match real
    period records. Java writes them because the native writer refuses them. The midnight
    record has D ``10SEP2018:0000`` and E ``09SEP2018:2400``: one instant, two spellings.
    """
    zero = grid.run(f"java7_zero_{wet_label:%H%M}", "java", wet_label=wet_label, zero_length=True)
    index = list(LABELS).index(wet_label)
    expected_end = "09SEP2018:2400" if wet_label == WET_LABEL else f"{wet_label:%d%b%Y:%H%M}".upper()
    expected_start = f"{wet_label:%d%b%Y:%H%M}".upper()
    assert zero.pathnames[index] == f"/SHG/BURST/PRECIP/{expected_start}/{expected_end}/AORC/"
    _assert_burst(zero, grid, wet_label)

    period = grid.run(f"java7_{wet_label:%H%M}", "java", wet_label=wet_label)
    _assert_burst(period, grid, wet_label)
    np.testing.assert_array_equal(zero.forcing_values, period.forcing_values)
    np.testing.assert_array_equal(zero.cumulative, period.cumulative)
    _assert_depths_match(grid, f"zero_period_{wet_label:%H%M}", zero, period)


def _xs_results(plan_hdf: Path) -> Dict[str, np.ndarray]:
    """Every numeric dataset of the unsteady time-series output."""
    out: Dict[str, np.ndarray] = {}
    with h5py.File(plan_hdf, "r") as hdf:
        group = hdf["Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"]

        def visit(name, obj):
            if isinstance(obj, h5py.Dataset) and np.issubdtype(obj.dtype, np.number):
                out[name] = obj[()]

        group.visititems(visit)
    assert out
    return out


class BoundaryBench:
    def __init__(self, root: Path, version: str):
        self.root, self.version = root, version
        self.project = _extract(version, BOUNDARY_PROJECT, root / "src")
        self.ras = init_ras_project(
            self.project, version, load_results_summary=False, hide_intro=True
        )
        _require_tcu(self.ras)
        self.name = self.ras.project_name
        unsteady = str(
            self.ras.plan_df.set_index("plan_number").loc[BOUNDARY_PLAN, "unsteady_number"]
        ).zfill(2)
        table = self.ras.boundaries_df
        rows = table[
            (table["unsteady_number"].astype(str).str.zfill(2) == unsteady)
            & (table["Use DSS"].astype(str) == "True")
        ]
        self.dss_name = str(rows["DSS File"].iloc[0])
        self.dss_file = self.project / self.dss_name
        self.original = self.root / "source_copy.dss"
        shutil.copy2(self.dss_file, self.original)
        with _native_backend():
            self.series = {
                path: RasDss.read_timeseries(self.original, path)
                for path in sorted(set(rows["DSS Path"]))
            }
        assert len(self.series) >= 5
        self._runs: Dict[str, Dict[str, Any]] = {}

    def requests(self, target, dss_version, scale):
        requests = []
        for index, (path, frame) in enumerate(self.series.items()):
            requests.append(dict(op="write_timeseries", kwargs=dict(
                dss_file=str(target),
                pathname=path,
                times=frame.index,
                values=frame["value"].to_numpy() * scale,
                units=frame.attrs["units"],
                data_type=frame.attrs["type"] or "INST-VAL",
                dss_version=dss_version if index == 0 else None,
            )))
        return requests

    def run(self, label, backend=None, dss_version=None, scale=1.0):
        if label in self._runs:
            return self._runs[label]
        target = self.root / f"{label}.dss"
        if backend is None:
            shutil.copy2(self.original, target)
        else:
            _require_backend(backend)
            _write(self.root / "java" / label, backend, self.requests(target, dss_version, scale))
        shutil.copy2(target, self.dss_file)
        dest = self.root / label
        result = RasCmdr.compute_plan(
            BOUNDARY_PLAN,
            dest_folder=dest,
            overwrite_dest=True,
            force_rerun=True,
            num_cores=1,
            ras_object=self.ras,
        )
        plan_hdf = _plan_hdf(dest, self.name, BOUNDARY_PLAN)
        messages = HdfResultsPlan.get_compute_messages_hdf_only(plan_hdf)
        assert result, messages[-2000:]
        with h5py.File(plan_hdf, "r") as hdf:
            flows = {}
            bc_group = hdf.get("Event Conditions/Unsteady/Boundary Conditions")
            if bc_group is not None:
                def visit(name, obj):
                    if isinstance(obj, h5py.Dataset) and np.issubdtype(obj.dtype, np.number):
                        flows[name] = obj[()]
                bc_group.visititems(visit)
        wse = HdfResultsXsec.get_xsec_timeseries(plan_hdf)["Water_Surface"].values
        run = dict(results=_xs_results(plan_hdf), flows=flows, wse=wse, messages=messages)
        shutil.rmtree(dest, ignore_errors=True)
        self._runs[label] = run
        _record(f"boundary_{self.version}_{label}", dict(
            label=label,
            datasets=len(run["results"]),
            boundary_datasets=sorted(flows),
            wse_max=float(np.nanmax(wse)),
            messages_tail=messages[-1200:],
        ))
        return run


@pytest.fixture(scope="module")
def boundary(version, tmp_path_factory):
    return BoundaryBench(tmp_path_factory.mktemp("boundary", numbered=True), version)


def _result_differences(left, right) -> Dict[str, float]:
    assert left.keys() == right.keys()
    return {
        name: float(np.nanmax(np.abs(left[name] - right[name])))
        for name in left
        if not np.array_equal(left[name], right[name], equal_nan=True)
    }


@pytest.mark.parametrize("dss_version", [6, 7])
@pytest.mark.parametrize("backend", ["native", "java"])
@pytest.mark.integration
@pytest.mark.real_ras
@pytest.mark.destructive_copy
@pytest.mark.slow
def test_rewritten_boundaries_give_results_identical_to_the_original_file(
    boundary, backend, dss_version
):
    original = boundary.run("original")
    rewritten = boundary.run(f"{backend}{dss_version}", backend, dss_version)
    assert original["flows"]
    assert _result_differences(original["flows"], rewritten["flows"]) == {}
    assert _result_differences(original["results"], rewritten["results"]) == {}


@pytest.mark.integration
@pytest.mark.real_ras
@pytest.mark.destructive_copy
@pytest.mark.slow
def test_boundary_control_scaled_flows_change_results(boundary):
    """Without this, identical results could mean HEC-RAS ignored the rewritten file."""
    _require_backend("native")
    original = boundary.run("original")
    scaled = boundary.run("native_scaled", "native", 7, scale=1.25)
    assert np.nanmax(scaled["wse"]) > np.nanmax(original["wse"]) + 0.1
    assert _result_differences(original["flows"], scaled["flows"])


#: Example projects whose unsteady files name DSS boundaries, by 7.0 archive scan.
READ_PROJECTS = [
    "Dam Breaching",
    "UngagedAreaInflows",
    "BaldEagleCrkMulti2D",
    "Example 24 - Mannings-n-Calibration",
]


def _native_boundaries(project: Path, version: str, work: Path):
    out_path = work / "native_boundaries.pkl"
    proc = subprocess.run(
        [sys.executable, str(NATIVE_WORKER), str(project), version, str(out_path)],
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    with open(out_path, "rb") as fh:
        return pickle.load(fh)


@pytest.mark.integration
@pytest.mark.parametrize("project_name", READ_PROJECTS)
def test_example_dss_boundaries_resolve_under_native_without_java(project_name, tmp_path):
    _require_backend("native")
    version = os.environ.get("RAS_DSS_ACCEPTANCE_VERSION", "7.0")
    archive = RasExamples.examples_dir / f"Example_Projects_{version.replace('.', '_')}.zip"
    if not archive.is_file():
        pytest.skip(f"example archive for {version} is not cached")
    project = _extract(version, project_name, tmp_path)
    native = _native_boundaries(project, version, tmp_path)
    assert native["jnius_loaded"] is False
    table = native["result"]
    dss_rows = table[table["Use DSS"].astype(str) == "True"]
    assert len(dss_rows) > 0
    unresolved = [
        (index, row["DSS File"], row["DSS Path"])
        for index, row in dss_rows.iterrows()
        if row["dss_timeseries"] is None or len(row["dss_timeseries"]) == 0
    ]
    _record(f"reads_{project_name.replace(' ', '_')}", dict(
        project=project_name,
        dss_boundaries=len(dss_rows),
        unresolved=unresolved,
    ))
    assert not unresolved

    if not HecMonolithDownloader().is_installed():
        return
    java_table = table.drop(columns=["dss_timeseries"])
    java = _java(tmp_path, [dict(op="extract_boundary_timeseries", kwargs=dict(
        boundaries_df=java_table, project_dir=str(project)))])[0]
    for index, row in dss_rows.iterrows():
        # Documented difference: Java returns HEC's missing marker as a number.
        java_values = java.at[index, "dss_timeseries"]["value"]
        pd.testing.assert_series_equal(
            row["dss_timeseries"]["value"],
            java_values.where(java_values != JAVA_MISSING),
            check_names=False,
            check_exact=True,
        )
