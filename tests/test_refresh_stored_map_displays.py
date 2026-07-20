from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "example_library"
    / "refresh_stored_map_displays.py"
)


def load_script():
    spec = importlib.util.spec_from_file_location("refresh_stored_map_displays", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_refresh_project_preserves_numeric_cog_and_semantic_context(tmp_path: Path) -> None:
    module = load_script()
    project = tmp_path / "projects" / "muncie"
    viewer = project / "viewer"
    cog = project / "archive" / "stored-maps" / "p03" / "depth-max.cog.tif"
    viewer.mkdir(parents=True)
    cog.parent.mkdir(parents=True)
    cog.write_bytes(b"numeric-cog")
    manifest = {
        "tilesets": [
            {"id": "terrain", "type": "raster", "sourceKind": "terrain"},
            {
                "id": "result-p03-depth-max",
                "name": "Depth (Max) - RASMapper Stored Map",
                "type": "raster",
                "sourceKind": "stored-map",
                "sourceCog": "../archive/stored-maps/p03/depth-max.cog.tif",
                "visible": False,
                "units": "ft",
                "domainPolicy": "fixed",
                "storedMap": {
                    "plan": "p03",
                    "mapType": "Depth",
                    "profile": "Max",
                    "geometry": "g02",
                },
            },
        ]
    }
    manifest_path = viewer / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    calls = []

    def fake_packager(cog_path, viewer_dir, **kwargs):
        calls.append((cog_path, viewer_dir, kwargs))
        updated = json.loads(manifest_path.read_text(encoding="utf-8"))
        updated["tilesets"][1]["maxzoom"] = kwargs["max_zoom"]
        manifest_path.write_text(json.dumps(updated), encoding="utf-8")

    result = module.refresh_project(
        project,
        max_zoom=16,
        scratch_root=tmp_path / "scratch",
        packager=fake_packager,
    )

    assert cog.read_bytes() == b"numeric-cog"
    assert result == {
        "project": "muncie",
        "refreshed": 1,
        "maxZoom": 16,
        "layers": ["result-p03-depth-max"],
    }
    assert calls[0][0] == cog.resolve()
    assert calls[0][2]["plan"] == "p03"
    assert calls[0][2]["map_type"] == "Depth"
    assert calls[0][2]["geometry"] == "g02"
    assert calls[0][2]["max_zoom"] == 16
    assert calls[0][2]["overwrite"] is True


def test_refresh_project_rejects_hosted_numeric_source(tmp_path: Path) -> None:
    module = load_script()
    project = tmp_path / "projects" / "muncie"
    viewer = project / "viewer"
    viewer.mkdir(parents=True)
    (viewer / "manifest.json").write_text(
        json.dumps(
            {
                "tilesets": [
                    {
                        "id": "result-p03-depth-max",
                        "type": "raster",
                        "sourceKind": "stored-map",
                        "sourceCog": "https://example.test/depth.tif",
                        "storedMap": {"plan": "p03", "mapType": "Depth"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    try:
        module.refresh_project(
            project,
            max_zoom=16,
            scratch_root=tmp_path / "scratch",
            packager=lambda *_args, **_kwargs: None,
        )
    except module.RefreshError as error:
        assert "manifest-relative" in str(error)
    else:
        raise AssertionError("Hosted sourceCog should fail closed")


@pytest.mark.parametrize(
    "source_cog",
    [
        "/outside/depth.tif",
        r"C:\outside\depth.tif",
        r"\\server\share\depth.tif",
        "../../outside/depth.tif",
    ],
)
def test_refresh_project_rejects_sources_outside_staged_project(
    tmp_path: Path, source_cog: str
) -> None:
    module = load_script()
    project = tmp_path / "projects" / "muncie"
    viewer = project / "viewer"
    viewer.mkdir(parents=True)
    (viewer / "manifest.json").write_text(
        json.dumps(
            {
                "tilesets": [
                    {
                        "id": "result-p03-depth-max",
                        "type": "raster",
                        "sourceKind": "stored-map",
                        "sourceCog": source_cog,
                        "storedMap": {"plan": "p03", "mapType": "Depth"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.RefreshError, match="manifest-relative|staged project"):
        module.refresh_project(
            project,
            max_zoom=16,
            scratch_root=tmp_path / "scratch",
            packager=lambda *_args, **_kwargs: None,
        )
