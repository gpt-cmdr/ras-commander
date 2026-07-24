"""Isolated HEC-RAS scenario preparation for external hydrologic DSS inputs."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Union

from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasCmdr import RasCmdr
from .RasPlan import RasPlan
from .RasPrj import RasPrj, init_ras_project
from .RasUnsteady import RasUnsteady
from .RasUtils import RasUtils

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
    result_exists: bool
    result_size_bytes: int

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
        copy_hydrology: bool = True,
        overwrite: bool = False,
    ) -> RasScenarioWorkspace:
        """Clone a RAS project, plan, and unsteady file for one HMS result."""
        source_file = RasScenario._resolve_project_file(source_project)
        source_folder = source_file.parent.resolve()
        destination = Path(workspace).resolve()
        hydrology_source = Path(hydrology_dss).resolve()
        links = tuple(
            link
            if isinstance(link, RasBoundaryLink)
            else RasBoundaryLink.from_mapping(link)
            for link in boundary_links
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
        checks = {
            "project_file_exists": workspace.project_file.is_file(),
            "plan_file_exists": workspace.plan_file.is_file(),
            "unsteady_file_exists": workspace.unsteady_file.is_file(),
            "hydrology_file_exists": workspace.hydrology_file.is_file(),
            "plan_uses_cloned_unsteady": (
                f"Flow File=u{workspace.unsteady_number}" in plan_text
            ),
            "all_dss_paths_present": all(
                f"DSS Path={link.dss_path}" in unsteady_text for link in links
            ),
            "all_mappings_recorded": (
                tuple(link.mapping_id for link in links)
                == workspace.boundary_mapping_ids
            ),
        }
        if not all(checks.values()):
            failed = [name for name, passed in checks.items() if not passed]
            raise ValueError(
                "Prepared RAS workspace failed validation: " + ", ".join(failed)
            )
        return checks

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
        project = init_ras_project(
            workspace.project_file,
            ras_version=str(Path(ras_exe_path)),
            ras_object=RasPrj(),
            load_results_summary=False,
            hide_intro=True,
        )
        started = datetime.now(timezone.utc)
        result = RasCmdr.compute_plan(
            workspace.plan_number,
            ras_object=project,
            timeout=timeout,
            num_cores=num_cores,
            verify=True,
        )
        finished = datetime.now(timezone.utc)
        result_exists = workspace.result_hdf.is_file()
        result_size = (
            workspace.result_hdf.stat().st_size if result_exists else 0
        )
        status = "succeeded" if bool(result) and result_size > 0 else "failed"
        return RasRunArtifact(
            scenario_id=workspace.scenario_id,
            status=status,
            plan_number=workspace.plan_number,
            project_folder=workspace.project_folder,
            result_hdf=workspace.result_hdf,
            started_at=started.isoformat().replace("+00:00", "Z"),
            finished_at=finished.isoformat().replace("+00:00", "Z"),
            result_exists=result_exists,
            result_size_bytes=result_size,
        )

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
