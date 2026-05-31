"""Shared setup helpers for example notebooks.

These helpers keep results-dependent notebooks self-sufficient without
committing large HEC-RAS result HDF files.
"""

from pathlib import Path
from typing import Any, Optional, Union

from ras_commander import RasCmdr, RasExamples


def get_or_extract_example_project(
    project_name: str,
    *,
    suffix: Optional[str] = None,
    output_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Return an existing extracted example project or extract it once.

    ``RasExamples.extract_project`` intentionally replaces an existing folder.
    Results-dependent notebooks need reruns to keep precomputed HDF files, so
    this helper reuses a valid project folder when it already exists.
    """
    base_output_path = Path(output_path) if output_path is not None else RasExamples.projects_dir
    folder_name = RasExamples._get_folder_name(project_name, suffix)
    project_path = base_output_path / folder_name

    if project_path.exists() and any(project_path.glob("*.prj")):
        print(f"Using existing extracted project: {project_path}")
        return project_path

    return Path(
        RasExamples.extract_project(
            project_name,
            output_path=output_path,
            suffix=suffix,
        )
    )


def get_plan_result_hdf_path(plan_number: Union[str, int], *, ras_object: Any) -> Path:
    """Return the expected result HDF path for a plan in the active project."""
    normalized_plan = str(plan_number).zfill(2)
    return Path(ras_object.project_folder) / f"{ras_object.project_name}.p{normalized_plan}.hdf"


def ensure_plan_result_hdf(
    plan_number: Union[str, int],
    *,
    ras_object: Any,
    num_cores: int = 2,
    clear_geompre: bool = False,
    **compute_kwargs: Any,
) -> Path:
    """Compute a plan only when its result HDF is missing."""
    normalized_plan = str(plan_number).zfill(2)
    hdf_path = get_plan_result_hdf_path(normalized_plan, ras_object=ras_object)

    if hdf_path.exists():
        print(f"Plan {normalized_plan} HDF already exists; skipping prerequisite compute: {hdf_path}")
        return hdf_path

    print(f"Plan {normalized_plan} HDF is missing; computing prerequisite: {hdf_path}")
    compute_options = {
        "ras_object": ras_object,
        "num_cores": num_cores,
        "clear_geompre": clear_geompre,
    }
    compute_options.update(compute_kwargs)
    RasCmdr.compute_plan(plan_number=normalized_plan, **compute_options)

    if not hdf_path.exists():
        raise FileNotFoundError(f"Plan HDF not found after compute: {hdf_path}")

    return hdf_path
