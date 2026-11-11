"""Content-keyed reuse of the native-path cell-polygon validation.

``_horizontal.prepare_grid(..., read_terrain=False)`` accepts a cell subset
only when every geometry is a valid, non-empty Polygon and no two interiors
share positive area. That answer depends on the ordered polygon coordinates
and ring structure alone, so a passed check is remembered under a SHA-256 of
exactly those values (with the validator schema and Shapely/GEOS versions).
File names, sizes and timestamps are never part of the key, and a changed
geometry, cell subset or grid plan produces a different key.

Only successes are recorded, and only those that hold for every grid plan. A
pass that accepted a positive-area overlap as coordinate-roundoff residue
depends on that plan's pixel centres (transform, window and shape), so it is
never recorded and is checked again on every call. A missing, unreadable or
mismatching record is ignored and the full validation runs.
"""

import hashlib
import json
import os
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np

SCHEMA = "fim-cell-validation/2"
ENVIRONMENT = "RAS_COMMANDER_FIM_VALIDATION_CACHE"
_MEMORY_RECORDS = 256
_STORE_RECORDS = 256
_passed = OrderedDict()
_lock = threading.Lock()


def identity(geometries):
    """Return the content digest of an ordered Polygon array, or ``None``.

    ``None`` (anything other than non-empty Polygons, or a failed read) means
    the result may be neither looked up nor recorded.
    """
    import shapely

    count = len(geometries)
    if not count:
        return None
    if not (shapely.get_type_id(geometries) == 3).all() or shapely.is_empty(geometries).any():
        return None
    holes = shapely.get_num_interior_rings(geometries)
    # Ring sizes in coordinate order (exterior, then holes) with the per-cell
    # ring counts fix how the flat coordinate list divides into polygons.
    sizes = shapely.get_num_coordinates(
        shapely.get_rings(geometries) if holes.any() else geometries
    )
    coordinates = shapely.get_coordinates(geometries)
    if int(sizes.sum()) != len(coordinates):
        return None
    digest = hashlib.sha256()
    digest.update(
        json.dumps([SCHEMA, shapely.__version__, shapely.geos_version_string, count]).encode()
    )
    for label, values, dtype in (
        ("holes", holes, "<i8"),
        ("sizes", sizes, "<i8"),
        ("xy", coordinates, "<f8"),
    ):
        values = np.ascontiguousarray(values, dtype=dtype)
        digest.update(f"|{label}:{values.shape}|".encode())
        digest.update(values.data)
    return digest.hexdigest()


def store_directory():
    """Directory of persisted records, or ``None`` when persistence is off.

    ``RAS_COMMANDER_FIM_VALIDATION_CACHE`` names another directory; ``0``,
    ``off``, ``false`` or ``no`` keeps reuse inside the process.
    """
    value = os.environ.get(ENVIRONMENT, "").strip()
    if value.lower() in {"0", "off", "false", "no"}:
        return None
    if value:
        return Path(value).expanduser()
    from ..RasExamples import _get_user_data_dir

    return _get_user_data_dir() / "fim-cell-validation"


def _record(digest, count):
    import shapely

    return {
        "schema": SCHEMA,
        "digest": digest,
        "cells": int(count),
        "result": "passed",
        "shapely": shapely.__version__,
        "geos": shapely.geos_version_string,
    }


def lookup(digest, count):
    """Whether this exact content already passed."""
    with _lock:
        if _passed.get(digest) == count:
            _passed.move_to_end(digest)
            return True
    try:
        folder = store_directory()
        if folder is None:
            return False
        path = folder / f"{digest}.json"
        if path.stat().st_size > 4096:
            return False
        if json.loads(path.read_text(encoding="utf-8")) != _record(digest, count):
            return False
        try:
            os.utime(path)
        except OSError:
            pass
    except (OSError, ValueError, RuntimeError):
        # RuntimeError: no resolvable home directory (e.g. a contained job).
        return False
    _remember_in_process(digest, count)
    return True


def _remember_in_process(digest, count):
    with _lock:
        _passed[digest] = count
        _passed.move_to_end(digest)
        while len(_passed) > _MEMORY_RECORDS:
            _passed.popitem(last=False)


def remember(digest, count):
    """Record a completed, passed validation. Storage failures are ignored."""
    _remember_in_process(digest, count)
    temporary = None
    try:
        folder = store_directory()
        if folder is None:
            return
        folder.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".pending-", suffix=".tmp", dir=folder)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(_record(digest, count), stream)
        os.replace(temporary, folder / f"{digest}.json")
        temporary = None
        records = sorted(
            (entry.stat().st_mtime_ns, entry.name, entry) for entry in folder.glob("*.json")
        )
        for _, _, entry in records[: max(0, len(records) - _STORE_RECORDS)]:
            entry.unlink(missing_ok=True)
        # A killed writer leaves its temporary behind; remove hour-old ones.
        stale = time.time() - 3600
        for entry in folder.glob(".pending-*.tmp"):
            if entry.stat().st_mtime < stale:
                entry.unlink(missing_ok=True)
    except (OSError, ValueError, RuntimeError):
        pass
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def validate(cells, terrain_path, plan, *, threads=1):
    """Validate the planned cell subset; return ``True`` when a pass was reused."""
    from . import _horizontal

    digest = None
    count = 0
    if all(plan.shape):
        try:
            geometries = cells.geometry.iloc[plan.cell_positions].to_numpy()
            count = len(geometries)
            digest = identity(geometries)
        except Exception:
            digest = None
        if digest is not None and lookup(digest, count):
            return True
    grid = _horizontal.prepare_grid(cells, terrain_path, plan, False, threads=threads)
    # Record only a pass with no tolerated overlap: that one is true of the
    # polygons alone. Anything else (or an unknown answer) is not recorded.
    if digest is not None and getattr(grid, "tolerated_overlaps", None) == 0:
        remember(digest, count)
    return False
