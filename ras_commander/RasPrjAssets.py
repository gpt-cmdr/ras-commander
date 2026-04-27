"""
Project asset resolution helpers for ras-commander.

This module centralizes plan, geometry, flow, and HDF artifact lookup while
preserving the public APIs that currently expose those paths.
"""

from dataclasses import dataclass
from numbers import Number
from pathlib import Path
from typing import Any, Optional, Union
import re

import pandas as pd

from .Decorators import log_call


@dataclass(frozen=True)
class PlanAssets:
    """Resolved file paths associated with one HEC-RAS plan."""

    plan_number: str
    plan_path: Optional[Path] = None
    results_hdf_path: Optional[Path] = None
    geometry_number: Optional[str] = None
    geometry_path: Optional[Path] = None
    geometry_hdf_path: Optional[Path] = None
    flow_path: Optional[Path] = None
    output_path: Optional[Path] = None
    compute_messages_path: Optional[Path] = None


class RasPrjAssets:
    """Static namespace for resolving project asset paths."""

    @staticmethod
    @log_call
    def normalize_number(value: Union[str, Number, Path], prefix: Optional[str] = None) -> str:
        """
        Normalize a RAS component selector to a two-digit number.

        Args:
            value: Number, prefixed selector, or path-like selector.
            prefix: Optional expected prefix such as ``"p"`` or ``"g"``.

        Returns:
            Two-digit number string.
        """
        if value is None:
            raise ValueError("RAS component number cannot be None")

        if isinstance(value, Path):
            text = value.name
        elif isinstance(value, Number):
            number_int = int(value)
            if float(value) != float(number_int):
                raise ValueError(f"RAS component number must be whole: {value}")
            return RasPrjAssets._validate_number_int(number_int)
        else:
            text = str(value).strip()

        expected_prefix = prefix.lower().lstrip(".") if prefix else None

        if expected_prefix:
            match = re.search(rf"\.{expected_prefix}(\d{{1,2}})$", text, re.IGNORECASE)
            if match:
                text = match.group(1)
            elif text.lower().startswith(expected_prefix):
                text = text[1:]
        else:
            match = re.search(r"\.[pguf](\d{1,2})$", text, re.IGNORECASE)
            if match:
                text = match.group(1)
            elif len(text) > 1 and text[0].lower() in {"p", "g", "u", "f"} and text[1:].isdigit():
                text = text[1:]

        if not str(text).isdigit():
            raise ValueError(f"Cannot normalize RAS component number: {value}")

        return RasPrjAssets._validate_number_int(int(text))

    @staticmethod
    @log_call
    def extract_number(value: Any, prefix: Optional[str] = None) -> Optional[str]:
        """
        Extract a normalized RAS component number from loose metadata.

        Unlike :meth:`normalize_number`, this helper returns ``None`` when the
        value is empty or not recognizable. It is intended for optional
        DataFrame/HDF metadata fields where missing values are valid.
        """
        if not RasPrjAssets._is_present(value):
            return None

        try:
            return RasPrjAssets.normalize_number(value, prefix=prefix)
        except ValueError:
            pass

        text = str(value).strip()
        expected_prefix = prefix.lower().lstrip(".") if prefix else None
        candidates = [text]
        try:
            path = Path(text)
            candidates.extend([path.name, path.stem])
        except (OSError, ValueError):
            pass

        if expected_prefix:
            patterns = [
                rf"\.{expected_prefix}(\d{{1,2}})(?:\.|$)",
                rf"^{expected_prefix}(\d{{1,2}})$",
            ]
        else:
            patterns = [
                r"\.[pguf](\d{1,2})(?:\.|$)",
                r"^[pguf](\d{1,2})$",
                r"^(\d{1,2})$",
            ]

        for candidate in candidates:
            for pattern in patterns:
                match = re.search(pattern, candidate, flags=re.IGNORECASE)
                if match:
                    return RasPrjAssets.normalize_number(match.group(1), prefix=prefix)
        return None

    @staticmethod
    @log_call
    def plan_path(
        plan_number_or_path: Union[str, Number, Path],
        ras_object=None,
        must_exist: bool = True,
    ) -> Optional[Path]:
        """Resolve a plan selector or path to a ``.p##`` file path."""
        direct_path = RasPrjAssets._direct_path(plan_number_or_path)
        if direct_path is not None:
            return RasPrjAssets._existing_or_optional(direct_path, must_exist)

        ras_obj = RasPrjAssets._ras_object(ras_object)
        plan_number = RasPrjAssets.normalize_number(plan_number_or_path, prefix="p")
        row = RasPrjAssets._matching_plan_row(ras_obj, plan_number)
        if row is None and RasPrjAssets._has_dataframe(ras_obj, "plan_df", "plan_number"):
            return None

        if row is not None:
            path = RasPrjAssets._path_from_row(row, "full_path")
            if path is not None:
                return RasPrjAssets._existing_or_optional(path, must_exist)

        path = RasPrjAssets._project_path(ras_obj, f"p{plan_number}")
        return RasPrjAssets._existing_or_optional(path, must_exist)

    @staticmethod
    @log_call
    def plan_results_hdf(
        plan_number_or_path: Union[str, Number, Path],
        ras_object=None,
        must_exist: bool = True,
    ) -> Optional[Path]:
        """Resolve a plan selector or path to a plan results HDF path."""
        direct_path = RasPrjAssets._direct_path(plan_number_or_path)
        if direct_path is not None:
            if direct_path.suffix.lower() == ".hdf":
                return RasPrjAssets._existing_or_optional(direct_path, must_exist)
            if re.search(r"\.p\d{1,2}$", direct_path.name, flags=re.IGNORECASE):
                return RasPrjAssets._existing_or_optional(
                    Path(str(direct_path) + ".hdf"),
                    must_exist,
                )

        ras_obj = RasPrjAssets._ras_object(ras_object)
        plan_number = RasPrjAssets.normalize_number(plan_number_or_path, prefix="p")
        row = RasPrjAssets._matching_plan_row(ras_obj, plan_number)
        if (
            row is None
            and must_exist
            and RasPrjAssets._has_dataframe(ras_obj, "plan_df", "plan_number")
        ):
            return None

        if row is not None:
            path = RasPrjAssets._path_from_row(row, "HDF_Results_Path")
            if path is not None:
                return RasPrjAssets._existing_or_optional(path, must_exist)

        path = RasPrjAssets._project_path(ras_obj, f"p{plan_number}.hdf")
        return RasPrjAssets._existing_or_optional(path, must_exist)

    @staticmethod
    @log_call
    def geometry_path(
        geom_number_or_path: Union[str, Number, Path],
        ras_object=None,
        must_exist: bool = True,
    ) -> Optional[Path]:
        """Resolve a geometry selector or path to a ``.g##`` file path."""
        direct_path = RasPrjAssets._direct_path(geom_number_or_path)
        if direct_path is not None:
            if direct_path.suffix.lower() == ".hdf":
                direct_path = Path(str(direct_path)[:-4])
            return RasPrjAssets._existing_or_optional(direct_path, must_exist)

        ras_obj = RasPrjAssets._ras_object(ras_object)
        geom_number = RasPrjAssets.normalize_number(geom_number_or_path, prefix="g")
        row = RasPrjAssets._matching_geom_row(ras_obj, geom_number)
        if row is None and RasPrjAssets._has_dataframe(ras_obj, "geom_df", "geom_number"):
            return None

        if row is not None:
            path = RasPrjAssets._path_from_row(row, "full_path")
            if path is not None:
                return RasPrjAssets._existing_or_optional(path, must_exist)

        path = RasPrjAssets._project_path(ras_obj, f"g{geom_number}")
        return RasPrjAssets._existing_or_optional(path, must_exist)

    @staticmethod
    @log_call
    def geometry_hdf(
        selector: Union[str, Number, Path],
        ras_object=None,
        selector_kind: str = "auto",
        must_exist: bool = True,
    ) -> Optional[Path]:
        """
        Resolve a geometry HDF path.

        Bare numeric selectors keep legacy behavior and resolve through the plan's
        geometry. Explicit ``g##`` selectors resolve geometry files directly.
        """
        direct_path = RasPrjAssets._direct_path(selector)
        if direct_path is not None:
            if direct_path.suffix.lower() == ".hdf" and re.search(
                r"\.g\d{1,2}\.hdf$",
                direct_path.name,
                flags=re.IGNORECASE,
            ):
                return RasPrjAssets._existing_or_optional(direct_path, must_exist)
            if direct_path.suffix.lower() == ".hdf" and re.search(
                r"\.p\d{1,2}\.hdf$",
                direct_path.name,
                flags=re.IGNORECASE,
            ):
                return RasPrjAssets._geometry_hdf_from_plan_hdf(
                    direct_path,
                    ras_object=ras_object,
                    must_exist=must_exist,
                )
            if re.search(r"\.g\d{1,2}$", direct_path.name, flags=re.IGNORECASE):
                return RasPrjAssets._existing_or_optional(
                    Path(str(direct_path) + ".hdf"),
                    must_exist,
                )

        kind = selector_kind.lower()
        text = str(selector).strip() if not isinstance(selector, Number) else ""
        direct_geom = kind == "geom" or (
            kind == "auto" and text.lower().startswith("g") and text[1:].isdigit()
        )

        if direct_geom:
            geom_path = RasPrjAssets.geometry_path(
                selector,
                ras_object=ras_object,
                must_exist=False,
            )
            if geom_path is None:
                return None
            return RasPrjAssets._existing_or_optional(
                Path(str(geom_path) + ".hdf"),
                must_exist,
            )

        if kind == "plan_hdf":
            direct_plan_hdf = RasPrjAssets.plan_results_hdf(
                selector,
                ras_object=ras_object,
                must_exist=must_exist,
            )
            if direct_plan_hdf is None:
                return None
            return RasPrjAssets._geometry_hdf_from_plan_hdf(
                direct_plan_hdf,
                ras_object=ras_object,
                must_exist=must_exist,
            )

        assets = RasPrjAssets.plan_assets(
            selector,
            ras_object=ras_object,
            must_exist=False,
        )
        if assets.geometry_hdf_path is None:
            return None
        return RasPrjAssets._existing_or_optional(
            assets.geometry_hdf_path,
            must_exist,
        )

    @staticmethod
    @log_call
    def plan_assets(
        plan_number: Union[str, Number, Path],
        ras_object=None,
        must_exist: bool = False,
    ) -> PlanAssets:
        """Resolve the core file assets associated with a plan."""
        ras_obj = RasPrjAssets._ras_object(ras_object)
        normalized_plan_number = RasPrjAssets.normalize_number(plan_number, prefix="p")
        row = RasPrjAssets._matching_plan_row(ras_obj, normalized_plan_number)

        plan_path = RasPrjAssets.plan_path(
            normalized_plan_number,
            ras_object=ras_obj,
            must_exist=must_exist,
        )
        results_hdf_path = RasPrjAssets.plan_results_hdf(
            normalized_plan_number,
            ras_object=ras_obj,
            must_exist=must_exist,
        )

        geometry_number = None
        geometry_path = None
        geometry_hdf_path = None
        flow_path = None

        if row is not None:
            geometry_number = RasPrjAssets._geometry_number_from_plan_row(row)
            flow_path = (
                RasPrjAssets._path_from_row(row, "Flow Path")
                or RasPrjAssets._project_path_from_value(ras_obj, row.get("unsteady_file"))
                or RasPrjAssets._project_path_from_value(ras_obj, row.get("steady_file"))
            )

        if geometry_number is not None:
            geometry_path = RasPrjAssets.geometry_path(
                geometry_number,
                ras_object=ras_obj,
                must_exist=must_exist,
            )
            if geometry_path is None and row is not None:
                geometry_path = RasPrjAssets._path_from_row(row, "Geom Path")
                geometry_path = RasPrjAssets._existing_or_optional(
                    geometry_path,
                    must_exist,
                )
            geometry_hdf_path = RasPrjAssets.geometry_hdf(
                f"g{geometry_number}",
                ras_object=ras_obj,
                selector_kind="geom",
                must_exist=must_exist,
            )
            if geometry_hdf_path is None and geometry_path is not None:
                geometry_hdf_path = RasPrjAssets._existing_or_optional(
                    Path(str(geometry_path) + ".hdf"),
                    must_exist,
                )

        output_path = RasPrjAssets._project_path(ras_obj, f"O{normalized_plan_number}")
        output_path = RasPrjAssets._existing_or_optional(output_path, must_exist)

        compute_messages_path = RasPrjAssets._project_path(
            ras_obj,
            f"p{normalized_plan_number}.computeMsgs.txt",
        )
        compute_messages_path = RasPrjAssets._existing_or_optional(
            compute_messages_path,
            must_exist,
        )

        return PlanAssets(
            plan_number=normalized_plan_number,
            plan_path=plan_path,
            results_hdf_path=results_hdf_path,
            geometry_number=geometry_number,
            geometry_path=geometry_path,
            geometry_hdf_path=geometry_hdf_path,
            flow_path=RasPrjAssets._existing_or_optional(flow_path, must_exist)
            if flow_path is not None
            else None,
            output_path=output_path,
            compute_messages_path=compute_messages_path,
        )

    @staticmethod
    def _validate_number_int(number_int: int) -> str:
        if not (1 <= number_int <= 99):
            raise ValueError(f"RAS component number must be between 1 and 99, got {number_int}")
        return f"{number_int:02d}"

    @staticmethod
    def _ras_object(ras_object=None):
        if ras_object is not None:
            return ras_object
        from .RasPrj import ras

        return ras

    @staticmethod
    def _direct_path(value: Union[str, Number, Path]) -> Optional[Path]:
        if isinstance(value, Path):
            return value
        if isinstance(value, Number) or value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        path = Path(text)
        if path.exists():
            return path

        if any(sep in text for sep in ("/", "\\")):
            return path

        if re.search(r"\.[pguf]\d{1,2}(\.hdf)?$", path.name, flags=re.IGNORECASE):
            return path

        return None

    @staticmethod
    def _existing_or_optional(path: Optional[Path], must_exist: bool) -> Optional[Path]:
        if path is None:
            return None
        path = Path(path)
        if must_exist and not path.exists():
            return None
        return path

    @staticmethod
    def _project_path(ras_obj, suffix: str) -> Optional[Path]:
        project_folder = getattr(ras_obj, "project_folder", None)
        project_name = getattr(ras_obj, "project_name", None)
        if project_folder is None or not project_name:
            return None
        return Path(project_folder) / f"{project_name}.{suffix}"

    @staticmethod
    def _project_path_from_value(ras_obj, value: Any) -> Optional[Path]:
        if not RasPrjAssets._is_present(value):
            return None
        path = Path(str(value))
        if path.is_absolute() or any(sep in str(value) for sep in ("/", "\\")):
            return path
        project_folder = getattr(ras_obj, "project_folder", None)
        if project_folder is None:
            return path
        return Path(project_folder) / path

    @staticmethod
    def _path_from_row(row, column: str) -> Optional[Path]:
        if row is None or column not in row.index:
            return None
        value = row.get(column)
        if not RasPrjAssets._is_present(value):
            return None
        return Path(str(value))

    @staticmethod
    def _is_present(value: Any) -> bool:
        if value is None:
            return False
        try:
            if pd.isna(value):
                return False
        except (TypeError, ValueError):
            pass
        return str(value) != ""

    @staticmethod
    def _matching_plan_row(ras_obj, plan_number: str):
        plan_df = getattr(ras_obj, "plan_df", None)
        if plan_df is None or len(plan_df) == 0 or "plan_number" not in plan_df.columns:
            return None
        mask = plan_df["plan_number"].astype(str).str.zfill(2).eq(plan_number)
        matches = plan_df[mask]
        return None if matches.empty else matches.iloc[0]

    @staticmethod
    def _matching_geom_row(ras_obj, geom_number: str):
        geom_df = getattr(ras_obj, "geom_df", None)
        if geom_df is None or len(geom_df) == 0 or "geom_number" not in geom_df.columns:
            return None
        mask = geom_df["geom_number"].astype(str).str.zfill(2).eq(geom_number)
        matches = geom_df[mask]
        return None if matches.empty else matches.iloc[0]

    @staticmethod
    def _has_dataframe(ras_obj, attr_name: str, required_column: str) -> bool:
        frame = getattr(ras_obj, attr_name, None)
        return frame is not None and required_column in getattr(frame, "columns", [])

    @staticmethod
    def _geometry_number_from_plan_row(row) -> Optional[str]:
        for column in ("geometry_number", "Geom File", "geom_file"):
            if column in row.index and RasPrjAssets._is_present(row.get(column)):
                geometry_number = RasPrjAssets.extract_number(row.get(column), prefix="g")
                if geometry_number is not None:
                    return geometry_number
        geom_path = RasPrjAssets._path_from_row(row, "Geom Path")
        if geom_path is not None:
            return RasPrjAssets.extract_number(geom_path, prefix="g")
        return None

    @staticmethod
    def _geometry_hdf_from_plan_hdf(
        plan_hdf_path: Path,
        ras_object=None,
        must_exist: bool = True,
    ) -> Optional[Path]:
        plan_hdf_path = Path(plan_hdf_path)
        geom_number = None

        try:
            from .hdf.HdfPlan import HdfPlan

            plan_info = HdfPlan.get_plan_information(plan_hdf_path)
            for key in ("Geometry File", "Geom File"):
                if key in plan_info:
                    try:
                        geom_number = RasPrjAssets.normalize_number(plan_info.get(key), prefix="g")
                        break
                    except ValueError:
                        continue
        except Exception:
            geom_number = None

        if geom_number:
            project_name = RasPrjAssets._project_name_from_plan_hdf(plan_hdf_path)
            hdf_path = plan_hdf_path.parent / f"{project_name}.g{geom_number}.hdf"
            found = RasPrjAssets._existing_or_optional(hdf_path, must_exist)
            if found is not None:
                return found

        ras_obj = ras_object
        if ras_obj is not None:
            plan_number_match = re.search(r"\.p(\d{1,2})\.hdf$", plan_hdf_path.name, flags=re.IGNORECASE)
            if plan_number_match:
                assets = RasPrjAssets.plan_assets(
                    plan_number_match.group(1),
                    ras_object=ras_obj,
                    must_exist=False,
                )
                if assets.geometry_hdf_path is not None:
                    return RasPrjAssets._existing_or_optional(
                        assets.geometry_hdf_path,
                        must_exist,
                    )

            plan_df = getattr(ras_obj, "plan_df", None)
            if plan_df is not None and "HDF_Results_Path" in plan_df.columns:
                mask = plan_df["HDF_Results_Path"].notna() & plan_df[
                    "HDF_Results_Path"
                ].map(lambda value: RasPrjAssets._paths_match(value, plan_hdf_path))
                matches = plan_df[mask]
                if not matches.empty:
                    geometry_number = RasPrjAssets._geometry_number_from_plan_row(matches.iloc[0])
                    if geometry_number:
                        return RasPrjAssets.geometry_hdf(
                            f"g{geometry_number}",
                            ras_object=ras_obj,
                            selector_kind="geom",
                            must_exist=must_exist,
                        )

        return None

    @staticmethod
    def _project_name_from_plan_hdf(plan_hdf_path: Path) -> str:
        stem = Path(plan_hdf_path).stem
        match = re.match(r"(.+)\.p\d{1,2}$", stem, flags=re.IGNORECASE)
        return match.group(1) if match else stem

    @staticmethod
    def _paths_match(path_a: Any, path_b: Any) -> bool:
        try:
            return Path(str(path_a)).absolute() == Path(str(path_b)).absolute()
        except Exception:
            return False
