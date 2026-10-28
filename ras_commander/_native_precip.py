"""Isolated vendor GDAL precipitation import; Python never authors raster values."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def import_native_gdal(
    unsteady: Path, install: Path, *, units: str, data_type: str, timeout: float
) -> dict:
    """Compile the original interop helper, import to a copy, validate, replace."""
    import h5py
    import numpy as np

    from .RasPrecipHdf import RasPrecipHdf
    from .RasUnsteady import RasUnsteady
    from ._native_helper import _wine_helper_single_cpu_affinity

    if not np.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    data_type = str(data_type).strip().lower()
    units = str(units).strip()
    RasPrecipHdf.validate_data_type_units(data_type, units)
    if data_type in {"per-cum", "inst-val"}:
        raise ValueError(
            "Native interval-amount/instantaneous accumulation is not implemented in the tested HEC runtimes; "
            "use the Python/HDF route or provide cumulative NetCDF"
        )
    config = RasUnsteady.get_met_precipitation_config(unsteady)
    if config["source"] != "GDAL Raster File(s)":
        raise ValueError("Configure a GDAL raster source before importing")
    reference = config["gdal_filename"]
    selector = config["gdal_group"]
    if not reference or not selector:
        raise ValueError(
            "Native import requires a source filename and explicit GDAL selector"
        )
    source = Path(reference.replace("\\", "/"))
    if not source.is_absolute():
        source = unsteady.parent / source
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix.lower() not in {".nc", ".nc4", ".netcdf"}:
        raise ValueError(
            "Native import currently supports NetCDF only; GRIB selection is unqualified"
        )
    hdf_path = Path(str(unsteady) + ".hdf")
    group_path = "Event Conditions/Meteorology/Precipitation/Imported Raster Data"
    if not hdf_path.is_file():
        raise FileNotFoundError("Configure GDAL metadata first: " + str(hdf_path))
    with h5py.File(hdf_path, "r") as hdf:
        if group_path in hdf:
            raise ValueError(
                "Imported precipitation already exists; use a clean staged sidecar"
            )
    install = install.absolute()
    if not (install / "Geospatial.GDALAssist.dll").is_file():
        raise FileNotFoundError("Vendor GDAL assembly missing from " + str(install))
    environment = dict(os.environ)
    if platform.system() == "Windows":
        launcher = []
        compiler = (
            Path(os.environ.get("WINDIR", "C:/Windows"))
            / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        )
        convert = str
    elif platform.system() == "Linux":
        # Avoid importing the mapping facade (and its optional GIS packages)
        # merely to run a focused vendor import in a minimal execution image.
        facade = sys.modules.get("ras_commander.RasProcess")
        wine = facade.RasProcess._get_wine_config() if facade else None
        prefix = Path(wine.wine_prefix if wine else os.environ.get("WINEPREFIX", ""))
        if not prefix.is_absolute() or not prefix.is_dir():
            raise RuntimeError(
                "Set WINEPREFIX to a task-private Wine prefix or configure RasProcess"
            )
        seed = os.environ.get("RAS_COMMANDER_WINE_PREFIX_SEED")
        if seed and prefix.resolve() == Path(seed).resolve():
            raise ValueError("Clone the immutable Wine seed before native import")
        environment.update(WINEPREFIX=str(prefix), WINEDEBUG="-all")
        launcher = [wine.wine_executable if wine else "wine"]
        compiler = (
            prefix / "drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        )

        def convert(path):
            absolute = Path(path).absolute()
            try:
                return "C:\\" + str(absolute.relative_to(prefix / "drive_c")).replace(
                    "/", "\\"
                )
            except ValueError:
                mapping = prefix / "dosdevices/z:"
                if not mapping.is_symlink() or mapping.resolve() != Path("/"):
                    raise ValueError(
                        "Native importer requires a verified Z: mapping to the POSIX root"
                    )
                return "Z:\\" + str(absolute).lstrip("/").replace("/", "\\")
    else:
        raise RuntimeError("Native precipitation import requires Windows or Linux/Wine")
    if not compiler.is_file():
        raise FileNotFoundError(
            "Native .NET Framework compiler missing: " + str(compiler)
        )
    helper_source = Path(__file__).parent / "native/RasMetImportHelper.cs"
    deadline = time.monotonic() + timeout
    source_digest = _sha256(source)
    sidecar_digest = _sha256(hdf_path)
    text_digest = _sha256(unsteady)
    # The staged HDF is beside its target so replacement is atomic on one volume.
    with tempfile.TemporaryDirectory(
        prefix=".ras-met-import-", dir=unsteady.parent
    ) as staging:
        stage = Path(staging)
        staged_hdf = stage / hdf_path.name
        shutil.copy2(hdf_path, staged_hdf)
        helper = stage / "RasMetImportHelper.exe"
        request = stage / "request.json"
        response = stage / "response.json"
        request.write_text(
            json.dumps(
                {
                    "source": convert(source.absolute()),
                    "dataset": selector,
                    "output": convert(staged_hdf),
                    "units": units,
                    "data_type": data_type,
                }
            ),
            encoding="utf-8",
        )
        helper.with_suffix(".exe.config").write_text(
            '<configuration><runtime><loadFromRemoteSources enabled="true"/>'
            "</runtime></configuration>",
            encoding="utf-8",
        )
        helper_command = [
            *launcher,
            convert(helper),
            convert(install),
            convert(request),
            convert(response),
        ]
        helper_host = "standalone_dotnet"
        if platform.system() == "Windows" and (
            str(helper).startswith("\\\\")
            or ctypes.windll.kernel32.GetDriveTypeW(str(helper.anchor)) == 4
        ):
            # SMB servers can allow source/data access while withholding Unix
            # execute bits from newly compiled files. Host the original .NET
            # entry point in installed Windows PowerShell; only the helper's
            # bytes are read from the share. No share ACL/config change or local
            # staging of raster data is required.
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            script = (
                "$ErrorActionPreference='Stop';"
                "$assembly=[Reflection.Assembly]::Load([IO.File]::ReadAllBytes("
                + quote(helper)
                + "));"
                "$invokeArgs=New-Object object[] 1;"
                "$invokeArgs[0]=[string[]]@("
                + ",".join(quote(value) for value in (install, request, response))
                + ");$code=$assembly.EntryPoint.Invoke($null,$invokeArgs);exit [int]$code"
            )
            powershell = (
                Path(os.environ.get("WINDIR", "C:/Windows"))
                / "System32/WindowsPowerShell/v1.0/powershell.exe"
            )
            helper_command = [
                str(powershell),
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                base64.b64encode(script.encode("utf-16-le")).decode("ascii"),
            ]
            helper_host = "windows_powershell_dotnet"
        commands = [
            [
                *launcher,
                convert(compiler),
                "/nologo",
                "/r:System.Web.Extensions.dll",
                "/out:" + convert(helper),
                convert(helper_source),
            ],
            helper_command,
        ]
        with _wine_helper_single_cpu_affinity():
            for command in commands:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Native GDAL import timeout")
                run = subprocess.run(
                    command,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=remaining,
                    check=False,
                )
                if run.returncode:
                    detail = run.stderr + "\n" + run.stdout
                    if response.exists():
                        detail += "\n" + response.read_text(encoding="utf-8-sig")
                    raise RuntimeError("Vendor GDAL import failed: " + detail[-12000:])
        result = json.loads(response.read_text(encoding="utf-8-sig"))
        if result.get("success") is not True:
            raise RuntimeError("Vendor GDAL import did not report success")
        with h5py.File(staged_hdf, "r") as hdf:
            imported = hdf[group_path]
            values = imported["Values"]
            vertical = imported["Values (Vertical)"]
            if (
                values.ndim != 2
                or not all(values.shape)
                or values.shape != vertical.shape
            ):
                raise ValueError("Native import produced an invalid raster payload")
            if values.shape[0] != result["bands"]:
                raise ValueError("Native import timestamps and raster rows disagree")
            decode = lambda value: (
                value.decode() if isinstance(value, bytes) else str(value)
            )
            if decode(values.attrs.get("Time Series Data Type", "")) != "Amount":
                raise ValueError(
                    "Native writer omitted cumulative time-series semantics"
                )
            if decode(values.attrs.get("Rate Time Units", "")) != "Hour":
                raise ValueError("Native writer omitted the rate-time unit contract")
            # Validate in bounded blocks, including equality of both storage orders.
            block_rows = max(1, min(16, 262144 // values.shape[1]))
            previous = None
            for start in range(0, values.shape[0], block_rows):
                block = values[start : start + block_rows]
                if not np.all(np.isfinite(block)):
                    raise ValueError("Native import contains nonfinite raster values")
                if np.any(block < 0) or np.any(np.diff(block, axis=0) < -1e-6):
                    raise ValueError(
                        "Cumulative native precipitation must be nonnegative and nondecreasing"
                    )
                if previous is not None and np.any(block[0] < previous - 1e-6):
                    raise ValueError(
                        "Cumulative native precipitation decreases across blocks"
                    )
                previous = block[-1].copy()
                if not np.array_equal(block, vertical[start : start + block_rows]):
                    raise ValueError("Native horizontal/vertical payloads disagree")
            result["shape"] = list(values.shape)
        if (
            _sha256(source) != source_digest
            or _sha256(hdf_path) != sidecar_digest
            or _sha256(unsteady) != text_digest
        ):
            raise RuntimeError(
                "Source or project changed during import; target was not replaced"
            )
        result.update(
            source_sha256=source_digest,
            helper_sha256=_sha256(helper),
            helper_source_sha256=_sha256(helper_source),
            unsteady_hdf_path=str(hdf_path),
            route="native_gdal",
            helper_host=helper_host,
            vendor_sha256={
                name: _sha256(install / name)
                for name in (
                    "Ras.exe",
                    "Geospatial.GDALAssist.dll",
                    "Geospatial.IO.dll",
                    "H5Assist.dll",
                )
                if (install / name).is_file()
            },
        )
        os.replace(staged_hdf, hdf_path)
        return result


def inspect_precipitation(hdf_path: Path) -> dict:
    """Read bounded precipitation/result evidence after all native writers exit."""
    import h5py
    import numpy as np

    from .fast_hdf import read_attr, read_typed

    def summarize(dataset):
        digest = hashlib.sha256()
        finite_count = nonzero = 0
        minimum, maximum = float("inf"), float("-inf")
        step = max(1, min(32, 262144 // max(1, int(np.prod(dataset.shape[1:])))))
        for offset in range(0, dataset.shape[0], step):
            block = np.asarray(read_typed(dataset, slice(offset, offset + step)))
            if block.dtype.kind in "SO":
                digest.update(json.dumps(block.astype(str).tolist()).encode())
                continue
            digest.update(np.ascontiguousarray(block).tobytes())
            finite = block[np.isfinite(block)]
            if finite.size:
                finite_count += int(finite.size)
                nonzero += int(np.count_nonzero(finite))
                minimum = min(minimum, float(finite.min()))
                maximum = max(maximum, float(finite.max()))
        result = {
            "shape": list(dataset.shape),
            "dtype": str(dataset.dtype),
            "sha256": digest.hexdigest(),
            "finite_count": finite_count,
            "nonzero": nonzero,
            "minimum": minimum if finite_count else None,
            "maximum": maximum if finite_count else None,
        }
        if dataset.dtype.kind not in "SO" and dataset.shape[0]:
            final = np.asarray(read_typed(dataset, -1))
            valid_final = final[np.isfinite(final)]
            result["final_maximum"] = (
                float(valid_final.max()) if valid_final.size else None
            )
            result["final_nonzero"] = int(np.count_nonzero(np.nan_to_num(final)))
        if "Times" in dataset.attrs:
            result["times"] = [
                v.decode() if isinstance(v, bytes) else str(v)
                for v in read_attr(dataset, "Times")
            ]
        result["semantics"] = {
            key: (
                read_attr(dataset, key).decode()
                if isinstance(read_attr(dataset, key), bytes)
                else str(read_attr(dataset, key))
            )
            for key in (
                "Time Series Data Type",
                "Rate Time Units",
                "Units",
                "Data Type",
            )
            if key in dataset.attrs
        }
        return result

    out = {"path": str(hdf_path), "exists": hdf_path.is_file(), "datasets": {}}
    if not hdf_path.is_file():
        return out
    precipitation = "Event Conditions/Meteorology/Precipitation"
    base = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas"
    with h5py.File(hdf_path, "r") as hdf:
        parameters = hdf.get("Plan Data/Plan Parameters")
        out["solver_core_settings"] = (
            {}
            if parameters is None
            else {
                key: np.asarray(read_attr(parameters, key)).tolist()
                for key in ("1D Cores", "2D Cores (per mesh)")
                if key in parameters.attrs
            }
        )
        selected = [
            precipitation + "/" + suffix
            for suffix in (
                "Imported Raster Data/Values",
                "Imported Raster Data/Values (Vertical)",
                "Values",
                "Timestamp",
            )
        ]
        if base in hdf:
            selected.extend(
                base + "/" + area + "/" + variable
                for area in hdf[base]
                for variable in (
                    "Cell Cumulative Precipitation Depth",
                    "Cell Hydraulic Depth",
                    "Water Surface",
                )
            )
        for path in selected:
            if path in hdf:
                out["datasets"][path] = summarize(hdf[path])
        event = hdf.get("Event Conditions")
        if event is not None:
            from ._preprocess_validation import _scalar_text

            out["event_completed"] = _scalar_text(
                read_attr(event, "Completed Successfully", None)
            ) in {"true", "1"}
    return out
