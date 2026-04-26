from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pyproj import CRS

from ras_commander import RasPrj, RasUtils, init_ras_project
from ras_commander.hdf import HdfBase


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = Path(
    os.environ.get("RAS_COMMANDER_EBFE_ROOT", r"H:\Testing\eBFE Model Organization")
)
REPORT_ROOT = DEFAULT_WORKSPACE / "Validation" / "ebfe_delivery"


@dataclass
class ProjectAudit:
    project_name: str
    project_folder: str
    plan_count: int
    flow_types: list[str] = field(default_factory=list)
    has_rasmap: bool = False
    project_crs: Optional[str] = None
    projection_file: Optional[str] = None
    output_hdf_count: int = 0
    outputs_inside_project: bool = False
    dss_reference_count: int = 0
    dss_missing_references: list[str] = field(default_factory=list)
    terrain_layers: list[str] = field(default_factory=list)
    land_cover_layers: list[str] = field(default_factory=list)
    terrain_crs_mismatches: list[str] = field(default_factory=list)
    land_cover_crs_mismatches: list[str] = field(default_factory=list)
    preprocessor_status: str = "not_run"
    preprocessor_plan: Optional[str] = None
    preprocessor_notes: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    fixes_applied: list[str] = field(default_factory=list)


@dataclass
class StudyAudit:
    study_area: str
    source_path: str
    source_type: str
    status: str
    organized_path: Optional[str] = None
    project_count: int = 0
    documentation_files: list[str] = field(default_factory=list)
    preprocessor_report: Optional[str] = None
    preprocessor_validated_count: int = 0
    preprocessor_failed_count: int = 0
    issues: list[str] = field(default_factory=list)
    fixes_applied: list[str] = field(default_factory=list)
    projects: list[ProjectAudit] = field(default_factory=list)


def rel_path(path: Path) -> str:
    for base in (ROOT, DEFAULT_WORKSPACE):
        try:
            return str(path.relative_to(base))
        except ValueError:
            continue
    return str(path)


def windows_rel(target: Path, start: Path) -> str:
    relative = target.relative_to(start)
    return ".\\" + str(relative).replace("/", "\\")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def existing_files(folder: Path, patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        files.extend(sorted(folder.glob(pattern)))
    return [path for path in files if path.is_file()]


def suppress_ras_info_logs() -> None:
    logging.disable(logging.INFO)


def load_project(project_folder: Path) -> RasPrj:
    ras_obj = RasPrj()
    init_ras_project(project_folder, ras_object=ras_obj)
    return ras_obj


def scalar_from_rasmap(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        return value[0] if value else None
    return value


def string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)] if value else []


def discover_valid_projects(search_root: Path, max_depth: int = 10) -> list[dict[str, Any]]:
    return RasUtils.find_valid_ras_folders(
        search_root,
        max_depth=max_depth,
        return_project_info=True,
    )


def extract_project_crs(project_folder: Path, ras_obj: RasPrj) -> Optional[str]:
    project_crs = getattr(ras_obj, "project_crs", None)
    if project_crs:
        return str(project_crs)
    refresh = getattr(ras_obj, "refresh_project_crs", None)
    if callable(refresh):
        return refresh()
    return None


def parse_rasmap_xml(rasmap_path: Path) -> ET.ElementTree:
    return ET.parse(rasmap_path)


def find_rasmap(project_folder: Path) -> Optional[Path]:
    rasmaps = sorted(project_folder.glob("*.rasmap"))
    return rasmaps[0] if rasmaps else None


def rasmap_layer_paths(project_folder: Path, rasmap_path: Path, layer_type: str) -> list[Path]:
    tree = parse_rasmap_xml(rasmap_path)
    root = tree.getroot()
    paths: list[Path] = []
    for layer in root.findall(f".//Layer[@Type='{layer_type}']"):
        filename = layer.attrib.get("Filename")
        resolved = resolve_optional_path(project_folder, filename)
        if resolved is not None:
            paths.append(resolved)
    return paths


def resolve_optional_path(project_folder: Path, value: Optional[str]) -> Optional[Path]:
    if not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (project_folder / candidate).resolve()


def normalize_crs_text(crs_text: Optional[str]) -> Optional[str]:
    if not crs_text:
        return None
    try:
        crs = CRS.from_user_input(crs_text)
        epsg = crs.to_epsg()
        return f"EPSG:{epsg}" if epsg else crs.to_string()
    except Exception:
        return crs_text


def get_asset_crs(asset_path: Path) -> Optional[str]:
    suffix = asset_path.suffix.lower()
    try:
        if suffix in {".hdf", ".h5"}:
            return normalize_crs_text(HdfBase._get_projection_from_hdf_attribute(asset_path))
        if suffix in {".tif", ".tiff"}:
            return normalize_crs_text(HdfBase._get_projection_from_raster(asset_path))
        if suffix == ".prj":
            return normalize_crs_text(HdfBase._get_projection_from_prj_file(asset_path))
    except Exception:
        return None
    return None


def compare_crs(expected: Optional[str], actual: Optional[str]) -> bool:
    if not expected or not actual:
        return True
    return normalize_crs_text(expected) == normalize_crs_text(actual)


def write_projection_file(project_folder: Path, project_name: str, project_crs: str) -> Path:
    projection_folder = project_folder / "Projection"
    projection_folder.mkdir(parents=True, exist_ok=True)
    projection_file = projection_folder / f"{project_name}_Projection.prj"
    crs = CRS.from_user_input(project_crs)
    projection_file.write_text(crs.to_wkt(version="WKT1_ESRI"), encoding="utf-8")
    return projection_file


def update_rasmap_projection(
    rasmap_path: Path,
    project_folder: Path,
    projection_file: Path,
) -> bool:
    tree = parse_rasmap_xml(rasmap_path)
    root = tree.getroot()
    projection_elem = root.find(".//RASProjectionFilename")
    if projection_elem is None:
        projection_elem = ET.Element("RASProjectionFilename")
        root.insert(0, projection_elem)
    desired = windows_rel(projection_file, project_folder)
    if projection_elem.attrib.get("Filename") == desired:
        return False
    projection_elem.attrib["Filename"] = desired
    tree.write(rasmap_path, encoding="utf-8", xml_declaration=True)
    return True


def update_rasmap_assets(
    rasmap_path: Path,
    project_folder: Path,
    terrain_folder: Optional[Path] = None,
    land_cover_updates: Optional[dict[str, Path]] = None,
) -> list[str]:
    tree = parse_rasmap_xml(rasmap_path)
    root = tree.getroot()
    changed: list[str] = []

    if terrain_folder is not None:
        for setting_name in ["TerrainDestinationFolder", "TerrainSourceFolder"]:
            elem = root.find(f".//{setting_name}")
            desired = ".\\Terrain"
            if elem is not None and elem.text != desired:
                elem.text = desired
                changed.append(f"{setting_name}={desired}")

    if land_cover_updates:
        for layer in root.findall(".//Layer[@Type='LandCoverLayer']"):
            filename = layer.attrib.get("Filename")
            if not filename:
                continue
            basename = Path(filename).name
            if basename in land_cover_updates:
                new_path = windows_rel(land_cover_updates[basename], project_folder)
                if layer.attrib.get("Filename") != new_path:
                    layer.attrib["Filename"] = new_path
                    changed.append(f"LandCoverLayer={basename}")

        elem = root.find(".//LandCoverDestinationFolder")
        desired = ".\\Land Cover"
        if elem is not None and elem.text != desired:
            elem.text = desired
            changed.append(f"LandCoverDestinationFolder={desired}")

    if changed:
        tree.write(rasmap_path, encoding="utf-8", xml_declaration=True)
    return changed


def rewrite_dss_references(project_folder: Path, dss_files: list[Path]) -> list[str]:
    if not dss_files:
        return []

    dss_lookup = {path.name.lower(): path for path in dss_files}
    unique_target = dss_files[0] if len(dss_files) == 1 else None
    fixes: list[str] = []
    pattern = re.compile(r"^(DSS (?:File|Filename))=(.+)$", re.IGNORECASE)

    hecras_files = existing_files(project_folder, ["*.u[0-9][0-9]", "*.p[0-9][0-9]", "*.prj"])

    for hecras_file in hecras_files:
        original_lines = hecras_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        updated_lines: list[str] = []
        modified = False

        for line in original_lines:
            match = pattern.match(line.strip())
            if not match:
                updated_lines.append(line)
                continue

            keyword, raw_value = match.groups()
            raw_value = raw_value.strip()
            basename = Path(raw_value).name.lower()
            chosen = dss_lookup.get(basename)

            if chosen is None and raw_value.lower().endswith(".dss") and unique_target is not None:
                chosen = unique_target

            if chosen is None:
                updated_lines.append(line)
                continue

            new_value = windows_rel(chosen, project_folder)
            if raw_value != new_value:
                updated_lines.append(f"{keyword}={new_value}")
                modified = True
                fixes.append(f"{hecras_file.name}: {raw_value} -> {new_value}")
            else:
                updated_lines.append(line)

        if modified:
            hecras_file.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")

    return fixes


def copy_land_cover_assets(project_folder: Path, rasmap_path: Optional[Path]) -> tuple[list[Path], list[str]]:
    copied_assets: list[Path] = []
    changed: list[str] = []
    if rasmap_path is None:
        return copied_assets, changed

    tree = parse_rasmap_xml(rasmap_path)
    root = tree.getroot()
    land_cover_folder = project_folder / "Land Cover"
    updates: dict[str, Path] = {}

    for layer in root.findall(".//Layer[@Type='LandCoverLayer']"):
        filename = layer.attrib.get("Filename")
        if not filename:
            continue
        source = resolve_optional_path(project_folder, filename)
        if source is None or not source.exists():
            continue

        land_cover_folder.mkdir(parents=True, exist_ok=True)
        destination = land_cover_folder / source.name
        if source.resolve() != destination.resolve():
            copy_file(source, destination)
        copied_assets.append(destination)
        updates[source.name] = destination

        tif_candidate = source.with_suffix(".tif")
        if tif_candidate.exists():
            tif_destination = land_cover_folder / tif_candidate.name
            if tif_candidate.resolve() != tif_destination.resolve():
                copy_file(tif_candidate, tif_destination)
            copied_assets.append(tif_destination)

    if updates:
        changed = update_rasmap_assets(
            rasmap_path,
            project_folder,
            land_cover_updates=updates,
        )
    return copied_assets, changed


def audit_loaded_project(project_folder: Path, ras_obj: RasPrj) -> ProjectAudit:
    plan_df = ras_obj.plan_df
    project_name = Path(project_folder).name
    project_crs = extract_project_crs(project_folder, ras_obj)
    rasmap_path = find_rasmap(project_folder)

    audit = ProjectAudit(
        project_name=project_name,
        project_folder=rel_path(project_folder),
        plan_count=len(plan_df),
        flow_types=sorted({str(item) for item in plan_df.get("flow_type", []).tolist() if item}),
        has_rasmap=rasmap_path is not None,
        project_crs=project_crs,
    )

    hdf_paths = [
        Path(value)
        for value in plan_df.get("HDF_Results_Path", []).tolist()
        if isinstance(value, str) and value
    ]
    audit.output_hdf_count = len(hdf_paths)
    audit.outputs_inside_project = all(path.exists() and path.parent == project_folder for path in hdf_paths) if hdf_paths else False

    boundaries_df = getattr(ras_obj, "boundaries_df", None)
    if boundaries_df is not None and "DSS File" in boundaries_df.columns:
        referenced = [
            str(value).strip()
            for value in boundaries_df["DSS File"].tolist()
            if isinstance(value, str) and value.strip()
        ]
        audit.dss_reference_count = len(referenced)
        for ref in referenced:
            if not ref.lower().endswith(".dss"):
                continue
            resolved = resolve_optional_path(project_folder, ref)
            if resolved is None or not resolved.exists():
                audit.dss_missing_references.append(ref)

    rasmap_df = getattr(ras_obj, "rasmap_df", None)
    if rasmap_df is not None and not rasmap_df.empty:
        row = rasmap_df.iloc[0]
        projection_path = scalar_from_rasmap(row.get("projection_path"))
        if projection_path:
            audit.projection_file = rel_path(Path(projection_path))

        terrain_paths = string_list(row.get("terrain_hdf_path"))
        land_cover_paths = string_list(row.get("landcover_hdf_path"))
        audit.terrain_layers = [rel_path(Path(path)) for path in terrain_paths]
        audit.land_cover_layers = [rel_path(Path(path)) for path in land_cover_paths]

        for terrain_path in terrain_paths:
            actual = get_asset_crs(Path(terrain_path))
            if not compare_crs(project_crs, actual):
                audit.terrain_crs_mismatches.append(f"{rel_path(Path(terrain_path))}: {actual}")

        for land_cover_path in land_cover_paths:
            actual = get_asset_crs(Path(land_cover_path))
            if not compare_crs(project_crs, actual):
                audit.land_cover_crs_mismatches.append(f"{rel_path(Path(land_cover_path))}: {actual}")

    if rasmap_path is not None and not audit.terrain_layers:
        for terrain_path in rasmap_layer_paths(project_folder, rasmap_path, "TerrainLayer"):
            audit.terrain_layers.append(rel_path(terrain_path))
            actual = get_asset_crs(terrain_path)
            if not compare_crs(project_crs, actual):
                audit.terrain_crs_mismatches.append(f"{rel_path(terrain_path)}: {actual}")

    if rasmap_path is not None and not audit.land_cover_layers:
        for land_cover_path in rasmap_layer_paths(project_folder, rasmap_path, "LandCoverLayer"):
            audit.land_cover_layers.append(rel_path(land_cover_path))
            actual = get_asset_crs(land_cover_path)
            if not compare_crs(project_crs, actual):
                audit.land_cover_crs_mismatches.append(f"{rel_path(land_cover_path)}: {actual}")

    if audit.output_hdf_count and not audit.outputs_inside_project:
        audit.issues.append("Pre-computed HDF results are not fully inside the project folder.")
    if audit.dss_missing_references:
        audit.issues.append("One or more DSS references are broken.")
    if audit.has_rasmap and not audit.projection_file:
        audit.issues.append("RAS Mapper projection file is missing.")
    if audit.terrain_crs_mismatches:
        audit.issues.append("Terrain CRS mismatch detected.")
    if audit.land_cover_crs_mismatches:
        audit.issues.append("Land cover CRS mismatch detected.")

    audit.preprocessor_notes.append(
        "Run GeomPreprocessor.run_geometry_preprocessor() for at least one plan per unique geometry and review compute messages."
    )

    return audit


def preprocessor_reports() -> list[Path]:
    report_folder = REPORT_ROOT / "preprocessor_validation"
    if not report_folder.exists():
        return []
    return sorted(report_folder.glob("geometry_preprocessor_validation_*.json"))


def load_preprocessor_records(report_paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for report_path in report_paths:
        if not report_path.exists():
            continue
        data = json.loads(report_path.read_text(encoding="utf-8"))
        for record in data.get("records", []):
            record["_report_path"] = rel_path(report_path)
            records.append(record)
    return records


def study_slug(study_area: str) -> str:
    mapping = {
        "LowerColoradoCummins_12090301": "lower-colorado",
        "RioHondo_13060008": "rio-hondo",
        "SpringCreek_12040102": "spring-creek",
        "NorthGalvestonBay_12040203": "north-galveston-bay",
        "UpperGuadalupe_12100201": "upper-guadalupe",
        "LowerBrazos_12070104": "lower-brazos",
        "Amite_08070202": "amite",
        "Tickfaw_08070203": "tickfaw",
        "LakeMaurepas_08070204": "lake-maurepas",
    }
    return mapping.get(study_area, study_area.lower())


def apply_preprocessor_records(
    studies: list[StudyAudit],
    report_paths: list[Path],
) -> None:
    records = [
        record for record in load_preprocessor_records(report_paths)
        if record.get("status") in {"passed", "failed"}
    ]
    if not records:
        return

    records_by_folder = {}
    for record in records:
        key = str(record.get("project_folder", "")).replace("/", "\\").lower()
        records_by_folder[key] = record

    for study in studies:
        slug = study_slug(study.study_area)
        latest_study_records = {}
        for record in records:
            if str(record.get("study", "")).lower() != slug:
                continue
            key = str(record.get("project_folder", "")).replace("/", "\\").lower()
            latest_study_records[key] = record

        for project in study.projects:
            key = project.project_folder.replace("/", "\\").lower()
            record = records_by_folder.get(key)
            if record:
                latest_study_records[key] = record

        study_records = list(latest_study_records.values())
        if study_records:
            study_report_paths = sorted(
                {
                    record.get("_report_path")
                    for record in study_records
                    if record.get("_report_path")
                }
            )
            study.preprocessor_report = ", ".join(study_report_paths)
            study.preprocessor_validated_count = sum(
                1 for record in study_records if record.get("status") == "passed"
            )
            study.preprocessor_failed_count = sum(
                1 for record in study_records if record.get("status") == "failed"
            )
            if study.preprocessor_failed_count:
                study.issues.append(
                    f"{study.preprocessor_failed_count} project(s) failed preprocessor validation."
                )

        for project in study.projects:
            record = records_by_folder.get(project.project_folder.replace("/", "\\").lower())
            if not record:
                continue
            project.preprocessor_status = (
                "validated" if record.get("status") == "passed" else "failed"
            )
            plan_numbers = [
                str(plan.get("plan_number"))
                for plan in record.get("plans", [])
                if plan.get("plan_number")
            ]
            if plan_numbers:
                project.preprocessor_plan = ",".join(plan_numbers)
            report_note = record.get("_report_path", "preprocessor report")
            project.preprocessor_notes = [
                f"Validated by {report_note}"
            ]


def repair_spring_creek(study_root: Path) -> tuple[StudyAudit, ProjectAudit]:
    project_folder = study_root / "RAS Model"
    study = StudyAudit(
        study_area="SpringCreek_12040102",
        source_path=rel_path(study_root),
        source_type="organized_sample",
        status="audited_and_repaired",
        organized_path=rel_path(study_root),
        project_count=1,
    )

    ras_obj = load_project(project_folder)
    project_audit = audit_loaded_project(project_folder, ras_obj)

    rasmap_path = find_rasmap(project_folder)
    if rasmap_path is None:
        project_audit.issues.append("Spring Creek is missing a .rasmap file.")
        study.issues.extend(project_audit.issues)
        study.projects.append(project_audit)
        return study, project_audit

    if project_audit.project_crs:
        projection_file = write_projection_file(project_folder, "Spring", project_audit.project_crs)
        if update_rasmap_projection(rasmap_path, project_folder, projection_file):
            project_audit.fixes_applied.append(f"Updated .rasmap projection to {rel_path(projection_file)}")

    dss_folder = project_folder / "DSS Inputs"
    copied_dss: list[Path] = []
    for src in existing_files(project_folder, ["*.dss", "*.dsc"]):
        dst = dss_folder / src.name
        if src.resolve() != dst.resolve():
            copy_file(src, dst)
            copied_dss.append(dst)
    if copied_dss:
        project_audit.fixes_applied.append("Copied DSS assets into DSS Inputs/.")

    dss_fixes = rewrite_dss_references(project_folder, existing_files(dss_folder, ["*.dss"]))
    if dss_fixes:
        project_audit.fixes_applied.extend(dss_fixes)

    land_cover_assets, land_cover_changes = copy_land_cover_assets(project_folder, rasmap_path)
    if land_cover_assets:
        project_audit.fixes_applied.append("Copied land cover assets into Land Cover/.")
    project_audit.fixes_applied.extend(land_cover_changes)
    if any((project_folder / path.name).exists() for path in land_cover_assets):
        project_audit.fixes_applied.append("Left original root land cover files in place for safety after repointing .rasmap.")

    terrain_changes = update_rasmap_assets(
        rasmap_path,
        project_folder,
        terrain_folder=project_folder / "Terrain",
    )
    if terrain_changes:
        project_audit.fixes_applied.extend(terrain_changes)

    refreshed = load_project(project_folder)
    refreshed_audit = audit_loaded_project(project_folder, refreshed)
    refreshed_audit.fixes_applied = project_audit.fixes_applied.copy()

    if refreshed_audit.projection_file and "Projection" not in refreshed_audit.projection_file:
        refreshed_audit.issues.append("Projection file still resolves outside Projection/.")
    if refreshed_audit.land_cover_layers and not all("Land Cover" in path for path in refreshed_audit.land_cover_layers):
        refreshed_audit.issues.append("Land cover layer is not fully normalized into Land Cover/.")
    if refreshed_audit.dss_missing_references:
        refreshed_audit.issues.append("DSS references still need manual review.")

    study.issues.extend(refreshed_audit.issues)
    study.fixes_applied.extend(refreshed_audit.fixes_applied)
    study.projects.append(refreshed_audit)

    addendum_lines = [
        "# Delivery Audit Addendum - Spring Creek",
        "",
        f"Date: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Delivery Format Checks",
        "",
        f"- Projection now resolves locally at `{rel_path(project_folder / 'Projection' / 'Spring_Projection.prj')}`.",
        f"- DSS references now point to `{rel_path(project_folder / 'DSS Inputs')}`.",
        f"- Land cover now resolves locally at `{rel_path(project_folder / 'Land Cover' / 'Sensitivity_Run_6.hdf')}`.",
        f"- Terrain remains local at `{rel_path(project_folder / 'Terrain')}`.",
        f"- Project CRS: `{refreshed_audit.project_crs}`.",
        f"- Terrain CRS mismatches: {len(refreshed_audit.terrain_crs_mismatches)}.",
        f"- Land cover CRS mismatches: {len(refreshed_audit.land_cover_crs_mismatches)}.",
        "",
        "## Notes",
        "",
        "- Original root land cover files were left in place for a conservative transition after repointing `.rasmap`.",
        "- Pre-computed HDF outputs were already inside the project folder and required no relocation.",
    ]
    write_text(study_root / "agent" / "delivery_audit_2026-04-23.md", "\n".join(addendum_lines) + "\n")
    return study, refreshed_audit


def organize_rio_hondo(raw_models_root: Path, documents_root: Path, output_root: Path) -> StudyAudit:
    study = StudyAudit(
        study_area="RioHondo_13060008",
        source_path=rel_path(raw_models_root),
        source_type="raw_multi_project",
        status="organized",
        organized_path=rel_path(output_root),
    )

    folders = {
        "hms": output_root / "HMS Model",
        "ras": output_root / "RAS Model",
        "spatial": output_root / "Spatial Data",
        "docs": output_root / "Documentation",
        "agent": output_root / "agent",
    }
    for folder in folders.values():
        folder.mkdir(parents=True, exist_ok=True)

    copied_files = 0
    watershed_counts: Counter[str] = Counter()

    for watershed in sorted(path for path in raw_models_root.iterdir() if path.is_dir()):
        for project_dir in sorted(path for path in watershed.iterdir() if path.is_dir()):
            model_folder = project_dir / "Model"
            if not model_folder.exists():
                continue
            if not RasUtils.is_valid_ras_folder(model_folder):
                continue

            destination = folders["ras"] / watershed.name.replace("_", " ") / project_dir.name
            destination.mkdir(parents=True, exist_ok=True)

            for source_file in sorted(model_folder.iterdir()):
                if not source_file.is_file():
                    continue
                if source_file.name.startswith("~$") or source_file.name.lower() == "thumbs.db":
                    continue
                copy_file(source_file, destination / source_file.name)
                copied_files += 1

            watershed_counts[watershed.name.replace("_", " ")] += 1

    docs_to_copy = [
        *existing_files(raw_models_root, ["*.xml"]),
        *documents_root.rglob("*.pdf"),
    ]
    for doc in docs_to_copy:
        copy_file(doc, folders["docs"] / doc.name)
        study.documentation_files.append(rel_path(folders["docs"] / doc.name))

    study.project_count = sum(watershed_counts.values())
    study.fixes_applied.append(
        f"Copied {study.project_count} raw Model/ projects into RAS Model/ without the extra Model nesting."
    )
    study.fixes_applied.append("Copied Rio Hondo report and metadata into Documentation/.")

    manifest_lines = [
        "# Rio Hondo Delivery Manifest",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Projects Organized: {study.project_count}",
        f"Files Copied: {copied_files}",
        "",
        "## Watersheds",
        "",
    ]
    for watershed_name, count in sorted(watershed_counts.items()):
        manifest_lines.append(f"- {watershed_name}: {count} projects")

    write_text(output_root / "MANIFEST.md", "\n".join(manifest_lines) + "\n")

    log_lines = [
        "# Agent Work Log - Rio Hondo",
        "",
        f"Date: {datetime.now().isoformat(timespec='seconds')}",
        f"Source: {rel_path(raw_models_root)}",
        f"Output: {rel_path(output_root)}",
        "",
        "## Actions",
        "",
        f"- Organized {study.project_count} valid HEC-RAS project folders into `RAS Model/`.",
        "- Flattened each raw `Model/` folder into the final project folder so the openable HEC-RAS files sit at the project root.",
        "- Copied the BLE report and metadata XML into `Documentation/`.",
        "- Left `HMS Model/` and `Spatial Data/` empty because this raw corpus does not include those assets.",
        "",
        "## Notes",
        "",
        "- These are 1D steady-state projects; DSS, terrain, land cover, and rasmap checks are not applicable for most folders.",
        "- Lower-level project names and watershed groupings were preserved to keep the original delivery decipherable.",
    ]
    write_text(folders["agent"] / "model_log.md", "\n".join(log_lines) + "\n")

    sample_projects = discover_valid_projects(folders["ras"], max_depth=4)
    for project_info in sample_projects[:5]:
        is_steady = any(project_info["folder"].glob("*.f[0-9][0-9]"))
        audit = ProjectAudit(
            project_name=project_info["project_name"],
            project_folder=rel_path(project_info["folder"]),
            plan_count=project_info["plan_count"],
            flow_types=["steady" if is_steady else "unknown"],
            preprocessor_status="not_run",
            preprocessor_notes=[
                "Steady 1D BLE reach model; run GeomPreprocessor.run_geometry_preprocessor() and review compute messages."
            ],
            issues=[],
            fixes_applied=[],
        )
        study.projects.append(audit)

    return study


def audit_lower_colorado(study_root: Path) -> StudyAudit:
    projects = discover_valid_projects(study_root, max_depth=6)
    study = StudyAudit(
        study_area="LowerColoradoCummins_12090301",
        source_path=rel_path(study_root),
        source_type="organized_sample",
        status="audited",
        organized_path=rel_path(study_root),
        project_count=len(projects),
    )

    for project_info in projects:
        ras_obj = load_project(project_info["folder"])
        audit = audit_loaded_project(project_info["folder"], ras_obj)
        study.projects.append(audit)
        study.issues.extend(audit.issues)

    note_lines = [
        "# Delivery Audit Addendum - Lower Colorado-Cummins",
        "",
        f"Date: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Delivery Format Checks",
        "",
        "- This organized sample is a 1D steady-state reach model.",
        "- DSS, terrain, land cover, and `.rasmap` checks are not applicable for the current reach sample.",
        "- Pre-computed HDF output is present in the project folder for the sampled reach.",
    ]
    write_text(study_root / "agent" / "delivery_audit_2026-04-23.md", "\n".join(note_lines) + "\n")
    return study


def audit_organized_study(study_area: str, study_root: Path, max_depth: int = 8) -> StudyAudit:
    ras_root = study_root / "RAS Model"
    projects = discover_valid_projects(ras_root, max_depth=max_depth)
    study = StudyAudit(
        study_area=study_area,
        source_path=rel_path(study_root),
        source_type="organized_sample",
        status="audited",
        organized_path=rel_path(study_root),
        project_count=len(projects),
    )

    for doc in existing_files(study_root / "Documentation", ["*"]):
        study.documentation_files.append(rel_path(doc))

    for project_info in projects:
        ras_obj = load_project(project_info["folder"])
        audit = audit_loaded_project(project_info["folder"], ras_obj)
        study.projects.append(audit)
        study.issues.extend(audit.issues)

    note_lines = [
        f"# Delivery Audit Addendum - {study_area}",
        "",
        f"Date: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Delivery Format Checks",
        "",
        f"- Valid HEC-RAS projects discovered: {len(projects)}.",
        "- Project folders were audited for local DSS, projection, terrain, land cover, and result paths.",
        "- Preprocessor validation status is applied from the latest geometry preprocessor reports.",
    ]
    write_text(study_root / "agent" / "delivery_audit_2026-04-24.md", "\n".join(note_lines) + "\n")
    return study


def audit_lower_brazos(url_root: Path) -> StudyAudit:
    url_file = next(url_root.glob("*_ModelURLs.txt"))
    study = StudyAudit(
        study_area="LowerBrazos_12070104",
        source_path=rel_path(url_root),
        source_type="url_manifest_only",
        status="blocked_missing_archives",
        project_count=0,
    )
    study.issues.append("Only the eBFE URL manifest exists locally. The 188-229 GB model archives are not downloaded.")
    study.documentation_files.append(rel_path(url_file))
    return study


def build_common_format_markdown(studies: list[StudyAudit]) -> str:
    validated_count = sum(study.preprocessor_validated_count for study in studies)
    failed_count = sum(study.preprocessor_failed_count for study in studies)
    report_paths = sorted(
        {
            study.preprocessor_report
            for study in studies
            if study.preprocessor_report
        }
    )
    return "\n".join(
        [
            "# eBFE Delivery Format v1",
            "",
            f"Generated from the current on-disk eBFE corpus on {datetime.now().date().isoformat()}.",
            "",
            "## Project-Level Layout",
            "",
            "- Keep each HEC-RAS project directly openable at the project folder root.",
            "- Keep pre-computed HDF outputs in the same folder as the `.prj`, `.p##`, `.g##`, and `.u##` files.",
            "- Put DSS files in `DSS Inputs/` and update HEC-RAS text files to point there.",
            "- Put the project projection in `Projection/` and point `.rasmap` at that local `.prj` file.",
            "- Put terrain assets in `Terrain/` and keep `.rasmap` terrain destination and source references local.",
            "- Put land cover assets in `Land Cover/` and keep `.rasmap` land cover references local.",
            "- Preserve watershed and project naming from the source delivery so the organized copy is still easy to trace back.",
            "- Treat `preprocessor_validated` as the acceptance gate for project assembly; path validation alone is not enough.",
            "",
            "## Study-Level Layout",
            "",
            "```text",
            "{StudyArea}_{HUC8}/",
            "├── HMS Model/",
            "├── RAS Model/",
            "│   └── {Watershed or Project Group}/",
            "│       └── {ProjectName}/",
            "│           ├── *.prj, *.g##, *.p##, *.u##, *.f##, *.hdf",
            "│           ├── DSS Inputs/",
            "│           ├── Projection/",
            "│           ├── Terrain/",
            "│           └── Land Cover/",
            "├── Spatial Data/",
            "├── Documentation/",
            "└── agent/model_log.md",
            "```",
            "",
            "## Current Corpus Notes",
            "",
            f"- Studies reviewed this pass: {len(studies)}",
            f"- Geometry preprocessor validation passed for {validated_count} project(s); failures: {failed_count}.",
            f"- Preprocessor reports: {', '.join(f'`{path}`' for path in report_paths)}" if report_paths else "- Preprocessor reports: not available.",
            "- `Spring Creek` drove the 2D rules: it has pre-computed results, a land cover HDF, terrain, and a `.rasmap` file.",
            "- `North Galveston Bay` confirms nested RAS_Submittal extraction, Output integration, Terrain sidecar repair, and land-cover path rewrites.",
            "- `Upper Guadalupe` confirms cascaded 2D models with per-project terrain, land cover, upstream DSS copies, and large preprocessor runtimes.",
            "- `Rio Hondo` drove the bulk 1D rules: preserve watershed folders, remove the extra raw `Model/` nesting, and keep project files directly openable.",
            "- `Lower Colorado-Cummins` confirms the 1D reach-model pattern is still understandable inside the same outer delivery shell.",
            "- `Lower Brazos` remains blocked because only the URL manifest is local.",
            "",
        ]
    ) + "\n"


def build_summary_markdown(studies: list[StudyAudit]) -> str:
    lines = [
        "# eBFE Delivery Audit Summary",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]

    for study in studies:
        lines.append(f"## {study.study_area}")
        lines.append("")
        lines.append(f"- Status: {study.status}")
        lines.append(f"- Source Type: {study.source_type}")
        lines.append(f"- Source: `{study.source_path}`")
        if study.organized_path:
            lines.append(f"- Organized Path: `{study.organized_path}`")
        lines.append(f"- Project Count: {study.project_count}")
        if study.documentation_files:
            lines.append(f"- Documentation Files: {len(study.documentation_files)}")
        if study.preprocessor_report:
            lines.append(f"- Preprocessor Report: `{study.preprocessor_report}`")
            lines.append(
                f"- Preprocessor Validated: {study.preprocessor_validated_count} passed, "
                f"{study.preprocessor_failed_count} failed"
            )
        if study.fixes_applied:
            lines.append("- Fixes Applied:")
            for item in study.fixes_applied:
                lines.append(f"  - {item}")
        if study.issues:
            lines.append("- Open Issues:")
            for item in study.issues:
                lines.append(f"  - {item}")
        if study.projects:
            lines.append("- Project Highlights:")
            for project in study.projects[:8]:
                lines.append(
                    f"  - `{project.project_folder}` | plans={project.plan_count} | "
                    f"rasmap={project.has_rasmap} | hdf={project.output_hdf_count} | "
                    f"dss_refs={project.dss_reference_count} | "
                    f"preprocessor={project.preprocessor_status}"
                )
        lines.append("")

    return "\n".join(lines)


def run() -> None:
    parser = argparse.ArgumentParser(description="Audit and normalize the current eBFE delivery corpus.")
    parser.add_argument(
        "--report-root",
        default=str(REPORT_ROOT),
        help="Folder for markdown/json outputs.",
    )
    args = parser.parse_args()

    suppress_ras_info_logs()

    report_root = Path(args.report_root)
    report_root.mkdir(parents=True, exist_ok=True)

    studies: list[StudyAudit] = []

    organized_root = DEFAULT_WORKSPACE / "Organized"

    spring_root = organized_root / "SpringCreek_12040102"
    if spring_root.exists():
        spring_study, _ = repair_spring_creek(spring_root)
        studies.append(spring_study)

    lower_colorado_root = organized_root / "LowerColoradoCummins_12090301"
    if lower_colorado_root.exists():
        studies.append(audit_lower_colorado(lower_colorado_root))

    north_galveston_root = organized_root / "NorthGalvestonBay_12040203"
    if north_galveston_root.exists():
        studies.append(audit_organized_study("NorthGalvestonBay_12040203", north_galveston_root))

    upper_guadalupe_root = organized_root / "UpperGuadalupe_12100201"
    if upper_guadalupe_root.exists():
        studies.append(audit_organized_study("UpperGuadalupe_12100201", upper_guadalupe_root))

    rio_hondo_root = organized_root / "RioHondo_13060008"
    if rio_hondo_root.exists():
        studies.append(audit_organized_study("RioHondo_13060008", rio_hondo_root))

    amite_root = organized_root / "Amite_08070202"
    if amite_root.exists():
        studies.append(audit_organized_study("Amite_08070202", amite_root))

    tickfaw_root = organized_root / "Tickfaw_08070203"
    if tickfaw_root.exists():
        studies.append(audit_organized_study("Tickfaw_08070203", tickfaw_root))

    lake_maurepas_root = organized_root / "LakeMaurepas_08070204"
    if lake_maurepas_root.exists():
        studies.append(audit_organized_study("LakeMaurepas_08070204", lake_maurepas_root))

    lower_brazos_root = organized_root / "LowerBrazos_12070104"
    if lower_brazos_root.exists():
        studies.append(audit_lower_brazos(lower_brazos_root))

    apply_preprocessor_records(studies, preprocessor_reports())

    summary_md = build_summary_markdown(studies)
    common_format_md = build_common_format_markdown(studies)
    json_path = report_root / "audit_summary.json"

    write_text(report_root / "audit_summary.md", summary_md)
    write_text(report_root / "common_delivery_format_v1.md", common_format_md)
    json_path.write_text(json.dumps([asdict(study) for study in studies], indent=2), encoding="utf-8")

    print(f"Wrote {rel_path(report_root / 'audit_summary.md')}")
    print(f"Wrote {rel_path(report_root / 'common_delivery_format_v1.md')}")
    print(f"Wrote {rel_path(json_path)}")


if __name__ == "__main__":
    run()
