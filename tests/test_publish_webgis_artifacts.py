from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).parents[1]
    / "scripts"
    / "example_library"
    / "publish_webgis_artifacts.py"
)
SPEC = importlib.util.spec_from_file_location(
    "publish_webgis_artifacts",
    SCRIPT_PATH,
)
assert SPEC and SPEC.loader
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


def make_webgis_root(tmp_path: Path) -> Path:
    root = tmp_path / "data" / "rasexamples" / "hec-ras-7.0"
    root.mkdir(parents=True)
    (root / "example-projects.geojson").write_text(
        '{"type":"FeatureCollection"}\n',
        encoding="utf-8",
    )
    extent = root / "projects" / "muncie" / "viewer" / "model_extent.geojson"
    extent.parent.mkdir(parents=True)
    extent.write_text('{"type":"FeatureCollection"}\n', encoding="utf-8")
    return root


def test_validate_webgis_root_requires_expected_namespace(tmp_path: Path) -> None:
    root = make_webgis_root(tmp_path)
    assert publisher.validate_webgis_root(root) == root.resolve()

    invalid_root = tmp_path / "unexpected"
    invalid_root.mkdir()
    with pytest.raises(ValueError, match="must be named"):
        publisher.validate_webgis_root(invalid_root)


@pytest.mark.parametrize(
    "host",
    ["CLB03", "clb03.example.internal", "192.168.3.20"],
)
def test_validate_remote_host_accepts_hostnames_and_addresses(host: str) -> None:
    assert publisher.validate_remote_host(host) == host


@pytest.mark.parametrize("host", ["CLB03;id", "bad host", "root@CLB03"])
def test_validate_remote_host_rejects_remote_shell_syntax(host: str) -> None:
    with pytest.raises(ValueError):
        publisher.validate_remote_host(host)


@pytest.mark.parametrize(
    "path",
    ["/mnt/pool_12tb/staging", "/usr/local/sbin/publisher"],
)
def test_validate_remote_path_accepts_absolute_paths(path: str) -> None:
    assert publisher.validate_remote_path(path, label="test") == path


@pytest.mark.parametrize("path", ["relative/path", "/tmp/../escape", "/tmp;id"])
def test_validate_remote_path_rejects_shell_syntax_and_traversal(path: str) -> None:
    with pytest.raises(ValueError):
        publisher.validate_remote_path(path, label="test")


@pytest.mark.parametrize(
    "release_id",
    ["a", "rasexamples-20260713T203000Z", "v1.2_3"],
)
def test_validate_release_id_accepts_safe_values(release_id: str) -> None:
    assert publisher.validate_release_id(release_id) == release_id


@pytest.mark.parametrize(
    "release_id",
    ["", "../escape", "bad space", "-starts-with-punctuation"],
)
def test_validate_release_id_rejects_unsafe_values(release_id: str) -> None:
    with pytest.raises(ValueError):
        publisher.validate_release_id(release_id)


def test_build_manifest_uses_size_inventory_by_default(tmp_path: Path) -> None:
    root = make_webgis_root(tmp_path)
    manifest = publisher.build_manifest(root, "rasexamples-test")

    assert manifest["schemaVersion"] == 2
    assert manifest["releaseId"] == "rasexamples-test"
    assert manifest["integrity"] == "size"
    assert [item["path"] for item in manifest["files"]] == [
        "data/rasexamples/hec-ras-7.0/example-projects.geojson",
        "data/rasexamples/hec-ras-7.0/projects/muncie/viewer/model_extent.geojson",
    ]
    assert all("sha256" not in item for item in manifest["files"])


def test_build_manifest_can_include_sha256(tmp_path: Path) -> None:
    root = make_webgis_root(tmp_path)
    manifest = publisher.build_manifest(
        root,
        "rasexamples-test",
        integrity="sha256",
    )

    assert manifest["integrity"] == "sha256"
    by_path = {item["path"]: item for item in manifest["files"]}
    assert by_path[
        "data/rasexamples/hec-ras-7.0/example-projects.geojson"
    ]["sha256"] == publisher.file_sha256(root / "example-projects.geojson")
    assert by_path[
        "data/rasexamples/hec-ras-7.0/projects/muncie/viewer/model_extent.geojson"
    ]["sha256"] == publisher.file_sha256(
        root / "projects" / "muncie" / "viewer" / "model_extent.geojson"
    )


def test_build_manifest_rejects_unknown_integrity_mode(tmp_path: Path) -> None:
    root = make_webgis_root(tmp_path)

    with pytest.raises(ValueError, match="integrity mode"):
        publisher.build_manifest(
            root,
            "rasexamples-test",
            integrity="crc32",
        )


def test_build_manifest_rejects_symlinks(tmp_path: Path) -> None:
    root = make_webgis_root(tmp_path)
    try:
        (root / "linked.json").symlink_to(root / "example-projects.geojson")
    except OSError as error:
        pytest.skip(f"The current Windows token cannot create symlinks: {error}")

    with pytest.raises(ValueError, match="Symlinks"):
        publisher.build_manifest(root, "rasexamples-test")
