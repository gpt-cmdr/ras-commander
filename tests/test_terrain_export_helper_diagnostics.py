"""Regression tests for terrain export helper failure diagnostics.

Covers three failure modes seen when running the native RAS Mapper terrain
helper under Wine:

* RAS Mapper's empty-window error ("... does not have embedded statistics"),
  which must be reported as an empty extent once source coverage confirms it;
* helper failures whose only stderr is Wine's harmless ``XDG_RUNTIME_DIR``
  warning, and helpers that report success but exit non-zero;
* .NET ``System.OutOfMemoryException`` at helper start.

The helper process is replaced by a fake that writes the response JSON the
real helper would write, so the real ``_run_helper`` supervision runs.
Terrain sources are synthetic GeoTIFFs.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ras_commander import RasMap, RasTerrain
from ras_commander.native import terrain_export_host as host

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

XDG_WARNING = "error: XDG_RUNTIME_DIR is invalid or not set in the environment."
EMPTY_WINDOW_ERROR = (
    "Target file: Z:\\scratch\\.export.partial.tif does not have embedded statistics"
)
EMPTY_WINDOW_DETAILS = (
    "System.Exception: " + EMPTY_WINDOW_ERROR + "\n"
    "   at TiffAssist.FloatTiffWriter.ComputeSetHistogram()\n"
    "   at RasMapperLib.InterpolatedLayer.AddHistogram()\n"
    "   at RasMapperLib.TerrainLayer.GenerateNewRasTerrain()"
)
OOM_DETAILS = (
    "System.TypeInitializationException: The type initializer for "
    "'RasMapperLib.Layer' threw an exception. ---> "
    "System.OutOfMemoryException: Insufficient memory to continue the "
    "execution of the program.\n   at RasMapperLib.Layer..cctor()"
)
# Synthetic projected CRS used for the source raster and the .rasmap
# projection file.
CRS_EPSG = 26915


def _base_response(operation: str, sources: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "helper": "RasMapperTerrainExportHelper",
        "success": True,
        "operation": operation,
        "terrain_extent": {"min_x": 0, "min_y": 0, "max_x": 20, "max_y": 20},
        "sources": sources,
    }


def _source(filename: str) -> dict:
    return {
        "index": 0,
        "filename": filename,
        "priority": 0,
        "columns": 4,
        "rows": 4,
        "extent": {"min_x": 0.0, "min_y": 0.0, "max_x": 20.0, "max_y": 20.0},
        "cell_sizes": [5.0],
        "levels": 1,
    }


def _export_success(request: dict, sources: list[dict]) -> dict:
    return {
        **_base_response("export", sources),
        "resample_method": "near",
        "resample_to_one_rfi": True,
        "generate_method_is_public": False,
        "new_rfis": [request["output_path"]],
        "messages": [],
        "output_exists": True,
    }


def _failure(error: str, error_type: str, details: str) -> dict:
    return {
        "schema_version": 1,
        "helper": "RasMapperTerrainExportHelper",
        "success": False,
        "error": error,
        "error_type": error_type,
        "details": details,
    }


def _write_source_tif(path: Path, valid: bool) -> Path:
    data = np.full((4, 4), -9999.0, dtype="float32")
    if valid:
        data[1, 2] = 101.5
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="float32",
        crs=f"EPSG:{CRS_EPSG}",
        transform=from_origin(0.0, 20.0, 5.0, 5.0),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(data, 1)
    return path


def _valid_gdalinfo() -> dict:
    return {
        "driverShortName": "GTiff",
        "size": [4, 4],
        "geoTransform": [0.0, 5.0, 0.0, 20.0, 0.0, -5.0],
        "coordinateSystem": {"wkt": "PROJCRS[...]"},
        "bands": [{
            "type": "Float32",
            "noDataValue": -9999.0,
            "computedMin": 1.0,
            "computedMax": 8.0,
            "checksum": 42,
        }],
    }


def _project(monkeypatch, tmp_path: Path, source_filename: str):
    """Synthetic project: a .rasmap with a projection file and one terrain."""
    from pyproj import CRS

    projection = tmp_path / "Projection.prj"
    projection.write_text(CRS.from_epsg(CRS_EPSG).to_wkt("WKT1_ESRI"), encoding="utf-8")
    rasmap = tmp_path / "Synthetic.rasmap"
    rasmap.write_text(
        '<RASMapper><RASProjectionFilename Filename=".\\Projection.prj" />'
        "<Terrains/></RASMapper>",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        RasMap,
        "list_terrain_layers",
        staticmethod(lambda *_args, **_kwargs: pd.DataFrame([{
            "name": "Terrain",
            "resolved_path": str(tmp_path / "Terrain.hdf"),
        }])),
    )
    monkeypatch.setattr(
        host,
        "_resolve_hecras_source",
        lambda *_args: ("6.6", tmp_path / "fake-ras", None),
    )
    monkeypatch.setattr(
        host,
        "_stage_runtime",
        lambda stage, *_args: (stage / "helper.exe", tmp_path / "fake-ras", None),
    )
    monkeypatch.setattr(host, "_runtime_env", lambda *_: {})
    monkeypatch.setattr(host, "_run_gdalinfo", lambda *_args: _valid_gdalinfo())
    return rasmap, tmp_path / "out" / "terrain.tif", [_source(source_filename)]


def _fake_process(monkeypatch, export_behavior):
    """Replace the helper process; inspect succeeds, export is scripted.

    ``export_behavior(request)`` returns ``(response_or_None, exit_code,
    stderr, write_tiff)``.
    """
    calls = []

    def run(command, **_kwargs):
        request = json.loads(Path(command[-2]).read_text(encoding="utf-8"))
        response_path = Path(command[-1])
        calls.append(request["operation"])
        if request["operation"] == "inspect":
            response = _base_response("inspect", run.sources)
            exit_code, stderr = 0, XDG_WARNING
        else:
            response, exit_code, stderr, write_tiff = export_behavior(request)
            if write_tiff:
                Path(request["output_path"]).write_bytes(b"native TIFF bytes")
        if response is not None:
            response_path.write_text(json.dumps(response), encoding="utf-8")
        return subprocess.CompletedProcess(command, exit_code, "", stderr)

    monkeypatch.setattr(host, "run_owned_process", run)
    run.calls = calls
    return run


def _run_export(rasmap, output, **kwargs):
    return RasTerrain.export_rasmapper_terrain(
        rasmap, output, terrain_name="Terrain", hecras_version="6.6", **kwargs
    )


def _receipt(result) -> dict:
    return json.loads(Path(result.receipt_path).read_text(encoding="utf-8"))


# --- Gap 1: empty export window -------------------------------------------


def _empty_window_failure(request):
    return (
        _failure(EMPTY_WINDOW_ERROR, "System.Exception", EMPTY_WINDOW_DETAILS),
        1,
        XDG_WARNING + "\n" + EMPTY_WINDOW_DETAILS,
        True,
    )


def test_confirmed_empty_window_reports_empty_extent(monkeypatch, tmp_path):
    source = _write_source_tif(tmp_path / "source.tif", valid=False)
    rasmap, output, sources = _project(monkeypatch, tmp_path, str(source))
    process = _fake_process(monkeypatch, _empty_window_failure)
    process.sources = sources

    result = _run_export(rasmap, output)

    assert not result
    assert result.failure_kind == "empty_extent"
    assert result.error.startswith("No terrain data in the requested extent")
    assert "embedded statistics" in result.error
    assert result.empty_extent_check["status"] == "empty"
    assert result.empty_extent_check["sources"][0]["valid_cells"] == 0
    assert not output.exists()
    receipt = _receipt(result)
    assert receipt["result"]["failure_kind"] == "empty_extent"
    assert receipt["result"]["helper_invocations"][-1]["response"]["error"] == (
        EMPTY_WINDOW_ERROR
    )


def test_empty_window_nodata_opt_in_writes_valid_all_nodata_tiff(monkeypatch, tmp_path):
    source = _write_source_tif(tmp_path / "source.tif", valid=False)
    rasmap, output, sources = _project(monkeypatch, tmp_path, str(source))
    process = _fake_process(monkeypatch, _empty_window_failure)
    process.sources = sources

    result = _run_export(rasmap, output, empty_extent="nodata")

    assert result, result.error
    assert result.empty_extent is True
    assert result.failure_kind is None
    assert result.validation["empty_extent"] is True
    assert result.validation["valid_cell_count"] == 0
    with rasterio.open(output) as dataset:
        assert (dataset.width, dataset.height) == (4, 4)
        assert dataset.crs.to_epsg() == CRS_EPSG
        assert dataset.nodata == -9999.0
        assert tuple(dataset.transform)[:6] == tuple(from_origin(0.0, 20.0, 5.0, 5.0))[:6]
        assert np.all(dataset.read(1) == -9999.0)
    assert _receipt(result)["result"]["empty_extent"] is True


def test_statistics_error_with_source_data_is_not_called_empty(monkeypatch, tmp_path):
    source = _write_source_tif(tmp_path / "source.tif", valid=True)
    rasmap, output, sources = _project(monkeypatch, tmp_path, str(source))
    process = _fake_process(monkeypatch, _empty_window_failure)
    process.sources = sources

    result = _run_export(rasmap, output, empty_extent="nodata")

    assert not result
    assert result.failure_kind == "native_error"
    assert result.empty_extent_check["status"] == "has_data"
    assert "not an empty-window failure" in result.error
    assert not output.exists()


def test_statistics_error_with_unreadable_source_is_unconfirmed(monkeypatch, tmp_path):
    rasmap, output, sources = _project(
        monkeypatch, tmp_path, str(tmp_path / "missing source.tif")
    )
    process = _fake_process(monkeypatch, _empty_window_failure)
    process.sources = sources

    result = _run_export(rasmap, output, empty_extent="nodata")

    assert not result
    assert result.failure_kind == "empty_extent_unconfirmed"
    assert "could not be confirmed" in result.error
    assert "error" in result.empty_extent_check["sources"][0]


def test_invalid_empty_extent_option_is_rejected_before_native_work(tmp_path):
    with pytest.raises(ValueError, match="empty_extent"):
        RasTerrain.export_rasmapper_terrain(
            "missing.prj", tmp_path / "out.tif", hecras_version="6.6",
            empty_extent="skip",
        )


# --- Gap 2: Wine stderr fallback and success with non-zero exit ------------


def test_success_with_nonzero_exit_keeps_and_validates_output(monkeypatch, tmp_path):
    rasmap, output, sources = _project(monkeypatch, tmp_path, "source.tif")
    process = _fake_process(
        monkeypatch,
        lambda request: (_export_success(request, sources), 3, XDG_WARNING, True),
    )
    process.sources = sources

    result = _run_export(rasmap, output)

    assert result, result.error
    assert output.read_bytes() == b"native TIFF bytes"
    export_record = result.helper_invocations[-1]
    assert export_record["status"] == "success_nonzero_exit"
    assert export_record["exit_code"] == 3
    assert any("exited with code 3" in message for message in result.messages)
    receipt = _receipt(result)
    assert receipt["result"]["helper_invocations"][-1]["exit_code"] == 3


def test_success_with_nonzero_exit_and_missing_output_fails(monkeypatch, tmp_path):
    rasmap, output, sources = _project(monkeypatch, tmp_path, "source.tif")
    process = _fake_process(
        monkeypatch,
        lambda request: (_export_success(request, sources), 3, XDG_WARNING, False),
    )
    process.sources = sources

    result = _run_export(rasmap, output)

    assert not result
    assert result.failure_kind == "native_error"
    assert "reported success but exited with code 3" in result.error


def test_missing_response_with_only_wine_warning_names_exit_code(monkeypatch, tmp_path):
    rasmap, output, sources = _project(monkeypatch, tmp_path, "source.tif")
    process = _fake_process(
        monkeypatch, lambda request: (None, 1, XDG_WARNING, False)
    )
    process.sources = sources

    result = _run_export(rasmap, output)

    assert not result
    assert result.failure_kind == "no_response"
    assert "exit=1" in result.error
    assert "only Wine runtime warnings" in result.error
    assert not result.error.startswith("Native terrain helper failed: error: XDG")
    record = _receipt(result)["result"]["helper_invocations"][-1]
    assert record["exit_code"] == 1
    assert record["status"] == "no_response"
    assert record["request"]["operation"] == "export"
    assert XDG_WARNING in record["stderr"]


def test_failure_without_error_text_does_not_summarize_as_wine_warning():
    detail = host._helper_failure_detail({"success": False}, XDG_WARNING, 1)
    summary = detail.splitlines()[0]
    assert summary.startswith("helper exited with code 1 without reporting an error")
    assert "XDG_RUNTIME_DIR" not in summary
    assert XDG_WARNING in detail  # still retained, labelled as stderr


def test_failure_receipt_keeps_native_response(monkeypatch, tmp_path):
    rasmap, output, sources = _project(monkeypatch, tmp_path, "source.tif")
    response = _failure("Terrain layer could not be opened", "System.IO.IOException",
                        "System.IO.IOException: Terrain layer could not be opened")
    process = _fake_process(monkeypatch, lambda request: (response, 1, XDG_WARNING, False))
    process.sources = sources

    result = _run_export(rasmap, output)

    assert result.failure_kind == "native_error"
    assert result.error.startswith(
        "Native terrain helper failed: Terrain layer could not be opened"
    )
    record = _receipt(result)["result"]["helper_invocations"][-1]
    assert record["response"]["error_type"] == "System.IO.IOException"


# --- Gap 3: out-of-memory at helper start ----------------------------------


def test_wrapped_out_of_memory_is_classified(monkeypatch, tmp_path):
    rasmap, output, sources = _project(monkeypatch, tmp_path, "source.tif")
    response = _failure(
        "The type initializer for 'RasMapperLib.Layer' threw an exception.",
        "System.TypeInitializationException",
        OOM_DETAILS,
    )
    process = _fake_process(monkeypatch, lambda request: (response, 1, XDG_WARNING, False))
    process.sources = sources

    result = _run_export(rasmap, output)

    assert not result
    assert result.failure_kind == "out_of_memory"
    assert result.error.startswith("Native terrain helper ran out of memory")
    assert "OutOfMemoryException" in result.error


def test_out_of_memory_without_response_is_classified(tmp_path, monkeypatch):
    def run(command, **_kwargs):
        return subprocess.CompletedProcess(
            command, 134, "", XDG_WARNING + "\n" + OOM_DETAILS
        )

    monkeypatch.setattr(host, "run_owned_process", run)
    monkeypatch.setattr(host, "_runtime_env", lambda *_: {})
    request = {
        "schema_version": 1, "operation": "inspect", "terrain_name": "Terrain",
        "rasmap_path": str(tmp_path / "example.rasmap"),
    }
    invocations: list[dict] = []
    with pytest.raises(host.TerrainHelperError) as error:
        host._run_helper(
            tmp_path / "helper.exe", tmp_path, None, request, tmp_path, 1,
            invocations=invocations,
        )
    assert error.value.failure_kind == "out_of_memory"
    assert invocations[0]["exit_code"] == 134
    assert invocations[0]["status"] == "out_of_memory"


@pytest.mark.parametrize(
    "response, stderr, expected",
    [
        ({"error_type": "System.OutOfMemoryException"}, "", "out_of_memory"),
        ({"details": OOM_DETAILS}, "", "out_of_memory"),
        ({"error": EMPTY_WINDOW_ERROR}, "", "empty_extent_unconfirmed"),
        ({}, EMPTY_WINDOW_DETAILS, "empty_extent_unconfirmed"),
        ({"error": "Something else"}, XDG_WARNING, "native_error"),
    ],
)
def test_classify_helper_failure(response, stderr, expected):
    assert host.classify_helper_failure(response, stderr) == expected
