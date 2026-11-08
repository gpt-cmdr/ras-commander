"""Canonical stored-TIN staging for the diagnostic clipped 1D Rust method.

Preparation follows retained 7.0.1 staging evidence. The 6.6 normalization and
endpoint-selection source agrees; full-corpus parity remains unqualified.
No raster arithmetic or HEC runtime is used here.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .errors import FimUnsupportedError
from ..Decorators import log_call

METHOD_ID = "one-d-xs-surface-diagnostic/5"
REQUEST_SCHEMA = "fast-map-one-d-diagnostic/3"
STORAGE_METHOD_ID = "storage-area-level-pool/1"
STORAGE_SCHEMA = "fast-map-storage/1"
COMPOSITION_METHOD_ID = "one-d-two-d-storage-coverage-first-diagnostic/1"
COMPOSITION_SCHEMA = "fast-map-coupled-diagnostic/2"


def digest(path):
    """Hash incrementally on every supported Python version (including 3.10)."""
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _profile_selection(profiles):
    """Keep public profile names separate from ordered hydraulic selectors."""
    from . import _engine
    if profiles is None:
        names, selectors = ["Max"], ["Max"]
    elif isinstance(profiles, Mapping):
        names, selectors = list(profiles), list(profiles.values())
    else:
        if isinstance(profiles, (str, bytes)):
            raise TypeError("profiles must be a name/selector mapping or an ordered selector sequence")
        selectors = list(profiles)
        names = [f"profile_{i:04d}" for i in range(len(selectors))]
    if (not names or any(not isinstance(name, str) or not _engine._SAFE_ID.fullmatch(name)
                        or name in (".", "..") for name in names)
            or len({name.casefold() for name in names}) != len(names)):
        raise ValueError("profiles must have unique safe output names")
    if any(isinstance(value, (bool, np.bool_)) or not (
            isinstance(value, str) and bool(value) or
            isinstance(value, (int, np.integer)) and value >= 0) for value in selectors):
        raise ValueError('profile selectors must be nonempty stored names, Max, or nonnegative indices')
    return names, tuple(int(value) if isinstance(value, np.integer) else value for value in selectors)


def station_m(station, first, last, left, right):
    """Native piecewise Float32 ComputeM, with explicit endpoint clamps."""
    f = np.float32
    station, first, last, left, right = map(f, (station, first, last, left, right))
    if station <= first:
        return f(-2)
    if station < left:
        return f(f(-2) + f(f(station-first) / f(left-first)))
    if station < right:
        return f(f(-1) + f(f(f(2)*f(station-left)) / f(right-left)))
    if station < last:
        return f(f(1) + f(f(station-right) / f(last-right)))
    return f(2)


def normalize_segment(points):
    offsets = []
    for z in (1., 0.):
        ids = np.flatnonzero(points[:, 2] == z)
        if not len(ids):
            raise FimUnsupportedError("TIN lacks exact endpoint Z anchors")
        # Native 6.6/7.0.1 chooses the first nearest M in stored point order.
        # argmin retains the first tie, matching the strict-less-than scan.
        anchors = [points[ids[int(np.argmin(np.abs(points[ids, 3] - m)))]]
                   for m in (0., -1., 1.)]
        center, left, right = anchors
        def distance(a, b):
            return math.pow(math.pow(float(a[0]-b[0]), 2.) +
                            math.pow(float(a[1]-b[1]), 2.), .5)
        dl, dr = np.float32(distance(center, left)), np.float32(distance(center, right))
        total = np.float32(dl + dr)
        if not np.isfinite(total) or total <= 0:
            raise FimUnsupportedError("degenerate normalization distances")
        offsets.append(float(np.float32(float(np.float32(dl/total))*2.-1.)))
    us, ds = offsets
    result = points[:, 3].copy()
    for i, (_, _, z, m) in enumerate(points):
        if -1. < m < 1.:
            if m < 0.:
                u, d = m*(us+1.)+us, m*(ds+1.)+ds
            else:
                u, d = m*(1.-us)+us, m*(1.-ds)+ds
            result[i] = u*z + d*(1.-z)
    return result, offsets


def render_ranks(ids, rivers):
    promoted = []
    for k, river in enumerate(rivers):
        ends = np.flatnonzero(ids[:, 1] == k)
        starts = np.flatnonzero(ids[:, 0] == k)
        candidates, side = (ends, 0) if len(ends) > 1 and len(starts) <= 1 else (
            (starts, 1) if len(ends) <= 1 and len(starts) > 1 else ([], 0))
        for s in candidates:
            if rivers[ids[s, side]] == river:
                promoted.append(int(s))
                break
    order = list(dict.fromkeys(promoted + list(range(len(ids)))))
    ranks = np.empty(len(ids), dtype="<u4")
    ranks[order] = np.arange(len(ids), dtype="<u4")
    return ranks


def _slice(info, values, row, columns):
    record = info[row]
    if len(record) != columns or any(int(v) != v or v < 0 for v in record):
        raise FimUnsupportedError("invalid stored range")
    start, count = map(int, record[:2])
    if start + count > len(values):
        raise FimUnsupportedError("stored range exceeds values")
    return values[start:start+count]


def canonical_arrays(data):
    attrs = data["Attributes"]
    n = len(attrs)
    points = np.asarray(data["TIN Points"], dtype="<f8")
    triangles = np.asarray(data["TIN Triangles"])
    info, ids = np.asarray(data["TIN Info"]), np.asarray(data["XSIDs"])
    if (points.ndim != 2 or points.shape[1] != 4 or not np.isfinite(points).all()
            or triangles.ndim != 2 or triangles.shape[1] != 3 or
            info.ndim != 2 or info.shape[1] != 4 or ids.shape != (len(info), 2)
            or not len(info) or n < 2 or (ids < 0).any() or (ids >= n).any()):
        raise FimUnsupportedError("invalid global stored TIN or XS identities")
    for a in (triangles, info, ids):
        if not np.equal(a, np.floor(a)).all() or (a > np.iinfo(np.int32).max).any():
            raise FimUnsupportedError("TIN integer range exceeds transport")
    normalized = np.empty(len(points), dtype="<f8")
    covered = np.zeros(len(points), dtype=bool)
    triangle_covered = np.zeros(len(triangles), dtype=bool)
    normalized_receipt = []
    for s, (ps, pc, ts, tc) in enumerate(info):
        ps, pc, ts, tc = map(int, (ps, pc, ts, tc))
        if min(ps, pc, ts, tc) < 0 or not pc or not tc or ps+pc > len(points) or ts+tc > len(triangles):
            raise FimUnsupportedError("invalid or empty TIN surface")
        if triangle_covered[ts:ts+tc].any():
            raise FimUnsupportedError("overlapping TIN triangle ranges")
        triangle_covered[ts:ts+tc] = True
        if covered[ps:ps+pc].any():
            raise FimUnsupportedError("overlapping TIN point ranges")
        p, t = points[ps:ps+pc], triangles[ts:ts+tc]
        if (t < 0).any() or (t >= pc).any():
            raise FimUnsupportedError("triangle local index out of range")
        q = p[t.astype(int), :2]
        area = (q[:, 1, 0]-q[:, 0, 0])*(q[:, 2, 1]-q[:, 0, 1]) - (q[:, 1, 1]-q[:, 0, 1])*(q[:, 2, 0]-q[:, 0, 0])
        if (area == 0).any() or not np.isfinite(area).all():
            raise FimUnsupportedError(f"degenerate TIN triangles in surface {s}; no triangles dropped")
        m, offsets = normalize_segment(p)
        normalized[ps:ps+pc] = m
        covered[ps:ps+pc] = True
        normalized_receipt.append({"surface": s, "offsets": offsets})
    if not triangle_covered.all():
        raise FimUnsupportedError("unowned stored TIN triangles")
    if not covered.all():
        raise FimUnsupportedError("unowned stored TIN points")
    clips = np.full((n, 8), np.nan, dtype="<f4")
    receipts = []
    for k, ar in enumerate(attrs):
        se = _slice(data["Station Elevation Info"], data["Station Elevation Values"], k, 2)
        xy = _slice(data["Polyline Info"], data["Polyline Points"], k, 4)
        pi = data["Polyline Info"][k]
        if pi[2] + pi[3] > len(data["Polyline Parts"]):
            raise FimUnsupportedError("XS part range exceeds stored parts")
        parts = data["Polyline Parts"][int(pi[2]):int(pi[2]+pi[3])]
        if len(se) < 2 or not len(parts) or not np.isfinite(se).all():
            raise FimUnsupportedError("missing XS station profile or polyline")
        length = 0.
        for start, count in parts:
            if start < 0 or count < 2 or start+count > len(xy):
                raise FimUnsupportedError("invalid XS polyline part")
            part = xy[int(start):int(start+count)]
            for a, b in zip(part[:-1], part[1:]):
                length += math.pow(math.pow(float(a[0]-b[0]), 2.)+math.pow(float(a[1]-b[1]), 2.), .5)
        raw_first, raw_last = se[0, 0], se[-1, 0]
        raw_lb, raw_rb = ar["Left Bank"], ar["Right Bank"]
        if not raw_first <= raw_lb < raw_rb <= raw_last or not np.isfinite(length) or length <= 0:
            raise FimUnsupportedError("invalid XS banks/endpoints")
        # The native modern HDF loader translates stationing before building
        # banks/levees or selecting end obstructions. Each addition is Float32;
        # translating only a final ComputeM quotient is not bit-equivalent.
        f = np.float32
        station_offset = f(f(-1) * f(raw_first))
        def zero_station(value):
            value = f(value)
            return f(value + station_offset) if station_offset != 0 else value
        first, last, lb, rb = map(zero_station, (raw_first, raw_last, raw_lb, raw_rb))
        if not np.isfinite([station_offset, first, last, lb, rb]).all():
            raise FimUnsupportedError("XS stationing exceeds native Float32 range")
        def m(sta):
            return station_m(sta, first, last, lb, rb)
        levee_receipts = {}
        for side, offset in (("Left", 0), ("Right", 2)):
            fields = (side+" Levee Sta", side+" Levee Elev")
            if not any(field in attrs.dtype.names for field in fields):
                continue
            if not all(field in attrs.dtype.names for field in fields):
                raise FimUnsupportedError("partial levee fields")
            sta, elev = ar[fields[0]], ar[fields[1]]
            if np.isnan(sta) and np.isnan(elev):
                continue
            if not np.isfinite([sta, elev]).all():
                raise FimUnsupportedError("partial or infinite levee")
            native_sta, native_elev = zero_station(sta), f(elev)
            if not np.isfinite([native_sta, native_elev]).all():
                raise FimUnsupportedError("levee exceeds native Float32 range")
            clips[k, offset:offset+2] = m(native_sta), native_elev
            levee_receipts[side.lower()] = {
                "station": float(sta), "elevation": float(elev),
                "zero_based_station": float(native_sta), "native_elevation": float(native_elev),
                "native_f32_bits": np.asarray([native_sta, native_elev], dtype="<f4").view("<u4").tolist(),
            }
        blocks = []
        selected = [None, None]
        if "Obstruction Info" in data:
            obs = _slice(data["Obstruction Info"], data["Obstruction Blocks"], k, 2)
            for order, block in enumerate(obs):
                raw = [float(block[v]) for v in ("Left Sta", "Right Sta", "Elevation")]
                if not np.isfinite(raw).all():
                    raise FimUnsupportedError("invalid obstruction block")
                # Native Obstruction fields are Float32. The right-end test
                # promotes that rounded station before subtracting the double
                # polyline length; its 0.01 tolerance is also double precision.
                l, r = [float(zero_station(value)) for value in raw[:2]]
                e = float(f(raw[2]))
                if not np.isfinite([l, r, e]).all():
                    raise FimUnsupportedError("obstruction exceeds native Float32 range")
                blocks.append({"order": order, "left": raw[0], "right": raw[1], "elevation": raw[2],
                               "reversed_interval": raw[0] > raw[1],
                               "native_left": l, "native_right": r, "native_elevation": e,
                               "native_f32_bits": np.asarray([l, r, e], dtype="<f4").view("<u4").tolist()})
                if selected[0] is None and abs(l) < .01:
                    selected[0] = order
                    clips[k, 4:6] = m(r), e
                elif selected[1] is None and abs(r-length) < .01:
                    selected[1] = order
                    clips[k, 6:8] = m(l), e
                else:
                    blocks[-1]["selection"] = "ignored by 7.0.1 endpoint-only selector"
        identity = {name: (ar[name].decode().rstrip("\0 ") if isinstance(ar[name], bytes) else str(ar[name]))
                    for name in ("River", "Reach", "RS") if name in attrs.dtype.names}
        receipts.append({"xs": k, "identity": identity, "first_station": float(raw_first), "last_station": float(raw_last),
                         "polyline_length": length, "banks": [float(raw_lb), float(raw_rb)],
                         "native_stationing": {
                             "offset": float(station_offset),
                             "offset_f32_bits": int(np.asarray(station_offset, dtype="<f4").view("<u4")),
                             "first_station": float(first), "last_station": float(last),
                             "banks": [float(lb), float(rb)],
                             "stored_f32_bits": np.asarray([raw_first, raw_last, raw_lb, raw_rb], dtype="<f4").view("<u4").tolist(),
                             "zero_based_f32_bits": np.asarray([first, last, lb, rb], dtype="<f4").view("<u4").tolist(),
                         }, "levees": levee_receipts,
                         "ordered_blocks": blocks, "selected_left": selected[0], "selected_right": selected[1],
                         "clip_values": [float(v) if np.isfinite(v) else None for v in clips[k]],
                         "clip_f32_bits": clips[k].view("<u4").tolist()})
    rivers = [v.decode().rstrip("\0 ") if isinstance(v, bytes) else str(v) for v in attrs["River"]]
    return {"points": points, "triangles": triangles.astype("<i4"), "tin_info": info.astype("<i4"),
            "xs_ids": ids.astype("<i4"), "render_order": render_ranks(ids.astype(int), rivers),
            "normalized_m": normalized, "xs_clip": clips}, receipts, normalized_receipt


@dataclass(frozen=True)
class FimPreparedOneDModel:
    """Receipt-bound staged global geometry; use with map_one_d_profiles.

    Source and payload hashes are rechecked before each mapping call.
    """
    folder: Path
    _receipt_sha256: str = field(init=False, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "folder", Path(self.folder).resolve(strict=True))
        object.__setattr__(self, "_receipt_sha256", digest(self.folder / "one_d_preparation.json"))

    @property
    def receipt(self):
        path = self.folder / "one_d_preparation.json"
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != self._receipt_sha256:
            raise FimUnsupportedError("prepared 1D receipt changed")
        return json.loads(payload)

    @log_call
    def validate(self):
        from pyproj.exceptions import CRSError
        receipt = self.receipt
        if (receipt.get("schema") != "ras-commander-one-d-preparation/1"
                or receipt.get("method_id") != METHOD_ID
                or receipt.get("request_schema") != REQUEST_SCHEMA):
            raise FimUnsupportedError("invalid prepared 1D receipt identity")
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
            storage = receipt.get("storage")
            if storage is not None:
                count = storage["count"]
                if (isinstance(count, bool) or not isinstance(count, int) or count <= 0
                        or len(storage["names"]) != count or len(set(storage["names"])) != count
                        or len(storage["levels"]) != len(levels)
                        or storage["method_id"] != "storage-area-level-pool/1"
                        or storage["request_schema"] != "fast-map-storage/1"):
                    raise ValueError("storage receipt identity/cardinality")
                required.extend([storage["polygons"], *storage["levels"]])
                if any(Path(path).stat().st_size != count*4 for path in storage["levels"]):
                    raise ValueError("storage profile byte count")
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
            # Reconstructing a prepared instance binds its current receipt, so
            # validate grid and datum labels against the hashed source files as
            # well. A changed receipt cannot relabel unchanged raster bytes.
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
            with rasterio.open(receipt["terrain"]) as terrain:
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
            raise FimUnsupportedError(f"invalid or changed prepared 1D inputs: {exc}") from exc
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
        return map_one_d_profiles(
            self, None, output_folder, profiles=profiles,
            allow_unqualified=allow_unqualified, bbox=bbox, polygon=polygon,
            polygon_layer=polygon_layer, aoi_crs=aoi_crs, engine_path=engine_path,
            threads=threads, max_working_mib=max_working_mib, timeout=timeout,
            raise_on_failure=raise_on_failure)


def prepare_one_d_model(hdf_path, terrain_path, output_folder, *, profiles=None,
                        allow_unqualified=False, max_working_mib=1024):
    import rasterio
    from pyproj import CRS
    from pyproj.exceptions import CRSError
    from ..hdf.HdfBase import HdfBase
    from ..hdf.HdfXsec import HdfXsec
    from .RasFim import _positive_int, _prepare_output_folder

    if not isinstance(allow_unqualified, bool):
        raise ValueError("allow_unqualified must be a boolean")
    if not allow_unqualified:
        raise FimUnsupportedError("canonical 1D is unqualified; diagnostic use requires allow_unqualified=True")
    profile_ids, profiles = _profile_selection(profiles)
    budget = _positive_int(max_working_mib, "max_working_mib") * 1024**2
    hdf, terrain = Path(hdf_path).resolve(strict=True), Path(terrain_path).resolve(strict=True)
    before = {str(p): digest(p) for p in (hdf, terrain)}
    folder = None
    output_existed = Path(output_folder).exists()
    created_paths = []
    try:
        try:
            data = HdfXsec.get_one_d_mapping_inputs(hdf, profiles=profiles, max_bytes=budget//4)
        except (ValueError, KeyError) as exc:
            raise FimUnsupportedError(f"stored 1D inputs cannot be staged: {exc}") from exc
        if data["unsupported_features"]:
            raise FimUnsupportedError("unsupported 1D features: " + repr(data["unsupported_features"]))
        from . import _storage_areas
        storage = _storage_areas.read(hdf, max_bytes=budget//4,
                                     geometry_policy=_storage_areas.NATIVE_EVEN_ODD)
        storage_values = (_storage_areas.profile_values(hdf, storage, dict(zip(profile_ids, profiles)),
                                                      max_bytes=budget//4) if storage else {})
        arrays, xs_receipts, offsets = canonical_arrays(data)
        try:
            crs = CRS.from_user_input(HdfBase.get_projection(hdf))
        except CRSError as exc:
            raise FimUnsupportedError("model has no valid projected CRS") from exc
        if not crs.is_projected or any(abs(a.unit_conversion_factor-1200/3937) > 1e-12 for a in crs.axis_info[:2]):
            raise FimUnsupportedError("1D requires a projected CRS in US survey feet; explicit conversion required")
        with rasterio.open(terrain) as src:
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
        if storage:
            storage_file = folder / "storage_areas.wkb"
            created_paths.append(storage_file)
            _storage_areas.stage_polygons(storage, folder)
            pool_levels = []
            for i, name in enumerate(profile_ids):
                path = folder / f"storage-profile-{i:04d}.f32"
                created_paths.append(path)
                storage_values[name].tofile(path)
                pool_levels.append(str(path))
            storage_receipt = {"names": list(storage.names), "count": len(storage),
                               "polygons": str(storage_file), "levels": pool_levels,
                               "method_id": _storage_areas.METHOD_ID, "request_schema": "fast-map-storage/1",
                               "geometry": _storage_areas.geometry_metadata(storage)}
        # Per-point raw/normalized evidence preserves Float64 bits including unchanged points.
        evidence = np.column_stack((arrays["points"][:, 3], arrays["normalized_m"]))
        evidence_path = folder / "point-m-evidence.f64"
        created_paths.append(evidence_path)
        evidence.astype("<f8").tofile(evidence_path)
        receipt = {"schema": "ras-commander-one-d-preparation/1", "qualified": False,
                   "method_id": METHOD_ID, "request_schema": REQUEST_SCHEMA,
                   "semantics_reference": "7.0.1 preparation; 6.6 normalization/endpoint selection source-verified; full-corpus parity unqualified",
                   "scope": "stored XS TIN, levees, XS end obstructions and disjoint storage level pools",
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
        receipt_path = folder / "one_d_preparation.json"
        created_paths.extend((receipt_path, receipt_path.with_name(receipt_path.name + ".partial")))
        write_json(receipt_path, receipt)
        if any(digest(p) != sha for p, sha in before.items()):
            raise FimUnsupportedError("1D input changed during preparation")
        return FimPreparedOneDModel(folder)
    except BaseException as exc:
        # Only remove files owned by this attempt, never pre-existing data or
        # concurrent files another caller may have added to the destination.
        import logging
        for path in reversed(created_paths):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logging.getLogger(__name__).warning("Cannot clean failed 1D preparation file %s", path, exc_info=True)
        if folder is not None and not output_existed:
            try:
                folder.rmdir()
            except OSError:
                logging.getLogger(__name__).warning("Cannot remove failed 1D preparation folder %s", folder, exc_info=True)
        if isinstance(exc, CRSError):
            raise FimUnsupportedError("model or terrain has an invalid CRS") from exc
        raise


def map_one_d_profiles(hdf_path, terrain_path, output_folder, *, profiles=None,
                       allow_unqualified=False, bbox=None, polygon=None, aoi_crs=None,
                       polygon_layer=None, engine_path=None, threads=1,
                       max_working_mib=1024, timeout=None, raise_on_failure=True):
    """Render globally prepared XS surfaces through Rust, returning a manifest.

    A prepared model may replace hdf_path; terrain_path must then be None.
    AOIs restrict output only. All global geometry and original tile origins
    remain intact. The diagnostic transport is sequential (threads is an upper
    budget, not a promise of parallelism).
    """
    import tempfile
    import pandas as pd
    import rasterio
    from affine import Affine
    from rasterio.windows import Window
    from . import _aoi, _engine, _products
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
        raise FimUnsupportedError("canonical 1D is unqualified; pass allow_unqualified=True for diagnostics")
    engine = _engine.find_engine(engine_path)
    capabilities = RasFim.get_capabilities(engine)
    support = capabilities.methods.get("one_d_clipped_diagnostic")
    if (support is None or support.method_id != METHOD_ID or
            support.request_schemas and REQUEST_SCHEMA not in support.request_schemas):
        raise FimUnsupportedError("engine lacks the clipped 1D /5 request contract")
    def plain(value):
        if isinstance(value, Mapping):
            return {key: plain(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [plain(item) for item in value]
        return value
    engine_identity = plain(capabilities.raw_record.get("engine", {}))
    engine_hash = digest(engine)
    with tempfile.TemporaryDirectory(prefix="fim-one-d-") as scratch_name:
        scratch = Path(scratch_name)
        if isinstance(hdf_path, FimPreparedOneDModel):
            if terrain_path is not None:
                raise ValueError("prepared models already bind terrain")
            prepared = hdf_path
        else:
            prepared = prepare_one_d_model(hdf_path, terrain_path, scratch / "prepared",
                                           profiles=profiles, allow_unqualified=True,
                                           max_working_mib=max_working_mib)
        receipt = prepared.validate()
        names = receipt.get("profile_ids", [f"profile_{i:04d}" for i in range(len(receipt["profiles"]))])
        if isinstance(hdf_path, FimPreparedOneDModel) and profiles is not None:
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
        storage = receipt.get("storage")
        final_support = support
        final_method_id, final_schema = METHOD_ID, REQUEST_SCHEMA
        component_contracts = {"xs": {"method_id": METHOD_ID, "request_schema": REQUEST_SCHEMA}}
        if storage:
            pool_support = capabilities.methods.get("storage")
            coupled = capabilities.methods.get("coupled_storage_diagnostic")
            if (pool_support is None or pool_support.method_id != STORAGE_METHOD_ID or
                    STORAGE_SCHEMA not in pool_support.request_schemas):
                raise FimUnsupportedError("engine lacks storage-only transport fast-map-storage/1")
            if (coupled is None or coupled.method_id != COMPOSITION_METHOD_ID or
                    COMPOSITION_SCHEMA not in coupled.request_schemas):
                raise FimUnsupportedError("engine lacks coupled storage composition /2")
            final_support = coupled
            final_method_id, final_schema = COMPOSITION_METHOD_ID, COMPOSITION_SCHEMA
            component_contracts["storage"] = {"method_id": STORAGE_METHOD_ID, "request_schema": STORAGE_SCHEMA}
        grid = receipt["grid"]
        transform = Affine.from_gdal(*grid["geo_transform"])
        constraint = _aoi.resolve_aoi(bbox=bbox, polygon=polygon, aoi_crs=aoi_crs,
                                      polygon_layer=polygon_layer, default_crs=grid["crs"])
        if constraint is None:
            window = Window(0, 0, grid["width"], grid["height"])
            mask = None
        else:
            selected = _aoi.aoi_window(constraint, transform, grid["width"], grid["height"], grid["crs"])
            if selected.is_empty:
                raise FimUnsupportedError("AOI contains no source-grid pixels")
            window = Window(*selected.window)
            mask = selected.mask
        pixels = int(window.width * window.height)
        pool_overhead = (Path(storage["polygons"]).stat().st_size * 32 + storage["count"] * 4096 + 1024**2) if storage else 0
        if (pixels * (160 if storage else 32) + pool_overhead +
                receipt["point_count"] * 128 + receipt["triangle_count"] * 256 > budget):
            raise FimUnsupportedError("planned 1D delivery/geometry exceeds max_working_mib")
        with rasterio.open(receipt["terrain"]) as source:
            terrain = source.read(1, window=window, masked=True).astype("<f4").filled(np.nan)
        terrain_file = scratch / "terrain.bin"
        terrain.tofile(terrain_file)
        inputs = {path: {"path": path, "size": Path(path).stat().st_size, "sha256": sha}
                  for path, sha in receipt["sha256"].items()}
        aoi_description = constraint.describe() if constraint else None
        if aoi_description is not None:
            aoi_description["geometry_wkb_hex"] = constraint.geometry.wkb_hex
        details = {
            "aoi": aoi_description,
            "aoi_mask": ("rasterio-center-mask/1" if mask is not None else
                         "pixel-center-bounds/1") if constraint else None,
            "options": {"profiles": selected_profiles, "allow_unqualified": allow_unqualified,
                        "threads": threads, "max_working_mib": budget // (1024**2),
                        "timeout": None if timeout is None else float(timeout)},
            "engine_path": str(engine), "inputs": inputs,
            "engine": engine_identity, "method_record": plain(final_support.flags),
            "component_contracts": component_contracts,
        }
        folder = _prepare_output_folder(output_folder)
        rows, reports = [], []
        staged_products = []
        published_products = []
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
                                threads_requested=threads, threads_effective=min(threads, 4) if storage else 1, engine_sha256=engine_hash)
            return result

        def persist(status, error=None):
            RasFim._write_manifest(folder, manifest_frame(), {
                       "method": final_method_id, "method_id": final_method_id,
                       "request_schema": final_schema, **details,
                       "qualified": False,
                       "preparation": receipt, "engine_sha256": engine_hash, "reports": reports,
                       "status": status, "error": error,
                       "threads_requested": threads, "threads_effective": min(threads, 4) if storage else 1})

        def verify_inputs():
            prepared.validate()
            if digest(engine) != engine_hash:
                raise FimEngineError("engine changed during mapping")

        try:
            persist("in_progress")
            for i, (profile, levels) in enumerate(zip(selected_names, selected_levels)):
                request = {"schema": REQUEST_SCHEMA, "scope": "xs-surface-only",
                           "point_count": receipt["point_count"], "triangle_count": receipt["triangle_count"],
                           "segment_count": receipt["segment_count"], "cross_section_count": receipt["cross_section_count"],
                           "levels_file": levels, "terrain_file": str(terrain_file),
                           "width": grid["width"], "height": grid["height"],
                           "geo_transform": grid["geo_transform"], "tile_size": grid["tile_size"],
                           "window": dict(zip(("col", "row", "width", "height"), map(int, (window.col_off, window.row_off, window.width, window.height)))),
                           "max_working_bytes": budget, "clipping_scope": "levees-and-xs-end-obstructions-only"}
                request.update({name + "_file": path for name, path in receipt["files"].items()})
                request_file = scratch / f"request-{i}.json"
                write_json(request_file, request)
                out = scratch / f"engine-{i}"
                proc = _engine.run_engine([str(engine), "one-d-diagnostic", str(request_file), str(out)], "1D mapping", timeout)
                if proc.returncode != 0:
                    raise _engine.read_refusal(out, proc.stderr) or FimEngineError(proc.stderr[-4000:])
                report = json.loads((out / "report.json").read_text())
                if report.get("status") != "complete" or report.get("method", {}).get("method_id") != METHOD_ID:
                    raise FimEngineError("incomplete or mismatched 1D engine report")
                reports.append(report)
                if storage:
                    pool_out = scratch / f"storage-{i}"
                    pool_request = {"schema": "fast-map-storage/1", "storage_areas_file": storage["polygons"],
                                    "storage_area_count": storage["count"],
                                    "levels_file": storage["levels"][positions[i]],
                                    "terrain_file": str(terrain_file), "width": int(window.width),
                                    "height": int(window.height),
                                    "geo_transform": list(rasterio.windows.transform(window, transform).to_gdal()),
                                    "max_working_bytes": budget, "threads": min(threads, 4)}
                    pool_file = scratch / f"storage-request-{i}.json"
                    write_json(pool_file, pool_request)
                    proc = _engine.run_engine([str(engine), "storage", str(pool_file), str(pool_out)], "storage mapping", timeout)
                    if proc.returncode:
                        raise _engine.read_refusal(pool_out, proc.stderr) or FimEngineError(proc.stderr[-4000:])
                    pool_report = json.loads((pool_out / "report.json").read_text())
                    if pool_report.get("status") != "complete" or pool_report.get("method", {}).get("method_id") != "storage-area-level-pool/1":
                        raise FimEngineError("incomplete or mismatched storage report")
                    reports.append(pool_report)
                    # Empty 2D component is explicitly supported by coupled schema /2.
                    # These are transport placeholders, never fabricated cells.
                    zero = scratch / "zero-owners.u32"
                    dry = scratch / "dry.f32"
                    if not zero.exists():
                        np.zeros(pixels, dtype="<u4").tofile(zero)
                        np.full(pixels, np.nan, dtype="<f4").tofile(dry)
                    def component(depth, wse):
                        return {"profile_id": profile, "crs": grid["crs"], "width": int(window.width),
                                "height": int(window.height), "geo_transform": pool_request["geo_transform"],
                                "depth_file": str(depth), "wse_file": str(wse)}
                    composition = {"schema": "fast-map-coupled-diagnostic/2",
                                   "xs": component(out / "depth.bin", out / "wse.bin"),
                                   "two_d": component(dry, dry), "two_d_owners_file": str(zero),
                                   "two_d_cell_count": 0,
                                   "storage": {"component": component(pool_out / "depth.bin", pool_out / "wse.bin"),
                                               "owners_file": str(pool_out / "owners.bin"), "area_count": storage["count"]},
                                   "max_working_bytes": budget}
                    composed = scratch / f"composed-{i}"
                    composition_file = scratch / f"composition-{i}.json"
                    write_json(composition_file, composition)
                    proc = _engine.run_engine([str(engine), "coupled-diagnostic", str(composition_file), str(composed)], "XS/storage composition", timeout)
                    if proc.returncode:
                        raise _engine.read_refusal(composed, proc.stderr) or FimEngineError(proc.stderr[-4000:])
                    composition_report = json.loads((composed / "report.json").read_text())
                    if (composition_report.get("status") != "complete" or
                            composition_report.get("schema") != COMPOSITION_SCHEMA or
                            composition_report.get("method", {}).get("method_id") != COMPOSITION_METHOD_ID or
                            composition_report.get("profile_id") != profile or
                            composition_report.get("crs") != grid["crs"] or
                            composition_report.get("width") != int(window.width) or
                            composition_report.get("height") != int(window.height) or
                            composition_report.get("geo_transform") != pool_request["geo_transform"]):
                        raise FimEngineError("incomplete or mismatched composition report")
                    reports.append(composition_report)
                    out = composed
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
                    row[product + "_tif"] = str(path)
            # No products are acknowledged until the complete batch and the
            # original source/payload/engine identities have been checked.
            verify_inputs()
            for partial, path in staged_products:
                published_products.append(path)
                partial.replace(path)
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
