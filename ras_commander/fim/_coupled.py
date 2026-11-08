"""Receipt-bound global mixed 1D/2D staging and Rust coverage-first composition."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..Decorators import log_call
from .errors import FimUnsupportedError, FimEngineError
from ._one_d import (digest, write_json, _profile_selection, canonical_arrays,
                     _plan_delivery_aoi, METHOD_ID as XS_METHOD_ID,
                     REQUEST_SCHEMA as XS_SCHEMA)

METHOD_ID = "one-d-two-d-coverage-first-diagnostic/1"
REQUEST_SCHEMA = "fast-map-coupled-diagnostic/1"
TWO_D_METHOD = "rasmapper-plain-sloping/1"
TWO_D_SCHEMA = "ras-commander-sloping-request/1"
_PREPARATION_SEAL = object()


def _resources(threads, max_working_mib):
    from .RasFim import _positive_int
    threads = _positive_int(threads, "threads")
    mib = _positive_int(max_working_mib, "max_working_mib")
    if threads > 64:
        raise ValueError("threads must be <= 64")
    return threads, mib * 1024**2


def _terrain_validity(source):
    """Require identical terrain validity for rasterio and the Rust decoder."""
    from rasterio.enums import MaskFlags
    if any(MaskFlags.per_dataset in flags or MaskFlags.alpha in flags
           for flags in source.mask_flag_enums):
        raise FimUnsupportedError("coupled terrain with a dataset/alpha mask is unsupported; export nodata-tagged terrain")
    if source.nodata is None:
        raise FimUnsupportedError("coupled terrain must declare its nodata value")
    terrain = Path(source.name).resolve(strict=True)
    if (any(Path(name).resolve(strict=True) != terrain for name in source.files)
            or any(Path(str(terrain) + suffix).exists() for suffix in (".aux.xml", ".msk", ".ovr"))):
        raise FimUnsupportedError("coupled terrain with auxiliary sidecar dependencies is unsupported; export a self-contained nodata-tagged TIFF")


def _require_mixed(hdf):
    from .RasFim import RasFim
    scope = RasFim.inspect_model_scope(hdf)
    if scope.dimension != "mixed_1d_2d" or not scope.mesh_names or not scope.cross_section_count:
        raise FimUnsupportedError("coupled mapping requires actual mixed_1d_2d geometry")
    if scope.storage_area_names:
        raise FimUnsupportedError("mixed models with storage areas are unsupported")
    return scope


def _require_engine(engine_path):
    from . import _engine
    from .RasFim import RasFim
    engine = _engine.find_engine(engine_path)
    before = digest(engine)
    caps = RasFim.get_capabilities(engine)
    if digest(engine) != before:
        raise FimEngineError("engine changed during capability discovery")
    for key, method, schema in (("one_d_clipped_diagnostic", XS_METHOD_ID, XS_SCHEMA),
                                 ("sloping", TWO_D_METHOD, TWO_D_SCHEMA),
                                 ("coupled_diagnostic", METHOD_ID, REQUEST_SCHEMA)):
        support = caps.methods.get(key)
        if support is None or support.method_id != method or schema not in support.request_schemas:
            raise FimUnsupportedError("engine lacks coupled component contract: " + key)
    if caps.methods["sloping"].flags.get("export_physical_ownership") is not True:
        raise FimUnsupportedError("engine lacks export_physical_ownership capability")
    return engine, caps


def _alignment(hdf, profiles):
    """Prove every selected component uses the same stored Base Output axis."""
    import h5py
    from ..fast_hdf import read_typed
    from .. import HdfMesh, HdfResultsMesh
    prefix = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/"
    with h5py.File(hdf, "r") as source:
        if "Results/Steady" in source or prefix not in source:
            raise FimUnsupportedError("coupled mapping requires unambiguous unsteady results")
        axis_path = next((prefix + n for n in ("Time Date Stamp (ms)", "Time Date Stamp") if prefix+n in source), None)
        if axis_path is None:
            raise FimUnsupportedError("mixed output lacks a stored timestamp identity axis")
        ds = source[axis_path]
        if ds.ndim != 1 or ds.dtype.kind not in "SU" or ds.size * ds.dtype.itemsize > 16*1024**2:
            raise FimUnsupportedError("unsupported mixed timestamp axis")
        axis = [v.decode().strip("\0 ") if isinstance(v, bytes) else str(v).strip("\0 ") for v in read_typed(ds)]
        if not axis or not all(axis) or len(set(axis)) != len(axis):
            raise FimUnsupportedError("ambiguous mixed timestamp identities")
        xs = source[prefix+"Cross Sections/Water Surface"]
        if xs.ndim != 2 or xs.shape[0] != len(axis):
            raise FimUnsupportedError("XS output rows do not match stored timestamp axis")
        components = {"xs": {"dataset": xs.name, "shape": list(xs.shape)}}
        summary_prefix = prefix.replace("Unsteady Time Series/", "Summary Output/")
        if "Max" in profiles:
            summary = source.get(summary_prefix + "Cross Sections/Maximum Water Surface")
            if (not isinstance(summary, h5py.Dataset) or summary.ndim not in (1, 2)
                    or summary.shape[-1] != xs.shape[1] or not summary.size):
                raise FimUnsupportedError("XS Max requires a stored summary matching the global XS axis")
            components["xs"]["maximum"] = {"dataset": summary.name, "shape": list(summary.shape)}
        for name in HdfMesh.get_mesh_area_names(hdf):
            view = HdfResultsMesh.get_mesh_timeseries(hdf, name, "Water Surface", truncate=False,
                                                     return_type="view", include_ghost_cells=True)
            dataset = source[view.dataset_path]
            if not dataset.name.lstrip("/").startswith(prefix) or dataset.ndim != 2 or dataset.shape[0] != len(axis):
                raise FimUnsupportedError("mesh output does not bind the shared Base Output timestamp axis")
            components[name] = {"dataset": dataset.name, "shape": list(dataset.shape)}
            if "Max" in profiles:
                try:
                    summary = HdfResultsMesh.get_mesh_summary_output_group(source, name, "Maximum Water Surface")
                except (KeyError, ValueError) as exc:
                    raise FimUnsupportedError("mesh Max requires a stored Base Output summary") from exc
                if (not isinstance(summary, h5py.Dataset)
                        or not summary.name.lstrip("/").startswith(summary_prefix)
                        or summary.shape != (2, dataset.shape[1])):
                    raise FimUnsupportedError("mesh Max summary does not match the complete cell axis")
                components[name]["maximum"] = {"dataset": summary.name, "shape": list(summary.shape)}
        for selector in profiles:
            if selector != "Max" and (not isinstance(selector, int) or selector >= len(axis)):
                raise FimUnsupportedError("mixed profile must select Max or a stored timestamp index")
        return {"axis_path": axis_path, "timestamps": axis, "components": components,
                "selected": ["Max" if p == "Max" else axis[p] for p in profiles]}


def _stage_mesh(hdf, folder, selected, budget, threads):
    from ._sloping_inputs import _write_binary_mesh_payloads
    from ._sloping import _stage_profiles
    from ._horizontal_engine import _write_geometry
    from .. import HdfMesh
    from ..fast_hdf import backend_scope
    _require_mixed(hdf)
    import h5py
    from ..fast_hdf import read_typed
    from ._sloping_inputs import _BINARY_FIELDS
    with h5py.File(hdf, "r") as handle:
        attrs = read_typed(handle["Geometry/2D Flow Areas/Attributes"])
        physical_counts = {(row["Name"].decode().strip("\0 ") if isinstance(row["Name"], bytes) else str(row["Name"]).strip("\0 ")): int(row["Cell Count"]) for row in attrs}
        planned = 0
        for name in HdfMesh.get_mesh_area_names(hdf):
            prefix = "Geometry/2D Flow Areas/" + name + "/"
            for field, _ in _BINARY_FIELDS.values():
                ds = handle[prefix+field]
                planned += ds.size * max(ds.dtype.itemsize, 8) * 3
            ds = handle[prefix+"Cells Center Coordinate"]
            planned += ds.shape[0] * (64 + len(selected)*8)
        if planned > budget//2:
            raise FimUnsupportedError("global mesh payload reads exceed preparation admission")
    files, meshes, maxima = _write_binary_mesh_payloads(hdf, folder, threads=threads,
        include_max="Max" in selected.values(), max_staged_bytes=budget//3)
    units, _, _ = _stage_profiles(hdf, folder, meshes, maxima, selected,
                                  max_staged_bytes=budget//4)
    with backend_scope("rust"):
        cells = HdfMesh.get_mesh_cell_polygons(hdf, strict=True, engine="native", threads=threads)
    if cells.empty or not cells.geometry.is_valid.all() or cells.geometry.is_empty.any():
        raise FimUnsupportedError("coupled physical ownership requires complete valid polygons")
    lookup = {mesh["mesh_name"]: i for i, mesh in enumerate(meshes)}
    addresses = [[lookup[row.mesh_name], int(row.cell_id)] for row in cells.itertuples()]
    expected = {(lookup[name], cell) for name, count in physical_counts.items() for cell in range(count)}
    if set(map(tuple, addresses)) != expected:
        raise FimUnsupportedError("physical polygons do not cover every physical cell identity")
    if len(set(map(tuple, addresses))) != len(addresses):
        raise FimUnsupportedError("duplicate physical cell identities")
    _write_geometry(folder / "cells.wkb", cells.geometry.to_numpy())
    return {"mesh_files": files, "meshes": meshes, "profiles": units,
            "geometry_file": "cells.wkb", "owner_cells": addresses,
            "physical_cell_count": len(addresses)}


def _validate_coupled_receipt(prepared, receipt):
    try:
        mesh = receipt["mesh"]
        scope = _require_mixed(receipt["source_hdf"])
        if scope.to_dict() != receipt["scope_evidence"]:
            raise ValueError("model scope evidence changed")
        geometry_path = getattr(scope, "geometry_path", None)
        if geometry_path is not None and str(geometry_path) not in receipt["sha256"]:
            raise ValueError("missing source geometry hash coverage")
        if receipt["alignment"] != _alignment(receipt["source_hdf"], receipt["profiles"]):
            raise ValueError("timestamp alignment changed")
        if receipt["engine_sha256"] != digest(receipt["engine_path"]):
            raise ValueError("prepared engine changed")
        if mesh["physical_cell_count"] != len(mesh["owner_cells"]) or not mesh["owner_cells"]:
            raise ValueError("physical ownership cardinality")
        for address in mesh["owner_cells"]:
            if (not isinstance(address, list) or len(address) != 2
                    or any(isinstance(v, bool) or not isinstance(v, int) for v in address)
                    or not 0 <= address[0] < len(mesh["meshes"])
                    or not 0 <= address[1] < mesh["meshes"][address[0]]["cell_count"]):
                raise ValueError("physical owner address shape/range")
        if [p["id"] for p in mesh["profiles"]] != receipt["profile_ids"]:
            raise ValueError("mesh profile identities")
        for relative in [mesh["geometry_file"], *mesh["mesh_files"],
                         *(f for p in mesh["profiles"] for f in p["values_files"])]:
            path = str(prepared.folder / relative)
            if path not in receipt["sha256"]:
                raise ValueError("missing mesh payload hash coverage")
        for metadata in mesh["mesh_files"]:
            payload = json.loads((prepared.folder / metadata).read_text())
            for descriptor in payload["arrays"].values():
                if str((prepared.folder / metadata).parent / descriptor["path"]) not in receipt["sha256"]:
                    raise ValueError("missing mesh topology hash coverage")
        for unit in mesh["profiles"]:
            if len(unit["values_files"]) != len(mesh["meshes"]):
                raise ValueError("mesh profile cardinality")
            for name, model in zip(unit["values_files"], mesh["meshes"]):
                if (prepared.folder / name).stat().st_size != model["cell_count"]*4:
                    raise ValueError("mesh profile bytes")
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise FimUnsupportedError(f"invalid coupled receipt: {exc}") from exc


@dataclass(frozen=True)
class FimPreparedCoupledModel:
    """Immutable global mixed inputs created only by prepare_coupled_model.

    Source, engine, receipt and payload hashes are rechecked for every mapping
    and before/after whole-batch publication. Reconstructed instances refuse.
    """
    folder: Path
    _receipt_sha256: str = field(init=False, default="", repr=False)
    _seal: object = field(init=False, default=None, repr=False)

    def __post_init__(self):
        if self._seal is not _PREPARATION_SEAL:
            raise FimUnsupportedError("coupled preparation must be created by prepare_coupled_model")
        object.__setattr__(self, "folder", Path(self.folder).resolve(strict=True))

    @classmethod
    def _from_preparation(cls, folder, receipt_sha256):
        prepared = object.__new__(cls)
        object.__setattr__(prepared, "folder", folder)
        object.__setattr__(prepared, "_receipt_sha256", receipt_sha256)
        object.__setattr__(prepared, "_seal", _PREPARATION_SEAL)
        prepared.__post_init__()
        return prepared


    @property
    def receipt(self):
        path = self.folder / "coupled_preparation.json"
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != self._receipt_sha256:
            raise FimUnsupportedError("prepared coupled receipt changed")
        return json.loads(payload)

    @log_call
    def validate(self):
        from pyproj.exceptions import CRSError
        receipt = self.receipt
        if (receipt.get("schema") != "ras-commander-coupled-preparation/1"
                or receipt.get("method_id") != METHOD_ID
                or receipt.get("request_schema") != REQUEST_SCHEMA
                or receipt.get("component_contracts") != {
                    "xs": {"method_id": XS_METHOD_ID, "request_schema": XS_SCHEMA},
                    "two_d": {"method_id": TWO_D_METHOD, "request_schema": TWO_D_SCHEMA}}):
            raise FimUnsupportedError("invalid prepared coupled receipt identity")
        try:
            counts = {key: receipt[key] for key in
                      ("point_count", "triangle_count", "segment_count", "cross_section_count")}
            if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in counts.values()):
                raise ValueError("invalid counts")
            profiles, levels = receipt["profiles"], receipt["levels"]
            names = receipt.get("profile_ids", [f"profile_{i:04d}" for i in range(len(profiles))])
            if (not isinstance(profiles, list) or not isinstance(levels, list) or not isinstance(names, list)
                    or not len(profiles) == len(levels) == len(names)):
                raise ValueError("profile cardinality")
            _profile_selection(dict(zip(names, profiles)))
            if not profiles or len(set(names)) != len(names):
                raise ValueError("profile identities")
            p, t, s, x = (counts[k] for k in ("point_count", "triangle_count", "segment_count", "cross_section_count"))
            sizes = {"points": p*4*8, "triangles": t*3*4, "tin_info": s*4*4,
                     "xs_ids": s*2*4, "render_order": s*4,
                     "normalized_m": p*8, "xs_clip": x*8*4}
            files, hashes = receipt["files"], receipt["sha256"]
            if not isinstance(files, dict) or set(files) != set(sizes) or not isinstance(hashes, dict):
                raise ValueError("required payloads")
            required = [receipt["source_hdf"], receipt["terrain"], receipt["point_m_evidence"], *files.values(), *levels]
            if receipt.get("storage") is not None:
                raise ValueError("mixed storage is unsupported")
            if any(not isinstance(path, str) or path not in hashes for path in required):
                raise ValueError("missing source/payload hash coverage")
            for name, size in sizes.items():
                if Path(files[name]).stat().st_size != size:
                    raise ValueError("payload byte count")
            if any(Path(path).stat().st_size != x*4 for path in levels):
                raise ValueError("profile byte count")
            if Path(receipt["point_m_evidence"]).stat().st_size != p*2*8:
                raise ValueError("normalization evidence byte count")
            for path, expected in hashes.items():
                if not isinstance(expected, str) or len(expected) != 64 or digest(path) != expected:
                    raise ValueError("source or payload changed: " + str(path))
            # Validate grid and datum labels against the hashed source files
            # in addition to checking the bound preparation fingerprint.
            import rasterio
            from pyproj import CRS
            from ..hdf.HdfBase import HdfBase
            grid = receipt["grid"]
            transform = grid["geo_transform"]
            if (not isinstance(transform, list) or len(transform) != 6
                    or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in transform)
                    or any(isinstance(grid[k], bool) or not isinstance(grid[k], int) or grid[k] <= 0 for k in ("width", "height"))):
                raise ValueError("invalid source grid")
            declared_crs = CRS.from_user_input(grid["crs"])
            if declared_crs.to_epsg() is None:
                raise FimUnsupportedError("coupled terrain CRS must have an EPSG code; no CRS relabelling is performed")
            with rasterio.open(receipt["terrain"]) as terrain:
                _terrain_validity(terrain)
                if (grid["width"] != terrain.width or grid["height"] != terrain.height
                        or tuple(transform) != terrain.transform.to_gdal()
                        or grid["tile_size"] != 256 or terrain.block_shapes != [(256, 256)]
                        or terrain.count != 1 or terrain.dtypes != ("float32",)
                        or CRS.from_user_input(terrain.crs) != declared_crs):
                    raise ValueError("grid or CRS differs from bound terrain")
            if (not declared_crs.is_projected
                    or any(abs(axis.unit_conversion_factor - 1200/3937) > 1e-12 for axis in declared_crs.axis_info[:2])
                    or declared_crs != CRS.from_user_input(HdfBase.get_projection(receipt["source_hdf"]))):
                raise ValueError("CRS differs from bound source model")
            units = HdfBase.get_result_unit_metadata(receipt["source_hdf"])
            if receipt["units"] != units or units.get("unit_system") != "US Customary" or units.get("warnings") or units.get("contradictions"):
                raise ValueError("units differ from bound source model")
        except (KeyError, TypeError, ValueError, OSError, CRSError) as exc:
            raise FimUnsupportedError(f"invalid or changed prepared coupled inputs: {exc}") from exc
        _validate_coupled_receipt(self, receipt)
        return receipt

    @log_call
    def map_profiles(self, output_folder, *, profiles=None, allow_unqualified=False,
                     bbox=None, polygon=None, polygon_layer=None, aoi_crs=None,
                     engine_path=None, threads=1, max_working_mib=1024, timeout=None,
                     raise_on_failure=True):
        """Map prepared profile names into a new or empty output folder.

        ``profiles`` is an ordered sequence of prepared names, following the
        prepared sloping API. None selects all names. AOIs preserve the complete
        source geometry and terrain grid; preparation remains unqualified.
        """
        return map_coupled_profiles(
            self, None, output_folder, profiles=profiles,
            allow_unqualified=allow_unqualified, bbox=bbox, polygon=polygon,
            polygon_layer=polygon_layer, aoi_crs=aoi_crs, engine_path=engine_path,
            threads=threads, max_working_mib=max_working_mib, timeout=timeout,
            raise_on_failure=raise_on_failure)

def prepare_coupled_model(hdf_path, terrain_path, output_folder, *, profiles=None,
                        allow_unqualified=False, max_working_mib=1024, engine_path=None, threads=1):
    import rasterio
    from pyproj import CRS
    from pyproj.exceptions import CRSError
    from ..hdf.HdfBase import HdfBase
    from ..hdf.HdfXsec import HdfXsec
    from .RasFim import _positive_int, _prepare_output_folder

    if not isinstance(allow_unqualified, bool):
        raise ValueError("allow_unqualified must be a boolean")
    if not allow_unqualified:
        raise FimUnsupportedError("canonical coupled is unqualified; diagnostic use requires allow_unqualified=True")
    threads, budget = _resources(threads, max_working_mib)
    engine, capabilities = _require_engine(engine_path)
    profile_ids, profiles = _profile_selection(profiles)
    budget = _positive_int(max_working_mib, "max_working_mib") * 1024**2
    hdf, terrain = Path(hdf_path).resolve(strict=True), Path(terrain_path).resolve(strict=True)
    before = {str(p): digest(p) for p in (hdf, terrain, engine)}
    folder = None
    output_existed = Path(output_folder).exists()
    created_paths = []
    try:
        scope = _require_mixed(hdf)
        geometry_path = getattr(scope, "geometry_path", None)
        if geometry_path is not None:
            before[str(geometry_path)] = digest(geometry_path)
        alignment = _alignment(hdf, profiles)
        try:
            data = HdfXsec.get_one_d_mapping_inputs(hdf, profiles=profiles, max_bytes=budget//4)
        except (ValueError, KeyError) as exc:
            raise FimUnsupportedError(f"stored 1D inputs cannot be staged: {exc}") from exc
        if data["result_kind"] != "unsteady":
            raise FimUnsupportedError("mixed steady results are unsupported")
        if set(data["unsupported_features"]) - {"Geometry/2D Flow Areas"}:
            raise FimUnsupportedError("unsupported 1D features: " + repr(data["unsupported_features"]))
        storage = None
        arrays, xs_receipts, offsets = canonical_arrays(data)
        try:
            crs = CRS.from_user_input(HdfBase.get_projection(hdf))
        except CRSError as exc:
            raise FimUnsupportedError("model has no valid projected CRS") from exc
        if not crs.is_projected or any(abs(a.unit_conversion_factor-1200/3937) > 1e-12 for a in crs.axis_info[:2]):
            raise FimUnsupportedError("coupled preparation requires a projected CRS in US survey feet; explicit conversion required")
        if crs.to_epsg() is None:
            raise FimUnsupportedError("coupled terrain CRS must have an EPSG code; no CRS relabelling is performed")
        with rasterio.open(terrain) as src:
            _terrain_validity(src)
            if CRS.from_user_input(src.crs) != crs:
                raise FimUnsupportedError("terrain and model CRS differ; no datum relabelling or automatic reprojection")
            gt = src.transform.to_gdal()
            if src.count != 1 or src.dtypes[0] != "float32" or not src.is_tiled or src.block_shapes != [(256, 256)] or gt[1] != -gt[5] or gt[2] or gt[4] or gt[1] <= 0:
                raise FimUnsupportedError("requires original single-band Float32 square-pixel 256-tiled north-up terrain")
            grid = {"width": src.width, "height": src.height, "geo_transform": list(gt), "tile_size": 256, "crs": crs.to_wkt()}
        # Units metadata is retained, never inferred by assigning a CRS.
        units = HdfBase.get_result_unit_metadata(hdf)
        if units.get("unit_system") != "US Customary" or units.get("warnings") or units.get("contradictions"):
            raise FimUnsupportedError("ambiguous model unit metadata")
        checked_levels = []
        for row in data["levels"]:
            values = np.asarray(row, dtype="<f4")
            if values.shape != (len(data["Attributes"]),) or not np.isfinite(values).all():
                raise FimUnsupportedError("WSE must contain one finite Float32 value per global XS")
            checked_levels.append(values)
        for k, xs_receipt in enumerate(xs_receipts):
            xs_receipt["profile_wse"] = [float(row[k]) for row in checked_levels]
            xs_receipt["profile_wse_f32_bits"] = [int(row[k:k+1].view("<u4")[0]) for row in checked_levels]
        folder = _prepare_output_folder(output_folder)
        files = {}
        for name, array in arrays.items():
            path = folder / (name + ".bin")
            created_paths.append(path)
            array.tofile(path)
            files[name] = str(path)
        levels = []
        for i, row in enumerate(checked_levels):
            values = np.asarray(row, dtype="<f4")
            if values.shape != (len(data["Attributes"]),) or not np.isfinite(values).all():
                raise FimUnsupportedError("WSE must contain one finite Float32 value per global XS")
            path = folder / f"levels-{i}.bin"
            created_paths.append(path)
            values.tofile(path)
            levels.append(str(path))
        storage_receipt = None
        # Per-point raw/normalized evidence preserves Float64 bits including unchanged points.
        evidence = np.column_stack((arrays["points"][:, 3], arrays["normalized_m"]))
        evidence_path = folder / "point-m-evidence.f64"
        created_paths.append(evidence_path)
        evidence.astype("<f8").tofile(evidence_path)
        receipt = {"schema": "ras-commander-coupled-preparation/1", "qualified": False,
                   "method_id": METHOD_ID, "request_schema": REQUEST_SCHEMA,
                   "component_contracts": {
                       "xs": {"method_id": XS_METHOD_ID, "request_schema": XS_SCHEMA},
                       "two_d": {"method_id": TWO_D_METHOD, "request_schema": TWO_D_SCHEMA}},
                   "semantics_reference": "7.0.1 preparation; 6.6 normalization/endpoint selection source-verified; full-corpus parity unqualified",
                   "scope": "global stored XS TIN and physical 2D plain corner-sloping coverage",
                   "storage": storage_receipt, "result_kind": data["result_kind"],
                   "stored_profile_names": data["stored_profile_names"],
                   "source_hdf": str(hdf), "terrain": str(terrain), "grid": grid,
                   "units": units, "files": files, "levels": levels,
                   "profiles": list(data["profiles"]), "profile_ids": profile_ids,
                   "cross_section_count": len(data["Attributes"]),
                   "point_count": len(arrays["points"]), "triangle_count": len(arrays["triangles"]),
                   "segment_count": len(arrays["tin_info"]), "obstruction_selection": xs_receipts,
                   "normalization_offsets": offsets,
                   "normalization_anchor_rule": "endpoint-Z-first-nearest-M/1; source-verified 6.6 and 7.0.1",
                   "normalization_anchor_indices": [
                       [[int(np.flatnonzero(arrays["points"][start:start+count, 2] == z)[
                           int(np.argmin(np.abs(arrays["points"][start:start+count][arrays["points"][start:start+count, 2] == z, 3] - m)))])
                         for m in (0., -1., 1.)] for z in (1., 0.)]
                       for start, count, _, _ in arrays["tin_info"]], "point_m_evidence": str(evidence_path),
                   "point_m_evidence_columns": ["raw_m", "normalized_strip_m"],
                   "normalized_changed_points": int(np.count_nonzero(evidence[:, 0] != evidence[:, 1])),
                   "sha256": before | {str(p): digest(p) for p in folder.iterdir()}}
        mesh_folder = folder / "two_d"
        mesh_folder.mkdir()
        created_paths.append(mesh_folder)
        mesh = _stage_mesh(hdf, mesh_folder, dict(zip(profile_ids, profiles)), budget, threads)
        for key in ("geometry_file",):
            mesh[key] = "two_d/" + mesh[key]
        mesh["mesh_files"] = ["two_d/" + f for f in mesh["mesh_files"]]
        for unit in mesh["profiles"]:
            unit["values_files"] = ["two_d/" + f for f in unit["values_files"]]
        receipt.update(mesh=mesh, alignment=alignment, engine_path=str(engine),
                       engine_sha256=before[str(engine)], scope_evidence=_require_mixed(hdf).to_dict())
        if any(path not in created_paths for path in folder.iterdir()):
            raise FimUnsupportedError("coupled preparation destination changed during staging")
        receipt["sha256"].update({str(p): digest(p) for p in folder.rglob("*") if p.is_file()})
        receipt["sha256"][str(engine)] = before[str(engine)]
        receipt_path = folder / "coupled_preparation.json"
        created_paths.extend((receipt_path, receipt_path.with_name(receipt_path.name + ".partial")))
        write_json(receipt_path, receipt)
        if any(digest(p) != sha for p, sha in before.items()):
            raise FimUnsupportedError("coupled input changed during preparation")
        return FimPreparedCoupledModel._from_preparation(folder, digest(receipt_path))
    except BaseException as exc:
        # Only remove files owned by this attempt, never pre-existing data or
        # concurrent files another caller may have added to the destination.
        import logging
        for path in reversed(created_paths):
            try:
                if path.is_dir():
                    import shutil
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
            except OSError:
                logging.getLogger(__name__).warning("Cannot clean failed coupled preparation file %s", path, exc_info=True)
        if folder is not None and not output_existed:
            try:
                folder.rmdir()
            except OSError:
                logging.getLogger(__name__).warning("Cannot remove failed coupled preparation folder %s", folder, exc_info=True)
        if isinstance(exc, CRSError):
            raise FimUnsupportedError("model or terrain has an invalid CRS") from exc
        raise



def _run(engine, command, request, out, timeout):
    from . import _engine
    proc = _engine.run_engine([str(engine), command, str(request), str(out)], "coupled " + command, timeout)
    if proc.returncode:
        raise _engine.read_refusal(out, proc.stderr) or FimEngineError(proc.stderr[-4000:])
    return json.loads((out / "report.json").read_text())


def _verify_products(out, pixels):
    arrays = []
    for product in ("depth", "wse"):
        path = out / (product + ".bin")
        if path.stat().st_size != pixels*4:
            raise FimEngineError("component product byte count differs")
        arrays.append(np.memmap(path, dtype="<f4", mode="r"))
    valid = 0
    try:
        for start in range(0, pixels, 65536):
            depth, wse = [a[start:start+65536] for a in arrays]
            finite = np.isfinite(depth)
            if (np.isinf(depth).any() or np.isinf(wse).any() or (depth[finite] < 0).any()
                    or not np.array_equal(finite, np.isfinite(wse))):
                raise FimEngineError("invalid component product masks or values")
            valid += int(finite.sum())
    finally:
        arrays.clear()
    return valid


def _validate_xs_report(report, receipt, window):
    from affine import Affine
    import rasterio
    grid = receipt["grid"]
    expected = {"schema": XS_SCHEMA, "status": "complete", "width": int(window.width),
                "height": int(window.height), "source_width": grid["width"],
                "source_height": grid["height"], "source_geo_transform": grid["geo_transform"],
                "source_col": int(window.col_off), "source_row": int(window.row_off),
                "geo_transform": list(rasterio.windows.transform(window, Affine.from_gdal(*grid["geo_transform"])).to_gdal()),
                "tile_size": 256, "scope": "xs-surface-only",
                "clipping_scope": "levees-and-xs-end-obstructions-only",
                "depth_file": "depth.bin", "wse_file": "wse.bin", "dtype": "little-endian float32", "nodata": "NaN"}
    if any(report.get(k) != v for k, v in expected.items()) or report.get("method", {}).get("method_id") != XS_METHOD_ID:
        raise FimEngineError("mismatched XS component report")
    valid = report.get("valid_pixels")
    if isinstance(valid, bool) or not isinstance(valid, int) or not 0 <= valid <= window.width*window.height:
        raise FimEngineError("invalid XS valid pixel count")


def _validate_two_d_report(report, request, gt, out):
    window = request["window"]
    count = window[2]*window[3]
    owners = report.get("physical_ownership", {})
    expected = {"kind": "physical_2d", "dtype": "<u4", "count": count, "path": "owners.bin",
                "bytes": count*4, "width": window[2], "height": window[3], "window": window,
                "geo_transform": gt, "epsg": request["epsg"], "crs_identity": request["crs_identity"],
                "owner_cell_count": len(request["owner_cells"])}
    if (report.get("schema") != "ras-commander-sloping-report/1" or report.get("status") != "complete"
            or report.get("method", {}).get("method_id") != TWO_D_METHOD or report.get("window") != window
            or any(owners.get(k) != v for k, v in expected.items())
            or report.get("profiles") is None
            or [(p.get("id"), p.get("status")) for p in report["profiles"]] != [(request["profiles"][0]["id"], "complete")]
            or (out / "owners.bin").stat().st_size != count*4):
        raise FimEngineError("mismatched physical 2D ownership/component report")
    labels = np.memmap(out / "owners.bin", dtype="<u4", mode="r")
    owned = 0
    for start in range(0, count, 65536):
        block = labels[start:start+65536]
        if (block > len(request["owner_cells"])).any():
            raise FimEngineError("physical owner labels exceed global owner ordering")
        owned += int(np.count_nonzero(block))
    del labels
    if owners.get("owned_pixels") != owned:
        raise FimEngineError("physical ownership coverage count differs")


def map_coupled_profiles(hdf_path, terrain_path, output_folder, *, profiles=None,
                       allow_unqualified=False, bbox=None, polygon=None, aoi_crs=None,
                       polygon_layer=None, engine_path=None, threads=1,
                       max_working_mib=1024, timeout=None, raise_on_failure=True):
    """Compose globally prepared XS and physical 2D surfaces through Rust.

    A prepared model may replace hdf_path; terrain_path must then be None.
    AOIs restrict output only. All global geometry and original tile origins
    remain intact. Components execute serially; sloping uses the bounded Rust
    thread pool while the XS and compositor transports are sequential.
    """
    import tempfile
    import pandas as pd
    import rasterio
    from affine import Affine
    from . import _aoi, _aoi_lattice, _engine, _products
    from .errors import FimEngineError, FimMappingError
    from .RasFim import MANIFEST_COLUMNS, MANIFEST_SCHEMA, RasFim, _positive_int, _prepare_output_folder

    threads = _positive_int(threads, "threads")
    budget = _positive_int(max_working_mib, "max_working_mib") * 1024**2
    if not isinstance(raise_on_failure, bool):
        raise ValueError("raise_on_failure must be a boolean")
    if threads > 64:
        raise ValueError("threads must be <= 64")
    if timeout is not None and (isinstance(timeout, bool) or not np.isfinite(timeout) or timeout <= 0):
        raise ValueError("timeout must be positive and finite, or None")
    if not isinstance(allow_unqualified, bool):
        raise ValueError("allow_unqualified must be a boolean")
    if not allow_unqualified:
        raise FimUnsupportedError("canonical coupled is unqualified; pass allow_unqualified=True for diagnostics")
    threads, budget = _resources(threads, max_working_mib)
    engine, capabilities = _require_engine(engine_path)
    support = capabilities.methods["coupled_diagnostic"]
    def plain(value):
        if isinstance(value, Mapping):
            return {key: plain(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [plain(item) for item in value]
        return value
    engine_identity = plain(capabilities.raw_record.get("engine", {}))
    engine_hash = digest(engine)
    with tempfile.TemporaryDirectory(prefix="fim-coupled-") as scratch_name:
        scratch = Path(scratch_name)
        if isinstance(hdf_path, FimPreparedCoupledModel):
            if terrain_path is not None:
                raise ValueError("prepared models already bind terrain")
            prepared = hdf_path
        else:
            prepared = prepare_coupled_model(hdf_path, terrain_path, scratch / "prepared",
                                           profiles=profiles, allow_unqualified=True,
                                           max_working_mib=max_working_mib, engine_path=engine, threads=threads)
        receipt = prepared.validate()
        names = receipt.get("profile_ids", [f"profile_{i:04d}" for i in range(len(receipt["profiles"]))])
        if isinstance(hdf_path, FimPreparedCoupledModel) and profiles is not None:
            if isinstance(profiles, Mapping):
                raise TypeError("prepared profiles must be names, not selectors")
            selected_names = [profiles] if isinstance(profiles, str) else list(profiles)
            if (not selected_names or any(not isinstance(name, str) for name in selected_names)
                    or len(set(selected_names)) != len(selected_names)):
                raise ValueError("profiles must contain unique prepared names")
            if any(name not in names for name in selected_names):
                raise ValueError("profiles contain names that were not prepared")
            positions = [names.index(name) for name in selected_names]
        else:
            positions = list(range(len(names)))
        selected_names = [names[i] for i in positions]
        selected_levels = [receipt["levels"][i] for i in positions]
        selected_profiles = {name: receipt["profiles"][i]
                             for name, i in zip(selected_names, positions)}
        if receipt["engine_path"] != str(engine) or receipt["engine_sha256"] != engine_hash:
            raise FimUnsupportedError("mapping engine differs from the prepared engine")
        identity = _engine.terrain_identity(engine, Path(receipt["terrain"]), receipt["grid"]["crs"], timeout=timeout)
        final_support = support
        final_method_id, final_schema = METHOD_ID, REQUEST_SCHEMA
        component_contracts = {"xs": {"method_id": XS_METHOD_ID, "request_schema": XS_SCHEMA},
                               "two_d": {"method_id": TWO_D_METHOD, "request_schema": TWO_D_SCHEMA}}
        grid = receipt["grid"]
        transform = Affine.from_gdal(*grid["geo_transform"])
        constraint = _aoi.resolve_aoi(bbox=bbox, polygon=polygon, aoi_crs=aoi_crs,
                                      polygon_layer=polygon_layer, default_crs=grid["crs"])
        window, mask_geometry, aoi_scratch = _plan_delivery_aoi(constraint, transform, grid, budget)
        pixels = int(window.width * window.height)
        staged_bytes = sum(Path(path).stat().st_size for path in receipt["sha256"]
                           if prepared.folder in Path(path).parents)
        component_overhead = staged_bytes*3 + 16*1024**2
        if (pixels * 192 + aoi_scratch + component_overhead +
                (pixels if mask_geometry is not None else 0) +
                receipt["point_count"] * 128 + receipt["triangle_count"] * 256 > budget):
            raise FimUnsupportedError("planned coupled delivery/component geometry exceeds max_working_mib")
        mask = None
        if mask_geometry is not None:
            # Use complete projected geometry and ORIGINAL source transform;
            # never clip geometry or normalize against a cropped transform.
            mask = _aoi_lattice.mask(mask_geometry, transform, window)
            if not mask.any():
                raise FimUnsupportedError("AOI contains no source-grid pixels")
        with rasterio.open(receipt["terrain"]) as source:
            terrain = source.read(1, window=window, masked=True).astype("<f4").filled(np.nan)
        terrain_file = scratch / "terrain.bin"
        terrain.tofile(terrain_file)
        inputs = {path: {"path": path, "size": Path(path).stat().st_size, "sha256": sha}
                  for path, sha in receipt["sha256"].items()}
        aoi_description = constraint.describe() if constraint else None
        if aoi_description is not None:
            aoi_description["geometry_wkb_hex"] = constraint.geometry.wkb_hex
            if mask_geometry is not None:
                aoi_description["projected_geometry_wkb_hex"] = mask_geometry.wkb_hex
                aoi_description["projected_crs_wkt"] = grid["crs"]
        details = {
            "threads_by_component": {"xs": 1, "two_d": threads, "composition": 1},
            "aoi": aoi_description,
            "aoi_mask": (_aoi_lattice.METHOD if mask is not None else
                         "pixel-center-bounds/1") if constraint else None,
            "options": {"profiles": selected_profiles, "allow_unqualified": allow_unqualified,
                        "threads": threads, "max_working_mib": budget // (1024**2),
                        "timeout": None if timeout is None else float(timeout)},
            "engine_path": str(engine), "inputs": inputs,
            "preparation_receipt": {"path": str(prepared.folder / "coupled_preparation.json"),
                                    "sha256": prepared._receipt_sha256,
                                    "ephemeral": not isinstance(hdf_path, FimPreparedCoupledModel)},
            "engine": engine_identity, "method_record": plain(final_support.flags),
            "component_contracts": component_contracts,
        }
        folder = _prepare_output_folder(output_folder)
        rows, reports = [], []
        staged_products = []
        published_products = []
        raw_hashes = {terrain_file: digest(terrain_file)}
        published_hashes = {}
        for profile in selected_names:
            row = dict.fromkeys(MANIFEST_COLUMNS)
            row.update(profile=profile, status="pending", col_off=int(window.col_off), row_off=int(window.row_off),
                       width=int(window.width), height=int(window.height), crs=rasterio.crs.CRS.from_wkt(grid["crs"]).to_string(),
                       transform=tuple(rasterio.windows.transform(window, transform))[:6])
            rows.append(row)

        def manifest_frame():
            result = pd.DataFrame(rows, columns=MANIFEST_COLUMNS)
            result.attrs.update(schema=MANIFEST_SCHEMA, method_id=final_method_id,
                                request_schema=final_schema, **details,
                                qualified=False, preparation=receipt,
                                threads_requested=threads, threads_effective=threads, engine_sha256=engine_hash)
            return result

        def persist(status, error=None):
            RasFim._write_manifest(folder, manifest_frame(), {
                       "method": final_method_id, "method_id": final_method_id,
                       "request_schema": final_schema, **details,
                       "qualified": False,
                       "preparation": receipt, "engine_sha256": engine_hash, "reports": reports,
                       "status": status, "error": error,
                       "threads_requested": threads, "threads_effective": threads})

        def verify_inputs():
            prepared.validate()
            for path, expected in (raw_hashes | published_hashes).items():
                if digest(path) != expected:
                    raise FimEngineError("mapping product changed before publication: " + str(path))
            if digest(engine) != engine_hash:
                raise FimEngineError("engine changed during mapping")

        try:
            persist("in_progress")
            for i, (profile, levels) in enumerate(zip(selected_names, selected_levels)):
                request = {"schema": XS_SCHEMA, "scope": "xs-surface-only",
                           "point_count": receipt["point_count"], "triangle_count": receipt["triangle_count"],
                           "segment_count": receipt["segment_count"], "cross_section_count": receipt["cross_section_count"],
                           "levels_file": levels, "terrain_file": str(terrain_file),
                           "width": grid["width"], "height": grid["height"],
                           "geo_transform": grid["geo_transform"], "tile_size": grid["tile_size"],
                           "window": dict(zip(("col", "row", "width", "height"), map(int, (window.col_off, window.row_off, window.width, window.height)))),
                           "max_working_bytes": budget-component_overhead-pixels*24-aoi_scratch, "clipping_scope": "levees-and-xs-end-obstructions-only"}
                request.update({name + "_file": path for name, path in receipt["files"].items()})
                request_file = scratch / f"request-{i}.json"
                write_json(request_file, request)
                out = scratch / f"engine-{i}"
                proc = _engine.run_engine([str(engine), "one-d-diagnostic", str(request_file), str(out)], "1D mapping", timeout)
                if proc.returncode != 0:
                    raise _engine.read_refusal(out, proc.stderr) or FimEngineError(proc.stderr[-4000:])
                report = json.loads((out / "report.json").read_text())
                if report.get("status") != "complete" or report.get("method", {}).get("method_id") != XS_METHOD_ID:
                    raise FimEngineError("incomplete or mismatched 1D engine report")
                reports.append(report)
                raw_hashes[request_file] = digest(request_file)
                reports.append({"component": "xs", "profile_id": profile, "selector": selected_profiles[profile],
                                "request": request, "request_sha256": raw_hashes[request_file],
                                "report_sha256": digest(out / "report.json")})
                _validate_xs_report(report, receipt, window)
                mesh = receipt["mesh"]
                unit = mesh["profiles"][positions[i]]
                two_request = {"schema": TWO_D_SCHEMA, "terrain": receipt["terrain"],
                    "epsg": identity["epsg"], "crs_identity": identity["crs_identity"],
                    "terrain_transform": grid["geo_transform"],
                    "window": [int(window.col_off), int(window.row_off), int(window.width), int(window.height)],
                    "geometry_file": str(prepared.folder / mesh["geometry_file"]),
                    "mesh_files": [str(prepared.folder / f) for f in mesh["mesh_files"]],
                    "owner_cells": mesh["owner_cells"],
                    "profiles": [dict(id=profile, values_files=[str(prepared.folder / f) for f in unit["values_files"]])],
                    "threads": threads, "max_working_bytes": budget-component_overhead-pixels*24-aoi_scratch,
                    "stream_outputs": False, "export_physical_ownership": True}
                two_file = scratch / f"two-d-request-{i}.json"
                write_json(two_file, two_request)
                two_out = scratch / f"two-d-{i}"
                two_report = _run(engine, "sloping", two_file, two_out, timeout)
                gt = list(rasterio.windows.transform(window, transform).to_gdal())
                _validate_two_d_report(two_report, two_request, gt, two_out)
                reports.append(two_report)
                raw_hashes[two_file] = digest(two_file)
                reports.append({"component": "two_d", "request_sha256": raw_hashes[two_file],
                                "report_sha256": digest(two_out / "report.json")})
                def component(depth, wse):
                    return {"profile_id": profile, "crs": grid["crs"], "width": int(window.width),
                            "height": int(window.height), "geo_transform": gt,
                            "depth_file": str(depth), "wse_file": str(wse)}
                if _verify_products(out, pixels) != report["valid_pixels"]:
                    raise FimEngineError("XS product validity count differs from report")
                _verify_products(two_out / profile, pixels)
                composition = {"schema": REQUEST_SCHEMA,
                    "xs": component(out / "depth.bin", out / "wse.bin"),
                    "two_d": component(two_out / profile / "depth.bin", two_out / profile / "wse.bin"),
                    "two_d_owners_file": str(two_out / "owners.bin"),
                    "two_d_cell_count": mesh["physical_cell_count"], "max_working_bytes": budget-component_overhead-pixels*24-aoi_scratch}
                component_paths = [out / "depth.bin", out / "wse.bin", two_out / profile / "depth.bin",
                                   two_out / profile / "wse.bin", two_out / "owners.bin"]
                raw_hashes.update({path: digest(path) for path in component_paths})
                verify_inputs()
                composition_file = scratch / f"composition-{i}.json"
                write_json(composition_file, composition)
                composed = scratch / f"composed-{i}"
                composition_report = _run(engine, "coupled-diagnostic", composition_file, composed, timeout)
                expected = {"schema": REQUEST_SCHEMA, "status": "complete", "profile_id": profile,
                            "crs": grid["crs"], "width": int(window.width), "height": int(window.height),
                            "geo_transform": gt}
                if (any(composition_report.get(k) != v for k, v in expected.items()) or
                        composition_report.get("method", {}).get("method_id") != METHOD_ID):
                    raise FimEngineError("mismatched coupled composition report")
                reports.append(composition_report)
                raw_hashes[composition_file] = digest(composition_file)
                reports.append({"component": "composition", "request_sha256": raw_hashes[composition_file],
                                "report_sha256": digest(composed / "report.json")})
                reports.append({"profile_id": profile, "input_products": {
                    str(path): {"sha256": digest(path), "bytes": path.stat().st_size}
                    for path in [out / "depth.bin", out / "wse.bin", two_out / profile / "depth.bin",
                                 two_out / profile / "wse.bin", two_out / "owners.bin"]}})
                out = composed
                valid_count = _verify_products(out, pixels)
                counts = composition_report.get("counts", {})
                if (counts.get("valid_pixels") != valid_count or
                        counts.get("two_d_owned_pixels") != two_report["physical_ownership"]["owned_pixels"] or
                        isinstance(counts.get("dry_two_d_suppressed_wet_xs"), bool) or
                        not isinstance(counts.get("dry_two_d_suppressed_wet_xs"), int) or
                        not 0 <= counts["dry_two_d_suppressed_wet_xs"] <= counts["two_d_owned_pixels"]):
                    raise FimEngineError("coupled composition coverage counts differ")
                raw_hashes.update({out / (product + ".bin"): digest(out / (product + ".bin"))
                                   for product in ("depth", "wse")})
                row = rows[i]
                for product in ("depth", "wse"):
                    raw = out / (product + ".bin")
                    if raw.stat().st_size != pixels*4:
                        raise FimEngineError("invalid 1D output byte count")
                    values = np.fromfile(raw, "<f4").reshape(int(window.height), int(window.width))
                    if np.isinf(values).any():
                        raise FimEngineError("infinite 1D output")
                    if mask is not None:
                        values[~mask] = np.nan
                    if product == "depth":
                        from ._products import flooded_mask
                        row["depth_finite_pixels"] = int(np.isfinite(values).sum())
                        row["flooded_pixels"] = int(flooded_mask(values).sum())
                    path = _products.product_paths(folder, profile)[0 if product == "depth" else 1]
                    partial = path.with_name(path.name + ".partial")
                    staged_products.append((partial, path))
                    _products.write_raster(partial, values, rasterio.windows.transform(window, transform), grid["crs"])
                    published_hashes[partial] = digest(partial)
                    row[product + "_tif"] = str(path)
            # No products are acknowledged until the complete batch and the
            # original source/payload/engine identities have been checked.
            verify_inputs()
            for partial, path in staged_products:
                published_products.append(path)
                partial.replace(path)
                published_hashes[path] = published_hashes.pop(partial)
            verify_inputs()
            for row in rows:
                row["status"] = "complete"
            persist("complete")
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"
            cleanup_errors = []
            for path in [partial for partial, _ in staged_products] + published_products:
                try:
                    path.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    cleanup_errors.append(f"{path.name}: {cleanup_error}")
            if cleanup_errors:
                error += "; product cleanup failed: " + "; ".join(cleanup_errors)
            for row in rows:
                row.update(status="failed", depth_tif=None, wse_tif=None,
                           depth_finite_pixels=None, flooded_pixels=None, error=error)
            manifest = manifest_frame()
            try:
                persist("failed", error)
            except Exception as receipt_error:
                if isinstance(exc, Exception):
                    raise FimMappingError(f"{error}; failed to write failure manifest: {receipt_error}", manifest) from exc
                raise exc
            if isinstance(exc, Exception):
                if raise_on_failure:
                    raise FimMappingError(error, manifest) from exc
                return manifest
            raise
        return manifest_frame()
