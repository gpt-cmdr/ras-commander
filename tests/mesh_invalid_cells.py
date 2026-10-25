"""Derived real mesh with known invalid source cells, for tests that need them.

``make_invalid_copy`` copies the public eBFE-derived ``AustinOyster.p01.hdf``
(HEC-RAS 6.6, one 2D area ``Perimeter 1``; Source: FEMA estimated Base Flood
Elevation (eBFE) program) and moves one interior FacePoint 450 ft east, across
the boundaries of its neighbouring 200 ft cells. Two original cells then have
self-intersecting boundaries: the Python reference omits them as
``no_polygon``, strict native assembly refuses the first, and native
fluvial/pluvial refuses both. Nothing else in the copy changes; the source is
opened read-only.
"""
import hashlib
import shutil
from pathlib import Path

import h5py
import numpy as np

SOURCE_NAME = "AustinOyster.p01.hdf"
SOURCE_SHA256 = "c9eff69c9c477ea293dcc69aea16fe88da8adf24da388c1e7249fec954da90f8"
MESH = "Perimeter 1"
SHIFT_FT = 450.0
INVALID_CELLS = (1420, 1479)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 22), b""):
            digest.update(block)
    return digest.hexdigest()


def make_invalid_copy(source, destination):
    """Write the derived copy to ``destination`` and return its path."""
    source, destination = Path(source), Path(destination)
    assert _sha256(source) == SOURCE_SHA256, f"unexpected source: {source}"
    shutil.copyfile(source, destination)
    with h5py.File(destination, "r+") as hdf:
        group = hdf[f"Geometry/2D Flow Areas/{MESH}"]
        points = group["FacePoints Coordinate"][()]
        perimeter = group["FacePoints Is Perimeter"][()]
        order = np.argsort(((points - points.mean(axis=0)) ** 2).sum(axis=1), kind="stable")
        index = int(next(i for i in order if perimeter[i] == 0))
        points[index, 0] += SHIFT_FT
        group["FacePoints Coordinate"][...] = points
    return destination
