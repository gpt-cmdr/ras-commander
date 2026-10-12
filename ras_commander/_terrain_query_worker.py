"""Native-only terrain query process. Launch directly with -I, never with -m.

This process imports no Commander package, h5py, NumPy or GIS library. Its
managed reader must bind the verified thread-safe HEC-RAS HDF5 runtime.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import math
import struct
import sys
from pathlib import Path


def _load_runtime(install: Path) -> tuple:
    _check_python_imports()
    helper = Path(__file__).with_name("_property_tables_worker.py")
    spec = importlib.util.spec_from_file_location("native_runtime", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with contextlib.redirect_stdout(sys.stderr):
        handles, libraries = module._initialize_runtime(install)
    from HDF.PInvoke import H5

    _check_python_imports()

    metadata = {
        "schema": "ras-commander-native-terrain-runtime/v1",
        "status": "initialized",
        "managed_hdf5_version": list(H5.get_libversion(0, 0, 0))[1:],
        "managed_hdf5_threadsafe": bool(H5.is_library_threadsafe(0)[1]),
        "dll_identity_verified": True,
        "loaded_hdf5_modules": [
            str(p) for p in module._check_hdf5_modules(install / "bin64").values()
        ],
        "python_gis_hdf_imported": bool(_prohibited_python_imports()),
    }
    return handles, libraries, metadata


def _prohibited_python_imports() -> list[str]:
    prohibited = {"h5py", "numpy", "rasterio", "geopandas", "ras_commander"}
    return sorted({name.split(".")[0] for name in sys.modules} & prohibited)


def _check_python_imports() -> None:
    imported = _prohibited_python_imports()
    if imported:
        raise RuntimeError(
            "Native-only terrain worker imported forbidden Python packages: "
            + ", ".join(imported)
        )


def _point_reader(mapper: str, name: str, modifications: bool, cell_size: float):
    import clr
    from RasMapperLib import PointM, RASMapperCom, SharedData, TerrainLayer
    from System import Array
    from System.Xml import XmlDocument

    expected = ["RasMapperLib.PointM[]", "System.Boolean", "System.Double"]
    methods = [
        m
        for m in clr.GetClrType(TerrainLayer).GetMethods()
        if str(m.Name) == "ComputePointElevations"
        and [str(p.ParameterType) for p in m.GetParameters()] == expected
    ]
    if len(methods) != 1 or str(methods[0].ReturnType) != "System.Single[]":
        raise RuntimeError("The qualified native point-array contract changed")
    if [str(p.Name) for p in methods[0].GetParameters()] != [
        "points",
        "useObstructions",
        "cellSize",
    ]:
        raise RuntimeError(
            "The qualified native point-array parameter semantics changed"
        )
    doc = XmlDocument()
    doc.Load(mapper)
    SharedData.RasMapFilename = mapper
    SharedData.SRSFilename = RASMapperCom.GetSRSFromRasmapDoc(doc, mapper)
    units = doc.SelectSingleNode("/RASMapper/Units")
    if units is not None and str(units.InnerText).strip():
        SharedData.SetUnitsSystem(str(units.InnerText).strip())
    layers = [
        n
        for n in doc.SelectNodes("/RASMapper/Terrains/Layer")
        if str(n.GetAttribute("Name")) == name
    ]
    if len(layers) != 1:
        raise ValueError("Exactly one registered terrain must match terrain_name")
    terrain = TerrainLayer(name)
    terrain.XMLLoad(layers[0])
    terrain.ResampleMethod = "near"

    def evaluate(coordinates: list) -> list:
        if not 1 <= len(coordinates) <= 4096:
            raise ValueError("A native query requires 1 to 4096 points")
        extent = terrain.Extent
        minimum_x, maximum_x, minimum_y, maximum_y = (
            float(extent.MinX),
            float(extent.MaxX),
            float(extent.MinY),
            float(extent.MaxY),
        )
        points = []
        for x, y in coordinates:
            if not (math.isfinite(x) and math.isfinite(y)) or not (
                minimum_x <= x <= maximum_x and minimum_y <= y <= maximum_y
            ):
                raise ValueError(
                    "Supplied points lie outside the selected native terrain extent"
                )
            point = PointM(x, y)
            if struct.pack("<dd", point.X, point.Y) != struct.pack("<dd", x, y):
                raise RuntimeError(
                    "Native points changed supplied binary64 coordinates"
                )
            points.append(point)
        values = terrain.ComputePointElevations(
            Array[PointM](points), modifications, cell_size
        )
        return None if values is None else [float(v) for v in values]

    return evaluate


def _profile_reader(mapper: str, geometry: str):
    from RasMapperLib import RASMapperCom
    from System import Array, Double, Single

    com = RASMapperCom()

    def evaluate(request: dict) -> dict:
        coords = request["coordinates"]
        x, y = (
            Array[Double]([p[0] for p in coords]),
            Array[Double]([p[1] for p in coords]),
        )
        result = com.TerrainProfile(
            mapper,
            geometry,
            len(coords),
            x,
            y,
            request["filter_tolerance"],
            0,
            Array[Single]([]),
            Array[Single]([]),
            "",
        )
        count = int(result[6])
        return {
            "station": [float(result[7][i]) for i in range(count)],
            "elevation": [float(result[8][i]) for i in range(count)],
            "warning": str(result[9]),
        }

    return evaluate


def main() -> None:
    config = json.loads(sys.argv[2])
    handles, libraries, runtime = _load_runtime(Path(sys.argv[1]).absolute())
    from System import Console

    Console.SetOut(Console.Error)

    def serve():
        evaluator = (
            _point_reader(
                config["mapper"],
                config["terrain_name"],
                config["use_obstructions"],
                config["cell_size"],
            )
            if config["mode"] == "points"
            else _profile_reader(config["mapper"], config["geometry"])
        )
        _check_python_imports()
        from System.Threading import Thread, ThreadPool

        runtime["sampling_mode"] = "single-clr-pool-worker-v1"
        runtime["called_on_pool_worker"] = bool(Thread.CurrentThread.IsThreadPoolThread)
        runtime["sampling_max_threads"] = list(ThreadPool.GetMaxThreads())
        if not runtime["called_on_pool_worker"] or runtime["sampling_max_threads"] != [
            1,
            1,
        ]:
            raise RuntimeError("Native query did not enter the sole CLR pool worker")
        print(json.dumps({"ready": runtime}, allow_nan=False), flush=True)
        for line in sys.stdin:
            try:
                request = json.loads(line)
                result = evaluator(
                    request["coordinates"] if config["mode"] == "points" else request
                )
                print(json.dumps({"result": result}, allow_nan=False), flush=True)
            except Exception as exc:  # noqa: BLE001 - preserve CLR failures at the process boundary
                print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), flush=True)
                return 1
        return 0

    spec = importlib.util.spec_from_file_location(
        "native_serial_sampling",
        Path(__file__).with_name("_terrain_sampling_execution.py"),
    )
    serial = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serial)
    result, execution = serial.run_serial_sampling(serve, _initialized=True)
    if result:
        return result
    print(json.dumps({"finished": execution}, allow_nan=False), flush=True)
    # Keep both DLL and directory handles alive through every query.
    del libraries, handles


if __name__ == "__main__":
    sys.exit(main())
