"""
RasPermutation: Generalized parameter sweep framework for HEC-RAS.

This module creates plan permutations from a template plan, partitions them
across cloned project folders to respect the 99-plan HEC-RAS limit, executes
the resulting batches, and writes audit-friendly CSV logs.
"""

from __future__ import annotations

from dataclasses import dataclass
import itertools
import math
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import numpy as np
import pandas as pd

from .Decorators import log_call
from .LoggingConfig import get_logger


logger = get_logger(__name__)

MAX_PLANS_PER_PROJECT = 99


@dataclass
class RangeSpec:
    """Specification for a parameter range."""

    minimum: float
    maximum: float
    interval: float
    inclusive: bool = True

    def generate_values(self) -> List[float]:
        """Generate values from minimum to maximum at the given interval."""
        if self.interval <= 0:
            raise ValueError("interval must be greater than zero")

        if self.minimum > self.maximum:
            raise ValueError("minimum cannot be greater than maximum")

        values: List[float] = []
        current = self.minimum
        epsilon = self.interval * 1e-9
        limit = (
            self.maximum + epsilon
            if self.inclusive
            else self.maximum - epsilon
        )

        while current <= limit:
            values.append(round(current, 10))
            current += self.interval

        if self.inclusive and values:
            if not math.isclose(
                values[-1],
                self.maximum,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                values.append(round(self.maximum, 10))

        return values


class RasPermutation:
    """Static helpers for plan permutation workflows."""

    @staticmethod
    def _prepare_parameters_df(parameters_df: pd.DataFrame) -> pd.DataFrame:
        """Normalize parameter DataFrame and enforce sequential IDs."""
        if parameters_df is None or len(parameters_df) == 0:
            return pd.DataFrame(columns=["absolute_perm_id"])

        prepared = parameters_df.copy().reset_index(drop=True)

        if "absolute_perm_id" not in prepared.columns:
            prepared.insert(0, "absolute_perm_id", np.arange(1, len(prepared) + 1))

        parameter_columns = [
            column for column in prepared.columns
            if column != "absolute_perm_id"
        ]

        if not parameter_columns:
            raise ValueError(
                "parameters_df must contain at least one parameter column"
            )

        prepared["absolute_perm_id"] = np.arange(1, len(prepared) + 1)
        return prepared[["absolute_perm_id", *parameter_columns]]

    @staticmethod
    def _partition_dataframe(
        parameters_df: pd.DataFrame,
        batch_size: int,
    ) -> List[pd.DataFrame]:
        """Partition a DataFrame into batch-sized chunks."""
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")

        batches: List[pd.DataFrame] = []
        for start in range(0, len(parameters_df), batch_size):
            stop = start + batch_size
            batches.append(parameters_df.iloc[start:stop].copy())
        return batches

    @staticmethod
    def _derive_plan_title(template_title: str, absolute_perm_id: int) -> str:
        """Build an 80-character-safe plan title."""
        suffix = f" Perm {absolute_perm_id:05d}"
        base = (template_title or "Permutation").strip()
        max_base_length = max(0, 80 - len(suffix))
        return f"{base[:max_base_length]}{suffix}"

    @staticmethod
    def _derive_short_identifier(
        template_shortid: str,
        absolute_perm_id: int,
    ) -> str:
        """Build a 24-character-safe short identifier."""
        suffix = f"P{absolute_perm_id:05d}"
        base = re.sub(r"\s+", "", (template_shortid or "PERM")).upper()
        max_base_length = max(0, 24 - len(suffix))
        return f"{base[:max_base_length]}{suffix}"

    @staticmethod
    def _create_backup(file_path: Path) -> Path:
        """Create a simple .bak backup file."""
        backup_path = file_path.with_suffix(f"{file_path.suffix}.bak")
        shutil.copy2(file_path, backup_path)
        return backup_path

    @staticmethod
    def _read_text_lines(file_path: Path) -> List[str]:
        """Read text lines without newline translation."""
        with open(
            file_path,
            "r",
            encoding="utf-8",
            errors="ignore",
            newline="",
        ) as handle:
            return handle.readlines()

    @staticmethod
    def _write_text_lines_crlf(file_path: Path, lines: List[str]) -> None:
        """Write text lines with Windows CRLF line endings."""
        normalized_lines = [
            f"{line.rstrip(chr(13) + chr(10))}\r\n"
            for line in lines
        ]

        with open(
            file_path,
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            handle.writelines(normalized_lines)

        if not RasPermutation._has_crlf_only(file_path):
            raise RuntimeError(
                f"Failed to preserve CRLF line endings in {file_path}"
            )

    @staticmethod
    def _normalize_file_to_crlf(file_path: Path) -> None:
        """Normalize an existing text file to CRLF line endings."""
        lines = RasPermutation._read_text_lines(file_path)
        RasPermutation._write_text_lines_crlf(file_path, lines)

    @staticmethod
    def _has_crlf_only(file_path: Path) -> bool:
        """Return True when a text file contains only CRLF newlines."""
        content = file_path.read_bytes()

        if b"\n" not in content and b"\r" not in content:
            return True

        content_without_crlf = content.replace(b"\r\n", b"")
        return (
            b"\n" not in content_without_crlf
            and b"\r" not in content_without_crlf
        )

    @staticmethod
    def _update_plan_metadata(
        plan_file_path: Path,
        plan_title: str,
        short_id: str,
    ) -> None:
        """Update plan title and short ID while preserving CRLF."""
        lines = RasPermutation._read_text_lines(plan_file_path)

        title_found = False
        shortid_found = False
        title_insert_index = 0

        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("Plan Title="):
                lines[index] = f"Plan Title={plan_title}\r\n"
                title_found = True
                title_insert_index = index + 1
                continue

            if stripped.startswith("Short Identifier="):
                lines[index] = f"Short Identifier={short_id}\r\n"
                shortid_found = True

        if not title_found:
            lines.insert(0, f"Plan Title={plan_title}\r\n")
            title_insert_index = 1

        if not shortid_found:
            lines.insert(title_insert_index, f"Short Identifier={short_id}\r\n")

        RasPermutation._write_text_lines_crlf(plan_file_path, lines)

    @staticmethod
    def _consolidate_plan_file_entries(prj_file_path: Path) -> None:
        """
        Consolidate scattered or duplicated Plan File= entries in a .prj file.

        This is adapted from the production TNTech implementation because the
        current clone workflow can leave duplicate or poorly grouped plan
        references in the project file.
        """
        if not prj_file_path.exists():
            raise FileNotFoundError(f"Project file not found: {prj_file_path}")

        lines = RasPermutation._read_text_lines(prj_file_path)

        current_plan_indices = []
        for index, line in enumerate(lines):
            if line.strip().startswith("Current Plan="):
                current_plan_indices.append(index)

        if len(current_plan_indices) > 1:
            config_line_types = [
                "Geom File=",
                "Flow File=",
                "Unsteady File=",
                "Plan File=",
            ]

            all_config_entries: Dict[str, List[str]] = {
                line_type: [] for line_type in config_line_types
            }

            for line in lines:
                stripped = line.strip()
                for line_type in config_line_types:
                    if stripped.startswith(line_type):
                        all_config_entries[line_type].append(line)
                        break

            unique_config_entries: Dict[str, List[str]] = {}
            for line_type, entries in all_config_entries.items():
                seen = set()
                unique_entries = []
                for line in entries:
                    key = line.strip()
                    if key not in seen:
                        seen.add(key)
                        unique_entries.append(line)
                unique_config_entries[line_type] = unique_entries

            first_block_end = current_plan_indices[1]
            first_block_lines = lines[:first_block_end]

            insertion_point = 0
            for index, line in enumerate(first_block_lines):
                stripped = line.strip()
                if any(
                    stripped.startswith(line_type)
                    for line_type in config_line_types
                ):
                    insertion_point = index + 1

            if insertion_point == 0:
                for index, line in enumerate(first_block_lines):
                    if line.strip().startswith("Current Plan="):
                        insertion_point = index + 1
                        break

            result_lines: List[str] = []

            for index in range(insertion_point):
                stripped = first_block_lines[index].strip()
                if not any(
                    stripped.startswith(line_type)
                    for line_type in config_line_types
                ):
                    result_lines.append(first_block_lines[index])

            result_lines.extend(unique_config_entries["Geom File="])
            result_lines.extend(unique_config_entries["Flow File="])
            result_lines.extend(unique_config_entries["Unsteady File="])
            result_lines.extend(unique_config_entries["Plan File="])

            for index in range(insertion_point, len(first_block_lines)):
                stripped = first_block_lines[index].strip()
                if not any(
                    stripped.startswith(line_type)
                    for line_type in config_line_types
                ):
                    result_lines.append(first_block_lines[index])

            RasPermutation._create_backup(prj_file_path)
            RasPermutation._write_text_lines_crlf(prj_file_path, result_lines)
            return

        plan_file_lines = []
        for index, line in enumerate(lines):
            if line.strip().startswith("Plan File="):
                plan_file_lines.append((index, line))

        if len(plan_file_lines) <= 1:
            return

        first_plan_index = plan_file_lines[0][0]
        last_consecutive_index = first_plan_index

        for index in range(1, len(plan_file_lines)):
            if plan_file_lines[index][0] == last_consecutive_index + 1:
                last_consecutive_index = plan_file_lines[index][0]
            else:
                break

        if last_consecutive_index == plan_file_lines[-1][0]:
            return

        seen = set()
        unique_plan_lines = []
        for _, line in plan_file_lines:
            key = line.strip()
            if key not in seen:
                seen.add(key)
                unique_plan_lines.append(line)

        result_lines: List[str] = []
        plan_lines_inserted = False
        for line in lines:
            if line.strip().startswith("Plan File="):
                if not plan_lines_inserted:
                    result_lines.extend(unique_plan_lines)
                    plan_lines_inserted = True
            else:
                result_lines.append(line)

        RasPermutation._create_backup(prj_file_path)
        RasPermutation._write_text_lines_crlf(prj_file_path, result_lines)

    @staticmethod
    def _write_csv(dataframe: pd.DataFrame, output_path: Path) -> None:
        """Write a CSV with CRLF line endings."""
        dataframe.to_csv(
            output_path,
            index=False,
            encoding="utf-8",
            lineterminator="\r\n",
        )

    @staticmethod
    def _get_plan_path(plan_number: str, ras_object: Any) -> Path:
        """Resolve a plan path from plan_df, with a safe fallback."""
        plan_row = ras_object.plan_df[
            ras_object.plan_df["plan_number"] == plan_number
        ]

        if not plan_row.empty and pd.notna(plan_row.iloc[0].get("full_path")):
            return Path(str(plan_row.iloc[0]["full_path"]))

        return Path(ras_object.project_folder) / (
            f"{ras_object.project_name}.p{plan_number}"
        )

    @staticmethod
    def _derive_status(
        summary_row: pd.Series,
        execution_success: Optional[bool],
    ) -> str:
        """Collapse execution and summary flags into a single status string."""
        if execution_success is False:
            return "failed"

        completed = bool(summary_row.get("completed"))
        has_errors = bool(summary_row.get("has_errors"))
        hdf_exists = bool(summary_row.get("hdf_exists"))

        if completed and has_errors:
            return "completed_with_errors"

        if completed:
            return "completed"

        if hdf_exists:
            return "incomplete"

        if execution_success is True:
            return "executed_no_summary"

        return "not_run"

    @staticmethod
    def _extract_max_wse(hdf_path: Path, ras_object: Any = None) -> float:
        """Extract an overall max WSE with 1D-first, 2D-fallback logic."""
        from .hdf import HdfChannelCapacity, HdfResultsMesh

        try:
            xs_df = HdfChannelCapacity.extract_max_wse(
                hdf_path,
                profile_names=["max_wse"],
                ras_object=ras_object,
            )
            if not xs_df.empty and "max_wse" in xs_df.columns:
                values = pd.to_numeric(xs_df["max_wse"], errors="coerce")
                if values.notna().any():
                    return float(values.max())
        except Exception as exc:
            logger.debug(
                "1D max WSE extraction failed for %s: %s",
                hdf_path,
                exc,
            )

        try:
            mesh_gdf = HdfResultsMesh.get_mesh_max_ws(hdf_path)
            if (
                not mesh_gdf.empty
                and "maximum_water_surface" in mesh_gdf.columns
            ):
                values = pd.to_numeric(
                    mesh_gdf["maximum_water_surface"],
                    errors="coerce",
                )
                if values.notna().any():
                    return float(values.max())
        except Exception as exc:
            logger.debug(
                "2D max WSE extraction failed for %s: %s",
                hdf_path,
                exc,
            )

        return float("nan")

    @staticmethod
    @log_call
    def define_parameters(
        param_dict: Dict[str, Union[List[float], RangeSpec]],
    ) -> pd.DataFrame:
        """
        Expand parameter definitions into a Cartesian product DataFrame.
        """
        if not param_dict:
            logger.warning("No parameters were provided to define_parameters")
            return pd.DataFrame(columns=["absolute_perm_id"])

        expanded_params: Dict[str, List[float]] = {}
        for param_name, values in param_dict.items():
            if isinstance(values, RangeSpec):
                expanded_values = values.generate_values()
            else:
                expanded_values = list(values)

            if not expanded_values:
                raise ValueError(
                    f"Parameter '{param_name}' did not produce any values"
                )

            expanded_params[param_name] = expanded_values

        param_names = list(expanded_params.keys())
        permutations = itertools.product(
            *(expanded_params[name] for name in param_names)
        )

        rows = []
        for absolute_perm_id, permutation in enumerate(permutations, start=1):
            row = {"absolute_perm_id": absolute_perm_id}
            row.update(
                {
                    param_names[index]: permutation[index]
                    for index in range(len(param_names))
                }
            )
            rows.append(row)

        result = pd.DataFrame(rows, columns=["absolute_perm_id", *param_names])
        logger.info("Defined %s total permutation(s)", len(result))
        return result

    @staticmethod
    @log_call
    def generate_plans(
        template_plan: str,
        parameters_df: pd.DataFrame,
        apply_fn: Callable[[Path, pd.Series, Any], None],
        suffix: str = "perms",
        max_plans_per_batch: int = 99,
        clone_geom: bool = False,
        ras_object: Any = None,
    ) -> dict:
        """
        Generate plan permutations from a template plan.
        """
        from .RasPlan import RasPlan
        from .RasPrj import RasPrj, init_ras_project, ras
        from .RasUtils import RasUtils

        if not callable(apply_fn):
            raise TypeError("apply_fn must be callable")

        source_ras = ras_object or ras
        source_ras.check_initialized()

        prepared_df = RasPermutation._prepare_parameters_df(parameters_df)
        if prepared_df.empty:
            raise ValueError("parameters_df is empty")

        template_plan = RasUtils.normalize_ras_number(template_plan)
        suffix = str(suffix).strip() or "perms"
        max_plans_per_batch = int(max_plans_per_batch)

        if max_plans_per_batch <= 0:
            raise ValueError("max_plans_per_batch must be greater than zero")

        source_project = RasUtils.safe_resolve(Path(source_ras.project_folder))

        template_row = source_ras.plan_df[
            source_ras.plan_df["plan_number"] == template_plan
        ]
        if template_row.empty:
            raise ValueError(
                f"Template plan {template_plan} was not found in source project"
            )

        template_title = str(template_row.iloc[0].get("Plan Title", "")).strip()
        template_shortid = str(
            template_row.iloc[0].get("Short Identifier", "")
        ).strip()

        existing_plan_count = len(source_ras.plan_df.index)
        available_slots = MAX_PLANS_PER_PROJECT - existing_plan_count

        if available_slots <= 0:
            raise ValueError(
                "Template project already contains 99 plans; "
                "cannot add permutations"
            )

        effective_batch_size = min(
            MAX_PLANS_PER_PROJECT,
            max_plans_per_batch,
            available_slots,
        )
        batches = RasPermutation._partition_dataframe(
            prepared_df,
            effective_batch_size,
        )

        parameter_columns = [
            column for column in prepared_df.columns
            if column != "absolute_perm_id"
        ]

        batch_folders: List[Path] = []
        master_rows: List[Dict[str, Any]] = []

        for batch_index, batch_df in enumerate(batches, start=1):
            batch_folder = source_project.parent / (
                f"{source_project.name}_{suffix}_{batch_index:03d}"
            )

            if batch_folder.exists():
                if batch_folder.resolve() == source_project.resolve():
                    raise FileExistsError(
                        "Batch folder resolves to the source project folder"
                    )
                shutil.rmtree(batch_folder)

            shutil.copytree(
                source_project,
                batch_folder,
                ignore=RasUtils.ignore_windows_reserved,
            )

            batch_ras = RasPrj()
            init_ras_project(
                batch_folder,
                getattr(source_ras, "ras_exe_path", None),
                ras_object=batch_ras,
                load_results_summary=False,
            )

            template_plan_path = RasPermutation._get_plan_path(
                template_plan,
                batch_ras,
            )
            RasPermutation._create_backup(template_plan_path)

            batch_rows: List[Dict[str, Any]] = []
            for _, param_row in batch_df.iterrows():
                param_row = param_row.copy()
                absolute_perm_id = int(param_row["absolute_perm_id"])

                new_plan_number = RasPlan.clone_plan(
                    template_plan,
                    ras_object=batch_ras,
                )

                new_plan_path = RasPermutation._get_plan_path(
                    new_plan_number,
                    batch_ras,
                )

                # Clone the geometry per realization so geometry-modifying
                # apply_fns (Manning's n / breach) are isolated. clone_plan only
                # clones the .p## and leaves it pointing at the template geometry,
                # so without this every sample edits the SAME .g## and the writes
                # collide (last-write-wins) -> identical results.
                if clone_geom:
                    template_geom_number = None
                    perm_plan_df = getattr(batch_ras, "plan_df", None)
                    if (
                        perm_plan_df is not None
                        and not perm_plan_df.empty
                        and "plan_number" in perm_plan_df.columns
                        and "geometry_number" in perm_plan_df.columns
                    ):
                        normalized_plan_numbers = perm_plan_df["plan_number"].apply(
                            RasUtils.normalize_ras_number
                        )
                        match = perm_plan_df[
                            normalized_plan_numbers
                            == RasUtils.normalize_ras_number(template_plan)
                        ]
                        if not match.empty:
                            template_geom_number = RasUtils.normalize_ras_number(
                                match.iloc[0]["geometry_number"]
                            )
                    if template_geom_number is None:
                        raise ValueError(
                            "clone_geom=True but could not resolve the geometry "
                            f"number for template plan {template_plan}"
                        )
                    new_geom_number = RasPlan.clone_geom(
                        template_geom_number,
                        ras_object=batch_ras,
                    )
                    RasPlan.set_geom(
                        new_plan_number,
                        new_geom_number,
                        ras_object=batch_ras,
                    )

                plan_title = RasPermutation._derive_plan_title(
                    template_title,
                    absolute_perm_id,
                )
                short_id = RasPermutation._derive_short_identifier(
                    template_shortid,
                    absolute_perm_id,
                )

                RasPermutation._create_backup(new_plan_path)
                RasPermutation._update_plan_metadata(
                    new_plan_path,
                    plan_title,
                    short_id,
                )

                apply_fn(new_plan_path, param_row, batch_ras)
                RasPermutation._normalize_file_to_crlf(new_plan_path)

                batch_row = {
                    "absolute_perm_id": absolute_perm_id,
                    "plan_number": new_plan_number,
                    "plan_title": plan_title,
                }
                master_row = {
                    "absolute_perm_id": absolute_perm_id,
                    "batch_folder": batch_folder.name,
                    "batch_index": batch_index,
                    "plan_number": new_plan_number,
                    "short_id": short_id,
                    "plan_title": plan_title,
                }

                for column in parameter_columns:
                    batch_row[column] = param_row[column]
                    master_row[column] = param_row[column]

                batch_rows.append(batch_row)
                master_rows.append(master_row)

            RasPermutation._consolidate_plan_file_entries(Path(batch_ras.prj_file))

            batch_log_columns = [
                "absolute_perm_id",
                "plan_number",
                "plan_title",
                *parameter_columns,
            ]
            batch_log = pd.DataFrame(batch_rows, columns=batch_log_columns)
            RasPermutation._write_csv(
                batch_log,
                batch_folder / "permutations_log.csv",
            )

            batch_folders.append(batch_folder)

        master_log_columns = [
            "absolute_perm_id",
            "batch_folder",
            "batch_index",
            "plan_number",
            "short_id",
            "plan_title",
            *parameter_columns,
        ]
        master_log_df = pd.DataFrame(master_rows, columns=master_log_columns)
        master_log_path = source_project.parent / (
            f"{source_project.name}_{suffix}_master_log.csv"
        )
        RasPermutation._write_csv(master_log_df, master_log_path)

        logger.info(
            "Generated %s permutation(s) across %s batch(es)",
            len(prepared_df),
            len(batch_folders),
        )

        return {
            "master_log": master_log_path,
            "batch_folders": batch_folders,
            "total_permutations": len(prepared_df),
            "batches": len(batch_folders),
        }

    @staticmethod
    @log_call
    def execute_and_summarize(
        plan_matrix: dict,
        max_workers: int = 2,
        num_cores: int = 2,
        ras_object: Any = None,
        timeout_sec: Optional[int] = None,
        clear_geompre: bool = False,
        force_geompre: bool = False,
        workers: Optional[List[Any]] = None,
    ) -> pd.DataFrame:
        """
        Execute generated batch folders and append summary metrics to master log.

        Args:
            plan_matrix: Output from generate_plans().
            max_workers: Maximum parallel worker count (local execution).
            num_cores: HEC-RAS core count per plan execution.
            ras_object: Optional project object for multi-project workflows.
            timeout_sec: Optional per-plan timeout in seconds. NOTE: per-plan
                timeout is not yet supported by RasCmdr.compute_parallel() on the
                current Windows execution path; when set it is logged and ignored
                (tracked as a follow-up). The ensemble still runs to completion.
            clear_geompre: Clear .c## preprocessor files before execution.
            force_geompre: Force full geometry preprocessing before execution.
            workers: Optional list of remote worker objects from
                init_ras_worker(). When provided, plans are distributed
                across the remote fleet via compute_parallel_remote()
                instead of local compute_parallel().
        """
        from .RasCmdr import RasCmdr
        from .RasPrj import RasPrj, init_ras_project, ras

        if "master_log" not in plan_matrix:
            raise ValueError("plan_matrix must contain a 'master_log' entry")

        if "batch_folders" not in plan_matrix:
            raise ValueError("plan_matrix must contain 'batch_folders'")

        master_log_path = Path(plan_matrix["master_log"])
        master_df = pd.read_csv(master_log_path)

        source_ras = ras_object or ras
        ras_exe_path = getattr(source_ras, "ras_exe_path", None)

        use_remote = workers is not None and len(workers) > 0

        batch_results: List[pd.DataFrame] = []
        for batch_folder in plan_matrix["batch_folders"]:
            batch_folder = Path(batch_folder)
            batch_log_path = batch_folder / "permutations_log.csv"

            if not batch_log_path.exists():
                raise FileNotFoundError(f"Missing batch log: {batch_log_path}")

            batch_log_df = pd.read_csv(batch_log_path)
            batch_log_df["plan_number"] = (
                batch_log_df["plan_number"].astype(str).str.zfill(2)
            )

            batch_ras = RasPrj()
            init_ras_project(
                batch_folder,
                ras_exe_path,
                ras_object=batch_ras,
            )

            plan_numbers = batch_log_df["plan_number"].tolist()

            if use_remote:
                from .remote import compute_parallel_remote

                remote_results = compute_parallel_remote(
                    plan_numbers=plan_numbers,
                    workers=workers,
                    ras_object=batch_ras,
                    num_cores=num_cores,
                    clear_geompre=clear_geompre,
                    force_geompre=force_geompre,
                )

                execution_success_map = {
                    plan_num: er.success
                    for plan_num, er in remote_results.items()
                }

                summary_df = batch_ras.update_results_df(plan_numbers=plan_numbers)
                summary_df = summary_df[
                    summary_df["plan_number"].isin(plan_numbers)
                ].copy()
            else:
                if timeout_sec is not None:
                    logger.warning(
                        "timeout_sec=%s ignored: per-plan timeout is not yet supported "
                        "by RasCmdr.compute_parallel(); the ensemble runs without a "
                        "per-plan timeout (tracked as a follow-up).",
                        timeout_sec,
                    )
                compute_result = RasCmdr.compute_parallel(
                    plan_number=plan_numbers,
                    max_workers=max_workers,
                    num_cores=num_cores,
                    ras_object=batch_ras,
                    clear_geompre=clear_geompre,
                    force_geompre=force_geompre,
                )

                execution_success_map = compute_result.execution_results

                summary_df = compute_result.results_df.copy()
                if summary_df.empty:
                    summary_df = batch_ras.update_results_df(plan_numbers=plan_numbers)
                    summary_df = summary_df[
                        summary_df["plan_number"].isin(plan_numbers)
                    ].copy()

            if summary_df.empty:
                batch_summary = batch_log_df[
                    ["absolute_perm_id", "plan_number"]
                ].copy()
                batch_summary["status"] = batch_summary["plan_number"].map(
                    lambda plan_num: RasPermutation._derive_status(
                        pd.Series(dtype="object"),
                        # Branch-neutral: execution_success_map is populated for
                        # both local and remote paths (compute_result is local-only).
                        execution_success_map.get(plan_num),
                    )
                )
                batch_summary["max_wse"] = np.nan
                batch_summary["runtime_seconds"] = np.nan
                batch_summary["hdf_path"] = batch_summary["plan_number"].map(
                    lambda plan_num: str(
                        batch_folder
                        / f"{batch_ras.project_name}.p{plan_num}.hdf"
                    )
                    if (
                        batch_folder
                        / f"{batch_ras.project_name}.p{plan_num}.hdf"
                    ).exists()
                    else np.nan
                )
                batch_results.append(batch_summary)
                continue

            summary_df["plan_number"] = (
                summary_df["plan_number"].astype(str).str.zfill(2)
            )

            summary_df["status"] = summary_df.apply(
                lambda row: RasPermutation._derive_status(
                    row,
                    execution_success_map.get(row["plan_number"]),
                ),
                axis=1,
            )

            # The remote execution path (compute_parallel_remote) returns a
            # results_df without the local-compute 'runtime_complete_process_hours'
            # column. Default to NaN runtimes when it is absent rather than raising
            # KeyError -- this otherwise crashes batch summarization whenever a
            # remote batch has no successful plans (e.g. a transient worker/network
            # outage fails every plan), masking the real failure with a KeyError.
            if "runtime_complete_process_hours" in summary_df.columns:
                runtime_hours = pd.to_numeric(
                    summary_df["runtime_complete_process_hours"],
                    errors="coerce",
                )
            else:
                runtime_hours = pd.Series(np.nan, index=summary_df.index)
            summary_df["runtime_seconds"] = runtime_hours * 3600.0

            summary_df["max_wse"] = summary_df["hdf_path"].apply(
                lambda value: RasPermutation._extract_max_wse(
                    Path(value),
                    ras_object=batch_ras,
                )
                if pd.notna(value) and Path(value).exists()
                else np.nan
            )

            reduced_summary = summary_df[
                ["plan_number", "status", "max_wse", "runtime_seconds", "hdf_path"]
            ].copy()

            batch_summary = batch_log_df[
                ["absolute_perm_id", "plan_number"]
            ].merge(
                reduced_summary,
                on="plan_number",
                how="left",
            )
            batch_results.append(batch_summary)

        if batch_results:
            all_results_df = pd.concat(batch_results, ignore_index=True)
        else:
            all_results_df = pd.DataFrame(
                columns=[
                    "absolute_perm_id",
                    "status",
                    "max_wse",
                    "runtime_seconds",
                    "hdf_path",
                ]
            )

        result_columns = [
            "status",
            "max_wse",
            "runtime_seconds",
            "hdf_path",
        ]
        master_df = master_df.drop(
            columns=[column for column in result_columns if column in master_df],
            errors="ignore",
        )

        merged_df = master_df.merge(
            all_results_df[
                [
                    "absolute_perm_id",
                    "status",
                    "max_wse",
                    "runtime_seconds",
                    "hdf_path",
                ]
            ],
            on="absolute_perm_id",
            how="left",
        )

        RasPermutation._write_csv(merged_df, master_log_path)
        return merged_df

    @staticmethod
    @log_call
    def discover_batch_folders(
        base_folder: Union[str, Path],
        suffix: str = "perms",
    ) -> List[Path]:
        """
        Discover batch folders matching ``{project}_{suffix}_{NNN}``.
        """
        base_folder = Path(base_folder)
        suffix = str(suffix).strip() or "perms"

        if base_folder.is_file():
            base_folder = base_folder.parent

        if not base_folder.exists():
            raise FileNotFoundError(f"Base folder does not exist: {base_folder}")

        parent_folder = base_folder.parent
        pattern = re.compile(
            rf"^{re.escape(base_folder.name)}_{re.escape(suffix)}_(\d{{3}})$"
        )

        batch_folders = [
            folder
            for folder in parent_folder.iterdir()
            if folder.is_dir() and pattern.match(folder.name)
        ]

        return sorted(
            batch_folders,
            key=lambda folder: int(pattern.match(folder.name).group(1)),
        )
