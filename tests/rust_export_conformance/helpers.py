"""Packed input and independent decoding helpers; no tiling implementation."""
import gzip
import math
from pathlib import Path

import numpy as np
import pytest
mapbox_vector_tile = pytest.importorskip("mapbox_vector_tile")
reader_module = pytest.importorskip("pmtiles.reader")
MmapSource, Reader, all_tiles = reader_module.MmapSource, reader_module.Reader, reader_module.all_tiles
import shapely


def pack(geometries, ids=None):
    coordinates, rings, polygons, features = [], [0], [0], [0]
    for geom in geometries:
        for polygon in geom.geoms if geom.geom_type == "MultiPolygon" else [geom]:
            for ring in [polygon.exterior, *polygon.interiors]:
                coordinates.extend(ring.coords)
                rings.append(len(coordinates))
            polygons.append(len(rings) - 1)
        features.append(len(polygons) - 1)
    return dict(coordinates=np.asarray(coordinates, dtype="f8").reshape(-1, 2),
                ring_offsets=np.asarray(rings, dtype="i8"),
                polygon_offsets=np.asarray(polygons, dtype="i8"),
                feature_offsets=np.asarray(features, dtype="i8"),
                cell_ids=np.asarray(ids if ids is not None else range(len(geometries)), dtype="i8"),
                properties={})


def decode(path):
    with Path(path).open("rb") as stream:
        reader = Reader(MmapSource(stream))
        header, metadata = reader.header(), reader.metadata()
        tiles = {}
        for address, data in all_tiles(reader.get_bytes):
            if data[:2] == b"\x1f\x8b":
                data = gzip.decompress(data)
            tiles[address] = mapbox_vector_tile.decode(data, default_options={"y_coord_down": True})
        # Reopen and address tiles independently of the traversal.
        for (z, x, y), layers in tiles.items():
            raw = reader.get(z, x, y)
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            assert mapbox_vector_tile.decode(raw, default_options={"y_coord_down": True}) == layers
    return header, metadata, tiles


def pixels(geometry, z, x, y, extent):
    def transform(coords):
        lon, lat = coords[:, 0], np.radians(coords[:, 1])
        n = 2 ** z
        return np.column_stack([((lon + 180) / 360 * n - x) * extent,
            ((1 - np.log(np.tan(lat) + 1 / np.cos(lat)) / math.pi) / 2 * n - y) * extent])
    return shapely.transform(geometry, transform)
