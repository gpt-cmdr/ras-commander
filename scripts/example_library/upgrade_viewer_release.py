#!/usr/bin/env python
"""Apply the current ras2cng viewer template to an Example Library release."""

from __future__ import annotations

import argparse
import copy
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


ApplyTemplate = Callable[..., dict[str, Any]]
ValidateTemplate = Callable[[Mapping[str, Any]], None]

ASSET_REFERENCE_KEYS = {
    "baseUrl",
    "href",
    "samplePath",
    "sourceCog",
    "sourceProject",
    "statisticsPath",
    "tilePath",
}


class UpgradeError(RuntimeError):
    """Raised when a release cannot be upgraded without losing content."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UpgradeError(f"Could not read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise UpgradeError(f"Expected a JSON object: {path}")
    return value


def write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def layer_ids(manifest: Mapping[str, Any]) -> set[str]:
    layers = manifest.get("layers")
    if isinstance(layers, Mapping):
        return {str(layer_id) for layer_id in layers}
    result: set[str] = set()
    for tileset in manifest.get("tilesets") or []:
        if not isinstance(tileset, Mapping):
            continue
        if tileset.get("type") == "vector":
            for layer in tileset.get("layers") or []:
                if isinstance(layer, Mapping) and layer.get("id"):
                    result.add(str(layer["id"]))
        elif tileset.get("id"):
            result.add(str(tileset["id"]))
    return result


def asset_references(value: Any) -> Counter[tuple[str, str]]:
    references: Counter[tuple[str, str]] = Counter()

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if key in ASSET_REFERENCE_KEYS and isinstance(child, str) and child:
                    references[(str(key), child)] += 1
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return references


def _preserved_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(manifest[key])
        for key in ("tilesets", "groups", "services")
        if key in manifest
    }


def upgrade_manifest(
    manifest: Mapping[str, Any],
    *,
    archive: Mapping[str, Any] | None,
    apply_template: ApplyTemplate,
    validate_template: ValidateTemplate,
) -> dict[str, Any]:
    """Return one upgraded manifest after fail-closed preservation checks."""

    before = copy.deepcopy(dict(manifest))
    before_ids = layer_ids(before)
    before_references = asset_references(before)
    preserved = _preserved_payload(before)
    candidate = copy.deepcopy(before)

    apply_template(candidate, archive=archive)
    validate_template(candidate)

    after_ids = layer_ids(candidate)
    if before_ids != after_ids:
        missing = sorted(before_ids - after_ids)
        added = sorted(after_ids - before_ids)
        raise UpgradeError(
            f"Viewer layer IDs changed; missing={missing}, added={added}"
        )
    for key, expected in preserved.items():
        if candidate.get(key) != expected:
            raise UpgradeError(f"Viewer compatibility payload changed: {key}")
    missing_references = before_references - asset_references(candidate)
    if missing_references:
        detail = sorted(
            f"{key}={value!r} ({count})"
            for (key, value), count in missing_references.items()
        )
        raise UpgradeError("Viewer asset references were removed: " + ", ".join(detail))
    return candidate


def discover_projects(release_root: Path, selected: Sequence[str]) -> list[Path]:
    projects_root = release_root / "projects"
    if not projects_root.is_dir():
        raise UpgradeError(f"Release projects directory does not exist: {projects_root}")
    available = {
        path.name: path
        for path in projects_root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    }
    if selected:
        unknown = sorted(set(selected) - set(available))
        if unknown:
            raise UpgradeError("Project(s) absent from release: " + ", ".join(unknown))
        return [available[project_id] for project_id in selected]
    return [available[project_id] for project_id in sorted(available)]


def upgrade_release(
    release_root: Path,
    *,
    selected: Sequence[str] = (),
    dry_run: bool = False,
    apply_template: ApplyTemplate,
    validate_template: ValidateTemplate,
) -> dict[str, Any]:
    """Preflight and then atomically replace selected project manifests."""

    candidates: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []
    reports: list[dict[str, Any]] = []
    for project in discover_projects(release_root, selected):
        viewer_path = project / "viewer" / "manifest.json"
        archive_path = project / "archive" / "manifest.json"
        if not viewer_path.is_file():
            raise UpgradeError(f"Viewer manifest does not exist: {viewer_path}")
        before = read_json(viewer_path)
        archive = read_json(archive_path) if archive_path.is_file() else None
        candidate = upgrade_manifest(
            before,
            archive=archive,
            apply_template=apply_template,
            validate_template=validate_template,
        )
        candidates.append((viewer_path, before, candidate))
        reports.append(
            {
                "project": project.name,
                "schema": candidate.get("schema"),
                "viewerTemplate": candidate.get("viewerTemplate"),
                "layers": len(layer_ids(candidate)),
                "changed": before != candidate,
            }
        )

    if not dry_run:
        for viewer_path, _before, candidate in candidates:
            write_json_atomic(viewer_path, candidate)
    return {
        "schema": "rascommander.example-viewer-template-report/v1",
        "releaseRoot": str(release_root.resolve()),
        "dryRun": dry_run,
        "projects": reports,
        "changed": sum(1 for item in reports if item["changed"]),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--project", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    from ras2cng.viewer_manifest import apply_manifest_v2, validate_manifest_v2

    report = upgrade_release(
        args.release_root.resolve(),
        selected=args.project,
        dry_run=args.dry_run,
        apply_template=apply_manifest_v2,
        validate_template=validate_manifest_v2,
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(args.report, report)
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except UpgradeError as error:
        raise SystemExit(f"Viewer release upgrade stopped: {error}") from None
