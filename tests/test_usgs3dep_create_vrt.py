from importlib import import_module
import pytest
import subprocess


usgs_module = import_module("ras_commander.terrain.Usgs3depAws")
Usgs3depAws = usgs_module.Usgs3depAws


def test_create_vrt_prefers_hecras_gdalbuildvrt(monkeypatch, tmp_path):
    tile_a = tmp_path / "tile_a.tif"
    tile_b = tmp_path / "tile_b.tif"
    tile_a.write_text("a", encoding="utf-8")
    tile_b.write_text("b", encoding="utf-8")

    output_vrt = tmp_path / "terrain.vrt"
    gdalbuildvrt = tmp_path / "gdalbuildvrt.exe"
    gdalbuildvrt.write_text("", encoding="utf-8")
    input_list_path = tmp_path / "gdalbuildvrt-input.txt"

    calls = []

    def fake_run(cmd, capture_output, text, timeout):
        calls.append((cmd, capture_output, text, timeout))
        assert input_list_path.read_text(encoding="utf-8").splitlines() == [
            str(tile_a),
            str(tile_b),
        ]
        output_vrt.write_text("<VRTDataset />", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        Usgs3depAws,
        "_find_gdalbuildvrt_path",
        staticmethod(lambda hecras_version=None: gdalbuildvrt),
    )
    monkeypatch.setattr(usgs_module.subprocess, "run", fake_run)

    def fake_write_input_file_list(tile_paths, output_dir):
        input_list_path.write_text(
            "".join(f"{tile_path}\n" for tile_path in tile_paths),
            encoding="utf-8",
        )
        return input_list_path

    monkeypatch.setattr(
        Usgs3depAws,
        "_write_gdal_input_file_list",
        staticmethod(fake_write_input_file_list),
    )

    result = Usgs3depAws.create_vrt([tile_a, tile_b], output_vrt)

    assert result == output_vrt
    assert not input_list_path.exists()
    assert calls == [
        (
            [
                str(gdalbuildvrt),
                "-overwrite",
                "-r",
                "bilinear",
                "-input_file_list",
                str(input_list_path),
                str(output_vrt),
            ],
            True,
            True,
            600,
        )
    ]


def test_create_vrt_requires_hecras_gdalbuildvrt(monkeypatch, tmp_path):
    tile_a = tmp_path / "tile_a.tif"
    tile_b = tmp_path / "tile_b.tif"
    tile_a.write_text("a", encoding="utf-8")
    tile_b.write_text("b", encoding="utf-8")

    output_vrt = tmp_path / "terrain.vrt"

    monkeypatch.setattr(
        Usgs3depAws,
        "_find_gdalbuildvrt_path",
        staticmethod(
            lambda hecras_version=None: (_ for _ in ()).throw(FileNotFoundError("not installed"))
        ),
    )

    with pytest.raises(FileNotFoundError, match="requires HEC-RAS bundled gdalbuildvrt.exe"):
        Usgs3depAws.create_vrt([tile_a, tile_b], output_vrt)


def test_find_gdalbuildvrt_path_uses_explicit_version(monkeypatch, tmp_path):
    ras_66 = tmp_path / "6.6"
    gdal_bin = ras_66 / "GDAL" / "bin64"
    gdal_bin.mkdir(parents=True)
    gdalbuildvrt = gdal_bin / "gdalbuildvrt.exe"
    gdalbuildvrt.write_text("", encoding="utf-8")

    ras_terrain_module = import_module("ras_commander.terrain.RasTerrain")
    RasTerrain = ras_terrain_module.RasTerrain

    monkeypatch.setattr(
        RasTerrain,
        "_get_hecras_path",
        staticmethod(lambda version: ras_66 if version == "6.6" else None),
    )

    result = Usgs3depAws._find_gdalbuildvrt_path("6.6")

    assert result == gdalbuildvrt


def test_find_gdalbuildvrt_path_discovers_point_release_via_install_scan(monkeypatch, tmp_path):
    ras_terrain_module = import_module("ras_commander.terrain.RasTerrain")
    RasTerrain = ras_terrain_module.RasTerrain

    base_dir = tmp_path / "HEC-RAS"
    install_dir = base_dir / "6.6.1"
    gdal_bin = install_dir / "GDAL" / "bin64"
    gdal_bin.mkdir(parents=True)
    gdalbuildvrt = gdal_bin / "gdalbuildvrt.exe"
    gdalbuildvrt.write_text("", encoding="utf-8")

    monkeypatch.setattr(RasTerrain, "_HECRAS_BASE_PATHS", [base_dir])
    monkeypatch.setattr(
        RasTerrain,
        "get_available_versions",
        staticmethod(lambda: []),
    )

    result = Usgs3depAws._find_gdalbuildvrt_path()

    assert result == gdalbuildvrt


def test_find_gdalbuildvrt_path_prefers_newest_installed_version(monkeypatch, tmp_path):
    ras_terrain_module = import_module("ras_commander.terrain.RasTerrain")
    RasTerrain = ras_terrain_module.RasTerrain

    install_66 = tmp_path / "6.6"
    install_70 = tmp_path / "7.0"

    for install_dir in (install_66, install_70):
        gdal_bin = install_dir / "GDAL" / "bin64"
        gdal_bin.mkdir(parents=True)
        (gdal_bin / "gdalbuildvrt.exe").write_text("", encoding="utf-8")

    install_map = {
        "6.6": install_66,
        "7.0": install_70,
    }

    monkeypatch.setattr(
        RasTerrain,
        "get_available_versions",
        staticmethod(lambda: ["6.6", "7.0"]),
    )
    monkeypatch.setattr(
        RasTerrain,
        "_get_hecras_path",
        staticmethod(lambda version: install_map[version]),
    )

    result = Usgs3depAws._find_gdalbuildvrt_path()

    assert result == install_70 / "GDAL" / "bin64" / "gdalbuildvrt.exe"


def test_write_gdal_input_file_list_writes_one_tile_per_line(tmp_path):
    tile_a = tmp_path / "tile_a.tif"
    tile_b = tmp_path / "tile_b.tif"

    path = Usgs3depAws._write_gdal_input_file_list([tile_a, tile_b], tmp_path)

    try:
        assert path.parent == tmp_path
        assert path.read_text(encoding="utf-8").splitlines() == [
            str(tile_a),
            str(tile_b),
        ]
    finally:
        path.unlink(missing_ok=True)


@pytest.mark.parametrize("resolution", [10, 30])
def test_download_tiles_rejects_non_1m_resolutions(tmp_path, resolution):
    with pytest.raises(NotImplementedError, match="currently supports only 1m"):
        Usgs3depAws.download_tiles(
            bbox=(-77.1, 40.6, -77.0, 40.7),
            resolution=resolution,
            output_folder=tmp_path,
        )
