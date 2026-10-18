"""Shared consumer-contract helpers: provenance, call recording, decoders.

Used by the installed-wheel acceptance tests and by
``scripts/benchmarks/rust_consumer_contract/benchmark.py``. Nothing here
imports the source checkout's ``ras_commander``; the installed packages are the
system under test.

Environment (all required for native acceptance; absent -> explicit skip):
  RAS_CONSUMER_ACCEPTANCE_RECEIPT  accepted-source-build.json (H: path is fine)
  RAS_CONSUMER_FIXTURES            local fixture copy folder containing
                                   fixture-copy-receipt.json
  RAS_CONSUMER_SOURCE_CHECKOUT     isolated checkout of the accepted commit
  RAS_CONSUMER_REFERENCE_DEPTH     folder of shared reference-depth parquet files
"""
from __future__ import annotations

import contextlib
import functools
import gzip
import hashlib
import inspect
import json
import os
import struct
from collections import Counter
from pathlib import Path

RESULTS = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"


def sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 22), b""):
            digest.update(block)
    return digest.hexdigest()


def env_path(name):
    value = os.environ.get(name)
    return Path(value) if value else None


def load_receipt():
    path = env_path("RAS_CONSUMER_ACCEPTANCE_RECEIPT")
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def native_package():
    import ras_commander_fast_hdf
    return ras_commander_fast_hdf


def native_binary():
    """The actual extension module file, never the package ``__init__.py``."""
    import importlib
    pkg = native_package()
    inner = importlib.import_module("ras_commander_fast_hdf.ras_commander_fast_hdf")
    path = Path(inner.__file__).resolve()
    if path.suffix.lower() not in {".pyd", ".so"}:
        raise AssertionError(f"native origin is not an extension module: {path}")
    siblings = sorted(p.name for p in path.parent.iterdir()
                      if p.suffix.lower() in {".pyd", ".so"} or ".so." in p.name)
    return path, siblings, Path(pkg.__file__).resolve()


class NativeCalls:
    """Count calls into the installed native package without hiding signatures.

    ``ras_commander.fast_hdf`` resolves the extension with
    ``importlib.import_module('ras_commander_fast_hdf')`` at call time, so
    patching the package attributes observes every native entry it makes.
    ``functools.wraps`` keeps ``__wrapped__`` so ``inspect.signature`` (used by
    the adapter to detect optional parameters) still sees the binding signature.
    """

    def __init__(self, names):
        self.names = tuple(names)
        self.counts = Counter()
        self._saved = {}

    def __enter__(self):
        pkg = native_package()
        for name in self.names:
            original = getattr(pkg, name)
            self._saved[name] = original

            def make(fn, key):
                @functools.wraps(fn)
                def wrapper(*args, **kwargs):
                    self.counts[key] += 1
                    return fn(*args, **kwargs)
                return wrapper

            wrapper = make(original, name)
            if str(inspect.signature(wrapper)) != str(inspect.signature(original)):
                raise AssertionError(f"call recorder changed the signature of {name}")
            setattr(pkg, name, wrapper)
        return self

    def __exit__(self, *exc):
        pkg = native_package()
        for name, original in self._saved.items():
            setattr(pkg, name, original)
        return False

    def snapshot(self):
        return {name: self.counts[name] for name in self.names}


@contextlib.contextmanager
def replaced_native(name, replacement):
    pkg = native_package()
    original = getattr(pkg, name)
    setattr(pkg, name, replacement)
    try:
        yield original
    finally:
        setattr(pkg, name, original)


def chunks_touched(shape, chunks, selection):
    """Storage chunks intersected by a basic (start, stop, step) selection."""
    total = 1
    for (start, stop, step), chunk in zip(selection, chunks):
        idx = range(start, stop, step)
        total *= len({i // chunk for i in idx}) if len(idx) else 0
    return total


def process_counters():
    import psutil
    proc = psutil.Process()
    io = proc.io_counters()
    mem = proc.memory_info()
    return {"read_bytes": io.read_bytes, "read_count": io.read_count,
            "rss": mem.rss, "peak_wset": getattr(mem, "peak_wset", None)}


# ---------------------------------------------------------------------------
# Independent PMTiles v3 / MVT decoding (spec-level; no producer code reused).


def _varint(buf, pos):
    result = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if byte < 0x80:
            return result, pos
        shift += 7


def _decompress(data, compression):
    if compression in (0, 1):  # unknown/none
        return data
    if compression == 2:
        return gzip.decompress(data)
    raise ValueError(f"unsupported PMTiles compression {compression}")


def _directory(data):
    pos = 0
    count, pos = _varint(data, pos)
    ids, runs, lengths, offsets = [], [], [], []
    last = 0
    for _ in range(count):
        delta, pos = _varint(data, pos)
        last += delta
        ids.append(last)
    for _ in range(count):
        value, pos = _varint(data, pos)
        runs.append(value)
    for _ in range(count):
        value, pos = _varint(data, pos)
        lengths.append(value)
    for i in range(count):
        value, pos = _varint(data, pos)
        offsets.append(offsets[i - 1] + lengths[i - 1] if value == 0 and i > 0 else value - 1)
    return list(zip(ids, runs, lengths, offsets))


def _zxy(tile_id):
    acc, z = 0, 0
    while True:
        num = 1 << (2 * z)
        if tile_id < acc + num:
            break
        acc += num
        z += 1
    pos, n = tile_id - acc, 1 << z
    x = y = 0
    s = 1
    while s < n:
        rx = 1 & (pos // 2)
        ry = 1 & (pos ^ rx)
        if ry == 0:
            if rx == 1:
                x, y = s - 1 - x, s - 1 - y
            x, y = y, x
        x += s * rx
        y += s * ry
        pos //= 4
        s *= 2
    return z, x, y


def read_pmtiles(path):
    blob = Path(path).read_bytes()
    if blob[:7] != b"PMTiles" or blob[7] != 3:
        raise ValueError("not a PMTiles v3 archive")
    q = struct.unpack_from("<QQQQQQQQQQQ", blob, 8)
    (root_off, root_len, meta_off, meta_len, leaf_off, _leaf_len, data_off, _data_len,
     n_addressed, n_entries, n_contents) = q
    internal, tile_comp, tile_type, min_zoom, max_zoom = blob[97], blob[98], blob[99], blob[100], blob[101]
    metadata = json.loads(_decompress(blob[meta_off:meta_off + meta_len], internal) or b"{}")
    tiles = {}

    def walk(offset, length):
        for tile_id, run, size, off in _directory(_decompress(blob[offset:offset + length], internal)):
            if run == 0:
                walk(leaf_off + off, size)
            else:
                for r in range(run):
                    tiles[_zxy(tile_id + r)] = (data_off + off, size)

    walk(root_off, root_len)
    return {"header": dict(addressed=n_addressed, entries=n_entries, contents=n_contents,
                           tile_compression=tile_comp, tile_type=tile_type,
                           min_zoom=min_zoom, max_zoom=max_zoom),
            "metadata": metadata, "tiles": tiles, "blob": blob}


def _fields(buf):
    pos = 0
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(buf, pos)
        elif wire == 2:
            size, pos = _varint(buf, pos)
            value, pos = buf[pos:pos + size], pos + size
        elif wire == 5:
            value, pos = buf[pos:pos + 4], pos + 4
        elif wire == 1:
            value, pos = buf[pos:pos + 8], pos + 8
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        yield field, wire, value


def _packed(buf):
    out, pos = [], 0
    while pos < len(buf):
        value, pos = _varint(buf, pos)
        out.append(value)
    return out


def _zigzag(v):
    return (v >> 1) ^ -(v & 1)


def _rings(commands):
    rings, ring, x, y, i = [], [], 0, 0, 0
    while i < len(commands):
        cmd, count = commands[i] & 7, commands[i] >> 3
        i += 1
        if cmd == 7:
            if ring:
                rings.append(ring + [ring[0]])
            ring = []
            continue
        for _ in range(count):
            x += _zigzag(commands[i])
            y += _zigzag(commands[i + 1])
            i += 2
            if cmd == 1 and ring:
                rings.append(ring)
                ring = []
            ring.append((x, y))
    return rings


def mvt_polygons(commands):
    """Spec polygon assembly: positive shoelace area (tile y-down) = exterior.

    Returns (polygons, degenerate_rings). Zero-area rings are quantization
    collapses; they are counted, never repaired.
    """
    import shapely
    polygons, current, degenerate = [], None, 0
    for ring in _rings(commands):
        area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:])) / 2
        if area == 0 or len(ring) < 4:
            degenerate += 1
            continue
        if area > 0:
            if current is not None:
                polygons.append(shapely.Polygon(current[0], current[1:]))
            current = [ring]
        elif current is not None:
            current.append(ring)
        else:
            degenerate += 1  # hole before any exterior
    if current is not None:
        polygons.append(shapely.Polygon(current[0], current[1:]))
    return polygons, degenerate


def decode_mvt(data):
    layers = []
    for field, _wire, value in _fields(data):
        if field != 3:
            continue
        layer = {"features": [], "keys": [], "values": [], "extent": 4096}
        for f2, _w2, v2 in _fields(value):
            if f2 == 1:
                layer["name"] = v2.decode()
            elif f2 == 3:
                layer["keys"].append(v2.decode())
            elif f2 == 5:
                layer["extent"] = v2
            elif f2 == 4:
                val = None
                for f3, _w3, v3 in _fields(v2):
                    if f3 == 1:
                        val = v3.decode()
                    elif f3 == 2:
                        val = struct.unpack("<f", v3)[0]
                    elif f3 == 3:
                        val = struct.unpack("<d", v3)[0]
                    elif f3 in (4, 5):
                        val = v3 if f3 == 5 else (v3 - (1 << 64) if v3 >= 1 << 63 else v3)
                    elif f3 == 6:
                        val = _zigzag(v3)
                    elif f3 == 7:
                        val = bool(v3)
                layer["values"].append(val)
            elif f2 == 2:
                feature = {"id": None, "tags": [], "type": None, "geometry": []}
                for f3, _w3, v3 in _fields(v2):
                    if f3 == 1:
                        feature["id"] = v3
                    elif f3 == 2:
                        feature["tags"] = _packed(v3)
                    elif f3 == 3:
                        feature["type"] = v3
                    elif f3 == 4:
                        feature["geometry"] = _packed(v3)
                layer["features"].append(feature)
        layers.append(layer)
    return layers


def tile_payload(archive, zxy):
    offset, size = archive["tiles"][zxy]
    data = archive["blob"][offset:offset + size]
    return _decompress(data, archive["header"]["tile_compression"])


__all__ = [n for n in dir() if not n.startswith("_") and n not in {"annotations"}]
