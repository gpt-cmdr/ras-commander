#!/usr/bin/env python3
"""Capture and compare matched RASMapper and RAS Commander web views."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil
import sys
from typing import Any, Mapping
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen


SCHEMA = "rascommander.rasmapper-web-parity/v1"


def load_spec(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        spec = json.loads(text)
    else:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("PyYAML is required for YAML review specifications") from exc
        spec = yaml.safe_load(text)
    if not isinstance(spec, dict) or spec.get("schema") != SCHEMA:
        raise ValueError(f"Review specification must use schema {SCHEMA!r}")
    for key in ("project", "project_crs", "web_viewer_url", "web_manifest_url"):
        if not spec.get(key):
            raise ValueError(f"Review specification is missing {key!r}")
    return spec


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def copy_review_project(spec: Mapping[str, Any], output: Path) -> Path:
    source_project = Path(str(spec["project"])).resolve()
    if not source_project.is_file():
        raise FileNotFoundError(f"Computed HEC-RAS project does not exist: {source_project}")
    target_dir = output / "workspace" / source_project.parent.name
    target_project = target_dir / source_project.name
    if not target_project.exists():
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_project.parent, target_dir)
    return target_project


def prepare_rasmapper_project(spec: Mapping[str, Any], project: Path) -> dict[str, Any] | None:
    """Register a dynamic result map in the disposable review project when requested."""

    result = spec.get("rasmapper_result")
    if not result:
        return None
    required = ("plan", "plan_name", "layer_name", "map_type")
    missing = [key for key in required if not result.get(key)]
    if missing:
        raise ValueError("rasmapper_result is missing: " + ", ".join(missing))

    from ras_commander import RasMap, init_ras_project

    ras_object = init_ras_project(
        project,
        str(spec.get("ras_version") or "7.0"),
        ras_object="new",
        load_results_summary=False,
        hide_intro=True,
    )
    RasMap.ensure_results_plan_layer(
        result["plan"],
        name=str(result["plan_name"]),
        ras_object=ras_object,
    )
    return RasMap.add_results_map_layer(
        str(result["plan_name"]),
        str(result["layer_name"]),
        str(result["map_type"]),
        terrain_name=result.get("terrain_name") or spec.get("terrain_name"),
        profile_index=int(result.get("profile_index", 2147483647)),
        profile_name=str(result.get("profile_name") or "Max"),
        checked=True,
        replace_existing=True,
        ras_object=ras_object,
    )


def capture_rasmapper(spec: Mapping[str, Any], output: Path) -> dict[str, Any]:
    from ras_commander import RasMap

    project = copy_review_project(spec, output)
    configured_result = prepare_rasmapper_project(spec, project)
    result_setup = spec.get("rasmapper_result") or {}
    result_plan_name = spec.get("plan_name") or result_setup.get("plan_name")
    result_layer_name = spec.get("result_layer_name") or result_setup.get("layer_name")
    viewport = spec.get("rasmapper") or {}
    state = RasMap.create_spatial_review_package(
        project,
        output_dir=output / "rasmapper",
        geometry_number=spec.get("geometry_number"),
        geometry_name=spec.get("geometry_name"),
        layer_type=spec.get("geometry_layers"),
        terrain_name=spec.get("terrain_name"),
        result_plan_name=result_plan_name,
        result_layer_name=result_layer_name,
        result_layer_type="RASResultsMap" if result_layer_name else None,
        include_results=bool(result_layer_name),
        include_map_layers=False,
        update_legend_with_view=spec.get("range_mode") == "current-view",
        zoom_to_layer=True,
        capture_snapshot=True,
        delay_seconds=float(viewport.get("render_delay_seconds", 15)),
        snapshot_timeout_seconds=float(viewport.get("timeout_seconds", 1800)),
        require_snapshot=True,
        viewport_width=int(viewport.get("width", 1440)),
        viewport_height=int(viewport.get("height", 900)),
        dpi=int(viewport.get("dpi", 96)),
        expanded_tree_paths=spec.get("expanded_tree_paths"),
        ramp_id=spec.get("ramp_id"),
        range_mode=spec.get("range_mode"),
        selected_layer=spec.get("selected_web_layer"),
        result_profile=spec.get("result_profile"),
        render_mode=spec.get("render_mode"),
        basemap=spec.get("basemap"),
        ras_version=str(spec.get("ras_version") or "7.0"),
        web_manifest_url=str(spec["web_manifest_url"]),
    )
    state["configured_result"] = configured_result
    atomic_json(output / "rasmapper" / "review_state.json", state)
    return state


def _wgs84_bounds(spec: Mapping[str, Any], output: Path) -> list[float] | None:
    explicit = spec.get("bounds_wgs84")
    if explicit:
        return [float(value) for value in explicit]
    state_path = output / "rasmapper" / "review_state.json"
    if not state_path.is_file():
        return None
    state = json.loads(state_path.read_text(encoding="utf-8"))
    view = state.get("current_view_after") or {}
    values = [view.get(key) for key in ("min_x", "min_y", "max_x", "max_y")]
    if any(value is None for value in values):
        return None
    from pyproj import Transformer

    transformer = Transformer.from_crs(spec["project_crs"], "EPSG:4326", always_xy=True)
    west, south = transformer.transform(float(values[0]), float(values[1]))
    east, north = transformer.transform(float(values[2]), float(values[3]))
    return [west, south, east, north]


def capture_web(spec: Mapping[str, Any], output: Path) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Python Playwright is required for automated web capture; install it and Chromium"
        ) from exc

    bounds = _wgs84_bounds(spec, output)
    capture_dir = output / "web"
    capture_dir.mkdir(parents=True, exist_ok=True)
    records: dict[str, Any] = {"bounds_wgs84": bounds, "captures": {}}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for mode in ("desktop", "mobile"):
            viewport = spec.get(mode) or {}
            width = int(viewport.get("width", 1440 if mode == "desktop" else 390))
            height = int(viewport.get("height", 1100 if mode == "desktop" else 844))
            context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1)
            page = context.new_page()
            page.goto(str(spec["web_viewer_url"]), wait_until="domcontentloaded", timeout=120_000)
            page.wait_for_function("window.__rasCommanderViewerInstances?.length > 0", timeout=120_000)
            page.evaluate(
                """({spec, bounds}) => {
                  const viewer = window.__rasCommanderViewerInstances[0];
                  for (const [layerId] of Object.entries(viewer.manifest.layers || {})) {
                    if (layerId !== 'basemap-hybrid') viewer.setLayerVisible(layerId, false);
                  }
                  for (const layerId of spec.visible_web_layers || []) {
                    viewer.setLayerVisible(layerId, true);
                  }
                  if (spec.selected_web_layer) viewer.setActiveLayer(spec.selected_web_layer);
                  if (spec.selected_web_layer && spec.range_mode) {
                    viewer.setRangeMode(spec.selected_web_layer, spec.range_mode, {
                      exact: Boolean(spec.exact_range), domain: spec.custom_domain || null
                    });
                  }
                  if (bounds) {
                    viewer.map.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], {
                      padding: 40, duration: 0
                    });
                  }
                }""",
                {"spec": dict(spec), "bounds": bounds},
            )
            page.wait_for_function(
                """(layerId) => {
                  const viewer = window.__rasCommanderViewerInstances[0];
                  return viewer.map.loaded() && viewer.isIdle(layerId);
                }""",
                arg=spec.get("selected_web_layer"),
                timeout=120_000,
            )
            page.wait_for_timeout(1500)
            paths = {
                "page": capture_dir / f"{mode}-page.png",
                "map": capture_dir / f"{mode}-map.png",
                "tree": capture_dir / f"{mode}-tree.png",
                "legend": capture_dir / f"{mode}-legend.png",
            }
            page.screenshot(path=str(paths["page"]), full_page=True)
            page.locator("[data-map]").screenshot(path=str(paths["map"]))
            page.locator("[data-layer-list]").screenshot(path=str(paths["tree"]))
            legend = page.locator(".ras-raster-style").first
            if legend.count():
                legend.screenshot(path=str(paths["legend"]))
            records["captures"][mode] = {key: str(path) for key, path in paths.items() if path.exists()}
            context.close()
        browser.close()
    atomic_json(capture_dir / "capture-state.json", records)
    return records


def fetch_manifest(url: str) -> dict[str, Any]:
    direct_path = Path(url)
    if direct_path.is_file():
        return json.loads(direct_path.read_text(encoding="utf-8"))
    parsed = urlparse(url)
    if parsed.scheme in {"", "file"}:
        local_path = Path(unquote(parsed.path if parsed.scheme else url))
        return json.loads(local_path.read_text(encoding="utf-8"))
    request = Request(url, headers={"User-Agent": "ras-commander-parity/1"})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def semantic_assertions(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    manifest = fetch_manifest(str(spec["web_manifest_url"]))
    observed_roots = [item.get("id") for item in manifest.get("tree", [])]
    expected_roots = list(spec.get("expected_roots") or [])
    layers = manifest.get("layers") or {}
    checks = [
        {
            "id": "manifest-v2",
            "passed": manifest.get("schema") == "rascommander.maplibre/v2",
            "observed": manifest.get("schema"),
        },
        {
            "id": "semantic-roots",
            "passed": not expected_roots or observed_roots == expected_roots,
            "observed": observed_roots,
            "expected": expected_roots,
        },
    ]
    for layer_id in spec.get("required_web_layers") or []:
        checks.append({"id": f"layer:{layer_id}", "passed": layer_id in layers})
    return checks


def numeric_probes(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    probes = []
    if not spec.get("numeric_probes"):
        return probes
    import rasterio
    import numpy as np
    from rasterio.warp import transform

    for item in spec["numeric_probes"]:
        result = {"id": item["id"], "raster": item["raster"]}
        try:
            with rasterio.open(item["raster"]) as source:
                xs, ys = transform(
                    item.get("coordinate_crs", "EPSG:4326"),
                    source.crs,
                    [float(item["x"])],
                    [float(item["y"])],
                )
                sample = next(source.sample([(xs[0], ys[0])], masked=True))[0]
                value = None if np.ma.is_masked(sample) else float(sample)
            expected = float(item["expected"])
            tolerance = float(item.get("tolerance", 0))
            result.update(
                value=value,
                expected=expected,
                tolerance=tolerance,
                passed=value is not None and abs(value - expected) <= tolerance,
            )
        except Exception as error:
            result.update(value=None, passed=False, error=str(error))
        probes.append(result)
    return probes


def global_ssim(left, right) -> float:
    import numpy as np

    x = np.asarray(left.convert("L"), dtype="float64") / 255.0
    y = np.asarray(right.convert("L"), dtype="float64") / 255.0
    c1, c2 = 0.01**2, 0.03**2
    mean_x, mean_y = x.mean(), y.mean()
    var_x, var_y = x.var(), y.var()
    covariance = ((x - mean_x) * (y - mean_y)).mean()
    return float(((2 * mean_x * mean_y + c1) * (2 * covariance + c2)) /
                 ((mean_x**2 + mean_y**2 + c1) * (var_x + var_y + c2)))


def image_comparison(reference: Path, candidate: Path, crop, output: Path) -> dict[str, Any]:
    from PIL import Image, ImageChops, ImageOps
    import numpy as np

    with Image.open(reference) as source:
        left = source.convert("RGB").crop(tuple(crop)) if crop else source.convert("RGB")
    with Image.open(candidate) as source:
        right = ImageOps.fit(source.convert("RGB"), left.size)
    diff = ImageChops.difference(left, right)
    output.parent.mkdir(parents=True, exist_ok=True)
    diff.save(output)
    mae = float(np.asarray(diff, dtype="float64").mean() / 255.0)
    return {
        "reference": str(reference),
        "candidate": str(candidate),
        "diff": str(output),
        "ssim": global_ssim(left, right),
        "normalized_mae": mae,
        "size": list(left.size),
    }


def contact_sheet(paths: list[Path], output: Path) -> None:
    from PIL import Image, ImageOps

    images = []
    for path in paths:
        if path.is_file():
            with Image.open(path) as image:
                images.append(ImageOps.contain(image.convert("RGB"), (640, 420)))
    if not images:
        return
    width = 1280
    rows = math.ceil(len(images) / 2)
    sheet = Image.new("RGB", (width, rows * 440), "white")
    for index, image in enumerate(images):
        x = (index % 2) * 640
        y = (index // 2) * 440
        sheet.paste(image, (x, y))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def compare(spec: Mapping[str, Any], output: Path) -> dict[str, Any]:
    rasmapper = output / "rasmapper" / "rasmapper_spatial_review.png"
    comparisons = []
    regions = spec.get("rasmapper_regions") or {}
    for region in ("map", "tree", "legend"):
        candidate = output / "web" / f"desktop-{region}.png"
        if rasmapper.is_file() and candidate.is_file() and regions.get(region):
            comparisons.append(
                {
                    "region": region,
                    **image_comparison(
                        rasmapper,
                        candidate,
                        regions[region],
                        output / "comparison" / f"{region}-diff.png",
                    ),
                }
            )
    semantics = semantic_assertions(spec)
    probes = numeric_probes(spec)
    findings = []
    for check in semantics:
        if not check.get("passed"):
            findings.append({"classification": "Confirmed", "id": check["id"]})
    for probe in probes:
        if not probe.get("passed"):
            findings.append({"classification": "Confirmed", "id": f"probe:{probe['id']}"})
    for item in comparisons:
        if item["ssim"] < float(spec.get("image_ssim_warning", 0.65)):
            findings.append({"classification": "Likely", "id": f"image:{item['region']}"})
    if not comparisons:
        findings.append({"classification": "Uncertain", "id": "paired-images-missing"})
    report = {
        "schema": SCHEMA,
        "semantic_assertions": semantics,
        "numeric_probes": probes,
        "image_comparisons": comparisons,
        "findings": findings,
    }
    comparison_dir = output / "comparison"
    atomic_json(comparison_dir / "comparison.json", report)
    contact_sheet(
        [
            rasmapper,
            output / "web" / "desktop-page.png",
            output / "web" / "desktop-map.png",
            output / "web" / "mobile-page.png",
        ],
        comparison_dir / "contact-sheet.png",
    )
    lines = ["# RASMapper/Web Parity Findings", ""]
    lines.extend(
        f"- [{item['classification']}] {item['id']}" for item in findings
    )
    (comparison_dir / "findings.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("rasmapper", "web", "compare", "all"))
    parser.add_argument("spec", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    spec = load_spec(args.spec)
    args.output.mkdir(parents=True, exist_ok=True)
    if args.command in {"rasmapper", "all"}:
        capture_rasmapper(spec, args.output)
    if args.command in {"web", "all"}:
        capture_web(spec, args.output)
    if args.command in {"compare", "all"}:
        compare(spec, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
