"""Tests for bounded RasMapperLib geometry operations."""

import importlib
from pathlib import Path
from types import SimpleNamespace

import h5py

from ras_commander.geom import GeomMesh
from ras_commander.native import geometry_host

geom_mesh_module = importlib.import_module("ras_commander.geom.GeomMesh")


def test_run_managed_geometry_association_returns_process_receipt(
    monkeypatch, tmp_path
):
    executable = tmp_path / "RasMapperGeometryHelper.exe"
    executable.touch()
    geometry_hdf = tmp_path / "model.g01.hdf"
    geometry_hdf.touch()
    terrain_hdf = tmp_path / "Terrain.hdf"
    terrain_hdf.touch()
    monkeypatch.setattr(
        geometry_host,
        "ensure_managed_geometry_host",
        lambda _hecras_dir: executable,
    )
    monkeypatch.setattr(geometry_host, "_native_wine_controller", lambda: False)
    monkeypatch.setattr(geometry_host, "is_wine_runtime", lambda: False)
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        receipt_path = Path(command[4])
        receipt_path.write_text(
            '{"status":"complete","action":"associate",'
            '"command_returned":true,"error":""}',
            encoding="utf-8",
        )
        receipt_path.with_name(receipt_path.name + ".progress").write_text(
            "0.1 runtime-loaded\n0.2 association-command-returned\n",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(geometry_host, "_bounded_run", fake_run)
    receipt = geometry_host.run_managed_geometry_association(
        geometry_hdf,
        tmp_path / "HEC-RAS",
        {"terrain_hdf_path": terrain_hdf},
    )

    assert calls[0][1] == "associate"
    assert calls[0][5] == str(terrain_hdf)
    assert calls[0][6:] == ["", "", ""]
    assert receipt["status"] == "complete"
    assert receipt["return_code"] == 0
    assert receipt["attempt_count"] == 1
    assert receipt["stage_trace"][-1].endswith(
        "association-command-returned"
    )


def test_run_managed_property_tables_passes_exact_mesh_and_force(
    monkeypatch, tmp_path
):
    executable = tmp_path / "RasMapperGeometryHelper.exe"
    executable.touch()
    geometry_hdf = tmp_path / "model.g01.hdf"
    geometry_hdf.touch()
    monkeypatch.setattr(
        geometry_host,
        "ensure_managed_geometry_host",
        lambda _hecras_dir: executable,
    )
    monkeypatch.setattr(geometry_host, "_native_wine_controller", lambda: False)
    monkeypatch.setattr(geometry_host, "is_wine_runtime", lambda: False)

    def fake_run(command, **_kwargs):
        receipt_path = Path(command[4])
        receipt_path.write_text(
            '{"status":"complete","action":"property-tables",'
            '"mesh_name":"MainArea","command_returned":true,"error":""}',
            encoding="utf-8",
        )
        assert command[5:] == ["MainArea", "True", "", "True"]
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(geometry_host, "_bounded_run", fake_run)
    receipt = geometry_host.run_managed_property_tables(
        geometry_hdf,
        "MainArea",
        tmp_path / "HEC-RAS",
        force=True,
    )

    assert receipt["command_returned"] is True
    assert receipt["return_code"] == 0


def test_geom_mesh_association_auto_routes_wine_to_managed_host(
    monkeypatch, tmp_path
):
    geometry_hdf = tmp_path / "model.g01.hdf"
    terrain_hdf = tmp_path / "Terrain.hdf"
    terrain_hdf.touch()
    with h5py.File(geometry_hdf, "w") as hdf_file:
        hdf_file.create_group("Geometry")

    monkeypatch.setattr(geom_mesh_module, "is_wine_runtime", lambda: True)
    monkeypatch.setattr(
        geom_mesh_module,
        "_load_dlls",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Python.NET should not load under Wine")
        ),
    )

    def fake_association(_hdf_path, _hecras_dir, _paths, **_kwargs):
        with h5py.File(geometry_hdf, "a") as hdf_file:
            hdf_file["Geometry"].attrs["Terrain Filename"] = b".\\Terrain.hdf"
        return {
            "status": "complete",
            "return_code": 0,
            "command_returned": True,
            "stage_trace": ["association-command-returned"],
        }

    monkeypatch.setattr(
        geom_mesh_module,
        "run_managed_geometry_association",
        fake_association,
    )
    evidence = {}
    result = GeomMesh.set_geometry_association(
        geometry_hdf,
        terrain_hdf_path=terrain_hdf,
        hecras_dir=tmp_path / "HEC-RAS",
        managed_host_evidence=evidence,
    )

    assert result == geometry_hdf.resolve()
    assert evidence["command_returned"] is True
    assert GeomMesh.get_geometry_association(geometry_hdf)[
        "terrain_hdf_path"
    ] == str(terrain_hdf.resolve())


def test_geom_mesh_property_tables_auto_routes_wine_to_managed_host(
    monkeypatch, tmp_path
):
    geometry_text = tmp_path / "model.g01"
    geometry_text.write_text("Geom Title=Qualification\n", encoding="utf-8")
    rasmap_path = tmp_path / "model.rasmap"
    rasmap_path.write_text("<RASMapper />\n", encoding="utf-8")
    geometry_hdf = tmp_path / "model.g01.hdf"
    with h5py.File(geometry_hdf, "w") as hdf_file:
        hdf_file.create_group("Geometry/2D Flow Areas/MainArea")

    monkeypatch.setattr(geom_mesh_module, "is_wine_runtime", lambda: True)
    monkeypatch.setattr(
        geom_mesh_module,
        "_ensure_hdf",
        lambda *_args, **_kwargs: geometry_hdf,
    )
    monkeypatch.setattr(
        geom_mesh_module,
        "_load_dlls",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Python.NET should not load under Wine")
        ),
    )
    captured = {}

    def fake_tables(_hdf_path, mesh_name, _hecras_dir, **kwargs):
        captured.update(mesh_name=mesh_name, **kwargs)
        return {
            "status": "complete",
            "return_code": 0,
            "command_returned": True,
        }

    monkeypatch.setattr(
        geom_mesh_module,
        "run_managed_property_tables",
        fake_tables,
    )
    evidence = {}
    result = GeomMesh.compute_property_tables(
        geometry_text,
        hecras_dir=tmp_path / "HEC-RAS",
        complete_geometry=False,
        managed_host_evidence=evidence,
    )

    assert result is True
    assert captured["mesh_name"] == "MainArea"
    assert captured["force"] is True
    assert captured["complete_geometry"] is False
    assert captured["rasmap_path"] == rasmap_path.resolve()
    assert evidence["command_returned"] is True
