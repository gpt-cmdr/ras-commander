"""Optional native lossless HEC-RAS text index, typed geometry reads and atomic edits.

``FastText`` binds the Rust ``ras_text`` core in the optional
``ras_commander_fast_hdf`` extension. Ordinary installations need no native
extension: the public ``GeomCrossSection``/``GeomParser`` APIs are unchanged
and remain pure Python.

Backends (per call, or ``RAS_COMMANDER_FAST_TEXT`` when ``backend='auto'``):

* ``'rust'`` (env ``required``/``rust``) - native only; never falls back.
* ``'python'`` (env ``0``/``off``/``python``) - the existing
  ``GeomCrossSection`` readers, used as the reference implementation.
* ``'auto'`` - native when a compatible extension imports, else Python.

Bounded scope: lossless document/key index, raw byte-span batch edits, the
geometry (``.g##``) node index with station/elevation, Manning's n and bank
stations, and typed edits of those three records. Plan, flow, unsteady and
structure-specific families are not typed here.

Native semantics differ from the Python readers only where Python repairs or
guesses; native raises instead (documented per method):

* a counted block whose declared count disagrees with its payload raises
  ``FastTextParseError`` instead of returning a partial table;
* legacy ``Reach=`` headers resolve per-XS lookups (Python's per-XS readers
  only track ``River Reach=``; ``get_cross_sections`` handles both).

Input files are read once as bytes and never modified. Edits write a copied
destination through a sibling temporary file and ``os.replace``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import importlib
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from .Decorators import log_call
from .LoggingConfig import get_logger

logger = get_logger(__name__)

__all__ = ["FastText", "FastTextError", "FastTextParseError", "GeometryTextIndex"]

_TEXT_API_VERSION = 1
_ENV = "RAS_COMMANDER_FAST_TEXT"
_OPS = {"station_elevation": 2, "mannings_n": 3, "bank_stations": 2}

#: Native entry-point call counts (qualification: proves no Python fallback).
NATIVE_CALLS: Counter = Counter()


class FastTextError(RuntimeError):
    """The explicitly requested native text operation could not be completed."""


class FastTextParseError(ValueError):
    """A counted block is malformed; native reads raise instead of repairing."""


def _mode(backend: str) -> str:
    if backend not in {"auto", "python", "rust"}:
        raise ValueError("backend must be 'auto', 'python', or 'rust'")
    if backend != "auto":
        return backend
    value = os.environ.get(_ENV, "auto").strip().lower()
    if value in {"0", "off", "false", "python"}:
        return "python"
    if value in {"required", "rust"}:
        return "rust"
    if value in {"", "auto", "1", "on", "true"}:
        return "auto"
    raise ValueError(f"Invalid {_ENV} value: {value!r}")


def _native(mode: str):
    if mode == "python":
        return None
    try:
        module = importlib.import_module("ras_commander_fast_hdf")
    except (ImportError, OSError) as exc:
        if mode == "rust":
            raise FastTextError("The optional ras-commander-fast-hdf extension is unavailable") from exc
        return None
    if getattr(module, "TEXT_API_VERSION", None) != _TEXT_API_VERSION:
        if mode == "rust":
            raise FastTextError(
                f"ras-commander-fast-hdf lacks text API version {_TEXT_API_VERSION}"
            )
        logger.warning("Ignoring ras-commander-fast-hdf without a compatible text API")
        return None
    return module


def _require_native():
    return _native("rust")


def _call(module, name: str, *args, **kwargs):
    NATIVE_CALLS[name] += 1
    try:
        return getattr(module, name)(*args, **kwargs)
    except getattr(module, "TextParseError") as exc:
        raise FastTextParseError(str(exc)) from exc


def _text(raw: Optional[bytes]) -> Optional[str]:
    """Decode identifiers exactly as the Python readers do."""
    if raw is None:
        return None
    return raw.decode("utf-8", errors="replace").strip()


def _read(path: Union[str, Path]) -> Tuple[Path, bytes]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Geometry file not found: {path}")
    return path, path.read_bytes()


@dataclass
class GeometryTextIndex:
    """Decoded native geometry index of one immutable byte buffer.

    ``find_node``, ``station_elevation``, ``mannings_n`` and ``bank_stations``
    are lightweight state accessors used inside bulk reads/edits. They are
    deliberately not decorated with ``log_call``: public FastText operations
    log the boundary once, without logging each indexed node or its buffers.
    """

    path: Optional[Path]
    sha256: str
    title: Optional[str]
    program_version: Optional[str]
    nodes: pd.DataFrame
    blocks: pd.DataFrame
    diagnostics: pd.DataFrame
    error_count: int
    raw: Dict[str, Any] = field(repr=False)

    _lookup: Optional[Dict[Tuple[str, str, str], int]] = field(default=None, repr=False)

    def find_node(self, river: str, reach: str, rs: str) -> Optional[int]:
        """First node matching exact (case-sensitive) river/reach/RS, or None."""
        if self._lookup is None:
            lookup: Dict[Tuple[str, str, str], int] = {}
            keys = zip(self.nodes["River"], self.nodes["Reach"], self.nodes["RS"])
            for node, key in enumerate(keys):
                lookup.setdefault(key, node)
            self._lookup = lookup
        return self._lookup.get((river, reach, rs))

    def _table(self, name: str, node: int) -> Optional[np.ndarray]:
        table = self.raw[name]
        status = int(table["status"][node])
        if status == 0:
            return None
        if status == 2:
            raise FastTextParseError(
                f"Malformed {name} block for node {node} "
                f"({self.nodes.at[node, 'River']}/{self.nodes.at[node, 'Reach']}/"
                f"RS {self.nodes.at[node, 'RS']}); see diagnostics"
            )
        start, stop = table["offsets"][node], table["offsets"][node + 1]
        return table["values"][start:stop]

    def station_elevation(self, node: int) -> Optional[np.ndarray]:
        """(n, 2) station/elevation array, None if absent; raises if malformed."""
        return self._table("station_elevation", node)

    def mannings_n(self, node: int) -> Optional[np.ndarray]:
        """(n, 3) station/n/flag array, None if absent; raises if malformed."""
        return self._table("mannings_n", node)

    def bank_stations(self, node: int) -> Optional[Tuple[float, float]]:
        table = self.raw["bank_stations"]
        status = int(table["status"][node])
        if status == 0:
            return None
        if status == 2:
            raise FastTextParseError(f"Unparsable Bank Sta= for node {node}")
        left, right = table["values"][node]
        return float(left), float(right)


def _diagnostics_frame(items: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    columns = ["severity", "code", "line", "start", "end", "message"]
    rows = [
        {**item, "message": item["message"].decode("latin-1")} for item in items
    ]
    return pd.DataFrame(rows, columns=columns)


def _geometry_index(data: bytes, path: Optional[Path], tables: bool = True) -> GeometryTextIndex:
    module = _require_native()
    raw = _call(module, "text_geometry_index", data, tables)
    nodes = raw["nodes"]
    lengths = nodes["lengths"]
    frame = pd.DataFrame(
        {
            "River": [_text(v) for v in nodes["river"]],
            "Reach": [_text(v) for v in nodes["reach"]],
            "RS": [_text(v) for v in nodes["station"]],
            "Type": nodes["type"].astype("int64"),
            "Length_Left": lengths[:, 0],
            "Length_Channel": lengths[:, 1],
            "Length_Right": lengths[:, 2],
            "NodeName": [_text(v) for v in nodes["node_name"]],
            "header_line": nodes["header_line"],
        }
    )
    blocks = pd.DataFrame(
        raw["blocks"],
        columns=["key", "header_line", "count", "value_count", "section", "malformed"],
    )
    return GeometryTextIndex(
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        title=_text(raw["title"]),
        program_version=_text(raw["program_version"]),
        nodes=frame,
        blocks=blocks,
        diagnostics=_diagnostics_frame(raw["diagnostics"]),
        error_count=int(raw["error_count"]),
        raw=raw,
    )


def _python():
    from .geom.GeomCrossSection import GeomCrossSection

    return GeomCrossSection


def _cross_section_frame(index: GeometryTextIndex, river, reach) -> pd.DataFrame:
    diags = index.diagnostics
    bad_type = diags[diags["code"] == "bad-node-type"]
    if len(bad_type):
        # Python raises from the same unparsable type code.
        raise IOError(
            "Failed to extract cross sections: invalid node type at line "
            f"{int(bad_type['line'].iloc[0]) + 1}"
        )
    bad_length_lines = set(diags.loc[diags["code"] == "bad-node-length", "line"])
    nodes = index.nodes
    keep = nodes["River"].notna() & nodes["Reach"].notna()
    keep &= ~nodes["header_line"].isin(bad_length_lines)
    if river is not None:
        keep &= nodes["River"] == river
    if reach is not None:
        keep &= nodes["Reach"] == reach
    selected = nodes.loc[keep].drop(columns="header_line").reset_index(drop=True)
    if selected.empty:
        return pd.DataFrame([])
    return selected


def _subsection(station: float, banks: Optional[Tuple[float, float]]) -> str:
    if banks is None:
        return "Unknown"
    left, right = banks
    if station < left:
        return "LOB"
    if station < right:
        return "Channel"
    return "ROB"


def _write_copy(destination: Path, data: bytes) -> None:
    """Write ``data`` atomically next to ``destination``."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, destination)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _check_destination(source: Path, destination: Path, overwrite: bool) -> None:
    if source.resolve() == destination.resolve() or (
        destination.exists() and os.path.samefile(source, destination)
    ):
        raise ValueError("destination must differ from the immutable source file")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Destination exists: {destination} (pass overwrite=True)")


class FastText:
    """Static namespace for native lossless text parsing and atomic edits."""

    @staticmethod
    @log_call
    def available() -> bool:
        """Whether an extension with the text API imports, independently of policy."""
        return _native("auto") is not None

    @staticmethod
    @log_call
    def native_module_path() -> Optional[str]:
        """Path of the imported native extension package, or None."""
        module = _native("auto")
        return None if module is None else str(Path(module.__file__))

    @staticmethod
    @log_call
    def document_index(path_or_bytes: Union[str, Path, bytes]) -> Dict[str, Any]:
        """Lossless line/key index, encoding report and diagnostics (native only).

        Returns a dict with ``lines`` ((N, 3) int64: start, content_end, end),
        ``keys`` ((K, 5) int64: line, key_start, key_end, value_start,
        value_end), ``free_text`` (bool per line), ``key_counts`` (raw key
        bytes, count), ``encoding`` and ``diagnostics``. Spans are byte offsets
        into the unmodified input; no transcoding or BOM stripping occurs.
        """
        data = path_or_bytes if isinstance(path_or_bytes, bytes) else Path(path_or_bytes).read_bytes()
        return _call(_require_native(), "text_index", data)

    @staticmethod
    @log_call
    def apply_edits(
        data: bytes, edits: Sequence[Tuple[int, int, bytes, str]]
    ) -> Tuple[bytes, List[Tuple[str, int, int, int, int]]]:
        """Apply raw ``(start, end, replacement, label)`` edits as one batch.

        Returns ``(new_bytes, spans)`` with ``(label, original_start,
        original_end, updated_start, updated_end)`` per edit. Overlapping,
        reversed, out-of-range or same-offset-ambiguous edits reject the whole
        batch with ``ValueError`` (``TextEditError``); bytes outside edits are
        copied verbatim.
        """
        return _call(_require_native(), "text_apply_edits", data, list(edits))

    @staticmethod
    @log_call
    def geometry_index(geom_file: Union[str, Path, bytes], *, tables: bool = True) -> GeometryTextIndex:
        """Native bounded geometry index (nodes, blocks, diagnostics, tables)."""
        if isinstance(geom_file, bytes):
            return _geometry_index(geom_file, None, tables)
        path, data = _read(geom_file)
        return _geometry_index(data, path, tables)

    @staticmethod
    @log_call
    def get_cross_sections(
        geom_file: Union[str, Path],
        river: Optional[str] = None,
        reach: Optional[str] = None,
        *,
        backend: str = "auto",
    ) -> pd.DataFrame:
        """Same contract and columns as ``GeomCrossSection.get_cross_sections``."""
        if reach is not None and river is None:
            raise ValueError("If reach is specified, river must also be specified")
        mode = _mode(backend)
        if _native(mode) is None:
            return _python().get_cross_sections(geom_file, river=river, reach=reach)
        path, data = _read(geom_file)
        return _cross_section_frame(_geometry_index(data, path, tables=False), river, reach)

    @staticmethod
    def _node(geom_file, river, reach, rs) -> Tuple[GeometryTextIndex, int]:
        path, data = _read(geom_file)
        index = _geometry_index(data, path)
        node = index.find_node(river, reach, rs)
        if node is None:
            raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs} in {path.name}")
        return index, node

    @staticmethod
    @log_call
    def get_station_elevation(
        geom_file: Union[str, Path], river: str, reach: str, rs: str, *, backend: str = "auto"
    ) -> pd.DataFrame:
        """Same columns as ``GeomCrossSection.get_station_elevation``.

        Native raises ``FastTextParseError`` for a count/payload mismatch where
        Python logs a warning and returns the values it could salvage.
        """
        if _native(_mode(backend)) is None:
            return _python().get_station_elevation(geom_file, river, reach, rs)
        index, node = FastText._node(geom_file, river, reach, rs)
        values = index.station_elevation(node)
        if values is None:
            raise ValueError(f"#Sta/Elev data not found for {river}/{reach}/RS {rs}")
        return pd.DataFrame({"Station": values[:, 0].copy(), "Elevation": values[:, 1].copy()})

    @staticmethod
    @log_call
    def get_bank_stations(
        geom_file: Union[str, Path], river: str, reach: str, rs: str, *, backend: str = "auto"
    ) -> Optional[Tuple[float, float]]:
        """Same contract as ``GeomCrossSection.get_bank_stations``."""
        if _native(_mode(backend)) is None:
            return _python().get_bank_stations(geom_file, river, reach, rs)
        index, node = FastText._node(geom_file, river, reach, rs)
        return index.bank_stations(node)

    @staticmethod
    @log_call
    def get_mannings_n(
        geom_file: Union[str, Path], river: str, reach: str, rs: str, *, backend: str = "auto"
    ) -> pd.DataFrame:
        """Same columns/subsection rules as ``GeomCrossSection.get_mannings_n``."""
        if _native(_mode(backend)) is None:
            return _python().get_mannings_n(geom_file, river, reach, rs)
        index, node = FastText._node(geom_file, river, reach, rs)
        values = index.mannings_n(node)
        if values is None:
            raise ValueError(f"No Manning's n data found for {river}/{reach}/RS {rs}")
        banks = index.bank_stations(node)
        rows = [
            {"Station": float(s), "n_value": float(n), "Subsection": _subsection(s, banks)}
            for s, n, _ in values
        ]
        return pd.DataFrame(rows)

    @staticmethod
    @log_call
    def get_all_station_elevation(
        geom_file: Union[str, Path], *, backend: str = "auto"
    ) -> pd.DataFrame:
        """Long table of every reach node's station/elevation in file order.

        Columns ``River, Reach, RS, Station, Elevation``; one row per point.
        Nodes are those listed by ``get_cross_sections``. The Python backend
        calls ``get_station_elevation`` once per node (reference only).
        """
        columns = ["River", "Reach", "RS", "Station", "Elevation"]
        if _native(_mode(backend)) is None:
            gcs = _python()
            frames = []
            xs = gcs.get_cross_sections(geom_file)
            for row in xs.itertuples(index=False):
                try:
                    df = gcs.get_station_elevation(geom_file, row.River, row.Reach, row.RS)
                except ValueError:
                    continue
                frames.append(df.assign(River=row.River, Reach=row.Reach, RS=row.RS)[columns])
            return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)
        path, data = _read(geom_file)
        index = _geometry_index(data, path)
        listed = _cross_section_frame(index, None, None)
        if listed.empty:
            return pd.DataFrame(columns=columns)
        seen = set()
        parts = []
        for river, reach, rs in listed[["River", "Reach", "RS"]].itertuples(index=False):
            if (river, reach, rs) in seen:
                continue  # duplicate IDs resolve to the first node, as in Python
            seen.add((river, reach, rs))
            node = index.find_node(river, reach, rs)
            values = index.station_elevation(node)
            if values is None:
                continue
            parts.append((river, reach, rs, values))
        if not parts:
            return pd.DataFrame(columns=columns)
        counts = [len(p[3]) for p in parts]
        stacked = np.concatenate([p[3] for p in parts]) if parts else np.empty((0, 2))
        return pd.DataFrame(
            {
                "River": np.repeat([p[0] for p in parts], counts),
                "Reach": np.repeat([p[1] for p in parts], counts),
                "RS": np.repeat([p[2] for p in parts], counts),
                "Station": stacked[:, 0],
                "Elevation": stacked[:, 1],
            }
        )

    @staticmethod
    @log_call
    def edit_geometry(
        source: Union[str, Path],
        destination: Union[str, Path],
        edits: Sequence[Mapping[str, Any]],
        *,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """Apply typed geometry edits to a copy of ``source`` (native only).

        Each edit is a mapping with ``op`` (``station_elevation``,
        ``mannings_n`` or ``bank_stations``), ``river``, ``reach``, ``rs`` and
        ``values``: an (n, 2) station/elevation array or DataFrame, (n, 3)
        station/n/flag triplets, or a ``(left, right)`` pair. All edits are
        validated first; any failure raises and writes nothing. Only count
        tokens and payloads (or the two bank tokens) change; newline style, a
        missing final newline and every other byte are preserved. The source
        is never modified.

        Returns ``{"spans", "source_sha256", "output_sha256", "destination"}``.
        """
        module = _require_native()
        source = Path(source)
        destination = Path(destination)
        _check_destination(source, destination, overwrite)
        path, data = _read(source)
        index = _geometry_index(data, path, tables=False)
        ops = []
        for edit in edits:
            op = edit.get("op")
            if op not in _OPS:
                raise ValueError(f"Unsupported edit op {op!r}; expected one of {sorted(_OPS)}")
            node = index.find_node(edit["river"], edit["reach"], edit["rs"])
            if node is None:
                raise ValueError(
                    f"Cross section not found: {edit['river']}/{edit['reach']}/RS {edit['rs']}"
                )
            values = edit["values"]
            if isinstance(values, pd.DataFrame):
                values = values.to_numpy()
            values = np.ascontiguousarray(np.asarray(values, dtype=np.float64).reshape(-1, _OPS[op]))
            ops.append({"op": op, "node": node, "values": values})
        new_bytes, spans = _call(module, "text_geometry_edit", data, ops)
        _write_copy(destination, new_bytes)
        return {
            "spans": spans,
            "source_sha256": hashlib.sha256(data).hexdigest(),
            "output_sha256": hashlib.sha256(new_bytes).hexdigest(),
            "destination": destination,
        }
