"""Read-only, bounded fingerprints for comparing compiled HEC-RAS inputs."""

import base64
import hashlib
import json
import math
from pathlib import Path

import h5py
import numpy as np


def _value(value):
    if isinstance(value, np.ndarray):
        return [_value(x) for x in value] if value.ndim else _value(value.item())
    if isinstance(value, np.generic):
        return _value(value.item())
    if isinstance(value, bytes):
        return {"bytes_base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite": repr(value)}
    if isinstance(value, (tuple, list)):
        return [_value(x) for x in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported HDF attribute type: {type(value).__name__}")


def fingerprint_model_inputs(hdf_path: Path, groups, block_bytes: int) -> dict:
    """Fingerprint local hard-linked datasets; never traverse external storage."""
    before = hdf_path.stat()
    result = {
        "path": str(hdf_path),
        "groups": {},
        "datasets": {},
        "missing_groups": [],
        "aliases": {},
    }
    with h5py.File(hdf_path, "r") as hdf:
        visited = {}
        active = set()

        def visit(path):
            if not isinstance(hdf.get(path, getlink=True), h5py.HardLink):
                raise ValueError(f"Input fingerprint refuses non-hard HDF link: {path}")
            obj = hdf[path]
            address = h5py.h5o.get_info(obj.id).addr
            if address in active:
                raise ValueError(f"Input fingerprint refuses cyclic HDF object: {path}")
            if address in visited:
                result["aliases"][path] = visited[address]
                return
            visited[address] = path
            attrs = {key: _value(obj.attrs[key]) for key in sorted(obj.attrs)}
            if isinstance(obj, h5py.Group):
                result["groups"][path] = {"attributes": attrs}
                active.add(address)
                for name in sorted(obj):
                    visit(path.rstrip("/") + "/" + name)
                active.remove(address)
                return
            if obj.is_virtual or obj.external:
                raise ValueError(
                    f"Input fingerprint refuses external/virtual dataset: {path}"
                )
            # Separate field digests avoid uninitialized compound padding and
            # make hashes independent of the selected read block size.
            fields = obj.dtype.names or (None,)
            digests = {name: hashlib.sha256() for name in fields}
            if obj.shape is None:
                slices = []
            elif obj.shape == ():
                slices = [()]
            else:
                row_bytes = max(1, obj.dtype.itemsize * math.prod(obj.shape[1:]))
                if row_bytes > block_bytes:
                    raise ValueError(
                        f"Dataset row exceeds fingerprint block limit: {path}"
                    )
                rows = max(1, block_bytes // row_bytes)
                slices = (
                    slice(start, start + rows) for start in range(0, obj.shape[0], rows)
                )
            for selection in slices:
                block = np.asarray(obj[selection])
                for name, digest in digests.items():
                    values = block if name is None else block[name]
                    if values.dtype.kind in "OSU":
                        for item in values.reshape(-1):
                            payload = json.dumps(
                                _value(item), sort_keys=True, allow_nan=False
                            ).encode()
                            digest.update(len(payload).to_bytes(8, "little"))
                            digest.update(payload)
                    elif values.dtype.hasobject or values.dtype.names:
                        raise TypeError(f"Unsupported nested/object HDF dtype: {path}")
                    else:
                        digest.update(np.ascontiguousarray(values).tobytes())
            field_hashes = {
                str(key): digest.hexdigest() for key, digest in digests.items()
            }
            result["datasets"][path] = {
                "shape": None if obj.shape is None else list(obj.shape),
                "dtype": str(obj.dtype),
                "attributes": attrs,
                "sha256": hashlib.sha256(
                    json.dumps(field_hashes, sort_keys=True).encode()
                ).hexdigest(),
            }

        for group in groups:
            path = "/" + group.strip("/")
            parent = hdf
            missing = False
            # Validate every ancestor before lookup: a nested selection must
            # never traverse an external parent while checking membership.
            parts = path.strip("/").split("/")
            for part in parts:
                if not isinstance(parent, h5py.Group):
                    missing = True
                    break
                link = parent.get(part, getlink=True)
                if link is None:
                    missing = True
                    break
                if not isinstance(link, h5py.HardLink):
                    raise ValueError(
                        f"Input fingerprint refuses non-hard HDF link: {path}"
                    )
                parent = parent[part]
            if missing:
                result["missing_groups"].append(path)
            else:
                visit(path)
    after = hdf_path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise RuntimeError("HDF changed during input fingerprint inspection")
    return result
