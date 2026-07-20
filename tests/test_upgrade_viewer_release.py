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
    / "upgrade_viewer_release.py"
)


def load_script():
    spec = importlib.util.spec_from_file_location("upgrade_viewer_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def legacy_manifest(layer_id: str = "geometry") -> dict:
    return {
        "schema": "rascommander.maplibre.project/1",
        "groups": [{"id": "ras-geometry-g01", "visible": True}],
        "tilesets": [
            {
                "id": "geometry",
                "type": "vector",
                "href": "tiles/geometry.pmtiles",
                "layers": [
                    {
                        "id": layer_id,
                        "name": "Model Extents",
                        "kind": "model_extents",
                        "sourceLayer": layer_id,
                        "groupId": "ras-geometry-g01",
                        "visible": True,
                    }
                ],
            }
        ],
        "sourceProject": "../project.json",
    }


def fake_apply(manifest: dict, *, archive=None) -> dict:
    layer = manifest["tilesets"][0]["layers"][0]
    manifest["schema"] = "rascommander.maplibre/v2"
    manifest["viewerTemplate"] = "rascommander.example-project-viewer/1"
    manifest["layers"] = {
        layer["id"]: {
            "name": layer["name"],
            "resource": "geometry",
            "role": layer["kind"],
        }
    }
    manifest["resources"] = {
        "geometry": {"type": "vector-pmtiles", "href": "tiles/geometry.pmtiles"}
    }
    manifest["tree"] = [
        {
            "id": "geometries",
            "name": "Geometries",
            "children": [{"layerId": layer["id"]}],
        }
    ]
    return manifest


def fake_validate(manifest: dict) -> None:
    if manifest.get("viewerTemplate") != "rascommander.example-project-viewer/1":
        raise ValueError("wrong viewer template")


def write_project(root: Path, project_id: str, manifest: dict | None = None) -> Path:
    project = root / "projects" / project_id
    viewer = project / "viewer"
    archive = project / "archive"
    viewer.mkdir(parents=True)
    archive.mkdir()
    path = viewer / "manifest.json"
    path.write_text(json.dumps(manifest or legacy_manifest()), encoding="utf-8")
    (archive / "manifest.json").write_text(json.dumps({"geometry": []}), encoding="utf-8")
    return path


def test_upgrade_release_dry_run_is_idempotent_and_does_not_write(tmp_path: Path) -> None:
    module = load_script()
    path = write_project(tmp_path, "one")
    original = path.read_bytes()

    report = module.upgrade_release(
        tmp_path,
        dry_run=True,
        apply_template=fake_apply,
        validate_template=fake_validate,
    )

    assert report["dryRun"] is True
    assert report["changed"] == 1
    assert report["projects"][0]["viewerTemplate"] == (
        "rascommander.example-project-viewer/1"
    )
    assert path.read_bytes() == original

    upgraded = module.upgrade_manifest(
        legacy_manifest(),
        archive=None,
        apply_template=fake_apply,
        validate_template=fake_validate,
    )
    assert module.upgrade_manifest(
        upgraded,
        archive=None,
        apply_template=fake_apply,
        validate_template=fake_validate,
    ) == upgraded


def test_upgrade_release_preflights_all_projects_before_writing(tmp_path: Path) -> None:
    module = load_script()
    first = write_project(tmp_path, "one")
    second = write_project(tmp_path, "two", legacy_manifest("drop-me"))
    original = first.read_bytes()

    def destructive_apply(manifest: dict, *, archive=None) -> dict:
        fake_apply(manifest, archive=archive)
        if "drop-me" in manifest["layers"]:
            manifest["layers"] = {}
        return manifest

    with pytest.raises(module.UpgradeError, match="layer IDs changed"):
        module.upgrade_release(
            tmp_path,
            apply_template=destructive_apply,
            validate_template=fake_validate,
        )

    assert first.read_bytes() == original
    assert json.loads(second.read_text(encoding="utf-8"))["schema"].endswith("/1")


def test_upgrade_rejects_removed_asset_reference_and_payload_change() -> None:
    module = load_script()

    def removed_reference(manifest: dict, *, archive=None) -> dict:
        fake_apply(manifest, archive=archive)
        manifest["sourceProject"] = "../different-project.json"
        return manifest

    with pytest.raises(module.UpgradeError, match="asset references were removed"):
        module.upgrade_manifest(
            legacy_manifest(),
            archive=None,
            apply_template=removed_reference,
            validate_template=fake_validate,
        )

    def changed_tilesets(manifest: dict, *, archive=None) -> dict:
        fake_apply(manifest, archive=archive)
        manifest["tilesets"][0]["href"] = "tiles/replaced.pmtiles"
        return manifest

    with pytest.raises(module.UpgradeError, match="compatibility payload changed: tilesets"):
        module.upgrade_manifest(
            legacy_manifest(),
            archive=None,
            apply_template=changed_tilesets,
            validate_template=fake_validate,
        )


def test_upgrade_release_selects_bounded_projects_and_writes_atomically(tmp_path: Path) -> None:
    module = load_script()
    selected = write_project(tmp_path, "one")
    untouched = write_project(tmp_path, "two")
    untouched_bytes = untouched.read_bytes()

    report = module.upgrade_release(
        tmp_path,
        selected=["one"],
        apply_template=fake_apply,
        validate_template=fake_validate,
    )

    assert [item["project"] for item in report["projects"]] == ["one"]
    assert json.loads(selected.read_text(encoding="utf-8"))["viewerTemplate"].endswith("/1")
    assert untouched.read_bytes() == untouched_bytes
    assert not list(selected.parent.glob(".manifest.json.*.tmp"))
