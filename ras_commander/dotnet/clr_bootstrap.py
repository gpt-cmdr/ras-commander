"""Idempotent CLR bootstrap for RasMapperLib.dll interop."""

from __future__ import annotations

import importlib.util
import os
import platform
import re
import sys
from pathlib import Path
from typing import Optional, Union

from ..LoggingConfig import get_logger
from .._gdal_runtime import configure_rasmapper_gdal_bridge

logger = get_logger(__name__)

_DEPS = ["Utility.Core", "Geospatial.Core", "H5Assist", "RasMapperLib"]

_HECRAS_SEARCH_PATHS = [
    Path(r"C:\Program Files (x86)\HEC\HEC-RAS\7.0.1"),
    Path(r"C:\Program Files\HEC\HEC-RAS\7.0.1"),
    Path(r"C:\Program Files (x86)\HEC\HEC-RAS\7.0"),
    Path(r"C:\Program Files\HEC\HEC-RAS\7.0"),
    Path(r"C:\Program Files (x86)\HEC\HEC-RAS\6.7 Beta 5"),
    Path(r"C:\Program Files (x86)\HEC\HEC-RAS\6.6"),
    Path(r"C:\Program Files\HEC\HEC-RAS\6.6"),
]

_CLR_LOADED = False
_CLR_INSTALL_ROOT: Optional[Path] = None


def _version_sort_key(path: Path) -> tuple[int, ...]:
    """Return a sortable coarse version key for HEC-RAS install folders."""
    parts = [int(part) for part in re.findall(r"\d+", path.name)]
    return tuple(parts) if parts else (0,)


def _candidate_hecras_dirs(version: str | None = None) -> list[Path]:
    """Return candidate HEC-RAS install directories in preferred order."""
    candidates: list[Path] = []

    for env_name in ("HECRAS_INSTALL_ROOT", "RAS_INSTALL_ROOT"):
        env_value = os.environ.get(env_name)
        if env_value:
            candidates.append(Path(env_value))

    candidates.extend(_HECRAS_SEARCH_PATHS)

    for root in (
        Path(r"C:\Program Files (x86)\HEC\HEC-RAS"),
        Path(r"C:\Program Files\HEC\HEC-RAS"),
    ):
        if not root.exists():
            continue
        installed = [
            path
            for path in root.iterdir()
            if path.is_dir() and (path / "RasMapperLib.dll").exists()
        ]
        candidates.extend(sorted(installed, key=_version_sort_key, reverse=True))

    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        if version is not None and version not in candidate.name:
            continue
        key = str(candidate.resolve(strict=False)).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def find_hecras_install(version: str | None = None) -> Path:
    """Find a HEC-RAS install directory containing ``RasMapperLib.dll``."""
    candidates = _candidate_hecras_dirs(version=version)
    for candidate in candidates:
        if (candidate / "RasMapperLib.dll").exists():
            return candidate

    searched = ", ".join(str(path) for path in candidates) or "<none>"
    suffix = f" for version {version}" if version else ""
    raise FileNotFoundError(
        "Could not find a HEC-RAS install containing RasMapperLib.dll"
        f"{suffix}. Searched: {searched}"
    )


def _normalize_install_root(hecras_dir: Union[str, Path, None]) -> Path:
    if hecras_dir is None:
        return find_hecras_install()
    root = Path(hecras_dir)
    if not (root / "RasMapperLib.dll").exists():
        raise FileNotFoundError(f"RasMapperLib.dll not found in {root}")
    return root


def load_clr(hecras_dir: Path | None = None) -> None:
    """Load pythonnet CLR references for RasMapperLib once per process."""
    global _CLR_LOADED, _CLR_INSTALL_ROOT

    if _CLR_LOADED:
        if hecras_dir is None:
            return
        resolved_root = Path(hecras_dir).resolve(strict=False)
        if (
            _CLR_INSTALL_ROOT is not None
            and resolved_root != _CLR_INSTALL_ROOT.resolve(strict=False)
        ):
            raise RuntimeError(
                "pythonnet CLR is already loaded for "
                f"{_CLR_INSTALL_ROOT}; cannot rebind to {resolved_root}."
            )
        return

    root = _normalize_install_root(hecras_dir)
    resolved_root = root.resolve(strict=False)

    if importlib.util.find_spec("clr") is None:
        raise ImportError(
            "pythonnet is required for RasMapperLib interop. Install the "
            "ras-commander 'mesh' extra or add pythonnet>=3.0.5."
        )

    try:
        configure_rasmapper_gdal_bridge(resolved_root)
    except Exception as exc:
        if platform.system() == "Windows":
            raise RuntimeError(
                "Cannot load RasMapperLib.dll because the HEC-RAS GDAL "
                "bridge could not be initialized."
            ) from exc
        logger.debug(
            "HEC-RAS GDAL bridge could not be initialized; attempting CLR "
            "load anyway on this platform: %s",
            exc,
        )

    import clr  # type: ignore

    root_text = str(resolved_root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    for dep in _DEPS:
        dll = resolved_root / f"{dep}.dll"
        try:
            clr.AddReference(str(dll))
        except Exception as exc:
            raise RuntimeError(f"Cannot load {dll}: {exc}") from exc

    _CLR_LOADED = True
    _CLR_INSTALL_ROOT = resolved_root
    logger.debug("RasMapperLib CLR references loaded from %s", resolved_root)


def is_hecras_available() -> bool:
    """Return True when HEC-RAS and pythonnet are available for interop."""
    if importlib.util.find_spec("clr") is None:
        return False
    try:
        find_hecras_install()
    except Exception:
        return False
    return True
