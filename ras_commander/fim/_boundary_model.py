"""Internal adapters from canonical prepared models to signed XS inputs.

This does not change public qualification gates or provide a mapping fallback.
"""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import tempfile

from . import _coupled, _one_d
from .errors import FimUnsupportedError


_COUNTS = ("point_count", "triangle_count", "segment_count", "cross_section_count")
_FILES = ("points", "triangles", "tin_info", "xs_ids", "render_order", "normalized_m", "xs_clip")
_CLIPPING = "levees-and-xs-end-obstructions-only"


def _payload_path(value, folder):
    path = Path(value)
    if not path.is_absolute():
        path = folder / path
    path = path.resolve(strict=True)
    if not path.is_relative_to(folder.resolve(strict=True)) or not path.is_file():
        raise FimUnsupportedError("boundary payload escapes its managed preparation folder")
    return str(path)


def _adapt(receipt, folder, profiles, hdf, terrain):
    if (Path(receipt["source_hdf"]).resolve(strict=True) != hdf
            or Path(receipt["terrain"]).resolve(strict=True) != terrain):
        raise FimUnsupportedError("boundary preparation source identity differs from request")
    if any(isinstance(receipt[key], bool) or not isinstance(receipt[key], int)
           or receipt[key] <= 0 for key in _COUNTS):
        raise FimUnsupportedError("invalid boundary XS preparation counts")
    if receipt["point_count"] < 3 or receipt["cross_section_count"] < 2:
        raise FimUnsupportedError("invalid boundary XS preparation counts")
    names = receipt["profile_ids"]
    if (names != list(profiles) or receipt["profiles"] != list(profiles.values())
            or len(receipt["levels"]) != len(names)):
        raise FimUnsupportedError("boundary preparation profile identity/order differs from request")
    descriptor = {key: receipt[key] for key in _COUNTS}
    descriptor.update({key + "_file": _payload_path(receipt["files"][key], folder)
                       for key in _FILES})
    descriptor.update(clipping_scope=_CLIPPING, profiles=[
        {"id": name, "levels_file": _payload_path(path, folder)}
        for name, path in zip(names, receipt["levels"])])
    mesh = deepcopy(receipt.get("mesh"))
    if mesh is not None:
        mesh["geometry_file"] = _payload_path(mesh["geometry_file"], folder)
        mesh["mesh_files"] = [_payload_path(path, folder) for path in mesh["mesh_files"]]
        for profile in mesh["profiles"]:
            profile["values_files"] = [_payload_path(path, folder) for path in profile["values_files"]]
    storage = deepcopy(receipt.get("storage"))
    if storage is not None:
        storage["polygons"] = _payload_path(storage["polygons"], folder)
        storage["levels"] = [_payload_path(path, folder) for path in storage["levels"]]
    return {"xs": descriptor, "receipt": deepcopy(receipt), "mesh": mesh, "storage": storage}


@contextmanager
def prepare_boundary_xs(hdf, terrain, root, profiles, *, engine_path, threads,
                        max_working_mib, scope="one_d"):
    """Yield managed canonical XS descriptors; revalidate bindings on exit.

    Internal unqualified preparation is explicit. Callers must enforce their
    public scope/qualification policy before entering this adapter. No engine
    render, numerical qualification or CRS conversion occurs here.
    """
    from .RasFim import _positive_int

    if scope not in ("one_d", "coupled"):
        raise ValueError("boundary XS scope must be one_d or coupled")
    threads = _positive_int(threads, "threads")
    max_working_mib = _positive_int(max_working_mib, "max_working_mib")
    if threads > 64:
        raise ValueError("threads must be <=64")
    profile_names, selectors = _one_d._profile_selection(profiles)
    selected = dict(zip(profile_names, selectors))
    hdf, terrain = Path(hdf).resolve(strict=True), Path(terrain).resolve(strict=True)
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("boundary preparation root must be a directory")
    engine = Path(engine_path).resolve(strict=True) if engine_path is not None else None
    engine_hash = _one_d.digest(engine) if engine is not None else None
    with tempfile.TemporaryDirectory(prefix="boundary-xs-", dir=root) as temporary:
        folder = Path(temporary) / "prepared"
        kwargs = {"profiles": selected, "allow_unqualified": True,
                  "max_working_mib": max_working_mib}
        if scope == "one_d":
            prepared = _one_d.prepare_one_d_model(hdf, terrain, folder, **kwargs)
        else:
            prepared = _coupled.prepare_coupled_model(hdf, terrain, folder,
                engine_path=engine, threads=threads, **kwargs)
        receipt = deepcopy(prepared.validate())
        try:
            result = _adapt(receipt, folder, selected, hdf, terrain)
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise FimUnsupportedError(f"invalid boundary canonical preparation: {exc}") from exc

        def verify():
            if prepared.validate() != receipt:
                raise FimUnsupportedError("boundary preparation receipt changed during use")
            if engine is not None and _one_d.digest(engine) != engine_hash:
                raise FimUnsupportedError("boundary engine identity changed during preparation/use")

        verify()
        try:
            yield result
        except BaseException as original:
            try:
                verify()
            except BaseException as validation_error:
                if hasattr(original, "add_note"):
                    original.add_note(f"Boundary preparation post-failure validation: {validation_error}")
            raise
        else:
            verify()
