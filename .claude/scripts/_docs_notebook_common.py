#!/usr/bin/env python3
"""Shared helpers for the docs notebook build steps (stdlib only).

Both ``generate_examples_index.py`` (the Example Notebooks *overview table*) and
``prepare_notebooks_for_docs.py`` (which injects the Example Notebooks *left-nav*
into ``mkdocs.yml`` at build time) source the notebook list from disk
(``examples/*.ipynb``) -- never from the hand-authored nav -- so the table and the
sidebar always reflect exactly what ships. Putting the title / numbering / section
logic here guarantees the two never drift.

The published site builds from ``main``, where the ``Example Notebooks`` nav block
is just a single ``Overview`` entry; ``prepare_notebooks_for_docs.py`` expands it
from disk during the build. See that script and ``generate_examples_index.py``.

stdlib only (json, re, pathlib) so it runs under a bare ``python3``.
"""

import json
import re
from pathlib import Path
from typing import List, Optional, Tuple

# Descriptive names for each hundreds bucket, shown in the index headings and the
# left-nav group labels (e.g. "100s - Initialization & Execution"). Buckets without
# an entry fall back to the bare "<N>s" label, so adding a new 1000s series needs no
# code change -- only an (optional) label here.
BUCKET_LABELS = {
    100: "Initialization & Execution",
    200: "Geometry & Calibration",
    300: "Unsteady Flow & DSS",
    400: "HDF Results Extraction",
    500: "Remote Execution",
    600: "Floodplain Mapping",
    700: "Sensitivity & Precipitation",
    800: "Quality Assurance",
    900: "Data Integration & Forecasting",
}

AORC_AND_PRECIP = {
    "900_aorc_precipitation",
    "901_aorc_precipitation_catalog",
}

GAUGE_AND_VALIDATION = {
    "910_usgs_gauge_catalog",
    "911_usgs_gauge_data_integration",
    "911a_usgs_study_package_from_primitives",
    "912_usgs_real_time_monitoring",
    "913_bc_generation_from_live_gauge",
    "914_historical_event_validation",
    "918_model_validation_with_usgs",
    "921_usgs_study_package_from_primitives",
    "922_model_validation_with_usgs",
}

OPERATIONAL_FORECAST_SEQUENCE = {
    "915_realtime_forecast_workflow",
    "918_hms_ras_coupled_forecast",
    "919_operational_forecast_cycling",
}

FORECAST_INPUTS = {
    "916_hrrr_precipitation_forecast",
    "917_mrms_precipitation_qpe",
    "919_stofs3d_coastal_boundary",
    "923_stofs3d_coastal_boundary",
    "924_mrms_netcdf_rain_on_grid",
}

TERRAIN_AND_SURFACES = {
    "920_terrain_creation",
    "925_xs_interpolation_surface",
    "930_terrain_modification_analysis",
}


def load_notebook(notebook_path: Path) -> Optional[dict]:
    """Parse a notebook JSON, or return ``None`` if it can't be read."""
    try:
        with notebook_path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _cell_source_lines(cell: dict) -> List[str]:
    """A notebook cell's source as lines (source may be a str or list of str)."""
    source = cell.get("source", "")
    text = "".join(source) if isinstance(source, list) else source
    return text.splitlines()


def numeric_prefix(name: str) -> str:
    """The leading numeric id of a notebook basename, e.g. ``116`` or ``911a``.

    Returns ``""`` when the name has no numeric prefix.
    """
    m = re.match(r"^(\d+[a-zA-Z]?)_", name)
    return m.group(1) if m else ""


def prettify_filename(name: str) -> str:
    """Fallback title from a basename: drop the ``NNN_`` prefix, Title-Case the rest."""
    stem = re.sub(r"^\d+[a-zA-Z]?_", "", name)
    stem = stem.replace("_", " ").strip()
    if not stem:
        stem = name.replace("_", " ").strip()
    return stem.title()


def derive_title(notebook_path: Path, nb: Optional[dict]) -> str:
    """Title = first markdown ``# `` H1 in the notebook, else prettified filename."""
    name = notebook_path.stem
    if nb is not None:
        for cell in nb.get("cells", []):
            if cell.get("cell_type") != "markdown":
                continue
            for line in _cell_source_lines(cell):
                stripped = line.strip()
                if stripped.startswith("# "):
                    return stripped[1:].strip()
    return prettify_filename(name)


def numbered_title(name: str, title: str) -> str:
    """Display title with its leading number restored, e.g. ``100 - Using RasExamples``.

    If the notebook H1 already starts with the number, it is not duplicated. Notebooks
    with no numeric prefix are returned unchanged.
    """
    num = numeric_prefix(name)
    if not num:
        return title
    if re.match(rf"^{re.escape(num)}\b", title):
        return title
    return f"{num} - {title}"


def section_for(name: str) -> Tuple[int, str]:
    """``(sort_key, label)`` hundreds bucket for a basename (``911a_...`` -> 900s)."""
    m = re.match(r"^(\d+)", name)
    if not m:
        return (10_000, "Other")
    n = int(m.group(1))
    if name in AORC_AND_PRECIP:
        return (900, "900s - AORC & Gridded Precipitation")
    if name in GAUGE_AND_VALIDATION:
        return (910, "910s - Gauge Data & Validation")
    if name in OPERATIONAL_FORECAST_SEQUENCE:
        return (915, "915s - Operational Forecast Sequence")
    if name in FORECAST_INPUTS:
        return (916, "916s - Forecast Inputs")
    if name in TERRAIN_AND_SURFACES:
        return (920, "920s - Terrain & Surfaces")
    if 950 <= n < 960:
        return (950, "950s - eBFE Delivery")
    if 960 <= n < 970:
        return (960, "960s - Cloud-Native Export")
    bucket = (n // 100) * 100
    desc = BUCKET_LABELS.get(bucket)
    label = f"{bucket}s - {desc}" if desc else f"{bucket}s"
    return (bucket, label)
