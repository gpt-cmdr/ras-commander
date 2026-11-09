"""Bounded diagnostic transport preserves samples and refuses false identity."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import struct
import subprocess
import xml.etree.ElementTree as ET

import pytest

from ras_commander import _native_helper as helper


@pytest.fixture
def primitive_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(helper, "_IS_LINUX", False)
    monkeypatch.setattr(helper.platform, "system", lambda: "Windows")
    monkeypatch.setattr(helper, "_is_wine_helper_runtime", lambda: False)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    mapper = runtime / "RasMapperLib.dll"
    mapper.write_bytes(b"synthetic runtime identity")
    packaged = tmp_path / "helper.exe"
    packaged.write_bytes(b"not executed")

    @contextmanager
    def executable():
        yield packaged

    monkeypatch.setattr(helper, "packaged_helper_executable_path", executable)
    monkeypatch.setattr(helper, "_hecras_gdal_subprocess_env", lambda _: {})
    return runtime, tmp_path / "output"


def test_primitive_grid_transports_exact_float32_bits_and_checks_identity(monkeypatch, primitive_runtime):
    runtime, output = primitive_runtime
    observed = {}

    def run(command, **kwargs):
        observed.update(command=command, kwargs=kwargs)
        request = ET.parse(command[-2]).getroot()
        observed["bits"] = [node.get("bits") for node in request.findall("grid/v")]
        report = ET.Element("boundary-primitives-report", schema="ras-commander-boundary-primitives-report/1",
                            kind="grids", status="completed", mapper_path=str(runtime / "RasMapperLib.dll"),
                            mapper_sha256=hashlib.sha256((runtime / "RasMapperLib.dll").read_bytes()).hexdigest())
        ET.ElementTree(report).write(output / "primitive-report.xml", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "RESULT_SUCCESS=True", "")

    monkeypatch.setattr(helper, "_run_store_map_process", run)
    values = [-9999.0, -0.0, 1.0 / 3.0, 0.0]
    request = dict(kind="grids", grids=[dict(rows=2, cols=2, left=0, top=2, dx=1, dy=-1, values=values)])
    result = helper.run_boundary_primitive_helper(runtime, request, output)
    assert result.returncode == 0
    assert observed["bits"] == [f'{struct.unpack("<I", struct.pack("<f", value))[0]:08X}' for value in values]
    assert observed["command"][3] == "BoundaryPrimitives"
    assert Path(observed["kwargs"]["env"]["TEMP"]).parent == output
    assert (output / "helper.stdout.log").read_text() == "RESULT_SUCCESS=True"


@pytest.mark.parametrize("primitive_request", [
    {}, {"kind": "model"}, {"kind": "rings", "rings": [[[0, 0], [1.5, 0], [0, 1]]]},
    {"kind": "rings", "rings": [[[0, 0], [2**51, 0], [0, 1]]]},
    {"kind": "rings", "rings": [[[0, 0], [1, 0]]]},
    {"kind": "rings", "rings": [] , "execute": "arbitrary"},
    {"kind": "grids", "grids": []},
    {"kind": "grids", "grids": [dict(rows=34, cols=2, left=0, top=2, dx=1, dy=-1, values=[])]},
    {"kind": "grids", "grids": [dict(rows=2, cols=2, left=0, top=2, dx=1, dy=-1, values=[0, 0, 0, float("nan")])]},
])
def test_primitive_refuses_bad_requests_before_output_or_launch(monkeypatch, primitive_runtime, primitive_request):
    runtime, output = primitive_runtime
    monkeypatch.setattr(helper, "_run_store_map_process", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(ValueError):
        helper.run_boundary_primitive_helper(runtime, primitive_request, output)
    assert not output.exists()


@pytest.mark.parametrize("report_case", ["missing", "wrong-hash", "wrong-kind"])
def test_primitive_refuses_zero_exit_with_bad_report(monkeypatch, primitive_runtime, report_case):
    runtime, output = primitive_runtime

    def run(command, **kwargs):
        if report_case != "missing":
            root = ET.Element("boundary-primitives-report", schema="ras-commander-boundary-primitives-report/1",
                              status="completed", kind="grids" if report_case == "wrong-kind" else "rings",
                              mapper_path=str(runtime / "RasMapperLib.dll"),
                              mapper_sha256="wrong" if report_case == "wrong-hash" else hashlib.sha256((runtime / "RasMapperLib.dll").read_bytes()).hexdigest())
            ET.ElementTree(root).write(output / "primitive-report.xml", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(helper, "_run_store_map_process", run)
    with pytest.raises(RuntimeError, match="report"):
        helper.run_boundary_primitive_helper(runtime, dict(kind="rings", rings=[]), output)


def test_primitive_preserves_failure_diagnostics(monkeypatch, primitive_runtime):
    runtime, output = primitive_runtime
    monkeypatch.setattr(helper, "_run_store_map_process", lambda command, **kwargs: subprocess.CompletedProcess(command, 99, "diagnostic out", "native refusal"))
    result = helper.run_boundary_primitive_helper(runtime, dict(kind="rings", rings=[]), output)
    assert result.returncode == 99
    assert (output / "helper.stderr.log").read_text() == "native refusal"


@pytest.mark.parametrize("tile_ids", [[], list(range(9)), [0, 0], [-1], [True], [[1]], [2**31]])
def test_rfi_refuses_invalid_tiles_before_launch(monkeypatch, primitive_runtime, tile_ids):
    runtime, output = primitive_runtime
    monkeypatch.setattr(helper, "_run_store_map_process", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(ValueError, match="tile"):
        helper.run_boundary_primitive_helper(runtime, dict(kind="terrain_rfi", terrain_hdf_path="unused",
                                                         terrain_tiff_path="unused", tile_ids=tile_ids), output)
    assert not output.exists()


def test_rfi_transports_explicit_existing_sources(monkeypatch, primitive_runtime):
    runtime, output = primitive_runtime
    hdf, tiff = runtime / "terrain.hdf", runtime / "original.tif"
    hdf.write_bytes(b"retained HDF"); tiff.write_bytes(b"retained original TIFF")
    before = (hdf.read_bytes(), tiff.read_bytes())

    def run(command, **kwargs):
        request = ET.parse(command[-2]).getroot()
        assert Path(request.get("terrain_hdf_path")) == hdf
        assert Path(request.get("terrain_tiff_path")) == tiff
        assert [int(node.get("id")) for node in request.findall("tile")] == [1, 4]
        root = ET.Element("boundary-primitives-report", schema="ras-commander-boundary-primitives-report/1",
                          kind="terrain_rfi", status="completed", mapper_path=str(runtime / "RasMapperLib.dll"),
                          mapper_sha256=hashlib.sha256((runtime / "RasMapperLib.dll").read_bytes()).hexdigest())
        ET.ElementTree(root).write(output / "primitive-report.xml", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(helper, "_run_store_map_process", run)
    helper.run_boundary_primitive_helper(runtime, dict(kind="terrain_rfi", terrain_hdf_path=hdf,
                                                     terrain_tiff_path=tiff, tile_ids=[1, 4]), output)
    assert (hdf.read_bytes(), tiff.read_bytes()) == before


@pytest.mark.parametrize("rings", [
    [[[0, 0], [1, 0], [0, 1]]] * 10001,
    [[[0, 0]] * 500001],
])
def test_large_ring_diagnostic_refuses_before_xml_allocation_or_launch(monkeypatch, primitive_runtime, rings):
    runtime, output = primitive_runtime
    monkeypatch.setattr(helper, "_run_store_map_process", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(ValueError, match="At most"):
        helper.run_boundary_primitive_helper(runtime, dict(kind="rings", rings=rings), output)
    assert not output.exists()


@pytest.mark.parametrize("limit", [True, False, None, 0, -1, 50001, 10000.0, float("nan"), "50000"])
def test_explicit_ring_limit_refuses_invalid_before_output_or_launch(monkeypatch, primitive_runtime, limit):
    runtime, output = primitive_runtime
    monkeypatch.setattr(helper, "_run_store_map_process", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(ValueError, match="max_rings"):
        helper.run_boundary_primitive_helper(runtime, dict(kind="rings", rings=[]), output, max_rings=limit)
    assert not output.exists()


def test_explicit_ring_limit_admits_large_ordered_list_and_requires_readback(monkeypatch, primitive_runtime):
    runtime, output = primitive_runtime
    rings = [[[index, 0], [index + 1, 0], [index, 1]] for index in range(10001)]
    def run(command, **kwargs):
        request = ET.parse(command[-2]).getroot()
        assert request.get("max_rings") == "50000"
        transported = [[[int(point.get("x")), int(point.get("y"))] for point in ring.findall("p")]
                       for ring in request.findall("ring")]
        assert transported == rings
        report = ET.Element("boundary-primitives-report", schema="ras-commander-boundary-primitives-report/1",
                            kind="rings", status="completed", max_rings_effective="50000", max_report_vertices_effective="500000",
                            mapper_path=str(runtime / "RasMapperLib.dll"),
                            mapper_sha256=hashlib.sha256((runtime / "RasMapperLib.dll").read_bytes()).hexdigest())
        ET.ElementTree(report).write(output / "primitive-report.xml", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setattr(helper, "_run_store_map_process", run)
    assert helper.run_boundary_primitive_helper(runtime, dict(kind="rings", rings=rings), output,
                                               max_rings=50000).returncode == 0


@pytest.mark.parametrize("readback", [None, "10000", "50001", "050000"])
def test_explicit_ring_limit_false_success_refused(monkeypatch, primitive_runtime, readback):
    runtime, output = primitive_runtime
    def run(command, **kwargs):
        report = ET.Element("boundary-primitives-report", schema="ras-commander-boundary-primitives-report/1",
                            kind="rings", status="completed", mapper_path=str(runtime / "RasMapperLib.dll"),
                            mapper_sha256=hashlib.sha256((runtime / "RasMapperLib.dll").read_bytes()).hexdigest())
        if readback is not None:
            report.set("max_rings_effective", readback)
        ET.ElementTree(report).write(output / "primitive-report.xml", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setattr(helper, "_run_store_map_process", run)
    with pytest.raises(RuntimeError, match="max_rings readback"):
        helper.run_boundary_primitive_helper(runtime, dict(kind="rings", rings=[]), output, max_rings=50000)


def test_nondefault_ring_limit_refuses_nonring_kind(monkeypatch, primitive_runtime):
    runtime, output = primitive_runtime
    monkeypatch.setattr(helper, "_run_store_map_process", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(ValueError, match="requires kind=rings"):
        helper.run_boundary_primitive_helper(runtime, dict(kind="grids", grids=[]), output, max_rings=50000)
    assert not output.exists()


@pytest.mark.parametrize("rings", [[[[0, 0], [1, 0], [0, 1]]] * 50001, [[[0, 0]] * 500001]])
def test_explicit_ring_limit_keeps_ring_and_vertex_hard_caps(monkeypatch, primitive_runtime, rings):
    runtime, output = primitive_runtime
    monkeypatch.setattr(helper, "_run_store_map_process", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(ValueError, match="At most"):
        helper.run_boundary_primitive_helper(runtime, dict(kind="rings", rings=rings), output, max_rings=50000)
    assert not output.exists()


@pytest.mark.parametrize("readback", [None, "131072", "500001"])
def test_explicit_ring_limit_requires_matching_report_vertex_cap(monkeypatch, primitive_runtime, readback):
    runtime, output = primitive_runtime
    def run(command, **kwargs):
        report = ET.Element("boundary-primitives-report", schema="ras-commander-boundary-primitives-report/1",
                            kind="rings", status="completed", max_rings_effective="50000",
                            mapper_path=str(runtime / "RasMapperLib.dll"),
                            mapper_sha256=hashlib.sha256((runtime / "RasMapperLib.dll").read_bytes()).hexdigest())
        if readback is not None:
            report.set("max_report_vertices_effective", readback)
        ET.ElementTree(report).write(output / "primitive-report.xml", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setattr(helper, "_run_store_map_process", run)
    with pytest.raises(RuntimeError, match="vertex cap readback"):
        helper.run_boundary_primitive_helper(runtime, dict(kind="rings", rings=[]), output, max_rings=50000)
