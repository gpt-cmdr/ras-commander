#!/usr/bin/env python
"""Build the small JSON overlay for an immutable WebGIS release."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RELEASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
VERSION_ROOT_NAME = "hec-ras-7.0"
PUBLIC_VERSION_ROOT = f"/data/rasexamples/{VERSION_ROOT_NAME}"
ENCODED_VERSION_PREFIX_RE = re.compile(
    r"%2fdata%2frasexamples%2fhec-ras-7\.0%2f",
    re.IGNORECASE,
)
RASTER_ASSET_SCHEMA = "rascommander.raster-assets/v1"


def validate_release_id(release_id: str) -> str:
    """Return a release identifier safe for both URLs and filesystem paths."""

    if not RELEASE_ID_RE.fullmatch(release_id):
        raise ValueError(
            "Release ID must be 1-80 ASCII letters, digits, dots, underscores, "
            "or hyphens and must not start with punctuation."
        )
    return release_id


def release_public_root(release_id: str) -> str:
    """Return the public root for one immutable release."""

    return f"{PUBLIC_VERSION_ROOT}/releases/{validate_release_id(release_id)}"


def version_public_string(value: str, release_id: str) -> str:
    """Move stable project URLs into one immutable release namespace."""

    release_root = release_public_root(release_id)
    if value.rstrip("/") == PUBLIC_VERSION_ROOT:
        suffix = "/" if value.endswith("/") else ""
        return release_root + suffix
    value = value.replace(f"{PUBLIC_VERSION_ROOT}/", f"{release_root}/")
    encoded_release_prefix = (
        f"%2Fdata%2Frasexamples%2F{VERSION_ROOT_NAME}"
        f"%2Freleases%2F{release_id}%2F"
    )
    return ENCODED_VERSION_PREFIX_RE.sub(encoded_release_prefix, value)


def version_document(value: Any, release_id: str, *, key: str | None = None) -> Any:
    """Recursively version public URLs and numeric-service asset identifiers."""

    if isinstance(value, dict):
        return {
            item_key: version_document(item_value, release_id, key=item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [version_document(item, release_id) for item in value]
    if isinstance(value, str):
        if key == "serviceAsset" and not value.startswith("releases/"):
            return f"releases/{release_id}/{value}"
        return version_public_string(value, release_id)
    return value


def version_raster_catalog(document: dict[str, Any], release_id: str) -> dict[str, Any]:
    """Qualify catalog IDs and paths so older release assets can coexist."""

    if document.get("schema") != RASTER_ASSET_SCHEMA:
        raise ValueError("The release raster-assets.json has an unsupported schema")
    records = document.get("assets")
    if not isinstance(records, dict):
        raise ValueError("The release raster-assets.json has no asset mapping")
    prefix = f"releases/{release_id}/"
    assets: dict[str, dict[str, Any]] = {}
    for asset_id, record in records.items():
        if not isinstance(record, dict):
            raise ValueError(f"Raster asset {asset_id!r} is not an object")
        path = str(record.get("path") or "")
        if not path or path.startswith("/") or ".." in Path(path).parts:
            raise ValueError(f"Raster asset {asset_id!r} has an unsafe path")
        versioned_id = asset_id if asset_id.startswith(prefix) else prefix + asset_id
        versioned_record = dict(record)
        if not path.startswith(prefix):
            versioned_record["path"] = prefix + path.replace("\\", "/")
        assets[versioned_id] = versioned_record
    output = dict(document)
    output["releaseId"] = release_id
    output["dataRoot"] = "."
    output["assets"] = assets
    return output


def prepare_versioned_overlay(
    source_root: Path,
    output_root: Path,
    release_id: str,
) -> dict[str, Any]:
    """Write transformed JSON files without copying large release artifacts."""

    release_id = validate_release_id(release_id)
    source_root = Path(source_root).resolve()
    output_root = Path(output_root).resolve()
    if not source_root.is_dir() or source_root.name != VERSION_ROOT_NAME:
        raise ValueError(
            f"Source root must be an existing {VERSION_ROOT_NAME} directory"
        )
    if output_root == source_root or output_root.is_relative_to(source_root):
        raise ValueError("The overlay output must be outside the source release")
    output_root.mkdir(parents=True, exist_ok=True)
    transformed = 0
    metadata_paths = sorted(
        path
        for path in source_root.rglob("*")
        if path.suffix.lower() in {".json", ".geojson"}
    )
    for source_path in metadata_paths:
        if source_path.is_symlink():
            raise ValueError(f"Release JSON cannot be a symlink: {source_path}")
        relative_path = source_path.relative_to(source_root)
        document = json.loads(source_path.read_text(encoding="utf-8"))
        document = version_document(document, release_id)
        if relative_path.as_posix() == "raster-assets.json":
            document = version_raster_catalog(document, release_id)
        elif relative_path.as_posix() in {
            "catalog.json",
            "example-projects.geojson",
            "snapshot.json",
        }:
            if not isinstance(document, dict):
                raise ValueError(f"Release metadata must be an object: {source_path}")
            document["releaseId"] = release_id
        destination = output_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(document, indent=2) + "\n",
            encoding="utf-8",
        )
        transformed += 1

    required = (
        "catalog.json",
        "example-projects.geojson",
        "raster-assets.json",
        "snapshot.json",
    )
    missing = [name for name in required if not (output_root / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Release overlay is missing required metadata: {', '.join(missing)}"
        )
    release_document = {
        "schema": "rascommander.webgis.release/v1",
        "releaseId": release_id,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "baseUrl": release_public_root(release_id),
        "catalog": "catalog.json",
        "exampleProjects": "example-projects.geojson",
        "rasterAssets": "raster-assets.json",
    }
    (output_root / "release.json").write_text(
        json.dumps(release_document, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"releaseId": release_id, "jsonFiles": transformed + 1}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = prepare_versioned_overlay(
        args.source_root,
        args.output_root,
        args.release_id,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
