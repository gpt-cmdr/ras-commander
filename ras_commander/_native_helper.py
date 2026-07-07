"""Utilities for packaged native helper execution."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
from contextlib import contextmanager
from importlib import resources
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Iterator, Optional, Union

from ._gdal_runtime import resolve_hecras_gdal_paths
from .LoggingConfig import get_logger

logger = get_logger(__name__)

_NATIVE_PACKAGE = "ras_commander.native"
_HELPER_EXE_NAME = "RasStoreMapHelper.exe"
_HELPER_CS_NAME = "RasStoreMapHelper.cs"
_IS_LINUX = platform.system() == "Linux"


def _env_flag(name: str) -> bool:
    value = os.environ.get(name)
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _package_version() -> str:
    try:
        return version("ras-commander")
    except PackageNotFoundError:
        return "dev"


def _default_stage_dir() -> Path:
    if _IS_LINUX:
        return Path.home() / ".local" / "share" / "ras-commander" / "bin"

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "ras-commander" / "bin"

    return Path.home() / "AppData" / "Local" / "ras-commander" / "bin"


def _resource(filename: str):
    return resources.files(_NATIVE_PACKAGE).joinpath(filename)


def _helper_has_sibling_gdal(helper_path: Path) -> bool:
    return (helper_path.parent / "GDAL").is_dir()


def _bundle_name(helper_path: Path, hecras_dir: Optional[Path] = None) -> str:
    helper_digest = hashlib.sha256(helper_path.read_bytes()).hexdigest()[:12]
    bundle_name = f"RasStoreMapHelper-{_package_version()}-{helper_digest}"
    if hecras_dir is not None:
        hecras_digest = hashlib.sha256(
            str(hecras_dir).lower().encode("utf-8")
        ).hexdigest()[:12]
        bundle_name = f"{bundle_name}-{hecras_digest}"
    return bundle_name


def _link_or_copy_gdal_tree(source_dir: Path, dest_dir: Path) -> None:
    if dest_dir.exists() or dest_dir.is_symlink():
        return

    if not source_dir.is_dir():
        raise FileNotFoundError(f"HEC-RAS GDAL directory not found: {source_dir}")

    if _IS_LINUX:
        try:
            os.symlink(source_dir, dest_dir, target_is_directory=True)
            return
        except OSError as exc:
            logger.warning(
                "Could not symlink GDAL runtime; copying instead."
            )
            logger.debug(
                "Could not symlink GDAL runtime from %s to %s: %s",
                source_dir,
                dest_dir,
                exc,
                exc_info=True,
            )
    elif platform.system() == "Windows":
        try:
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(dest_dir), str(source_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
            return
        except (OSError, subprocess.CalledProcessError) as exc:
            logger.warning(
                "Could not create GDAL junction; copying instead."
            )
            logger.debug(
                "Could not create GDAL junction from %s to %s: %s",
                source_dir,
                dest_dir,
                exc,
                exc_info=True,
            )

    shutil.copytree(source_dir, dest_dir, dirs_exist_ok=True)


def _hecras_gdal_subprocess_env(hecras_dir: Path) -> dict:
    """Return an environment initialized for HEC-RAS's bundled GDAL runtime."""
    env = dict(os.environ)
    try:
        gdal_paths = resolve_hecras_gdal_paths(hecras_dir)
    except FileNotFoundError:
        return env

    path_prefixes = [str(gdal_paths.gdal_bin), str(gdal_paths.hecras_dir)]
    env["PATH"] = os.pathsep.join(path_prefixes + [env.get("PATH", "")])
    env["GDAL_DATA"] = str(gdal_paths.gdal_data)
    env["PROJ_LIB"] = str(gdal_paths.gdal_data)
    env.setdefault("PROJ_DATA", str(gdal_paths.gdal_data))
    return env


def normalize_store_map_render_mode(
    render_mode: Optional[Union[str, dict]],
    default: str = "horizontal",
) -> str:
    """Normalize RasMap/RasProcess render-mode inputs for the helper CLI."""
    if render_mode is None:
        render_mode = default

    if isinstance(render_mode, dict):
        render_mode = render_mode.get("mode", default)

    mode_map = {
        "horizontal": "horizontal",
        "sloping": "sloping",
        "slopingpretty": "slopingPretty",
        "sloped": "sloping",
    }

    normalized = mode_map.get(str(render_mode).strip().lower())
    if normalized is None:
        raise ValueError(
            f"Invalid render_mode: {render_mode}. "
            "Valid values: horizontal, sloping, slopingPretty"
        )
    return normalized


@contextmanager
def packaged_helper_executable_path() -> Iterator[Path]:
    """Yield the packaged helper executable path or a configured override."""
    override = os.environ.get("RAS_COMMANDER_MAP_HELPER_PATH")
    if override:
        helper_path = Path(override).expanduser()
        if not helper_path.exists():
            raise FileNotFoundError(
                "RAS_COMMANDER_MAP_HELPER_PATH points to a missing file: "
                f"{helper_path}"
            )
        yield helper_path
        return

    with resources.as_file(_resource(_HELPER_EXE_NAME)) as helper_path:
        helper_path = Path(helper_path)
        if not helper_path.exists():
            raise FileNotFoundError(
                f"{_HELPER_EXE_NAME} not found in packaged resources at "
                f"{helper_path}"
            )
        yield helper_path


@contextmanager
def packaged_helper_source_path() -> Iterator[Path]:
    """Yield the packaged helper C# source path."""
    with resources.as_file(_resource(_HELPER_CS_NAME)) as source_path:
        source_path = Path(source_path)
        if not source_path.exists():
            raise FileNotFoundError(
                f"{_HELPER_CS_NAME} not found in packaged resources at "
                f"{source_path}"
            )
        yield source_path


def stage_helper_executable(
    helper_path: Path,
    stage_dir: Optional[Union[str, Path]] = None,
    hecras_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """Copy the helper to a user-writable directory for execution."""
    helper_path = Path(helper_path)
    if not helper_path.exists():
        raise FileNotFoundError(f"Helper executable not found: {helper_path}")

    stage_root = (
        Path(stage_dir).expanduser()
        if stage_dir is not None
        else _default_stage_dir()
    )
    stage_root.mkdir(parents=True, exist_ok=True)

    staged_path: Path
    if hecras_dir is None:
        staged_name = f"{_bundle_name(helper_path)}{helper_path.suffix}"
        staged_path = stage_root / staged_name
        if not staged_path.exists():
            shutil.copy2(helper_path, staged_path)
            logger.debug(f"Staged RasStoreMapHelper.exe to {staged_path}")
        return staged_path

    hecras_dir = Path(hecras_dir)
    bundle_dir = stage_root / _bundle_name(helper_path, hecras_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    staged_path = bundle_dir / _HELPER_EXE_NAME
    if not staged_path.exists():
        shutil.copy2(helper_path, staged_path)
        logger.debug(f"Staged RasStoreMapHelper.exe to {staged_path}")

    gdal_source = hecras_dir / "GDAL"
    if gdal_source.is_dir():
        _link_or_copy_gdal_tree(gdal_source, bundle_dir / "GDAL")
    else:
        logger.warning(
            "HEC-RAS GDAL directory not found at %s; running helper without "
            "a staged GDAL sibling directory.",
            gdal_source,
        )

    return staged_path


def _filter_helper_stderr(
    result: subprocess.CompletedProcess,
) -> subprocess.CompletedProcess:
    if not result.stderr:
        return result

    filtered_lines = []
    for line in result.stderr.splitlines():
        if line.startswith(("0", "wine: ")) or "err:" in line[:20]:
            continue
        if "TIFFFetchNormalTag:ASCII value for tag" in line:
            continue
        filtered_lines.append(line)

    filtered_stderr = "\n".join(filtered_lines)
    return subprocess.CompletedProcess(
        result.args,
        result.returncode,
        result.stdout,
        filtered_stderr,
    )


def _run_store_all_maps_once(
    helper_path: Path,
    hecras_dir: Path,
    helper_mode: str,
    rasmap_path: Path,
    result_hdf_path: Path,
    timeout: int,
    working_dir: Optional[Path],
) -> subprocess.CompletedProcess:
    if _IS_LINUX:
        from .RasProcess import RasProcess

        wine_config = RasProcess._get_wine_config()
        if wine_config is None:
            raise RuntimeError(
                "Wine not configured on Linux. "
                "Call RasProcess.configure_wine() or set WINEPREFIX."
            )

        cmd = [
            wine_config.wine_executable,
            str(helper_path),
            RasProcess._resolve_path_for_rasprocess(hecras_dir),
            helper_mode,
            RasProcess._resolve_path_for_rasprocess(rasmap_path),
            RasProcess._resolve_path_for_rasprocess(result_hdf_path),
        ]
        env = {
            **os.environ,
            "WINEPREFIX": str(wine_config.wine_prefix),
            "DISPLAY": "",
            "WINEDEBUG": "-all",
        }
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(working_dir) if working_dir else None,
            env=env,
        )
        return _filter_helper_stderr(result)

    cmd = [
        str(helper_path),
        str(hecras_dir),
        helper_mode,
        str(rasmap_path),
        str(result_hdf_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(working_dir) if working_dir else None,
        env=_hecras_gdal_subprocess_env(hecras_dir),
    )
    return _filter_helper_stderr(result)


def run_store_all_maps_helper(
    hecras_dir: Union[str, Path],
    render_mode: Optional[Union[str, dict]],
    rasmap_path: Union[str, Path],
    result_hdf_path: Union[str, Path],
    timeout: int = 600,
    working_dir: Optional[Union[str, Path]] = None,
) -> subprocess.CompletedProcess:
    """Run the packaged helper without mutating the HEC-RAS install folder."""
    if _env_flag("RAS_COMMANDER_MAP_HELPER_DISABLE"):
        raise RuntimeError(
            "RasStoreMapHelper execution is disabled via "
            "RAS_COMMANDER_MAP_HELPER_DISABLE."
        )

    hecras_dir = Path(hecras_dir)
    rasmap_path = Path(rasmap_path)
    result_hdf_path = Path(result_hdf_path)
    working_dir = Path(working_dir) if working_dir is not None else None
    helper_mode = normalize_store_map_render_mode(render_mode)

    stage_dir_override = os.environ.get("RAS_COMMANDER_MAP_HELPER_STAGE_DIR")

    with packaged_helper_executable_path() as helper_path:
        helper_to_run = helper_path
        if not _helper_has_sibling_gdal(helper_path) and (hecras_dir / "GDAL").is_dir():
            helper_to_run = stage_helper_executable(
                helper_path,
                stage_dir=stage_dir_override,
                hecras_dir=hecras_dir,
            )
            logger.debug(
                "Using staged RasStoreMapHelper runtime at %s because the "
                "packaged helper has no sibling GDAL directory.",
                helper_to_run,
            )

        try:
            return _run_store_all_maps_once(
                helper_path=helper_to_run,
                hecras_dir=hecras_dir,
                helper_mode=helper_mode,
                rasmap_path=rasmap_path,
                result_hdf_path=result_hdf_path,
                timeout=timeout,
                working_dir=working_dir,
            )
        except (OSError, PermissionError, FileNotFoundError) as exc:
            staged_helper = stage_helper_executable(
                helper_path,
                stage_dir=stage_dir_override,
                hecras_dir=hecras_dir,
            )
            if staged_helper == helper_to_run:
                raise

            logger.warning(
                "Direct RasStoreMapHelper execution failed; retrying from staged path."
            )
            logger.debug(
                "Direct RasStoreMapHelper execution failed from %s; retrying "
                "from staged path %s: %s",
                helper_to_run,
                staged_helper,
                exc,
                exc_info=True,
            )
            return _run_store_all_maps_once(
                helper_path=staged_helper,
                hecras_dir=hecras_dir,
                helper_mode=helper_mode,
                rasmap_path=rasmap_path,
                result_hdf_path=result_hdf_path,
                timeout=timeout,
                working_dir=working_dir,
            )
