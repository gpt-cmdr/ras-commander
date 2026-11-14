"""Contract tests for the executed WPC QPF DSS rain-on-grid qualification (notebook 926).

The first two tests check the committed notebook source and its retained outputs. The
remaining tests execute the notebook's own WPC acquisition and GRIB metadata-check code
(the part of the import cell before the native DSS import) against offline fixtures:

- ``fixtures/wpc_qpf/2p5km_qpf_listing_20261114T0254Z.html`` is WPC's real
  ``2p5km_qpf`` directory listing recorded at 2026-11-14 02:54 UTC, trimmed to the
  rows of three cycles plus unrelated products and listing quirks.
- ``fixtures/wpc_qpf/p06m_2026110500_gdal_tags.json`` holds the GDAL band tags of the
  28 public GRIB2 files of the committed cycle, with their SHA-256 sums.

No test makes a network call: ``urllib.request.urlopen`` is replaced by a fake that
serves the recorded listing and stand-in file bytes.
"""

import ast
import io
import json
import re
import shutil
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import nbformat
import pytest


NOTEBOOK = Path(__file__).resolve().parents[1] / "examples/926_wpc_qpf_precipitation_forecast.ipynb"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "wpc_qpf"
LISTING = FIXTURES / "2p5km_qpf_listing_20261114T0254Z.html"
RECORDED_TAGS = FIXTURES / "p06m_2026110500_gdal_tags.json"
RECORDED_CYCLE = "2026110500"
SETUP_CONSTANTS = (
    "QPF_INTERVAL_HOURS", "EXPECTED_QPF_FORECAST_HOURS", "WPC_CYCLE_HOURS", "WPC_QPF_BASE",
)
IMPORT_MARKER = "x0, y0, x1, y1 ="


def _notebook():
    return nbformat.read(NOTEBOOK, as_version=4)


def _code_source(notebook):
    return "\n".join(
        cell.source for cell in notebook.cells
        if cell.cell_type == "code" and not cell.source.lstrip().startswith("%")
    )


# ---------------------------------------------------------------------------
# Committed source and retained outputs
# ---------------------------------------------------------------------------

def test_wpc_notebook_covers_native_forcing_source_dss_precompute_and_final_results():
    notebook = _notebook()
    source = "\n".join(cell.source for cell in notebook.cells)

    required_source = [
        "WPC QPF DSS-to-HEC-RAS Rain-on-Grid Qualification",
        # native acquisition and import
        "WPC_QPF_BASE",
        "RAS_COMMANDER_WPC_QPF_CYCLE",
        "RAS_COMMANDER_WPC_QPF_GRIB_DIR",
        'partial.replace(qpf_grib_dir / name)',
        '"GRIB_REF_TIME"',
        '"GRIB_VALID_TIME"',
        "RasDssGrid.import_gridded(",
        'product="total_precipitation"',
        'method="bilinear"',
        # forcing gates
        "RasDss.read_grid(",
        "def full_source_warp(",
        "FORCING_TOLERANCE_MM",
        "mesh_on_valid_forcing",
        # disclosed qpkit comparison
        'driver="GRIB"',
        "kit.qpf_dss.write(",
        "qpkit route spatially qualified",
        # hydraulic chain
        "RasUnsteady.configure_gridded_dss_precipitation(",
        "ratio=1.0",
        "RasPreprocess.preprocess_plan(",
        "solver_window_mask",
        "RasCmdr.compute_plan(",
        "HdfResultsPlan.get_compute_messages_hdf_only(",
        '"Cell Cumulative Precipitation Depth"',
        "active_mesh_mask",
        "RAS_COMMANDER_EXAMPLE_RUN_ROOT",
        "Review all HEC-RAS runtime and BCO messages",
    ]
    missing = [expected for expected in required_source if expected not in source]
    assert not missing

    # The removed qpkit acquisition and its NaN-aware reductions stay removed.
    for removed in ("QPFRequest(", "kit.download_qpf(", "download_to_dss(", "extents=WPC_BBOX",
                    "np.nansum", "np.nanmean"):
        assert removed not in source

    # Only the native file drives the forecast plan; the qpkit file is comparison only.
    tree = ast.parse(_code_source(notebook))
    configure_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and ast.unparse(node.func) == "RasUnsteady.configure_gridded_dss_precipitation"
    ]
    assert len(configure_calls) == 1
    dss_argument = {kw.arg: ast.unparse(kw.value) for kw in configure_calls[0].keywords}["dss_filename"]
    assert dss_argument == "str(qpf_dss_file)"
    assert 'qpf_dss_file = precipitation_dir / "wpc_qpf_native.dss"' in source


def test_wpc_notebook_is_fully_executed_clean_and_visual():
    notebook = _notebook()
    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    assert len(code_cells) == 13
    assert [cell.execution_count for cell in code_cells] == list(range(1, 14))

    outputs = [output for cell in code_cells for output in cell.get("outputs", [])]
    assert len(outputs) >= 25
    assert sum("image/png" in output.get("data", {}) for output in outputs) >= 6
    assert not [output for output in outputs if output.output_type == "error"]

    rendered_text = "\n".join(
        output.get("text", "")
        if output.output_type == "stream"
        else output.get("data", {}).get("text/plain", "")
        for output in outputs
    )
    stderr_text = "\n".join(
        output.get("text", "")
        for output in outputs
        if output.output_type == "stream" and output.get("name") == "stderr"
    )
    assert " - WARNING - " not in stderr_text
    assert " - ERROR - " not in stderr_text
    assert "UserWarning" not in rendered_text

    required_evidence = [
        # native acquisition of the retained fixed cycle
        "WPC cycle: 2026-11-05 00Z (fixed-cycle mode)",
        "GRIB files: 28 (28 cached, 0 downloaded)",
        "Native DSS grids written: 28",
        "Selected DSS mean total: 0.4299 inches",
        "All 28 frames: no missing cells; worst RMSE",
        "(gate 0.01 mm)",
        # disclosed qpkit comparison: missing cells kept and reported, route not qualified
        "missing cells per frame: [126]",
        "qpkit route spatially qualified: False (not used by any plan)",
        "4 selected six-hour native DSS grids",
        # hydraulic chain
        "maximum DSS-to-precompute error (in)",
        "Localized WSEL convergence outliers remain",
        "DSS-to-final RMSE (in)",
        "active positive-rain mesh cells",
        "WPC QPF DSS-to-HEC-RAS rain-on-grid qualification complete (native forcing).",
        "Localized WSEL convergence exceptions are mapped",
        "Review all HEC-RAS runtime and BCO messages",
    ]
    missing = [expected for expected in required_evidence if expected not in rendered_text]
    assert not missing

    # The completion checklist reports every gate as passed.
    checklist = code_cells[-1].outputs[0]["data"]["text/plain"]
    assert "False" not in checklist

    for private in ("C:\\Users\\", "Z:\\", "D:\\", "H:\\", "AppData", "/home/", "/Users/"):
        assert private not in rendered_text


# ---------------------------------------------------------------------------
# Offline execution of the notebook's acquisition and metadata-check code
# ---------------------------------------------------------------------------

def _acquisition_code():
    """Return the notebook's setup constants and the import cell up to the DSS import."""
    notebook = _notebook()
    setup = next(cell.source for cell in notebook.cells
                 if cell.cell_type == "code" and "WPC_QPF_BASE =" in cell.source)
    constants = [
        node for node in ast.parse(setup).body
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name) and node.targets[0].id in SETUP_CONSTANTS
    ]
    assert sorted(node.targets[0].id for node in constants) == sorted(SETUP_CONSTANTS)

    import_cell = next(cell.source for cell in notebook.cells
                       if cell.cell_type == "code" and "def cycle_file_names" in cell.source)
    assert import_cell.count(IMPORT_MARKER) == 1
    acquisition = import_cell.split(IMPORT_MARKER, 1)[0]
    return (compile(ast.Module(body=constants, type_ignores=[]), "<926 setup constants>", "exec"),
            compile(acquisition, "<926 WPC acquisition>", "exec"))


def _recorded_tags():
    return json.loads(RECORDED_TAGS.read_text(encoding="utf-8"))["files"]


def _tags_for_cycle(cycle):
    """Tags for any cycle, keeping each recorded file's reference-to-valid offset."""
    tags = {}
    for name, recorded in _recorded_tags().items():
        offset = int(recorded["GRIB_VALID_TIME"]) - int(recorded["GRIB_REF_TIME"])
        hour = re.search(r"f(\d{3})\.grb$", name).group(1)
        reference = int(cycle.timestamp())
        tags[f"p06m_{cycle:%Y%m%d%H}f{hour}.grb"] = {
            "GRIB_ELEMENT": recorded["GRIB_ELEMENT"],
            "GRIB_REF_TIME": str(reference),
            "GRIB_VALID_TIME": str(reference + offset),
        }
    return tags


def _fixture_bytes(name):
    return b"WPC-FIXTURE:" + name.encode()


class _Response(io.BytesIO):
    pass


class _InterruptedResponse:
    """A transfer that delivers one chunk and then drops the connection."""

    def __init__(self):
        self._sent = False

    def read(self, size=-1):
        if not self._sent:
            self._sent = True
            return b"partial GRIB bytes"
        raise ConnectionResetError("connection reset during transfer")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeWpc:
    """Offline stand-in for WPC's server: the recorded listing plus served files."""

    def __init__(self, base, listing, served):
        self.base, self.listing, self.served = base, listing, served
        self.requests = []

    def urlopen(self, url, timeout=None):
        self.requests.append(url)
        if url == self.base:
            return _Response(self.listing.encode("latin-1"))
        name = url[len(self.base):]
        content = self.served.get(name)
        if content is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if content == "interrupt":
            return _InterruptedResponse()
        return _Response(content)


class _TaggedRaster:
    def __init__(self, tags):
        self._tags = tags

    def tags(self, band):
        assert band == 1
        return dict(self._tags)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _raster_open(tags_by_name):
    """Read recorded tags for fixture bytes; hand anything else to real rasterio."""

    def open_(path):
        path = Path(path)
        if path.read_bytes() == _fixture_bytes(path.name):
            return _TaggedRaster(tags_by_name[path.name])
        import rasterio

        return rasterio.open(path)

    return open_


def _frozen_datetime(now):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    return FrozenDatetime


def _run_acquisition(tmp_path, *, now, cycle=None, listing=None, served=None, cached=(),
                     tags=None):
    constants, acquisition = _acquisition_code()
    namespace = {}
    exec(constants, {"tuple": tuple, "range": range}, namespace)
    base = namespace["WPC_QPF_BASE"]
    grib_dir = tmp_path / "grib"
    grib_dir.mkdir()
    for name in cached:
        (grib_dir / name).write_bytes(_fixture_bytes(name))
    server = _FakeWpc(base, listing if listing is not None else LISTING.read_text(encoding="latin-1"),
                      served or {})
    namespace.update(
        WPC_QPF_CYCLE=cycle,
        run_root=tmp_path / "run",
        ras=SimpleNamespace(project_folder=tmp_path / "project"),
        Path=Path, re=re, shutil=shutil,
        os=SimpleNamespace(environ={"RAS_COMMANDER_WPC_QPF_GRIB_DIR": str(grib_dir)}),
        datetime=_frozen_datetime(now), timedelta=timedelta, timezone=timezone,
        urllib=SimpleNamespace(request=SimpleNamespace(urlopen=server.urlopen)),
        rasterio=SimpleNamespace(open=_raster_open(tags or {})),
    )
    exec(acquisition, namespace)
    return namespace, server, grib_dir


def _served_cycle(cycle):
    names = list(_tags_for_cycle(cycle))
    return {name: _fixture_bytes(name) for name in names}


def test_recorded_wpc_fixtures_match_the_filename_contract():
    listing = LISTING.read_text(encoding="latin-1")
    assert "Index of /2p5km_qpf" in listing
    tags = _recorded_tags()
    assert len(tags) == 28
    cycle = datetime.strptime(RECORDED_CYCLE, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    for name, recorded in tags.items():
        hour = int(re.search(r"f(\d{3})\.grb$", name).group(1))
        assert recorded["GRIB_ELEMENT"] == "APCP06"
        assert int(recorded["GRIB_REF_TIME"]) == int(cycle.timestamp())
        # GDAL reports the end of the six-hour accumulation interval as the valid time.
        assert int(recorded["GRIB_VALID_TIME"]) == int((cycle + timedelta(hours=hour)).timestamp())
        assert re.fullmatch(r"[0-9a-f]{64}", recorded["sha256"])


def test_live_mode_selects_newest_complete_cycle_from_recorded_listing(tmp_path):
    now = datetime(2026, 11, 14, 2, 54, tzinfo=timezone.utc)
    cycle = datetime(2026, 11, 14, 0, tzinfo=timezone.utc)
    namespace, server, grib_dir = _run_acquisition(
        tmp_path, now=now, served=_served_cycle(cycle), tags=_tags_for_cycle(cycle))

    assert namespace["cycle_time"] == cycle
    assert namespace["rejected_cycles"] == []
    assert namespace["downloaded_hours"] == namespace["EXPECTED_QPF_FORECAST_HOURS"]
    assert server.requests[0] == namespace["WPC_QPF_BASE"]
    assert len(server.requests) == 1 + 28
    assert sorted(path.name for path in grib_dir.iterdir()) == sorted(_tags_for_cycle(cycle))
    assert not list(grib_dir.glob("*.part"))


def test_live_mode_rejects_incomplete_newest_cycle_and_ignores_extra_hours(tmp_path):
    listing = LISTING.read_text(encoding="latin-1")
    removed = 'href="p06m_2026111318f168.grb"'
    assert removed in listing and 'href="p06m_2026111318f174.grb"' in listing
    listing = "".join(line for line in listing.splitlines(keepends=True) if removed not in line)
    now = datetime(2026, 11, 13, 20, 5, tzinfo=timezone.utc)
    fallback = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)

    namespace, server, _ = _run_acquisition(
        tmp_path, now=now, listing=listing, served=_served_cycle(fallback),
        tags=_tags_for_cycle(fallback))

    assert namespace["cycle_time"] == fallback
    assert namespace["rejected_cycles"] == [{"cycle": "18Z", "missing": [168]}]
    assert all("2026111312" in url for url in server.requests[1:])


def test_live_mode_without_a_complete_current_day_cycle_raises_before_downloading(tmp_path):
    listing = LISTING.read_text(encoding="latin-1")
    removed = 'href="p06m_2026111400f006.grb"'
    listing = "".join(line for line in listing.splitlines(keepends=True) if removed not in line)
    now = datetime(2026, 11, 14, 5, 0, tzinfo=timezone.utc)

    with pytest.raises(RuntimeError, match="No complete current-day WPC QPF cycle"):
        _run_acquisition(tmp_path, now=now, listing=listing)


@pytest.mark.parametrize("failure", ["interrupt", "http-404"])
def test_failed_transfer_is_reported_and_never_published(tmp_path, failure):
    cycle = datetime.strptime(RECORDED_CYCLE, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    served = _served_cycle(cycle)
    failed = f"p06m_{RECORDED_CYCLE}f090.grb"
    if failure == "interrupt":
        served[failed] = "interrupt"
    else:
        del served[failed]
    cached = [f"p06m_{RECORDED_CYCLE}f006.grb"]
    grib_dir = tmp_path / "grib"

    with pytest.raises(RuntimeError, match="WPC acquisition failures") as raised:
        _run_acquisition(tmp_path, now=datetime(2026, 11, 5, 12, tzinfo=timezone.utc),
                         cycle=RECORDED_CYCLE, served=served, cached=cached,
                         tags=_recorded_tags())

    assert failed in str(raised.value)
    assert not (grib_dir / failed).exists()
    assert not list(grib_dir.glob("*.part"))
    assert len(list(grib_dir.glob("*.grb"))) == 27


def test_fixed_cycle_uses_cached_files_without_network(tmp_path):
    tags = _recorded_tags()
    namespace, server, _ = _run_acquisition(
        tmp_path, now=datetime(2026, 11, 13, tzinfo=timezone.utc), cycle=RECORDED_CYCLE,
        cached=list(tags), tags=tags)

    assert server.requests == []
    assert namespace["missing_names"] == []
    assert namespace["cycle_time"] == datetime(2026, 11, 5, tzinfo=timezone.utc)


def test_fixed_cycle_rejects_a_non_synoptic_hour(tmp_path):
    with pytest.raises(ValueError, match="WPC QPF cycles are"):
        _run_acquisition(tmp_path, now=datetime(2026, 11, 13, tzinfo=timezone.utc),
                         cycle="2026110503")


@pytest.mark.parametrize(
    ("tag", "shift", "message"),
    [
        ("GRIB_ELEMENT", None, "is not the 6-hour APCP"),
        ("GRIB_REF_TIME", -6 * 3600, "is not the 6-hour APCP"),
        # The first draft assumed the valid time was the interval start.
        ("GRIB_VALID_TIME", -6 * 3600, "unexpected valid time"),
    ],
)
def test_metadata_check_rejects_mislabelled_grib(tmp_path, tag, shift, message):
    tags = _recorded_tags()
    target = f"p06m_{RECORDED_CYCLE}f048.grb"
    if shift is None:
        tags[target][tag] = "APCP12"
    else:
        tags[target][tag] = str(int(tags[target][tag]) + shift)

    with pytest.raises(RuntimeError, match=message) as raised:
        _run_acquisition(tmp_path, now=datetime(2026, 11, 13, tzinfo=timezone.utc),
                         cycle=RECORDED_CYCLE, cached=list(tags), tags=tags)
    assert target in str(raised.value)


def test_corrupt_download_fails_the_metadata_check(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    cycle = datetime.strptime(RECORDED_CYCLE, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    served = _served_cycle(cycle)
    corrupt = f"p06m_{RECORDED_CYCLE}f012.grb"
    served[corrupt] = b"<html>503 Service Unavailable</html>"

    with pytest.raises(rasterio.errors.RasterioIOError):
        _run_acquisition(tmp_path, now=datetime(2026, 11, 5, 12, tzinfo=timezone.utc),
                         cycle=RECORDED_CYCLE, served=served, tags=_recorded_tags())
