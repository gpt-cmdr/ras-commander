"""Isolated HEC-RAS scenario preparation for external hydrologic DSS inputs."""

from __future__ import annotations

import json
import re
import shutil
from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError,
)
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, Iterable, Mapping, Optional, Union

import h5py

from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasCmdr import RasCmdr
from .RasPlan import RasPlan
from .RasPrj import RasPrj, init_ras_project
from .RasUnsteady import RasUnsteady
from .RasUtils import RasUtils
from .geom import GeomCrossSection, GeomStorage
from .hdf.HdfBase import HdfBase

logger = get_logger(__name__)


@dataclass(frozen=True)
class RasBoundaryLink:
    """One exact HMS DSS pathname to HEC-RAS boundary mapping."""

    mapping_id: str
    dss_path: str
    expected_bc_type: str
    interval: str = "5MIN"
    river: Optional[str] = None
    reach: Optional[str] = None
    station: Optional[str] = None
    sa_2d_name: Optional[str] = None
    bc_line: Optional[str] = None
    boundary_index: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.mapping_id.strip():
            raise ValueError("mapping_id must be non-empty")
        if not self.dss_path.startswith("/") or not self.dss_path.endswith("/"):
            raise ValueError(f"Invalid DSS pathname: {self.dss_path!r}")
        if len(self.dss_path.split("/")) < 8:
            raise ValueError(f"Invalid DSS pathname: {self.dss_path!r}")
        has_1d = any(value for value in (self.river, self.reach, self.station))
        has_2d = any(value for value in (self.sa_2d_name, self.bc_line))
        if has_1d and has_2d:
            raise ValueError(
                "A boundary link cannot mix 1D and 2D selectors"
            )
        if not (has_1d or has_2d or self.boundary_index is not None):
            raise ValueError("A boundary link requires an exact boundary selector")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RasBoundaryLink":
        """Build a link from a contract or CSV-derived mapping."""
        return cls(**dict(value))


@dataclass(frozen=True)
class RasScenarioWorkspace:
    """Prepared, GUI-verifiable RAS scenario workspace."""

    scenario_id: str
    source_project: Path
    project_folder: Path
    project_file: Path
    plan_number: str
    plan_file: Path
    unsteady_number: str
    unsteady_file: Path
    hydrology_source: Path
    hydrology_file: Path
    result_hdf: Path
    boundary_mapping_ids: tuple[str, ...]
    simulation_start: Optional[str] = None
    simulation_end: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable workspace record."""
        return {
            key: (
                str(value)
                if isinstance(value, Path)
                else list(value)
                if isinstance(value, tuple)
                else value
            )
            for key, value in asdict(self).items()
        }

    def write_manifest(self, path: Union[str, Path]) -> Path:
        """Write the workspace record atomically."""
        return _write_json(path, self.to_dict())


@dataclass(frozen=True)
class RasRunArtifact:
    """Result of one RAS scenario execution."""

    scenario_id: str
    status: str
    plan_number: str
    project_folder: Path
    result_hdf: Path
    started_at: str
    finished_at: str
    compute_returned_successfully: bool
    result_exists: bool
    result_size_bytes: int
    hdf_completed_successfully: bool
    output_start: Optional[str]
    output_end: Optional[str]
    time_window_matches: bool
    hdf_inspection_error: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable run artifact."""
        return {
            key: str(value) if isinstance(value, Path) else value
            for key, value in asdict(self).items()
        }

    def write_manifest(self, path: Union[str, Path]) -> Path:
        """Write the execution record atomically."""
        return _write_json(path, self.to_dict())


def _write_json(path: Union[str, Path], payload: Dict[str, Any]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return output


class RasScenario:
    """Static namespace for HMS-to-RAS scenario preparation and execution."""

    @staticmethod
    @log_call
    def format_dss_pathname_for_window(
        pathname: str,
        start_time: datetime,
        end_time: datetime,
    ) -> str:
        """Materialize a deterministic DSS D-part for the requested window.

        HEC-DSS stores regular series in physical blocks and clients may display
        a blank D-part after resolving them. Writing the requested model window
        into the boundary link makes the prepared contract explicit and was
        validated with HEC-RAS 6.6; it does not rewrite the source DSS catalog.
        """
        if end_time <= start_time:
            raise ValueError("end_time must be later than start_time")
        if not pathname.startswith("/") or not pathname.endswith("/"):
            raise ValueError(f"Invalid DSS pathname: {pathname!r}")
        parts = pathname.split("/")[1:-1]
        if len(parts) != 6:
            raise ValueError(
                "DSS pathname must contain six A-F parts: "
                f"{pathname!r}"
            )
        parts[3] = (
            f"{start_time:%d%b%Y}-{end_time:%d%b%Y}".upper()
        )
        return "/" + "/".join(parts) + "/"

    @staticmethod
    @log_call
    def prepare_workspace(
        source_project: Union[str, Path],
        workspace: Union[str, Path],
        scenario_id: str,
        source_plan: Union[str, int],
        hydrology_dss: Union[str, Path],
        boundary_links: Iterable[Union[RasBoundaryLink, Mapping[str, Any]]],
        start_time: datetime,
        end_time: datetime,
        *,
        ras_exe_path: Union[str, Path],
        linked_asset_directories: Optional[
            Iterable[Union[str, Path]]
        ] = None,
        copy_hydrology: bool = True,
        overwrite: bool = False,
    ) -> RasScenarioWorkspace:
        """Clone a RAS project and its declared linked assets for one HMS result.

        ``workspace`` is the destination project directory. Directories passed
        through ``linked_asset_directories`` are copied beside that directory,
        preserving the sibling layout used by relative paths in ``.prj`` and
        ``.rasmap`` files.
        """
        source_file = RasScenario._resolve_project_file(source_project)
        source_folder = source_file.parent.resolve()
        destination = Path(workspace).resolve()
        hydrology_source = Path(hydrology_dss).resolve()
        linked_sources = tuple(
            Path(path).resolve()
            for path in (linked_asset_directories or ())
        )
        raw_links = tuple(
            link
            if isinstance(link, RasBoundaryLink)
            else RasBoundaryLink.from_mapping(link)
            for link in boundary_links
        )
        links = tuple(
            replace(
                link,
                dss_path=RasScenario.format_dss_pathname_for_window(
                    link.dss_path,
                    start_time,
                    end_time,
                ),
            )
            for link in raw_links
        )

        if not links:
            raise ValueError("At least one boundary link is required")
        if len({link.mapping_id for link in links}) != len(links):
            raise ValueError("boundary mapping IDs must be unique")
        if not hydrology_source.is_file():
            raise FileNotFoundError(
                f"Hydrology DSS file not found: {hydrology_source}"
            )
        if end_time <= start_time:
            raise ValueError("end_time must be later than start_time")
        if start_time.tzinfo is not None or end_time.tzinfo is not None:
            raise ValueError(
                "start_time and end_time must be naive datetimes in RAS model time"
            )

        RasScenario._validate_copy_boundaries(source_folder, destination)
        linked_destinations = tuple(
            destination.parent / source.name for source in linked_sources
        )
        if len({path.name.casefold() for path in linked_sources}) != len(
            linked_sources
        ):
            raise ValueError("linked asset directory names must be unique")
        for source, linked_destination in zip(
            linked_sources,
            linked_destinations,
        ):
            if not source.is_dir():
                raise FileNotFoundError(
                    f"Linked asset directory not found: {source}"
                )
            RasScenario._validate_copy_boundaries(
                source,
                linked_destination,
            )
            if linked_destination.exists():
                raise FileExistsError(
                    "Linked asset destination already exists: "
                    f"{linked_destination}"
                )
        if destination.exists():
            if not overwrite:
                raise FileExistsError(f"Workspace already exists: {destination}")
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            source_folder,
            destination,
            ignore=RasUtils.ignore_windows_reserved,
        )
        for source, linked_destination in zip(
            linked_sources,
            linked_destinations,
        ):
            shutil.copytree(
                source,
                linked_destination,
                ignore=RasUtils.ignore_windows_reserved,
            )

        copied_project = destination / source_file.name
        project = init_ras_project(
            copied_project,
            ras_version=str(Path(ras_exe_path)),
            ras_object=RasPrj(),
            load_results_summary=False,
            hide_intro=True,
        )

        slug = RasScenario._scenario_slug(scenario_id)
        source_plan_path = RasPlan.get_plan_path(source_plan, ras_object=project)
        if source_plan_path is None:
            raise ValueError(f"Source plan {source_plan!r} was not found")
        source_plan_number = RasUtils.normalize_ras_number(source_plan)
        plan_matches = project.plan_df[
            project.plan_df["plan_number"] == source_plan_number
        ]
        if plan_matches.empty:
            raise ValueError(f"Source plan {source_plan!r} was not found")
        source_unsteady_number = str(
            plan_matches.iloc[0].get("unsteady_number", "")
        ).lower().removeprefix("u")
        if not source_unsteady_number:
            raise ValueError(f"Source plan {source_plan!r} has no unsteady flow file")

        unsteady_number = RasPlan.clone_unsteady(
            source_unsteady_number,
            new_title=f"FloodForecast {slug}"[:32],
            ras_object=project,
        )
        plan_number = RasPlan.clone_plan(
            source_plan,
            new_plan_shortid=f"FF_{slug}"[:24],
            new_title=f"FloodForecast {slug}"[:32],
            unsteady_flow=unsteady_number,
            description=f"FloodForecast scenario {scenario_id}",
            ras_object=project,
        )
        RasPlan.update_simulation_date(
            plan_number,
            start_time,
            end_time,
            ras_object=project,
        )
        project.set_current_plan(plan_number)

        hydrology_dir = destination / "hydrology"
        hydrology_dir.mkdir(parents=True, exist_ok=True)
        if copy_hydrology:
            hydrology_file = hydrology_dir / hydrology_source.name
            shutil.copy2(hydrology_source, hydrology_file)
            dss_reference = str(
                hydrology_file.relative_to(destination)
            ).replace("/", "\\")
        else:
            hydrology_file = hydrology_source
            dss_reference = str(hydrology_source)

        unsteady_file = RasPlan.get_unsteady_path(
            unsteady_number,
            ras_object=project,
        )
        if unsteady_file is None:
            raise RuntimeError("Cloned unsteady flow file could not be resolved")

        for link in links:
            changed = RasUnsteady.set_boundary_dss_link(
                unsteady_file,
                river=link.river,
                reach=link.reach,
                station=link.station,
                dss_file=dss_reference,
                dss_path=link.dss_path,
                interval=link.interval,
                ras_object=project,
                sa_2d_name=link.sa_2d_name,
                bc_line=link.bc_line,
                boundary_index=link.boundary_index,
                expected_bc_type=link.expected_bc_type,
            )
            if not changed:
                raise ValueError(
                    f"Boundary mapping {link.mapping_id!r} did not match"
                )

        plan_file = RasPlan.get_plan_path(plan_number, ras_object=project)
        if plan_file is None:
            raise RuntimeError("Cloned plan file could not be resolved")
        prepared = RasScenarioWorkspace(
            scenario_id=scenario_id,
            source_project=source_file,
            project_folder=destination,
            project_file=copied_project,
            plan_number=plan_number,
            plan_file=plan_file,
            unsteady_number=unsteady_number,
            unsteady_file=unsteady_file,
            hydrology_source=hydrology_source,
            hydrology_file=hydrology_file,
            result_hdf=destination / f"{project.project_name}.p{plan_number}.hdf",
            boundary_mapping_ids=tuple(link.mapping_id for link in links),
            simulation_start=start_time.isoformat(),
            simulation_end=end_time.isoformat(),
        )
        RasScenario.validate_workspace(prepared, links)
        logger.info("Prepared RAS scenario workspace: %s", destination)
        return prepared

    @staticmethod
    @log_call
    def validate_workspace(
        workspace: RasScenarioWorkspace,
        boundary_links: Iterable[RasBoundaryLink],
    ) -> Dict[str, bool]:
        """Validate the plan/unsteady references and all exact DSS links."""
        plan_text = workspace.plan_file.read_text(
            encoding="utf-8",
            errors="replace",
        )
        unsteady_text = workspace.unsteady_file.read_text(
            encoding="utf-8",
            errors="replace",
        )
        links = tuple(boundary_links)
        if workspace.simulation_start and workspace.simulation_end:
            start_time = datetime.fromisoformat(workspace.simulation_start)
            end_time = datetime.fromisoformat(workspace.simulation_end)
            links = tuple(
                replace(
                    link,
                    dss_path=RasScenario.format_dss_pathname_for_window(
                        link.dss_path,
                        start_time,
                        end_time,
                    ),
                )
                for link in links
            )
        boundaries = RasUnsteady.get_dss_boundaries(
            workspace.unsteady_file,
        )
        linked_pathnames = {link.dss_path for link in links}
        mapped_boundaries = boundaries[
            boundaries["dss_path"].isin(linked_pathnames)
        ]
        dss_references = tuple(
            str(reference).strip()
            for reference in mapped_boundaries["dss_file"]
            if str(reference).strip()
        )

        def is_resolvable_reference(reference: str) -> bool:
            windows_path = PureWindowsPath(reference)
            return (
                Path(reference).is_absolute()
                or windows_path.is_absolute()
                or reference.replace("/", "\\").startswith((".\\", "..\\"))
            )

        def resolve_reference(reference: str) -> Path:
            native_path = Path(reference)
            if native_path.is_absolute():
                return native_path
            windows_path = PureWindowsPath(reference)
            if windows_path.is_absolute():
                return Path(str(windows_path))
            return workspace.project_folder.joinpath(*windows_path.parts)

        current_plan_match = re.search(
            r"^Current Plan=p(\w+)\s*$",
            workspace.project_file.read_text(
                encoding="utf-8",
                errors="replace",
            ),
            flags=re.MULTILINE,
        )
        actual_window = RasScenario._parse_simulation_window(plan_text)
        expected_window = (
            (
                datetime.fromisoformat(workspace.simulation_start),
                datetime.fromisoformat(workspace.simulation_end),
            )
            if workspace.simulation_start and workspace.simulation_end
            else None
        )
        geometry_crosswalk = RasScenario._geometry_boundary_crosswalk(
            workspace,
            links,
            plan_text,
        )

        checks = {
            "project_file_exists": workspace.project_file.is_file(),
            "plan_file_exists": workspace.plan_file.is_file(),
            "unsteady_file_exists": workspace.unsteady_file.is_file(),
            "hydrology_file_exists": workspace.hydrology_file.is_file(),
            "plan_uses_cloned_unsteady": (
                f"Flow File=u{workspace.unsteady_number}" in plan_text
            ),
            "project_uses_cloned_plan": (
                current_plan_match is not None
                and current_plan_match.group(1).zfill(2)
                == workspace.plan_number
            ),
            "plan_window_matches_contract": (
                expected_window is None or actual_window == expected_window
            ),
            "all_dss_paths_present": all(
                f"DSS Path={link.dss_path}" in unsteady_text for link in links
            ),
            "all_dss_file_references_resolvable": (
                bool(dss_references)
                and all(
                    is_resolvable_reference(reference)
                    for reference in dss_references
                )
            ),
            "all_dss_files_exist": (
                bool(dss_references)
                and all(
                    resolve_reference(reference).is_file()
                    for reference in dss_references
                )
            ),
            "all_mappings_recorded": (
                tuple(link.mapping_id for link in links)
                == workspace.boundary_mapping_ids
            ),
            "all_boundaries_exist_in_active_geometry": (
                bool(geometry_crosswalk)
                and all(geometry_crosswalk.values())
            ),
        }
        if not all(checks.values()):
            failed = [name for name, passed in checks.items() if not passed]
            raise ValueError(
                "Prepared RAS workspace failed validation: " + ", ".join(failed)
            )
        return checks

    @staticmethod
    def _parse_simulation_window(
        plan_text: str,
    ) -> Optional[tuple[datetime, datetime]]:
        """Parse a HEC-RAS ``Simulation Date`` line."""
        match = re.search(
            r"^Simulation Date=([^,\r\n]+),([^,\r\n]+),"
            r"([^,\r\n]+),([^,\r\n]+)\s*$",
            plan_text,
            flags=re.MULTILINE,
        )
        if match is None:
            return None

        def parse(date_token: str, time_token: str) -> datetime:
            date_value = datetime.strptime(
                date_token.strip().upper(),
                "%d%b%Y",
            )
            time_format = "%H:%M" if ":" in time_token else "%H%M"
            time_value = datetime.strptime(time_token.strip(), time_format)
            return date_value.replace(
                hour=time_value.hour,
                minute=time_value.minute,
            )

        return (
            parse(match.group(1), match.group(2)),
            parse(match.group(3), match.group(4)),
        )

    @staticmethod
    def _geometry_boundary_crosswalk(
        workspace: RasScenarioWorkspace,
        links: tuple[RasBoundaryLink, ...],
        plan_text: str,
    ) -> Dict[str, bool]:
        """Check each boundary selector against the plan's active geometry."""
        geometry_match = re.search(
            r"^Geom File=g(\w+)\s*$",
            plan_text,
            flags=re.MULTILINE,
        )
        if geometry_match is None:
            return {link.mapping_id: False for link in links}
        geometry_file = (
            workspace.project_folder
            / f"{workspace.project_file.stem}.g{geometry_match.group(1)}"
        )
        if not geometry_file.is_file():
            return {link.mapping_id: False for link in links}

        cross_sections = GeomCrossSection.get_cross_sections(geometry_file)
        storage_areas = GeomStorage.get_storage_areas(
            geometry_file,
            exclude_2d=False,
        )
        geometry_text = geometry_file.read_text(
            encoding="utf-8",
            errors="replace",
        )
        area_names = {
            str(value).strip().casefold()
            for value in storage_areas.get("Name", ())
        }
        bc_line_names = {
            value.strip().casefold()
            for value in re.findall(
                r"^BC Line Name=([^\r\n,]+)",
                geometry_text,
                flags=re.MULTILINE,
            )
        }

        def same_station(left: Any, right: Any) -> bool:
            try:
                return float(left) == float(right)
            except (TypeError, ValueError):
                return str(left).strip().casefold() == str(right).strip().casefold()

        results: Dict[str, bool] = {}
        for link in links:
            if link.river or link.reach or link.station:
                results[link.mapping_id] = any(
                    str(row["River"]).strip().casefold()
                    == str(link.river).strip().casefold()
                    and str(row["Reach"]).strip().casefold()
                    == str(link.reach).strip().casefold()
                    and same_station(row["RS"], link.station)
                    for _, row in cross_sections.iterrows()
                )
                continue
            area_exists = (
                str(link.sa_2d_name).strip().casefold() in area_names
            )
            bc_line_exists = (
                True
                if not link.bc_line
                else str(link.bc_line).strip().casefold() in bc_line_names
            )
            results[link.mapping_id] = area_exists and bc_line_exists
        return results

    @staticmethod
    @log_call
    def execute(
        workspace: RasScenarioWorkspace,
        *,
        ras_exe_path: Union[str, Path],
        timeout: int = 3600,
        num_cores: Optional[int] = None,
    ) -> RasRunArtifact:
        """Execute a prepared scenario through RasCmdr and record its result."""
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        project = init_ras_project(
            workspace.project_file,
            ras_version=str(Path(ras_exe_path)),
            ras_object=RasPrj(),
            load_results_summary=False,
            hide_intro=True,
        )
        started = datetime.now(timezone.utc)
        executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="ras-scenario",
        )
        future = executor.submit(
            RasCmdr.compute_plan,
            workspace.plan_number,
            ras_object=project,
            num_cores=num_cores,
            verify=True,
        )
        try:
            result = future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            cancelled = RasCmdr.cancel_plan(
                workspace.plan_number,
                ras_object=project,
            )
            raise TimeoutError(
                f"RAS plan {workspace.plan_number} exceeded "
                f"{timeout} seconds; cancellation requested={cancelled}"
            ) from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        finished = datetime.now(timezone.utc)
        result_exists = workspace.result_hdf.is_file()
        result_size = (
            workspace.result_hdf.stat().st_size if result_exists else 0
        )
        hdf_check = RasScenario._inspect_result_hdf(workspace)
        status = (
            "succeeded"
            if (
                bool(result)
                and result_size > 0
                and hdf_check["completed_successfully"]
                and hdf_check["time_window_matches"]
            )
            else "failed"
        )
        return RasRunArtifact(
            scenario_id=workspace.scenario_id,
            status=status,
            plan_number=workspace.plan_number,
            project_folder=workspace.project_folder,
            result_hdf=workspace.result_hdf,
            started_at=started.isoformat().replace("+00:00", "Z"),
            finished_at=finished.isoformat().replace("+00:00", "Z"),
            compute_returned_successfully=bool(result),
            result_exists=result_exists,
            result_size_bytes=result_size,
            hdf_completed_successfully=hdf_check["completed_successfully"],
            output_start=hdf_check["output_start"],
            output_end=hdf_check["output_end"],
            time_window_matches=hdf_check["time_window_matches"],
            hdf_inspection_error=hdf_check["error"],
        )

    @staticmethod
    def _inspect_result_hdf(
        workspace: RasScenarioWorkspace,
    ) -> Dict[str, Any]:
        """Verify the HDF completion marker and exact scenario time axis."""
        result = {
            "completed_successfully": False,
            "output_start": None,
            "output_end": None,
            "time_window_matches": False,
            "error": None,
        }
        if not workspace.result_hdf.is_file():
            result["error"] = "result HDF does not exist"
            return result
        if not workspace.simulation_start or not workspace.simulation_end:
            result["error"] = "workspace simulation window is not recorded"
            return result

        try:
            with h5py.File(workspace.result_hdf, "r") as hdf_file:
                event_conditions = hdf_file.get("Event Conditions")
                if event_conditions is None:
                    raise ValueError("Event Conditions group is missing")
                completed = event_conditions.attrs.get(
                    "Completed Successfully",
                )
                if isinstance(completed, bytes):
                    completed = completed.decode("utf-8", errors="replace")
                result["completed_successfully"] = (
                    str(completed).strip().casefold() == "true"
                )

                timestamps = HdfBase.get_unsteady_timestamps(hdf_file)
                if not timestamps:
                    raise ValueError("unsteady output time axis is empty")
                output_start = timestamps[0]
                output_end = timestamps[-1]
                result["output_start"] = output_start.isoformat()
                result["output_end"] = output_end.isoformat()

                expected_start = datetime.fromisoformat(
                    workspace.simulation_start,
                ).replace(tzinfo=None)
                expected_end = datetime.fromisoformat(
                    workspace.simulation_end,
                ).replace(tzinfo=None)
                result["time_window_matches"] = (
                    output_start.replace(tzinfo=None) == expected_start
                    and output_end.replace(tzinfo=None) == expected_end
                )
        except (OSError, KeyError, TypeError, ValueError) as exc:
            result["error"] = str(exc)
        return result

    @staticmethod
    def _resolve_project_file(source_project: Union[str, Path]) -> Path:
        source = Path(source_project).resolve()
        if source.is_file():
            if source.suffix.lower() != ".prj":
                raise ValueError(f"Not a HEC-RAS project file: {source}")
            return source
        if not source.is_dir():
            raise FileNotFoundError(f"RAS project not found: {source}")
        candidates = sorted(source.glob("*.prj"))
        if len(candidates) != 1:
            raise ValueError(
                f"Expected one .prj file in {source}, found {len(candidates)}"
            )
        return candidates[0]

    @staticmethod
    def _scenario_slug(scenario_id: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9_-]+", "_", str(scenario_id)).strip("_")
        if not slug:
            raise ValueError("scenario_id must contain at least one letter or number")
        return slug[:40]

    @staticmethod
    def _validate_copy_boundaries(source: Path, destination: Path) -> None:
        source = source.resolve()
        destination = destination.resolve()
        if (
            source == destination
            or source in destination.parents
            or destination in source.parents
        ):
            raise ValueError(
                "Source project and scenario workspace must not overlap"
            )
