"""Admission and actual CLR control checks for serial native polygon exports."""
from contextlib import contextmanager
from pathlib import Path
import os
import subprocess

import pytest

from ras_commander import _native_helper as helper


@pytest.fixture
def native_helper_call(monkeypatch, tmp_path):
    monkeypatch.setattr(helper, "_IS_LINUX", False)
    monkeypatch.setattr(helper, "_is_wine_helper_runtime", lambda: False)
    monkeypatch.setattr(helper, "_hecras_gdal_subprocess_env", lambda _: dict(os.environ))
    terrain = tmp_path / "SelectedTerrain.hdf"
    terrain.write_bytes(b"identity-only fixture")
    executable = tmp_path / "helper.exe"
    executable.write_bytes(b"not launched")

    @contextmanager
    def packaged():
        yield executable

    monkeypatch.setattr(helper, "packaged_helper_executable_path", packaged)
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, "RESULT_SUCCESS=True", "")

    monkeypatch.setattr(helper, "_run_store_map_process", run)
    args = dict(hecras_dir=tmp_path / "runtime", render_mode="sloping",
                map_type="ProfileMap:depth", result_hdf_path=tmp_path / "results.hdf",
                profile_name="Max", output_base_path=tmp_path / "boundary")
    return args, terrain, calls


def test_serial_polygon_binds_explicit_terrain_in_child_only(monkeypatch, native_helper_call):
    args, terrain, calls = native_helper_call
    monkeypatch.setenv("RAS_COMMANDER_STORE_MAP_POLYGON_SERIAL", "parent-value")
    monkeypatch.setenv("RAS_COMMANDER_STORE_MAP_TERRAIN_HDF", "parent-terrain")
    helper.run_store_map_helper(**args, native_polygon_serial=True, terrain_hdf_path=terrain)
    env = calls[0][1]["env"]
    assert env["RAS_COMMANDER_STORE_MAP_POLYGON_SERIAL"] == "1"
    assert env["RAS_COMMANDER_STORE_MAP_TERRAIN_HDF"] == str(terrain.resolve())
    assert calls[0][0][3:5] == ["StoreMap", "ProfileMap:depth"]
    assert os.environ["RAS_COMMANDER_STORE_MAP_POLYGON_SERIAL"] == "parent-value"
    assert os.environ["RAS_COMMANDER_STORE_MAP_TERRAIN_HDF"] == "parent-terrain"


def test_ordinary_map_does_not_inherit_polygon_controls(monkeypatch, native_helper_call):
    args, _, calls = native_helper_call
    monkeypatch.setenv("RAS_COMMANDER_STORE_MAP_POLYGON_SERIAL", "1")
    monkeypatch.setenv("RAS_COMMANDER_STORE_MAP_TERRAIN_HDF", "parent-terrain")
    helper.run_store_map_helper(**args)
    assert "RAS_COMMANDER_STORE_MAP_POLYGON_SERIAL" not in calls[0][1]["env"]
    assert "RAS_COMMANDER_STORE_MAP_TERRAIN_HDF" not in calls[0][1]["env"]


@pytest.mark.parametrize("flag", [None, 0, 1, "true"])
def test_serial_flag_requires_bool(flag, native_helper_call):
    args, terrain, calls = native_helper_call
    with pytest.raises(ValueError, match="boolean"):
        helper.run_store_map_helper(**args, native_polygon_serial=flag, terrain_hdf_path=terrain)
    assert not calls


@pytest.mark.parametrize("map_type", ["Velocity", "ProfileMap:elevation", "InundationBoundary"])
def test_serial_refuses_non_depth_map(map_type, native_helper_call):
    args, terrain, calls = native_helper_call
    args["map_type"] = map_type
    with pytest.raises(ValueError, match="Depth map"):
        helper.run_store_map_helper(**args, native_polygon_serial=True, terrain_hdf_path=terrain)
    assert not calls


def test_serial_refuses_missing_explicit_terrain(native_helper_call):
    args, _, calls = native_helper_call
    with pytest.raises(ValueError, match="requires terrain_hdf_path"):
        helper.run_store_map_helper(**args, native_polygon_serial=True)
    assert not calls


def test_serial_refuses_missing_terrain_file(native_helper_call):
    args, terrain, calls = native_helper_call
    with pytest.raises(FileNotFoundError):
        helper.run_store_map_helper(**args, native_polygon_serial=True,
                                    terrain_hdf_path=terrain.with_suffix(".missing"))
    assert not calls


def test_serial_refuses_terrain_directory(native_helper_call):
    args, terrain, calls = native_helper_call
    with pytest.raises(ValueError, match="must be a file"):
        helper.run_store_map_helper(**args, native_polygon_serial=True, terrain_hdf_path=terrain.parent)
    assert not calls


def test_explicit_terrain_cannot_silently_change_default_raster(native_helper_call):
    args, terrain, calls = native_helper_call
    with pytest.raises(ValueError, match="requires native_polygon_serial"):
        helper.run_store_map_helper(**args, terrain_hdf_path=terrain)
    assert not calls


@pytest.mark.parametrize("linux,wine", [(True, False), (False, True)])
def test_serial_refuses_unqualified_platform(monkeypatch, native_helper_call, linux, wine):
    args, terrain, calls = native_helper_call
    monkeypatch.setattr(helper, "_IS_LINUX", linux)
    monkeypatch.setattr(helper, "_is_wine_helper_runtime", lambda: wine)
    with pytest.raises(ValueError, match="requires native Windows"):
        helper.run_store_map_helper(**args, native_polygon_serial=True, terrain_hdf_path=terrain)
    assert not calls


@pytest.fixture(scope="module")
def serial_clr_harness(tmp_path_factory):
    if os.name != "nt":
        pytest.skip("Windows .NET Framework compiler required")
    compiler = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not compiler.is_file():
        pytest.skip("Windows .NET Framework compiler unavailable")
    folder = tmp_path_factory.mktemp("serial-clr")
    source = folder / "ControlProbe.cs"
    source.write_text('''using System;
using System.Reflection;
public class Good { private bool FORCE_POLYGON_SERIAL; public float ContourPolygonValue {get;set;}
 public bool Serial {get {return FORCE_POLYGON_SERIAL;}} }
public class Missing { public float ContourPolygonValue {get;set;} }
public class Wrong { private int FORCE_POLYGON_SERIAL; public float ContourPolygonValue {get;set;} }
public class ReadOnly { private bool FORCE_POLYGON_SERIAL; public float ContourPolygonValue {get {return 0;}} }
public class Dishonest { private bool FORCE_POLYGON_SERIAL; public float ContourPolygonValue {get {return 9;} set {}} }
public class TerrainTwo { public string SourceFilename; public TerrainTwo(string name,string path) {SourceFilename=path;} }
public class TerrainOptional { public string SourceFilename; public bool CanEdit; public TerrainOptional(string name,string path,bool canEdit=true) {SourceFilename=path;CanEdit=canEdit;} }
public class TerrainRequired { public TerrainRequired(string name,string path,bool required) {} }
class Probe { static int Main(string[] args) {
 if(args[1].StartsWith("terrain")) {
 Type terrainType=args[1]=="terrain-two" ? typeof(TerrainTwo) : args[1]=="terrain-optional" ? typeof(TerrainOptional) : typeof(TerrainRequired);
 MethodInfo create=Assembly.LoadFrom(args[0]).GetType("RasStoreMapHelper").GetMethod("CreateTerrainLayer",BindingFlags.Static|BindingFlags.NonPublic);
 try { object instance=create.Invoke(null,new object[]{terrainType,"selected.hdf"});
 if(args[1]=="terrain-required" || (string)terrainType.GetField("SourceFilename").GetValue(instance)!="selected.hdf") return 4;
 if(args[1]=="terrain-optional" && !((TerrainOptional)instance).CanEdit) return 5;
 Console.WriteLine("BOUND_TERRAIN=True"); return 0;
 } catch(TargetInvocationException exc) {Console.WriteLine(exc.InnerException.Message); return args[1]=="terrain-required" ? 0 : 3;}
 }
 object value = args[1]=="good" ? (object)new Good() : args[1]=="missing" ? new Missing() : args[1]=="wrong" ? new Wrong() : args[1]=="readonly" ? (object)new ReadOnly() : new Dishonest();
 MethodInfo configure=Assembly.LoadFrom(args[0]).GetType("RasStoreMapHelper").GetMethod("ConfigurePolygonSerial",BindingFlags.Static|BindingFlags.NonPublic);
 try {configure.Invoke(null,new object[]{value,value.GetType()});
 if (args[1]!="good" || !((Good)value).Serial || ((Good)value).ContourPolygonValue!=0) return 4;
 return 0; }
 catch(TargetInvocationException exc) {Console.WriteLine(exc.InnerException.Message); return args[1]=="good" ? 3 : 0;}
 }}''', encoding="utf-8")
    executable = folder / "ControlProbe.exe"
    result = subprocess.run([str(compiler), "/nologo", "/target:exe", f"/out:{executable}", str(source)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    with helper.packaged_helper_executable_path() as packaged:
        yield executable, packaged


@pytest.mark.parametrize("case,message", [("good", "NATIVE_POLYGON_SERIAL_EFFECTIVE=True"),
    ("missing", "FORCE_POLYGON_SERIAL is unavailable"), ("wrong", "FORCE_POLYGON_SERIAL is unavailable"),
    ("readonly", "ContourPolygonValue is unavailable"), ("dishonest", "readback failed")])
def test_actual_helper_clr_controls_fail_closed(serial_clr_harness, case, message):
    executable, packaged = serial_clr_harness
    result = subprocess.run([str(executable), str(packaged), case], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert message in result.stdout


@pytest.mark.parametrize("case,message", [("terrain-two", "BOUND_TERRAIN=True"),
    ("terrain-optional", "BOUND_TERRAIN=True"), ("terrain-required", "constructor not found")])
def test_actual_helper_clr_terrain_optional_argument_binding(serial_clr_harness, case, message):
    executable, packaged = serial_clr_harness
    result = subprocess.run([str(executable), str(packaged), case], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert message in result.stdout
