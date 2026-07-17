from pathlib import Path

from scripts.example_library.prepare_archive_metadata_v2 import (
    redact_local_paths,
    resolve_project_file,
)


def test_resolve_project_file_uses_geometry_hdf_stem(tmp_path: Path) -> None:
    project_root = tmp_path / "model"
    project_root.mkdir()
    (project_root / "Model.g02.hdf").write_bytes(b"hdf")
    expected = project_root / "Model.prj"
    expected.write_text("Proj Title=Model\n", encoding="ascii")

    result = resolve_project_file(tmp_path, {"id": "model", "geometry_hdf": "model/Model.g02.hdf"})

    assert result == expected


def test_redact_local_paths_preserves_relative_public_metadata() -> None:
    value = {
        "source": "C:/private/model/terrain.tif",
        "linux": "/mnt/clb/private/result.tif",
        "relative": "terrain/public.cog.tif",
        "url": "https://example.test/data.tif",
    }

    assert redact_local_paths(value) == {
        "source": "terrain.tif",
        "linux": "result.tif",
        "relative": "terrain/public.cog.tif",
        "url": "https://example.test/data.tif",
    }
