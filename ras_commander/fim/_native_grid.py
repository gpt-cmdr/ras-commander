"""Source-preserving derivation for the opt-in stored terrain tile grid.

This module derives and validates framing only. Hydraulic interpolation and
physical ownership remain exclusively in the Rust engine.
"""
from __future__ import annotations

import math
import struct
import sys
from collections.abc import Mapping

from .errors import FimUnsupportedError

CONTRACT = "rasmapper-stored-tile-grid/1"
_FIELDS = {"id", "source_width", "source_height", "tile_size",
           "source_geo_transform", "output_geo_transform"}


def select(value):
    """Validate the public opt-in without interpreting arbitrary truthy values."""
    if value is not None and (not isinstance(value, str) or value != CONTRACT):
        raise FimUnsupportedError(f"grid_contract must be None or {CONTRACT!r}")
    return value


def _bits(value):
    return struct.pack("<d", float(value))


def _same_transform(left, right):
    try:
        return (isinstance(left, (list, tuple)) and len(left) == 6
                and all(not isinstance(v, bool) and isinstance(v, (int, float))
                        and math.isfinite(v) for v in left)
                and all(_bits(a) == _bits(b) for a, b in zip(left, right)))
    except (OverflowError, TypeError, ValueError, struct.error):
        return False


def derive(grid):
    """Derive native full framing and prove admitted global-center equivalence.

    The fixed Rust-compatible layout cap bounds work independently of the
    render memory budget. Verification uses constant scratch, never a raster-sized
    center array. Full logical edge tiles retain their original 256-pixel size.
    Binary64 expressions deliberately preserve the native operation order.
    """
    try:
        width, height, size = (grid[k] for k in ("width", "height", "tile_size"))
        if (any(isinstance(v, bool) or not isinstance(v, int) or not 0 < v <= min(sys.maxsize, 2**31-1)
                for v in (width, height, size)) or size != 256):
            raise ValueError("positive source dimensions and original 256-pixel tiles required")
        raw = grid["geo_transform"]
        if not _same_transform(raw, raw):
            raise ValueError("finite source transform required")
        x0, sx, rx, y0, ry, sy = map(float, raw)
        if rx != 0. or ry != 0. or sx <= 0. or sy != -sx:
            raise ValueError("north-up square source grid required")
        columns, rows = (width + size - 1)//size, (height + size - 1)//size
        if columns*size > sys.maxsize or rows*size > sys.maxsize:
            raise ValueError("padded source grid overflow")
        if columns*rows*512 > 16_777_216:
            raise ValueError("native grid center admission exceeds bounded layout scope")
        right, bottom = x0 + width*sx, y0 + height*sy
        cell = max((right-x0)/width, (y0-bottom)/height)
        initial_pitch = size*cell
        padded_right, padded_bottom = x0 + columns*initial_pitch, y0 - rows*initial_pitch
        pitch = max((padded_right-x0)/columns, (y0-padded_bottom)/rows)
        if (not all(math.isfinite(v) for v in (right, bottom, cell, padded_right, padded_bottom, pitch))
                or cell <= 0. or pitch <= 0.):
            raise ValueError("native grid extent overflow or collapse")
        for tr in range(rows):
            top, tile_bottom = y0-pitch*tr, y0-pitch*(tr+1)
            for tc in range(columns):
                left, tile_right = x0+pitch*tc, x0+pitch*(tc+1)
                step = max((tile_right-left)/size, (top-tile_bottom)/size)
                if not all(math.isfinite(v) for v in (left, tile_right, top, tile_bottom, step)) or step <= 0.:
                    raise ValueError("native tile extent overflow or collapse")
                for lc in range(min(size, width-tc*size)):
                    if _bits(left+step*(lc+0.5)) != _bits(x0+cell*(tc*size+lc+0.5)):
                        raise ValueError("logical tile centers differ from full output affine")
                for lr in range(min(size, height-tr*size)):
                    if _bits(top-step*(lr+0.5)) != _bits(y0-cell*(tr*size+lr+0.5)):
                        raise ValueError("logical tile centers differ from full output affine")
        return {"id": CONTRACT, "source_width": width, "source_height": height,
                "tile_size": size, "source_geo_transform": list(raw),
                "output_geo_transform": [x0, cell, 0., y0, 0., -cell]}
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise FimUnsupportedError(f"unsupported native stored tile grid: {exc}") from exc


def validate(record, grid):
    """Recompute a sealed descriptor; metadata fitting cannot satisfy identity."""
    expected = derive(grid)
    if not matches(record, expected):
        raise FimUnsupportedError("native grid descriptor differs from bound source/derived output framing")
    return expected


def matches(record, expected):
    """Compare an engine descriptor to an already independently derived one."""
    return (isinstance(record, Mapping) and set(record) == _FIELDS
            and record.get("id") == CONTRACT
            and all(not isinstance(record.get(k), bool) and isinstance(record.get(k), int)
                   and record[k] == expected[k]
                   for k in ("source_width", "source_height", "tile_size"))
            and _same_transform(record.get("source_geo_transform"), expected["source_geo_transform"])
            and _same_transform(record.get("output_geo_transform"), expected["output_geo_transform"]))
