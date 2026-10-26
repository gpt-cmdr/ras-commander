"""Explicit native corner preparation and read-only receipt validation.

Receipt validation never loads the native HEC-RAS runtime.
"""

from pathlib import Path
import hashlib
import json
import time

from .. import get_logger

logger = get_logger(__name__)


def _identity(path):
    path = Path(path).resolve(strict=True)
    stat = path.stat()
    return dict(path=str(path), size=stat.st_size, mtime_ns=stat.st_mtime_ns)


def _digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def prepare(hdf_path, output_folder, *, rasmap_path, terrain_name, hecras_version):
    from ..RasGeometryCompute import RasGeometryCompute, _LOCK
    from ..fast_hdf import release_native_sessions
    from .RasFim import RasFim

    if hecras_version != "7.0.1":
        raise ValueError("Corner preparation currently qualifies HEC-RAS 7.0.1 only")
    if not isinstance(terrain_name, str) or not terrain_name:
        raise ValueError("terrain_name must identify one registered RAS Mapper terrain")
    RasGeometryCompute._require_windows()
    hdf = Path(hdf_path).resolve(strict=True)
    rasmap = Path(rasmap_path).resolve(strict=True)
    scope = RasFim.validate_2d_model(hdf)
    folder = Path(output_folder).resolve()
    if folder.exists() and any(folder.iterdir()):
        raise FileExistsError("Corner preparation needs a new or empty output folder")
    folder.mkdir(parents=True, exist_ok=True)
    cache = folder / "PostProcessing.hdf"
    receipt = folder / "corner_elevation_receipt.json"
    started = time.perf_counter()
    inputs = {str(p): _identity(p) for p in (hdf, rasmap)}
    original_rasmap = rasmap.read_bytes()
    hdf_hash = _digest(hdf)
    result = dict(schema="ras-commander-corner-preparation/1", status="in_progress",
                  hdf=inputs[str(hdf)], hdf_sha256=hdf_hash, rasmap=inputs[str(rasmap)],
                  rasmap_sha256=hashlib.sha256(original_rasmap).hexdigest(),
                  terrain_name=terrain_name, runtime_version=hecras_version,
                  postprocessing_hdf=str(cache), meshes={}, inputs=inputs,
                  model_scope=scope)
    receipt.write_text(json.dumps(result, indent=2), encoding="utf-8")
    geometry = native_results = terrain = None
    try:
        release_native_sessions(hdf)
        with _LOCK:
            RasGeometryCompute._ensure_clr(hecras_version)
            import clr
            from System import Array, Int32, Object
            from System.Reflection import BindingFlags
            from System.Xml import XmlDocument
            from RasMapperLib import RASResults, SharedData, TerrainLayer
            from Utility.Progress import ProgressReporter

            assembly_path = Path(str(clr.GetClrType(RASResults).Assembly.Location))
            if assembly_path.parent.name != hecras_version:
                raise RuntimeError("Loaded RasMapperLib does not match the requested qualified runtime")

            document = XmlDocument()
            document.Load(str(rasmap))
            matches = [node for node in document.SelectNodes("/RASMapper/Terrains/Layer")
                       if node.GetAttribute("Name") == terrain_name]
            if len(matches) != 1:
                raise ValueError("terrain_name must match exactly one registered terrain")
            old_map = str(SharedData.RasMapFilename or "")
            try:
                SharedData.RasMapFilename = str(rasmap)
                terrain = TerrainLayer(terrain_name)
                terrain.XMLLoad(matches[0])
                if not terrain.AllSourceFilesExist():
                    raise FileNotFoundError("Registered terrain has missing source files")
                terrain_file = Path(str(terrain.SourceFilename)).resolve(strict=True)
                inputs[str(terrain_file)] = _identity(terrain_file)
                for index in range(terrain.RasterFileCount):
                    path = Path(str(terrain.RasterFileInfo(index).Filename)).resolve(strict=True)
                    inputs[str(path)] = _identity(path)
                native_results = RASResults.TryIdentifyResultsFile(str(hdf))
                if native_results is None:
                    raise ValueError("Native runtime could not identify the plan HDF")
                geometry = native_results.Geometry
                geometry.SetTerrainTemporary(terrain)
                processor = native_results.GetPostProcessor()
                flags = BindingFlags.Instance | BindingFlags.NonPublic
                field = processor.GetType().GetField("_filename", flags)
                if field is None:
                    raise RuntimeError("Native 7.0.1 postprocessor cache redirection unavailable")
                # Author a fresh cache, never overwrite the model's shared native cache.
                field.SetValue(processor, str(cache))
                import h5py
                for index in range(geometry.D2FlowArea.MeshCount):
                    name = str(geometry.D2FlowArea.GetFeatureName(index))
                    dataset = f"Geometry/2D Flow Areas/{name}/FacePoints Elevation"
                    source_path = Path(str(geometry.D2FlowArea.SourceFilename)).resolve(strict=True)
                    inputs[str(source_path)] = _identity(source_path)
                    with h5py.File(source_path, "r") as source:
                        copy = dataset in source
                    method_name = ("CopyPostProcessFacepointElevations" if copy
                                   else "ComputePostProcessFacepointElevations")
                    method = processor.GetType().GetMethod(method_name, flags)
                    if method is None:
                        raise RuntimeError("Native corner preparation method unavailable")
                    method.Invoke(processor, Array[Object]([
                        geometry.D2FlowArea, Int32(index), getattr(ProgressReporter, "None")()
                    ]))
                    result["meshes"][name] = dict(operation=method_name)
                result["runtime_assembly"] = str(clr.GetClrType(RASResults).Assembly.FullName)
                result["runtime_assembly_path"] = str(clr.GetClrType(RASResults).Assembly.Location)
            finally:
                SharedData.RasMapFilename = old_map
                RasGeometryCompute._release_geometry(geometry)
                geometry = native_results = terrain = None
        # Verify immutable sources and retain hashes for portable provenance.
        if rasmap.read_bytes() != original_rasmap or _digest(hdf) != hdf_hash:
            raise RuntimeError("Native preparation changed a source HDF or rasmap")
        for path, identity in inputs.items():
            if _identity(path) != identity:
                raise RuntimeError(f"Preparation source changed: {path}")
        result.update(status="complete", cache=_identity(cache), cache_sha256=_digest(cache),
                      elapsed_seconds=time.perf_counter() - started)
        receipt.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return {**result, "receipt_path": str(receipt)}
    except BaseException as error:
        result.update(status="aborted", error=str(error), elapsed_seconds=time.perf_counter()-started)
        cache.unlink(missing_ok=True)
        receipt.write_text(json.dumps(result, indent=2), encoding="utf-8")
        raise


def validate_receipt(hdf_path, cache_path):
    """Bind a cache-only source to the plan and terrain used for preparation."""
    cache = Path(cache_path).resolve(strict=True)
    receipt = cache.parent / "corner_elevation_receipt.json"
    if not receipt.is_file():
        raise ValueError("Cache-only mapping needs the receipt from RasFim.prepare_corner_elevations")
    document = json.loads(receipt.read_text(encoding="utf-8"))
    if document.get("schema") != "ras-commander-corner-preparation/1" or document.get("status") != "complete":
        raise ValueError("Corner preparation receipt is incomplete or unsupported")
    actual = _identity(hdf_path)
    expected = document["hdf"]
    if actual != expected:
        if actual["size"] != expected["size"] or _digest(hdf_path) != document["hdf_sha256"]:
            raise ValueError("Corner cache belongs to a different or changed plan HDF")
    if _digest(cache) != document["cache_sha256"]:
        raise ValueError("Corner cache changed after preparation")
    watched = {"corner_receipt": receipt}
    for index, (filename, identity) in enumerate(document["inputs"].items()):
        if filename == document["hdf"]["path"]:
            continue
        path = Path(filename)
        same_rasmap = (filename == document.get("rasmap", {}).get("path")
                       and path.exists() and _digest(path) == document["rasmap_sha256"])
        if not path.exists() or (_identity(path) != identity and not same_rasmap):
            raise ValueError(f"Corner preparation terrain/rasmap source changed: {path}")
        watched[f"corner_source_{index}"] = path
    return document, watched
