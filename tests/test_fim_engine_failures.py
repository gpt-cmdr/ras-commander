"""Synthetic protocol/process failures; no hydraulic or numerical qualification."""
import json
import io
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ras_commander.fim import RasFim, _coupled, _engine, _sloping
from ras_commander.fim.errors import FimEngineError, FimEngineNotFoundError, FimMappingError
from test_fim_coupled import (  # Existing format/staging fixtures, no vendor runtime.
    files, one_d_files, _prep_environment, _complete_engine,
)


@pytest.mark.parametrize("suffix", ["plain text"*900, "🙂"*5000, "é🙂漢"*2500])
def test_stderr_tail_read_is_bounded_and_keeps_last_decoded_characters(suffix):
    reads=[]
    class BoundedLog(io.BytesIO):
        def read(self,size=-1):
            assert 0 <= size <= 16000
            reads.append(size)
            return super().read(size)
    log=BoundedLog(b"ignored prefix"*100000+suffix.encode("utf-8"))
    assert _sloping._read_stderr_tail(log)==suffix[-4000:]
    assert reads==[16000]


@pytest.fixture
def stream_mapping(tmp_path, monkeypatch):
    """Run the actual map_profiles transport against an owned Python subprocess."""
    import geopandas as gpd
    from affine import Affine
    from rasterio.windows import Window
    from shapely.geometry import box
    from ras_commander.fim import _horizontal, _invalid_cells

    hdf, terrain = tmp_path / "protocol.hdf", tmp_path / "protocol.tif"
    # Prepared transport consumes staged geometry and cached terrain identity;
    # these are watched source sentinels, not pretend model/terrain fixtures.
    hdf.write_bytes(b"watched synthetic HDF sentinel")
    terrain.write_bytes(b"watched synthetic terrain sentinel")
    cells = gpd.GeoDataFrame({"mesh_name": ["mesh"], "cell_id": [0]},
                             geometry=[box(0, 0, 1, 1)], crs="EPSG:6588")
    plan = SimpleNamespace(shape=(1, 1), mask_geometry=False, cell_positions=np.array([0]),
                           window=Window(0, 0, 1, 1), transform=Affine(1, 0, 0, 0, -1, 1),
                           crs=cells.crs, geometry=box(0, 0, 1, 1))
    monkeypatch.setattr(_horizontal, "plan_grid", lambda *a, **k: plan)
    monkeypatch.setattr(_invalid_cells, "require_cells", lambda *a, **k: None)
    prepared = SimpleNamespace(
        _invalid_policy="repair", _terrain_crs_fnv1a64=None,
        _model_scope={"storage_areas": 0}, _supplied=False,
        _engine=Path(sys.executable),
        _method={"method_id": "rasmapper-plain-sloping/1", "stream_outputs": True},
        _watched={}, _cells=cells, _invalid_records=[], _validate_grid=lambda _: True,
        _terrain_identity={"epsg": 6588, "crs_identity": {"kind": "epsg"}},
        _mesh_files=[], _meshes=[{"mesh_name": "mesh", "cell_count": 1}],
        _units={"p": {"id": "p", "values_files": []}},
        _terrain_transform=[0., 1., 0., 1., 0., -1.],
        _reuse_native=False, _native_session=None, _window_cache_bytes=0,
        _hydraulic_cache_bytes=0, _info={}, info={}, _check_sources=lambda: None,
    )
    script = tmp_path / "protocol_process.py"
    script.write_text('''import json,sys,time,struct
from pathlib import Path
mode=sys.argv[1]
if mode in ('early','race','refusal'):
    sys.stderr.write('unsupported: source history\\n' if mode=='refusal' else 'budget exceeded: sloping decoder plan exceeds budget\\n')
    sys.stderr.flush()
    if mode=='race':
        sys.stdout.close();sys.stdout=None;time.sleep(.02)
    sys.exit(7)
if mode=='malformed':
    sys.stdout.buffer.write(b'not JSON\\n');sys.stdout.buffer.flush();time.sleep(30)
if mode=='idle':time.sleep(30)
if mode=='truncated':
    sys.stdout.buffer.write(b'{"id":"p","status":"complete","pixels":1}\\n');sys.stdout.buffer.flush()
    sys.stderr.write('budget exceeded: synthetic payload failure\\n');sys.stderr.flush();sys.exit(7)
def deliver(request,out,server):
    request=json.loads(Path(request).read_text());out=Path(out);out.mkdir()
    report={'status':'complete','method':{'method_id':'rasmapper-plain-sloping/1','options':{
        'CellRenderMode':'Sloping','CellStencilMode':'JustFacepoints','FacepointAdjustmentMode':'None',
        'ShallowBehaviorMode':'None','UseDepthWeightedFaces':False,'FaceWSMode':'Adjusted'}},
        'profiles':[{'id':p['id'],'status':'complete'} for p in request['profiles']],
        'session':{'geometry_reused':True}}
    (out/'report.json').write_text(json.dumps(report))
    for p in request['profiles']:
        sys.stdout.buffer.write(json.dumps({'id':p['id'],'status':'complete','pixels':1}).encode()+b'\\n')
        sys.stdout.buffer.write(struct.pack('<ff',2.,3.))
    if server:sys.stdout.buffer.write(b'not JSON\\n' if mode=='bad-server' else b'{"command_status":"complete"}\\n')
    sys.stdout.buffer.flush()
if mode in ('server','bad-server'):
    for line in sys.stdin.buffer:
        cmd=json.loads(line);deliver(cmd['request'],cmd['output'],True)
else:deliver(sys.argv[2],sys.argv[3],False)
''', encoding="utf-8")
    original_popen = subprocess.Popen
    children = []
    state = {"mode": "early", "interrupt": False, "startup": False, "dead_session": False}

    def launch(args, **kwargs):
        if state["startup"]:
            raise OSError("synthetic process startup failure")
        mode = "server" if args[1] == "sloping-server" else state["mode"]
        if mode == "server" and state["dead_session"]:
            mode = "early"
        elif mode == "server" and state["mode"] == "bad-server":
            mode = "bad-server"
        argv = [sys.executable, "-B", str(script), mode]
        if args[1] != "sloping-server":
            argv.extend(args[2:])
        process = original_popen(argv, **kwargs)
        children.append(process)
        if state["interrupt"]:
            wrapped = process.stdout
            class InterruptedStdout:
                def readline(self, *args):
                    raise KeyboardInterrupt("original protocol interruption")
                def close(self):
                    wrapped.close()
            process.stdout = InterruptedStdout()
        return process
    monkeypatch.setattr(_sloping.subprocess, "Popen", launch)
    output = tmp_path / "mapped"
    def run(mode, *, persistent=False, timeout=None, interrupt=False, startup=False, dead_session=False):
        state.update(mode=mode, interrupt=interrupt, startup=startup, dead_session=dead_session)
        prepared._reuse_native = persistent
        if dead_session:
            from ras_commander.fim._native_session import NativeSlopingSession
            prepared._native_session = NativeSlopingSession(prepared._engine)
            prepared._native_session.process.wait(timeout=5)
        started = time.monotonic()
        result = _sloping.map_profiles(hdf, terrain, output, profiles={"p": "Max"},
            _prepared=prepared, timeout=timeout, max_working_mib=64)
        return result, time.monotonic()-started
    yield SimpleNamespace(run=run, output=output, prepared=prepared, children=children)
    if prepared._native_session is not None:
        prepared._native_session.close()
    for child in children:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        for stream in (child.stdin, child.stdout):
            if stream is not None:
                stream.close()


@pytest.mark.parametrize("mode", ["early", "race"])
def test_stream_early_exit_retains_observed_exit_and_stderr(stream_mapping, mode):
    with pytest.raises(FimEngineError, match="exit 7: budget exceeded: sloping decoder plan exceeds budget"):
        stream_mapping.run(mode)
    manifest=json.loads((stream_mapping.output/"fim_manifest.json").read_text())
    assert manifest["engine_returncode"] == 7
    assert manifest["engine_cleanup_termination_requested"] is False
    assert manifest["status"] == "aborted"
    assert all(p["status"] == "failed" for p in manifest["profiles"])
    assert not list(stream_mapping.output.glob("*.tif*"))


def test_stream_unsupported_exit_preserves_refusal_type(stream_mapping):
    with pytest.raises(_engine.EngineRefusal, match="exit 7: .*unsupported: source history"):
        stream_mapping.run("refusal")
    manifest=json.loads((stream_mapping.output/"fim_manifest.json").read_text())
    assert manifest["engine_returncode"] == 7


def test_live_malformed_stream_is_killed_without_inventing_engine_failure(stream_mapping):
    started=time.monotonic()
    with pytest.raises(FimEngineError, match="Invalid sloping stream header JSON") as failure:
        stream_mapping.run("malformed")
    assert "failed with exit" not in str(failure.value)
    assert time.monotonic()-started < 5
    manifest=json.loads((stream_mapping.output/"fim_manifest.json").read_text())
    assert manifest["engine_returncode"] is None
    assert manifest["engine_cleanup_termination_requested"] is True
    assert isinstance(manifest["engine_cleanup_returncode"], int)
    assert manifest["profiles"][0]["error"].startswith("FimEngineError:")


def test_stream_timeout_keeps_timeout_precedence(stream_mapping):
    with pytest.raises(FimEngineError, match="Sloping engine timed out after"):
        stream_mapping.run("idle", timeout=.05)
    manifest=json.loads((stream_mapping.output/"fim_manifest.json").read_text())
    assert manifest["engine_returncode"] is None


def test_stream_interrupt_is_not_replaced_by_cleanup_exit(stream_mapping):
    with pytest.raises(KeyboardInterrupt, match="original protocol interruption"):
        stream_mapping.run("idle", interrupt=True)
    manifest=json.loads((stream_mapping.output/"fim_manifest.json").read_text())
    assert manifest["engine_returncode"] is None
    assert manifest["engine_cleanup_termination_requested"] is True
    assert "KeyboardInterrupt" in manifest["profiles"][0]["error"]


def test_live_persistent_success_records_command_not_process_exit(stream_mapping):
    frame,_=stream_mapping.run("success", persistent=True)
    assert frame.iloc[0].status == "complete"
    assert stream_mapping.children[0].poll() is None
    manifest=json.loads((stream_mapping.output/"fim_manifest.json").read_text())
    assert manifest["engine_returncode"] is None
    assert manifest["engine_command_status"] == "complete"


def test_truncated_payload_preserves_real_process_diagnostic(stream_mapping):
    with pytest.raises(FimEngineError, match="exit 7: budget exceeded: synthetic payload failure"):
        stream_mapping.run("truncated")
    manifest=json.loads((stream_mapping.output/"fim_manifest.json").read_text())
    assert manifest["engine_returncode"] == 7


@pytest.mark.parametrize("persistent", [False, True])
def test_startup_oserror_is_typed_without_invented_exit(stream_mapping, persistent):
    with pytest.raises(FimEngineNotFoundError, match="synthetic process startup failure"):
        stream_mapping.run("success", persistent=persistent, startup=True)
    manifest=json.loads((stream_mapping.output/"fim_manifest.json").read_text())
    assert manifest["engine_returncode"] is None
    assert manifest["status"] == "aborted"
    assert stream_mapping.prepared._native_session is None


def test_dead_persistent_session_keeps_startup_stderr_and_closes(stream_mapping):
    with pytest.raises(FimEngineError, match="exit 7: budget exceeded: sloping decoder plan exceeds budget"):
        stream_mapping.run("success", persistent=True, dead_session=True)
    manifest=json.loads((stream_mapping.output/"fim_manifest.json").read_text())
    assert manifest["engine_returncode"] == 7
    assert "budget exceeded" in manifest["engine_stderr"]
    assert stream_mapping.prepared._native_session is None


def test_bad_persistent_terminal_does_not_invent_cleanup_exit(stream_mapping):
    with pytest.raises(FimEngineError, match="Invalid native session completion frame"):
        stream_mapping.run("bad-server", persistent=True)
    manifest=json.loads((stream_mapping.output/"fim_manifest.json").read_text())
    assert manifest["engine_returncode"] is None
    assert manifest["engine_cleanup_termination_requested"] is True
    assert stream_mapping.prepared._native_session is None
    assert not list(stream_mapping.output.glob("*.tif*"))


@pytest.mark.parametrize("command,component", [("one-d-diagnostic","xs"), ("sloping","two_d"), ("coupled-diagnostic","composition")])
@pytest.mark.parametrize("code,stderr", [(7,"budget exceeded"), (4,""), (3,"unsupported: source history")])
def test_component_failure_context_and_execution_record(tmp_path, monkeypatch, command, component, code, stderr):
    monkeypatch.setattr(_engine, "run_engine", lambda *a,**k: subprocess.CompletedProcess(a[0],code,"",stderr))
    reports=[]
    expected=_engine.EngineRefusal if "unsupported:" in stderr else FimEngineError
    with pytest.raises(expected, match=f"Coupled {component} engine failed with exit {code}") as failure:
        _coupled._run(Path("engine"),command,tmp_path/"request.json",tmp_path/"out",None,reports=reports,profile_id="p")
    assert (stderr.strip() or "no diagnostic on stderr") in str(failure.value)
    assert reports[0]["component"] == component
    assert reports[0]["profile_id"] == "p"
    assert reports[0]["engine_returncode"] == code
    assert reports[0]["status"] == "failed"


@pytest.mark.parametrize("content", [None, "invalid", "[]", b"\xff"])
def test_component_success_exit_requires_object_report(tmp_path, monkeypatch, content):
    out=tmp_path/"out";out.mkdir()
    if isinstance(content,bytes):
        (out/"report.json").write_bytes(content)
    elif content is not None:
        (out/"report.json").write_text(content)
    monkeypatch.setattr(_engine, "run_engine", lambda *a,**k: subprocess.CompletedProcess(a[0],0,"",""))
    reports=[]
    with pytest.raises(FimEngineError, match="Coupled two_d engine exited with 0"):
        _coupled._run(Path("engine"),"sloping",tmp_path/"request.json",out,None,reports=reports)
    assert reports[0]["engine_returncode"] == 0
    assert reports[0]["status"] == "failed"


@pytest.mark.parametrize("component", ["one-d-diagnostic", "sloping", "coupled-diagnostic"])
@pytest.mark.parametrize("raise_on_failure", [False, True])
def test_coupled_component_exit_is_preserved_in_failure_manifest(files, tmp_path, monkeypatch, component, raise_on_failure):
    engine=_prep_environment(tmp_path,monkeypatch)
    prepared=RasFim.prepare_coupled_model(*files,tmp_path/"prep",profiles={"p":0},allow_unqualified=True)
    _complete_engine(monkeypatch,tmp_path,engine)
    original=_engine.run_engine
    def fail(args,what,timeout=None):
        if args[1]==component:
            return subprocess.CompletedProcess(args,7,"","")
        return original(args,what,timeout)
    monkeypatch.setattr(_engine,"run_engine",fail)
    output=tmp_path/"mapped"
    if raise_on_failure:
        with pytest.raises(FimMappingError,match="engine failed with exit 7"):
            prepared.map_profiles(output,bbox=(0,0,5,5),allow_unqualified=True,max_working_mib=64)
    else:
        frame=prepared.map_profiles(output,bbox=(0,0,5,5),allow_unqualified=True,max_working_mib=64,raise_on_failure=False)
        assert frame.iloc[0].status=="failed"
    manifest=json.loads((output/"fim_manifest.json").read_text())
    assert manifest["status"]=="failed"
    failed=[r for r in manifest["reports"] if r.get("kind")=="engine_execution" and r["status"]=="failed"]
    assert len(failed)==1
    assert failed[0]["engine_returncode"]==7
    assert "no diagnostic on stderr" in failed[0]["error"]
    assert not list(output.glob("*.tif*"))
