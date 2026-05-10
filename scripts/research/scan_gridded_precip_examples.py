"""Research scanner for CLB-674 gridded precipitation example inventory.

This script is intentionally artifact-oriented: it downloads available official
HEC-RAS example archives, scans unsteady flow files for meteorology and
precipitation configuration, and records ScienceBase candidate metadata.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DESIRED_RAS_EXAMPLE_VERSIONS = ("6.3", "6.5", "6.6", "7.0")
GITHUB_RELEASES_API = (
    "https://api.github.com/repos/HydrologicEngineeringCenter/"
    "hec-downloads/releases"
)
HEC_DOWNLOADS_PAGE = "https://www.hec.usace.army.mil/software/hec-ras/download.aspx"
SCIENCEBASE_ITEMS_API = "https://www.sciencebase.gov/catalog/items"
SCIENCEBASE_ITEM_API = "https://www.sciencebase.gov/catalog/item"
USER_AGENT = "ras-commander-clb-674-research"

UNSTEADY_RE = re.compile(r"\.u\d{2,3}$", re.IGNORECASE)
PRECIP_RE = re.compile(r"precip|rain|meteorolog|met\s*bc|met\s*station", re.IGNORECASE)
GRID_RE = re.compile(r"grid|gridded|netcdf|grib|dss\s+filename|radar|mrms|qpe", re.IGNORECASE)
DSS_RE = re.compile(r"\bDSS\s+(?:File|Filename)\s*=\s*(.+)", re.IGNORECASE)
PATHNAME_RE = re.compile(r"/[^/\r\n]+/[^/\r\n]*/[^/\r\n]*/[^/\r\n]*/[^/\r\n]*/[^/\r\n]*/")


@dataclass
class HttpResult:
    ok: bool
    status: int | None
    error: str | None = None
    headers: dict[str, str] | None = None


def request_json(url: str, timeout: int = 90) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def http_head(url: str, timeout: int = 45) -> HttpResult:
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResult(
                ok=200 <= response.status < 400,
                status=response.status,
                headers={k: v for k, v in response.headers.items()},
            )
    except urllib.error.HTTPError as exc:
        return HttpResult(ok=False, status=exc.code, error=str(exc))
    except Exception as exc:  # pragma: no cover - diagnostic script
        return HttpResult(ok=False, status=None, error=repr(exc))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def discover_release_assets() -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    assets_by_name: dict[str, dict[str, Any]] = {}
    release_rows: list[dict[str, Any]] = []

    for page in range(1, 6):
        url = f"{GITHUB_RELEASES_API}?per_page=100&page={page}"
        releases = request_json(url)
        if not releases:
            break
        for release in releases:
            tag = release.get("tag_name", "")
            for asset in release.get("assets", []) or []:
                name = asset.get("name", "")
                if not name.startswith("Example_Projects_"):
                    continue
                row = {
                    "tag": tag,
                    "name": name,
                    "size_bytes": asset.get("size", 0),
                    "size_mb": round(float(asset.get("size", 0)) / 1024 / 1024, 1),
                    "url": asset.get("browser_download_url", ""),
                }
                assets_by_name[name] = row
                release_rows.append(row)
    return assets_by_name, release_rows


def discover_ras_example_versions() -> list[dict[str, Any]]:
    assets_by_name, release_rows = discover_release_assets()
    desired_rows: list[dict[str, Any]] = []

    for version in DESIRED_RAS_EXAMPLE_VERSIONS:
        name = f"Example_Projects_{version.replace('.', '_')}.zip"
        asset = assets_by_name.get(name)
        if asset:
            desired_rows.append(
                {
                    "version": version,
                    "available": True,
                    "name": name,
                    "tag": asset["tag"],
                    "size_bytes": asset["size_bytes"],
                    "size_mb": asset["size_mb"],
                    "url": asset["url"],
                    "discovery_note": "found in HEC GitHub release assets",
                }
            )
        else:
            attempts = [
                f"https://github.com/HydrologicEngineeringCenter/hec-downloads/releases/download/1.0.33/{name}",
                f"https://github.com/HydrologicEngineeringCenter/hec-downloads/releases/download/1.0.31/{name}",
                f"https://www.hec.usace.army.mil/software/hec-ras/downloads/{name}",
            ]
            attempt_results = []
            for attempt in attempts:
                result = http_head(attempt)
                attempt_results.append(
                    f"{attempt} -> {result.status or result.error or 'unknown'}"
                )
            desired_rows.append(
                {
                    "version": version,
                    "available": False,
                    "name": name,
                    "tag": "",
                    "size_bytes": "",
                    "size_mb": "",
                    "url": "",
                    "discovery_note": "; ".join(attempt_results),
                }
            )

    desired_rows.append(
        {
            "version": "all_assets",
            "available": True,
            "name": "release asset count",
            "tag": "",
            "size_bytes": "",
            "size_mb": "",
            "url": GITHUB_RELEASES_API,
            "discovery_note": f"{len(release_rows)} Example_Projects assets discovered",
        }
    )
    desired_rows.append(
        {
            "version": "current_hec_page",
            "available": True,
            "name": "HEC-RAS download page",
            "tag": "",
            "size_bytes": "",
            "size_mb": "",
            "url": HEC_DOWNLOADS_PAGE,
            "discovery_note": "checked as current public download page",
        }
    )
    return desired_rows


def download_file(url: str, output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        sha256 = sha256_file(output_path)
        return {
            "downloaded": False,
            "path": str(output_path),
            "bytes": output_path.stat().st_size,
            "sha256": sha256,
        }

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    total = 0
    print(f"Downloading {url}")
    with urllib.request.urlopen(request, timeout=120) as response:
        with output_path.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                total += len(chunk)
                if total and total % (100 * 1024 * 1024) < 1024 * 1024:
                    print(f"  downloaded {round(total / 1024 / 1024, 1)} MB")
    return {
        "downloaded": True,
        "path": str(output_path),
        "bytes": total,
        "sha256": digest.hexdigest(),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode_text(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("latin-1", errors="replace")


def project_parts(zip_name: str) -> tuple[str, str]:
    parts = Path(zip_name).parts
    if len(parts) >= 3 and parts[0].lower().startswith("example_projects"):
        return parts[1], parts[2]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return "", ""


def classify_precip_type(
    text: str,
    matched_lines: list[str],
    project_files: list[str],
    precipitation_mode: str,
    met_precip_mode: str,
) -> str:
    if precipitation_mode.lower() == "disable":
        if met_precip_mode:
            return f"disabled_met_precip_template_{met_precip_mode.lower()}"
        return "disabled_met_precip_template"
    if precipitation_mode == "" and matched_lines:
        return "blank_met_precip_template"
    combined = "\n".join(matched_lines + project_files).lower()
    if any(token in combined for token in ("gridded", "grid", "netcdf", ".nc", "grib", "mrms", "qpe", "radar")):
        return "gridded_or_radar_candidate"
    if "dss filename" in combined or any("/precip" in line.lower() for line in matched_lines):
        return "dss_precip_candidate"
    if any(token in combined for token in ("met station", "gage", "gauge", "station")):
        return "station_or_gage_candidate"
    if "uniform" in combined:
        return "uniform_precip_candidate"
    if "precip" in text.lower() or "rain" in text.lower():
        return "precip_signal_unclassified"
    return "none"


def scan_zip(version_row: dict[str, Any], zip_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    unsteady_rows: list[dict[str, Any]] = []
    project_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []

    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        project_file_map: dict[tuple[str, str], list[str]] = {}
        for name in names:
            category, project = project_parts(name)
            if category and project:
                project_file_map.setdefault((category, project), []).append(name)

        for name in names:
            if not UNSTEADY_RE.search(name):
                continue
            category, project = project_parts(name)
            text = decode_text(archive.read(name))
            lines = text.splitlines()
            matched: list[str] = []
            dss_refs: list[str] = []
            pathnames: list[str] = []
            precipitation_modes: list[str] = []
            met_precip_modes: list[str] = []
            for index, line in enumerate(lines, start=1):
                if PRECIP_RE.search(line) or GRID_RE.search(line):
                    matched.append(f"{index}: {line.strip()}")
                if line.lower().startswith("precipitation mode="):
                    precipitation_modes.append(line.split("=", 1)[1].strip())
                met_mode_match = re.match(
                    r"Met BC=Precipitation\|Mode=(.+)",
                    line.strip(),
                    re.IGNORECASE,
                )
                if met_mode_match:
                    met_precip_modes.append(met_mode_match.group(1).strip())
                dss_match = DSS_RE.search(line)
                if dss_match:
                    dss_refs.append(dss_match.group(1).strip())
                pathnames.extend(PATHNAME_RE.findall(line))

            project_files = project_file_map.get((category, project), [])
            project_exts = {Path(item).suffix.lower() for item in project_files}
            project_dss = [item for item in project_files if item.lower().endswith(".dss")]
            project_nc = [
                item
                for item in project_files
                if item.lower().endswith((".nc", ".nc4", ".grib", ".grb", ".tif", ".tiff"))
            ]
            has_met_signal = bool(matched)
            has_precip_signal = bool(re.search(r"precip|rain", text, re.IGNORECASE))
            has_grid_signal = bool(GRID_RE.search(text) or project_nc)
            precipitation_mode = " | ".join(sorted(set(precipitation_modes)))
            met_precip_mode = " | ".join(sorted(set(met_precip_modes)))
            precipitation_enabled = any(
                mode.lower() in {"enable", "enabled", "true", "1", "-1"}
                for mode in precipitation_modes
            )
            row = {
                "version": version_row["version"],
                "category": category,
                "project": project,
                "unsteady_file": name,
                "precipitation_mode": precipitation_mode,
                "met_precipitation_mode": met_precip_mode,
                "precipitation_enabled": precipitation_enabled,
                "has_met_signal": has_met_signal,
                "has_precip_signal": has_precip_signal,
                "has_grid_signal": has_grid_signal,
                "precip_type_guess": classify_precip_type(
                    text,
                    matched,
                    project_files,
                    precipitation_mode,
                    met_precip_mode,
                ),
                "matched_line_count": len(matched),
                "dss_reference_count": len(dss_refs),
                "dss_references": " | ".join(sorted(set(dss_refs))),
                "dss_pathname_count": len(pathnames),
                "project_dss_count": len(project_dss),
                "project_grid_raster_count": len(project_nc),
                "project_extensions": " ".join(sorted(project_exts)),
                "source_url": version_row.get("url", ""),
                "matched_lines_sample": " || ".join(matched[:20]),
            }
            unsteady_rows.append(row)
            if has_met_signal or has_precip_signal or has_grid_signal:
                detail_rows.append(
                    {
                        **row,
                        "matched_lines": matched[:100],
                        "project_dss_files": project_dss[:100],
                        "project_grid_or_raster_files": project_nc[:100],
                    }
                )

        summary: dict[tuple[str, str], dict[str, Any]] = {}
        for row in unsteady_rows:
            key = (row["category"], row["project"])
            item = summary.setdefault(
                key,
                {
                    "version": version_row["version"],
                    "category": row["category"],
                    "project": row["project"],
                    "unsteady_file_count": 0,
                    "met_signal_files": 0,
                    "precip_signal_files": 0,
                    "grid_signal_files": 0,
                    "precip_type_guesses": set(),
                    "dss_references": set(),
                    "source_url": version_row.get("url", ""),
                },
            )
            item["unsteady_file_count"] += 1
            item["met_signal_files"] += int(bool(row["has_met_signal"]))
            item["precip_signal_files"] += int(bool(row["has_precip_signal"]))
            item["grid_signal_files"] += int(bool(row["has_grid_signal"]))
            if row["precip_type_guess"] != "none":
                item["precip_type_guesses"].add(row["precip_type_guess"])
            if row["dss_references"]:
                item["dss_references"].update(row["dss_references"].split(" | "))

        for item in summary.values():
            item["precip_type_guesses"] = " | ".join(sorted(item["precip_type_guesses"]))
            item["dss_references"] = " | ".join(sorted(item["dss_references"]))
            project_rows.append(item)

    return unsteady_rows, project_rows, detail_rows


def sciencebase_query(params: dict[str, str], timeout: int = 90) -> tuple[dict[str, Any] | None, str | None]:
    query = urllib.parse.urlencode(params)
    url = f"{SCIENCEBASE_ITEMS_API}?{query}"
    try:
        return request_json(url, timeout=timeout), None
    except Exception as exc:  # pragma: no cover - diagnostic script
        return None, repr(exc)


def collect_sciencebase_candidates() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    searches = [
        {"label": "HEC-RAS MRMS", "q": '"HEC-RAS" MRMS'},
        {"label": "HEC-RAS gridded precipitation", "q": '"HEC-RAS" "gridded precipitation"'},
        {"label": "HEC-RAS radar rainfall", "q": '"HEC-RAS" "radar rainfall"'},
        {"label": "HEC-RAS QPE", "q": '"HEC-RAS" QPE'},
        {"label": "HEC-RAS meteorological", "q": '"HEC-RAS" meteorological'},
        {"label": "tag HEC-RAS", "filter": "tags=HEC-RAS"},
    ]

    search_rows: list[dict[str, Any]] = []
    raw_items_by_id: dict[str, dict[str, Any]] = {}

    for search in searches:
        params = {
            "format": "json",
            "max": "25",
            "fields": "id,title,summary,link,files,tags,dates,contacts",
        }
        if "q" in search:
            params["q"] = search["q"]
        if "filter" in search:
            params["filter"] = search["filter"]
        started = time.time()
        result, error = sciencebase_query(params)
        elapsed = round(time.time() - started, 1)
        items = (result or {}).get("items", []) if result else []
        search_rows.append(
            {
                "search_label": search["label"],
                "total": (result or {}).get("total", ""),
                "returned": len(items),
                "elapsed_seconds": elapsed,
                "error": error or "",
            }
        )
        for item in items:
            raw_items_by_id[item["id"]] = item

    candidate_rows: list[dict[str, Any]] = []
    for item_id, item in raw_items_by_id.items():
        files = item.get("files", []) or []
        file_names = [file.get("name", "") for file in files]
        file_sizes = [
            f"{file.get('name', '')} ({round(float(file.get('size', 0)) / 1024 / 1024, 1)} MB)"
            for file in files
            if file.get("name")
        ]
        metadata_text = " ".join(
            [
                item.get("title", ""),
                item.get("summary", ""),
                " ".join(file_names),
            ]
        )
        precip_terms = sorted(set(re.findall(r"MRMS|QPE|radar|rainfall|precipitation|meteorological|rain", metadata_text, re.IGNORECASE)))
        model_archive_files = [
            file
            for file in files
            if file.get("name", "").lower().endswith(".zip")
            and re.search(r"model|ras|hec|archive", file.get("name", ""), re.IGNORECASE)
        ]
        download_links = [
            file.get("downloadUri", "")
            for file in files
            if file.get("downloadUri")
        ]
        assessment = "metadata_only"
        if model_archive_files and precip_terms:
            assessment = "model_archive_with_precip_terms_in_metadata"
        elif model_archive_files:
            assessment = "model_archive_no_precip_terms_in_metadata"
        elif precip_terms:
            assessment = "precip_terms_no_model_archive"
        candidate_rows.append(
            {
                "sciencebase_id": item_id,
                "title": item.get("title", ""),
                "url": (item.get("link") or {}).get("url", f"{SCIENCEBASE_ITEM_API}/{item_id}"),
                "file_count": len(files),
                "zip_model_files": " | ".join(file.get("name", "") for file in model_archive_files),
                "file_manifest": " | ".join(file_sizes),
                "download_uri_count": len(download_links),
                "metadata_precip_terms": " | ".join(precip_terms),
                "assessment": assessment,
            }
        )

    candidate_rows.sort(key=lambda row: (row["assessment"], row["title"]))
    raw_items = sorted(raw_items_by_id.values(), key=lambda item: item.get("id", ""))
    return search_rows, candidate_rows, raw_items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--keep-cache", action="store_true")
    args = parser.parse_args(argv)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    version_rows = discover_ras_example_versions()
    write_csv(
        args.output_dir / "ras_examples_release_manifest.csv",
        version_rows,
        [
            "version",
            "available",
            "name",
            "tag",
            "size_bytes",
            "size_mb",
            "url",
            "discovery_note",
        ],
    )

    download_rows: list[dict[str, Any]] = []
    all_unsteady_rows: list[dict[str, Any]] = []
    all_project_rows: list[dict[str, Any]] = []
    all_details: list[dict[str, Any]] = []

    for version_row in version_rows:
        if version_row.get("version") not in DESIRED_RAS_EXAMPLE_VERSIONS:
            continue
        if not version_row.get("available"):
            print(f"Skipping unavailable RasExamples {version_row['version']}")
            continue
        zip_path = args.cache_dir / str(version_row["name"])
        download_info = download_file(str(version_row["url"]), zip_path)
        download_rows.append(
            {
                "version": version_row["version"],
                "name": version_row["name"],
                "path": download_info["path"],
                "bytes": download_info["bytes"],
                "sha256": download_info["sha256"],
                "downloaded_this_run": download_info["downloaded"],
            }
        )
        print(f"Scanning {zip_path}")
        unsteady_rows, project_rows, detail_rows = scan_zip(version_row, zip_path)
        all_unsteady_rows.extend(unsteady_rows)
        all_project_rows.extend(project_rows)
        all_details.extend(detail_rows)

    write_csv(
        args.output_dir / "ras_examples_downloads.csv",
        download_rows,
        ["version", "name", "path", "bytes", "sha256", "downloaded_this_run"],
    )
    write_csv(
        args.output_dir / "ras_examples_unsteady_scan.csv",
        all_unsteady_rows,
        [
            "version",
            "category",
            "project",
            "unsteady_file",
            "precipitation_mode",
            "met_precipitation_mode",
            "precipitation_enabled",
            "has_met_signal",
            "has_precip_signal",
            "has_grid_signal",
            "precip_type_guess",
            "matched_line_count",
            "dss_reference_count",
            "dss_references",
            "dss_pathname_count",
            "project_dss_count",
            "project_grid_raster_count",
            "project_extensions",
            "source_url",
            "matched_lines_sample",
        ],
    )
    write_csv(
        args.output_dir / "ras_examples_project_summary.csv",
        all_project_rows,
        [
            "version",
            "category",
            "project",
            "unsteady_file_count",
            "met_signal_files",
            "precip_signal_files",
            "grid_signal_files",
            "precip_type_guesses",
            "dss_references",
            "source_url",
        ],
    )
    write_json(args.output_dir / "ras_examples_precip_candidate_details.json", all_details)

    search_rows, candidate_rows, raw_items = collect_sciencebase_candidates()
    write_csv(
        args.output_dir / "sciencebase_search_log.csv",
        search_rows,
        ["search_label", "total", "returned", "elapsed_seconds", "error"],
    )
    write_csv(
        args.output_dir / "sciencebase_candidates.csv",
        candidate_rows,
        [
            "sciencebase_id",
            "title",
            "url",
            "file_count",
            "zip_model_files",
            "file_manifest",
            "download_uri_count",
            "metadata_precip_terms",
            "assessment",
        ],
    )
    write_json(args.output_dir / "sciencebase_raw_candidate_items.json", raw_items)

    if not args.keep_cache:
        print(f"Removing cache directory {args.cache_dir}")
        shutil.rmtree(args.cache_dir, ignore_errors=True)

    print(f"Wrote research artifacts to {args.output_dir}")
    print(f"RasExamples unsteady files scanned: {len(all_unsteady_rows)}")
    print(f"RasExamples met/precip detail files: {len(all_details)}")
    print(f"ScienceBase candidates evaluated: {len(candidate_rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
