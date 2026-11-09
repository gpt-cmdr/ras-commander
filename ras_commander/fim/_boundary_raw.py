"""Bounded raw boundary evidence, without geometry repair or GEOS operations.

Raw ring identity is independent of topology validity. These helpers return
diagnostic dictionaries, never ordinary mapping/comparison product rows.
"""

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import uuid

from .errors import FimUnsupportedError

_CHUNK = 65536
_FIXED = 4 << 20


def validate_options(preserve_raw_geometry=False, *, method, allow_unqualified,
                     bbox=None, polygon=None, polygon_layer=None, aoi_crs=None):
    """Validate the explicit opt-in before engine/native execution."""
    if not isinstance(preserve_raw_geometry, bool):
        raise TypeError("preserve_raw_geometry must be a boolean")
    if not preserve_raw_geometry:
        return False
    if method != "native_serial" or allow_unqualified is not True:
        raise FimUnsupportedError(
            "raw boundary diagnostics require native_serial and allow_unqualified=True")
    if any(value is not None for value in (bbox, polygon, polygon_layer, aoi_crs)):
        raise FimUnsupportedError("raw boundary diagnostics require full extent without AOI options")
    return True


def _budget(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("max_working_bytes must be a positive integer")
    return value


def _regular(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise ValueError("Symlink/junction raw geometry paths are unsupported")
        stat = item.lstat()
        if getattr(stat, "st_file_attributes", 0) & 0x400:
            raise ValueError("Reparse-point raw geometry paths are unsupported")
    if not path.is_file():
        raise ValueError("Raw geometry requires regular files")
    return path.resolve(strict=True)


def _identity(path):
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(_CHUNK), b""):
            digest.update(block)
    return dict(size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                device=stat.st_dev, inode=stat.st_ino, sha256=digest.hexdigest())


def _same_sources(infos):
    for info in infos:
        for path, identity in info["identities"].items():
            if _identity(_regular(path)) != identity:
                raise ValueError("Raw geometry source changed during diagnostics")


def _check(callback):
    if callback is not None:
        if callback() is False:
            raise ValueError("Raw diagnostic source immutability check refused")


def _read_exact(stream, size):
    value = stream.read(size)
    if len(value) != size:
        raise ValueError("Truncated raw shapefile")
    return value


def _shp_header(stream, size):
    header = _read_exact(stream, 100)
    if (struct.unpack_from(">i", header)[0] != 9994
            or struct.unpack_from(">i", header, 24)[0] * 2 != size
            or struct.unpack_from("<ii", header, 28) != (1000, 5)):
        raise ValueError("Raw diagnostics require an intact XY Polygon shapefile")
    bounds = struct.unpack_from("<4d", header, 36)
    if (not all(math.isfinite(v) for v in bounds)
            or bounds[0] > bounds[2] or bounds[1] > bounds[3]):
        raise ValueError("Invalid raw shapefile bounds")
    return header, bounds


def _shp_counts(path):
    # Reuse the shared count/header gate, then check SHX/DBF/part structure too.
    from ._boundary_comparison import _shp_size_counts

    vertices, features = _shp_size_counts(path)
    parts_total = maximum = 0
    with path.open("rb") as stream, path.with_suffix(".shx").open("rb") as index:
        header, bounds = _shp_header(stream, path.stat().st_size)
        index_header, _ = _shp_header(index, path.with_suffix(".shx").stat().st_size)
        if index_header[28:68] != header[28:68] or path.with_suffix(".shx").stat().st_size != 100 + features * 8:
            raise ValueError("Shapefile index header/count differs")
        record = 0
        while stream.tell() < path.stat().st_size:
            offset = stream.tell()
            number, words = struct.unpack(">ii", _read_exact(stream, 8))
            record += 1
            if number != record or struct.unpack(">ii", _read_exact(index, 8)) != (offset // 2, words):
                raise ValueError("Shapefile record/index offsets differ")
            start = stream.tell()
            prefix = _read_exact(stream, 44)
            parts, points = struct.unpack_from("<ii", prefix, 36)
            previous = None
            for _ in range(parts):
                current = struct.unpack("<i", _read_exact(stream, 4))[0]
                if (current < 0 or current >= points
                        or (previous is None and current != 0)
                        or (previous is not None and current - previous < 4)):
                    raise ValueError("Invalid shapefile part offsets or short ring")
                if previous is not None:
                    maximum = max(maximum, current - previous)
                previous = current
            if previous is None or points - previous < 4:
                raise ValueError("Invalid shapefile final part")
            maximum = max(maximum, points - previous)
            parts_total += parts
            stream.seek(start + words * 2)
        if record != features:
            raise ValueError("Shapefile record count changed")
    dbf = path.with_suffix(".dbf")
    with dbf.open("rb") as stream:
        head = _read_exact(stream, 32)
        count = struct.unpack_from("<I", head, 4)[0]
        header_bytes, row_bytes = struct.unpack_from("<HH", head, 8)
        expected = header_bytes + count * row_bytes
        if (count != features or header_bytes < 33 or row_bytes < 1
                or dbf.stat().st_size not in (expected, expected + 1)):
            raise ValueError("Truncated or inconsistent shapefile DBF")
        stream.seek(header_bytes - 1)
        if _read_exact(stream, 1) != b"\r":
            raise ValueError("Invalid DBF field terminator")
        if dbf.stat().st_size == expected + 1:
            stream.seek(expected)
            if _read_exact(stream, 1) != b"\x1a":
                raise ValueError("Invalid DBF trailing data")
    return dict(vertices=vertices, features=features, rings=parts_total,
                max_ring=maximum, bounds=bounds)


def _headers(path, budget):
    from ._boundary_comparison import _files, _geojson_size_counts

    path = _regular(path)
    kind = path.suffix.lower()
    if kind not in (".shp", ".json", ".geojson"):
        raise ValueError("Raw boundary diagnostics support SHP and GeoJSON only")
    files = [_regular(p) for p in _files(path)]
    file_bytes = sum(p.stat().st_size for p in files)
    if file_bytes > budget:
        raise ValueError("Raw geometry files exceed planned working budget")
    identities = {str(p): _identity(p) for p in files}
    if kind == ".shp":
        counts = _shp_counts(path)
        counts["crs_bytes"] = path.with_suffix(".prj").stat().st_size
        if counts["crs_bytes"] > 1024 * 1024:
            raise ValueError("Raw CRS definition exceeds bounded header allowance")
    else:
        # The shared scanner retains at most one 1 MiB string token. Include
        # its character-list/decoded-string scratch before entering that pass.
        if _FIXED + 96 * min(file_bytes, 1024 * 1024) > budget:
            raise ValueError("Raw geometry lexical preflight exceeds planned working budget")
        vertices, features = _geojson_size_counts(path)
        # Conservative pre-parse bounds. Structural checks tighten these later.
        counts = dict(vertices=vertices, features=features,
                      rings=vertices // 4, max_ring=vertices,
                      json_nodes=_json_node_counts(path))
    info = dict(path=path, kind=kind, files=files, file_bytes=file_bytes,
                identities=identities, **counts)
    _same_sources([info])
    return info


def _admit(infos, budget):
    # Both JSON parse trees, exact canonical byte keys, dictionary/signature
    # indexes and the largest simultaneous ring buffers are planned BEFORE load.
    ring_scratch = max((i["max_ring"] for i in infos), default=0) * 128
    lexical_scratch = max((96 * min(i["file_bytes"], 1024 * 1024)
                           for i in infos if i["kind"] != ".shp"), default=0)
    estimate = _FIXED + max(ring_scratch, lexical_scratch)
    for info in infos:
        estimate += info["vertices"] * 64 + info["rings"] * 512
        if info["kind"] != ".shp":
            nodes = info["json_nodes"]
            estimate += (info["file_bytes"] * 16 + nodes["objects"] * 512
                         + nodes["arrays"] * 96 + nodes["strings"] * 256
                         + nodes["scalars"] * 64)
        else:
            estimate += info["crs_bytes"] * 16
    if estimate > budget:
        raise ValueError(f"Raw geometry pair/parsing budget exceeded ({estimate} > {budget} bytes)")
    return estimate


def _json_node_counts(path):
    """Count parse-tree constructors without retaining JSON values.

    The shared lexical pass already checked syntax, depth, finite values and
    string bounds. Counting non-coordinate metadata prevents a small vertex
    count from hiding a large properties parse tree.
    """
    counts = dict(objects=0, arrays=0, strings=0, scalars=0)
    quoted = escaped = scalar = False
    with path.open(encoding="utf-8") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK), ""):
            for char in chunk:
                if quoted:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        quoted = False
                elif char == '"':
                    quoted, scalar = True, False
                    counts["strings"] += 1
                elif char in "{}[],:" or char.isspace():
                    scalar = False
                    if char == "{":
                        counts["objects"] += 1
                    elif char == "[":
                        counts["arrays"] += 1
                elif not scalar:
                    counts["scalars"] += 1
                    scalar = True
    return counts


def _read_json(path, max_bytes, expected_sha256):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate raw GeoJSON object key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError(f"Nonfinite raw GeoJSON constant: {value}")

    # parse_int=float intentionally preserves the sign bit of JSON '-0'.
    with _regular(path).open("rb") as stream:
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Raw GeoJSON grew beyond admitted file bytes")
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("Raw GeoJSON source changed before parsing")
    return json.loads(data, parse_int=float, parse_float=float,
                      parse_constant=nonfinite, object_pairs_hook=unique)


def _prepare(info, model_crs):
    from ._source_crs import source_crs

    info = dict(info)
    if info["kind"] == ".shp":
        with _regular(info["path"].with_suffix(".prj")).open("rb") as stream:
            definition = stream.read(info["crs_bytes"] + 1)
        if len(definition) > info["crs_bytes"]:
            raise ValueError("Raw CRS grew beyond admitted header bytes")
        crs = definition.decode("utf-8")
    else:
        data = _read_json(info["path"], info["file_bytes"],
                          info["identities"][str(info["path"])]["sha256"])
        if (not isinstance(data, dict) or data.get("type") != "FeatureCollection"
                or not isinstance(data.get("features"), list)
                or len(data["features"]) != info["features"]):
            raise ValueError("Raw GeoJSON requires a polygon FeatureCollection")
        crs_record = data.get("crs")
        if not isinstance(crs_record, dict) or not isinstance(crs_record.get("properties"), dict):
            raise ValueError("Raw GeoJSON requires an explicit stored CRS")
        crs = crs_record["properties"].get("name")
        info["data"] = data
    if not isinstance(crs, str) or not crs or not source_crs(crs).equals(source_crs(model_crs)):
        raise ValueError("Raw boundary CRS differs from model CRS; reprojection is forbidden")
    info["actual_crs"] = crs
    return info


def _closed_finite(buffer, bounds=None):
    if len(buffer) < 64 or len(buffer) % 16:
        raise ValueError("Raw ring requires at least four stored XY positions")
    first = last = None
    for xy in struct.iter_unpack("<dd", buffer):
        if not all(math.isfinite(v) for v in xy):
            raise ValueError("Raw ring coordinates must be finite XY")
        if bounds is not None and not (bounds[0] <= xy[0] <= bounds[2]
                                       and bounds[1] <= xy[1] <= bounds[3]):
            raise ValueError("Raw point lies outside shapefile record bounds")
        if first is None:
            first = xy
        last = xy
    if first != last:
        raise ValueError("Raw ring is not closed")


def _shp_rings(info):
    path = info["path"]
    with path.open("rb") as stream, path.open("rb") as offsets:
        stream.seek(100)
        while stream.tell() < path.stat().st_size:
            _, words = struct.unpack(">ii", _read_exact(stream, 8))
            start = stream.tell()
            prefix = _read_exact(stream, 44)
            bounds = struct.unpack_from("<4d", prefix, 4)
            if (not all(math.isfinite(v) for v in bounds)
                    or bounds[0] > bounds[2] or bounds[1] > bounds[3]
                    or bounds[0] < info["bounds"][0] or bounds[1] < info["bounds"][1]
                    or bounds[2] > info["bounds"][2] or bounds[3] > info["bounds"][3]):
                raise ValueError("Invalid shapefile record bounds")
            parts, points = struct.unpack_from("<ii", prefix, 36)
            if (struct.unpack_from("<i", prefix)[0] != 5 or parts < 1
                    or parts > info["rings"] or points > info["vertices"]
                    or points < parts * 4 or words * 2 != 44 + parts * 4 + points * 16
                    or start + words * 2 > info["identities"][str(path)]["size"]):
                raise ValueError("Shapefile record changed beyond admitted counts")
            offsets.seek(start + 44)
            previous = struct.unpack("<i", _read_exact(offsets, 4))[0]
            if previous != 0:
                raise ValueError("Invalid shapefile initial part offset")
            stream.seek(start + 44 + 4 * parts)
            for part in range(parts):
                end = struct.unpack("<i", _read_exact(offsets, 4))[0] if part + 1 < parts else points
                count = end - previous
                if not 4 <= count <= info["max_ring"] or end > points:
                    raise ValueError("Raw ring exceeds preflight counts")
                buffer = bytearray(count * 16)
                view = memoryview(buffer)
                read = 0
                while read < len(buffer):
                    size = stream.readinto(view[read:])
                    if not size:
                        raise ValueError("Truncated raw shapefile points")
                    read += size
                _closed_finite(buffer, bounds)
                yield buffer
                previous = end
            if stream.tell() != start + words * 2:
                raise ValueError("Shapefile record changed during raw scan")


def _json_rings(info):
    count = parts = 0
    for feature in info["data"]["features"]:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError("Malformed raw GeoJSON feature")
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or not isinstance(geometry.get("coordinates"), list):
            raise ValueError("Malformed raw GeoJSON geometry")
        if geometry.get("type") == "Polygon":
            polygons = [geometry["coordinates"]]
        elif geometry.get("type") == "MultiPolygon":
            polygons = geometry["coordinates"]
        else:
            raise ValueError("Raw boundary must contain Polygon/MultiPolygon parts")
        for polygon in polygons:
            if not isinstance(polygon, list):
                raise ValueError("Malformed raw GeoJSON polygon")
            for ring in polygon:
                if not isinstance(ring, list) or not 4 <= len(ring) <= info["max_ring"]:
                    raise ValueError("Raw GeoJSON ring is too short or exceeds preflight")
                buffer = bytearray(16 * len(ring))
                for index, xy in enumerate(ring):
                    if (not isinstance(xy, list) or len(xy) != 2
                            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                   or not math.isfinite(v) for v in xy)):
                        raise ValueError("Raw coordinates must be finite XY")
                    struct.pack_into("<dd", buffer, index * 16, *xy)
                _closed_finite(buffer)
                count += len(ring)
                parts += 1
                yield buffer
    if count != info["vertices"] or parts > info["rings"]:
        raise ValueError("Raw GeoJSON coordinate counts differ from preflight")


def _rings(info):
    return _shp_rings(info) if info["kind"] == ".shp" else _json_rings(info)


def _rotation(buffer, count, reverse=False):
    def token(index):
        index %= count
        if reverse:
            index = count - 1 - index
        return struct.unpack_from("<QQ", buffer, index * 16)

    first, second, matched = 0, 1, 0
    while first < count and second < count and matched < count:
        a, b = token(first + matched), token(second + matched)
        if a == b:
            matched += 1
            continue
        if a > b:
            first += matched + 1
            if first <= second:
                first = second + 1
        else:
            second += matched + 1
            if second <= first:
                second = first + 1
        matched = 0
    return min(first, second)


def _canonical_bits(buffer):
    stored = len(buffer) // 16
    exact_closure = buffer[:16] == buffer[-16:]
    count = stored - int(exact_closure)
    forward, backward = _rotation(buffer, count), _rotation(buffer, count, True)
    reverse = False
    for offset in range(count):
        a = struct.unpack_from("<QQ", buffer, ((forward + offset) % count) * 16)
        b = struct.unpack_from("<QQ", buffer, (count - 1 - (backward + offset) % count) * 16)
        if a != b:
            reverse = b < a
            break
    start = backward if reverse else forward
    out = bytearray(9 + count * 16)
    struct.pack_into("<QB", out, 0, stored, exact_closure)
    view = memoryview(buffer)
    for offset in range(count):
        index = (start + offset) % count
        if reverse:
            index = count - 1 - index
        out[9 + offset * 16:25 + offset * 16] = view[index * 16:index * 16 + 16]
    return bytes(out)


def _scan(info, canonical=False):
    signatures = Counter() if canonical else None
    digest = hashlib.sha256()
    vertices = parts = maximum = 0
    for buffer in _rings(info):
        count = len(buffer) // 16
        vertices += count
        parts += 1
        maximum = max(maximum, count)
        digest.update(buffer)
        if canonical:
            signatures[_canonical_bits(buffer)] += 1
    if vertices != info["vertices"]:
        raise ValueError("Raw vector point count changed")
    return dict(vertices=vertices, parts=parts, max_ring_vertices=maximum,
                ordered_point_sha256=digest.hexdigest()), signatures


def _point_chunks(info):
    if info["kind"] == ".shp":
        # Finite/closed validation has already consumed every ring. The ordered
        # comparison streams the original point buffer without a per-ring copy.
        with info["path"].open("rb") as stream:
            stream.seek(100)
            while stream.tell() < info["path"].stat().st_size:
                _, words = struct.unpack(">ii", _read_exact(stream, 8))
                start = stream.tell()
                prefix = _read_exact(stream, 44)
                parts, points = struct.unpack_from("<ii", prefix, 36)
                if (parts < 1 or parts > info["rings"] or points > info["vertices"]
                        or words * 2 != 44 + parts * 4 + points * 16
                        or start + words * 2 > info["identities"][str(info["path"])]["size"]):
                    raise ValueError("Shapefile changed beyond admitted raw point counts")
                stream.seek(start + 44 + parts * 4)
                remaining = points * 16
                while remaining:
                    chunk = _read_exact(stream, min(_CHUNK, remaining))
                    yield chunk
                    remaining -= len(chunk)
        return
    for buffer in _rings(info):
        view = memoryview(buffer)
        for start in range(0, len(buffer), _CHUNK):
            yield view[start:start + _CHUNK]


def _part_chunks(info):
    with info["path"].open("rb") as stream:
        stream.seek(100)
        yield struct.pack("<Q", info["features"])
        while stream.tell() < info["path"].stat().st_size:
            number, words = struct.unpack(">ii", _read_exact(stream, 8))
            start = stream.tell()
            prefix = _read_exact(stream, 44)
            parts, points = struct.unpack_from("<ii", prefix, 36)
            if (parts < 1 or parts > info["rings"] or points > info["vertices"]
                    or words * 2 != 44 + parts * 4 + points * 16
                    or start + words * 2 > info["identities"][str(info["path"])]["size"]):
                raise ValueError("Shapefile changed beyond admitted raw part counts")
            yield struct.pack("<III", number, parts, points)
            remaining = 4 * parts
            while remaining:
                chunk = _read_exact(stream, min(_CHUNK, remaining))
                yield chunk
                remaining -= len(chunk)
            stream.seek(start + words * 2)


def _equal_chunks(left, right):
    a = b = memoryview(b"")
    ai = bi = 0
    while True:
        if ai == len(a):
            a, ai = memoryview(next(left, b"")), 0
        if bi == len(b):
            b, bi = memoryview(next(right, b"")), 0
        if not a or not b:
            return not a and not b
        count = min(len(a) - ai, len(b) - bi)
        if a[ai:ai + count] != b[bi:bi + count]:
            return False
        ai += count
        bi += count


def compare_raw_geometry(candidate, reference, model_crs, max_working_bytes, *, check_sources=None):
    """Compare exact raw buffers/ring multisets, independently of topology.

    Both inputs, JSON parsing, canonical byte keys and ring scratch are admitted
    before loading. Ordered SHP part comparison has its own eligibility flag;
    cross-format ring identity does not infer feature, shell or hole topology.
    """
    budget = _budget(max_working_bytes)
    _check(check_sources)
    infos = [_headers(path, budget) for path in (candidate, reference)]
    estimate = _admit(infos, budget)
    prepared = [_prepare(info, model_crs) for info in infos]
    left, left_bits = _scan(prepared[0], True)
    right, right_bits = _scan(prepared[1], True)
    ordered = _equal_chunks(iter(_point_chunks(prepared[0])), iter(_point_chunks(prepared[1])))
    shp_pair = all(info["kind"] == ".shp" for info in infos)
    parts_equal = (shp_pair and _equal_chunks(iter(_part_chunks(infos[0])),
                                             iter(_part_chunks(infos[1]))))
    _check(check_sources)
    _same_sources(infos)
    for summary, info in zip((left, right), prepared):
        summary.update(path=str(info["path"]), actual_crs=info["actual_crs"],
                       files=[dict(path=path, **identity)
                              for path, identity in info["identities"].items()])
    return dict(schema="ras-commander-raw-boundary-comparison/1", status="diagnostic_only",
                diagnostic_only=True, qualified=False, native_vector_parity=False,
                raw_ordered_part_comparison_eligible=shp_pair,
                raw_part_buffers_equal=bool(parts_equal), raw_point_bits_equal=ordered,
                raw_ring_bits_equal=left_bits == right_bits, candidate=left, reference=right,
                planned_working_bytes=estimate,
                topology_validity=dict(candidate="not_evaluated", reference="not_evaluated"),
                crs_comparison="bound-source-identity/1; no coordinate transformation",
                normalization=["ring_start", "ring_orientation", "part_order",
                               "exact_bit_structural_closure_counted_separately"],
                ring_scope="Exact full canonical byte keys; no winding/hole/feature-topology inference")


def _copy_bounded(original, copy, size):
    remaining = size
    while remaining:
        block = original.read(min(_CHUNK, remaining))
        if not block:
            raise ValueError("Raw source became truncated during retention")
        copy.write(block)
        remaining -= len(block)
    if original.read(1):
        raise ValueError("Raw source grew during bounded retention")


def retain_raw_geometry(path, folder, model_crs, max_working_bytes, *, validity_reason,
                        check_sources=None, topology_valid=None):
    """Retain byte-identical finite closed evidence in a new owned directory.

    A receipt is published last by atomic rename. On any failure/interrupt only
    this invocation's inode/token-verified directory is removed. Existing paths
    are never replaced or adopted. The new directory's parent must already
    exist without symlinks. The caller still raises FimGeometryError rather
    than publishing an ordinary valid-vector product.
    """
    budget = _budget(max_working_bytes)
    if not isinstance(validity_reason, str) or not validity_reason or len(validity_reason) > 65536:
        raise ValueError("validity_reason must be a nonempty bounded string")
    if topology_valid is not None and not isinstance(topology_valid, bool):
        raise TypeError("topology_valid must be bool or None")
    _check(check_sources)
    info = _headers(path, budget)
    estimate = _admit([info], budget)
    prepared = _prepare(info, model_crs)
    counts, _ = _scan(prepared)
    _same_sources([info])
    target = Path(folder).absolute()
    parent = target.parent.resolve(strict=True)
    if target.parent != parent or any(p.is_symlink() for p in (target.parent, *target.parent.parents)):
        raise ValueError("Diagnostic output parent must not contain symlinks")
    token = uuid.uuid4().hex
    target.mkdir(mode=0o700)
    owned = target.stat()
    marker = target / ".owner"
    marker_written = False
    try:
        marker.write_text(token, encoding="ascii")
        marker_written = True
        payloads = target / "artifacts"
        payloads.mkdir()
        artifacts = []
        for source in info["files"]:
            partial = payloads / (source.name + ".partial")
            destination = payloads / source.name
            with source.open("rb") as original, partial.open("xb") as copy:
                _copy_bounded(original, copy, info["identities"][str(source)]["size"])
                copy.flush()
                os.fsync(copy.fileno())
            if _identity(partial)["sha256"] != info["identities"][str(source)]["sha256"]:
                raise ValueError("Raw artifact copy differs from source")
            partial.rename(destination)
            identity = info["identities"][str(source)]
            artifacts.append(dict(path=str(destination), source=str(source),
                                  size=identity["size"], sha256=identity["sha256"],
                                  source_identity=identity, retained_identity=_identity(destination)))
        _check(check_sources)
        _same_sources([info])
        manifest = target / "diagnostic_manifest.json"
        receipt = dict(schema="ras-commander-raw-boundary-artifacts/1", status="aborted",
                       diagnostic_only=True, qualified=False, native_vector_parity=False,
                       diagnostic_manifest=str(manifest), artifacts=artifacts,
                       validity_reason=validity_reason, topology_validity=topology_valid,
                       actual_crs=prepared["actual_crs"], raw_counts=counts,
                       planned_working_bytes=estimate)
        temporary = target / "diagnostic_manifest.json.partial"
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, allow_nan=False)
        temporary.rename(manifest)
        return receipt
    except BaseException as error:
        # Verify explicit absolute destination, directory identity and ownership
        # before any recursive removal. Never remove an existing caller folder.
        try:
            if (target.resolve() == parent / target.name and target.is_dir()
                    and (target.stat().st_dev, target.stat().st_ino) == (owned.st_dev, owned.st_ino)
                    and (not marker_written or marker.read_text(encoding="ascii") == token)):
                shutil.rmtree(target)
        except (OSError, UnicodeError) as cleanup_error:
            if hasattr(error, "add_note"):
                error.add_note(f"Raw diagnostic cleanup could not be completed: {cleanup_error}")
        raise
