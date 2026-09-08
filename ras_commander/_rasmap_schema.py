"""Lightweight schema helpers for the single-row ``rasmap_df`` contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional, Union

import pandas as pd


RASMAP_LEGACY_COLUMNS = (
    "projection_path",
    "profile_lines_path",
    "soil_layer_path",
    "infiltration_hdf_path",
    "landcover_hdf_path",
    "terrain_hdf_path",
    "reference_map_layer_names",
    "reference_map_layer_path",
    "basemap_layer_names",
    "basemap_layer_path",
    "current_settings",
)

RASMAP_PROVENANCE_COLUMNS = (
    "rasmap_path",
    "rasmap_status",
    "rasmap_error",
    "rasmap_field_errors",
)

RASMAP_COLUMNS = RASMAP_LEGACY_COLUMNS + RASMAP_PROVENANCE_COLUMNS
RASMAP_STATUSES = frozenset({"absent", "parsed", "parsed_with_errors", "failed"})
RASMAP_USABLE_STATUSES = frozenset({"parsed", "parsed_with_errors"})


def expected_rasmap_path(
    project_folder: Union[str, Path],
    project_name: str,
) -> Path:
    """Return the canonical project ``.rasmap`` path."""
    return Path(project_folder) / f"{project_name}.rasmap"


def create_rasmap_dataframe(
    *,
    rasmap_path: Optional[Union[str, Path]] = None,
    rasmap_status: str = "absent",
    rasmap_error: Optional[str] = None,
    rasmap_field_errors: Optional[Mapping[str, str]] = None,
) -> pd.DataFrame:
    """Return a fresh, single-row ``rasmap_df`` with explicit parse provenance."""
    if rasmap_status not in RASMAP_STATUSES:
        raise ValueError(
            f"Unsupported rasmap_status {rasmap_status!r}; "
            f"expected one of {sorted(RASMAP_STATUSES)}"
        )

    return pd.DataFrame(
        {
            "projection_path": [None],
            "profile_lines_path": [[]],
            "soil_layer_path": [[]],
            "infiltration_hdf_path": [[]],
            "landcover_hdf_path": [[]],
            "terrain_hdf_path": [[]],
            "reference_map_layer_names": [[]],
            "reference_map_layer_path": [[]],
            "basemap_layer_names": [[]],
            "basemap_layer_path": [[]],
            "current_settings": [{}],
            "rasmap_path": [str(rasmap_path) if rasmap_path is not None else None],
            "rasmap_status": [rasmap_status],
            "rasmap_error": [rasmap_error],
            "rasmap_field_errors": [dict(rasmap_field_errors or {})],
        },
        columns=RASMAP_COLUMNS,
    )


def rasmap_dataframe_is_usable(rasmap_df: Any) -> bool:
    """Return whether a frame contains a usable RASMapper summary row.

    Frames created before provenance columns were introduced remain usable when
    they contain a row. New frames are usable only after a full or partial parse.
    """
    if not isinstance(rasmap_df, pd.DataFrame) or rasmap_df.empty:
        return False
    if "rasmap_status" not in rasmap_df.columns:
        return True
    return rasmap_df.iloc[0].get("rasmap_status") in RASMAP_USABLE_STATUSES
