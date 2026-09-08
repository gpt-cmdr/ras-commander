"""Forward-walking ZIP reader for archives that cannot be opened normally.

``zipfile`` locates members by seeking to the End Of Central Directory record at
the tail of the file and reading the index it points at. When that record is
absent the whole random-access model is unavailable -- ``zipfile.ZipFile``
raises ``BadZipFile`` and there is nothing to fall back on.

That is not a hypothetical. FEMA's eBFE delivery for HUC 12100302 (Medina) is a
52.09 GB object whose local headers declare 53.02 GB of member data: the final
member runs 935,101,777 bytes past the end of the object, and the central
directory -- which would have followed it -- was never written. The object
matches its published ``Content-Length`` and ETag exactly, so the truncation is
at the publisher, not in transit. 407 of its members are complete and extract
cleanly; only the last is lost.

This module walks local file headers forward instead, which needs no index and
no tail. It recovered all 407.

Deliberately **not** a ``zipfile.ZipFile`` drop-in. Random access is precisely
what a missing central directory cannot offer, and an API that implies otherwise
would invite ``namelist()``-then-``read()`` code that silently reads the archive
twice.

Example:
    >>> from ras_commander.sources.federal.ebfe_extract import StreamingZipReader
    >>> reader = StreamingZipReader("Medina_Models.zip")
    >>> survey = reader.probe()                       # headers only, no member data
    >>> survey.truncated
    True
    >>> survey.overrun_bytes
    935101777
    >>> for member, extracted in reader.walk(want=lambda m: m.name.endswith(".prj")):
    ...     pass
    >>> reader.stats.crc_fail
    0
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable, Iterator, Optional, Tuple, Union

from ras_commander.LoggingConfig import get_logger, log_call

logger = get_logger(__name__)

__all__ = ["ZipMemberInfo", "ArchiveSurvey", "ExtractStats", "StreamingZipReader"]

_LOCAL_HEADER_SIG = b"PK\x03\x04"
_CENTRAL_DIR_SIG = b"PK\x01\x02"
_EOCD_SIG = b"PK\x05\x06"
_DATA_DESCRIPTOR_SIG = b"PK\x07\x08"

_LOCAL_HEADER_STRUCT = struct.Struct("<4s2B4HL2L2H")
_LOCAL_HEADER_SIZE = _LOCAL_HEADER_STRUCT.size  # 30

_ZIP64_EXTRA_ID = 0x0001
_FLAG_DEFERRED_SIZES = 0x08  # sizes live in a trailing data descriptor
_STORED, _DEFLATED, _DEFLATED64 = 0, 8, 9

_DEFAULT_CHUNK = 4 << 20

# Deflate64 (method 9) is a real thing in FEMA deliveries -- seven result archives
# in the Baffin Bay East work area, 62 GB, are compressed with it -- and the
# standard library cannot read it. `zipfile-deflate64` supplies a decompressor;
# without it those members are reported unreadable with an actionable reason
# rather than silently skipped.
try:  # pragma: no cover - depends on optional dependency
    from zipfile_deflate64 import deflate64  # type: ignore

    _DEFLATE64_AVAILABLE = True
except ImportError:  # pragma: no cover
    deflate64 = None  # type: ignore
    _DEFLATE64_AVAILABLE = False


@dataclass
class ZipMemberInfo:
    """One member, as described by its own local header."""

    name: str
    header_offset: int
    data_offset: int
    compress_type: int
    compress_size: int
    file_size: int
    crc32: int
    flags: int
    is_dir: bool

    @property
    def sizes_deferred(self) -> bool:
        """True when sizes live in a trailing descriptor rather than the header."""
        return bool(self.flags & _FLAG_DEFERRED_SIZES)


@dataclass
class ArchiveSurvey:
    """What a header-only walk found. Cheap: no member data is read."""

    members: list = field(default_factory=list)
    declared_end: int = 0
    file_size: int = 0
    has_central_directory: bool = False
    stopped_reason: str = "clean"

    @property
    def truncated(self) -> bool:
        return self.declared_end > self.file_size

    @property
    def overrun_bytes(self) -> int:
        return max(0, self.declared_end - self.file_size)

    @property
    def complete_members(self) -> list:
        """Members whose data lies wholly inside the file."""
        return [m for m in self.members if m.data_offset + m.compress_size <= self.file_size]

    @property
    def truncated_members(self) -> list:
        return [m for m in self.members if m.data_offset + m.compress_size > self.file_size]

    @property
    def projected_bytes(self) -> int:
        """Uncompressed total of recoverable members -- the space gate's input.

        Without a central directory this is an estimate: members with deferred
        sizes report zero here, so allow margin rather than treating it as exact.
        """
        return sum(m.file_size for m in self.complete_members if not m.is_dir)


@dataclass
class ExtractStats:
    """Verification outcome. Part of the contract, not debug output.

    ``crc_ok`` / ``crc_fail`` are the substitute for hashing: the ZIP format
    already carries a CRC-32 per member, so checking it costs nothing beyond the
    decompression we are doing anyway and proves byte-correctness without a
    second full read of the data.
    """

    extracted: int = 0
    skipped: int = 0
    crc_ok: int = 0
    crc_fail: int = 0
    size_mismatch: int = 0
    unreadable: int = 0
    bytes_read: int = 0
    bytes_written: int = 0
    failures: list = field(default_factory=list)


def _read_zip64_extra(extra: bytes, need_sizes: bool) -> Tuple[Optional[int], Optional[int]]:
    """Pull 64-bit sizes out of the ZIP64 extra field.

    The ZIP64 record is **positional**, not tagged: fields appear in a fixed
    order and only when their 32-bit counterpart was saturated to 0xFFFFFFFF.
    Reading it as tagged key/value pairs yields plausible-looking garbage, so
    honour the order.
    """
    if not need_sizes:
        return None, None
    pos = 0
    while pos + 4 <= len(extra):
        header_id, size = struct.unpack_from("<HH", extra, pos)
        pos += 4
        if header_id == _ZIP64_EXTRA_ID:
            block = extra[pos : pos + size]
            uncompressed = compressed = None
            if len(block) >= 8:
                uncompressed = struct.unpack_from("<Q", block, 0)[0]
            if len(block) >= 16:
                compressed = struct.unpack_from("<Q", block, 8)[0]
            return uncompressed, compressed
        pos += size
    return None, None


class StreamingZipReader:
    """Walk a ZIP archive forward through its local file headers.

    Args:
        archive_path: Archive to read. Never modified.
        chunk_size: Read granularity in bytes.

    Attributes:
        stats: Populated by :meth:`walk`; ``crc_fail`` is the one to assert on.
    """

    def __init__(self, archive_path: Union[str, Path], chunk_size: int = _DEFAULT_CHUNK):
        self.archive_path = Path(archive_path)
        if not self.archive_path.exists():
            raise FileNotFoundError(f"Archive not found: {self.archive_path}")
        self.chunk_size = chunk_size
        self.file_size = self.archive_path.stat().st_size
        self.stats = ExtractStats()

    @staticmethod
    def supported_methods() -> tuple:
        """Compression methods this reader can decode in the current environment."""
        if _DEFLATE64_AVAILABLE:
            return (_STORED, _DEFLATED, _DEFLATED64)
        return (_STORED, _DEFLATED)

    # -- header walking ----------------------------------------------------

    def _read_local_header(self, handle: BinaryIO, offset: int) -> Optional[ZipMemberInfo]:
        """Parse one local header, or None when this is not a member record."""
        handle.seek(offset)
        raw = handle.read(_LOCAL_HEADER_SIZE)
        if len(raw) < _LOCAL_HEADER_SIZE:
            return None

        fields = _LOCAL_HEADER_STRUCT.unpack(raw)
        signature = fields[0]
        if signature != _LOCAL_HEADER_SIG:
            return None

        flags, compress_type = fields[3], fields[4]
        crc32, compress_size, file_size = fields[7], fields[8], fields[9]
        name_len, extra_len = fields[10], fields[11]

        name_bytes = handle.read(name_len)
        extra = handle.read(extra_len)
        if len(name_bytes) < name_len or len(extra) < extra_len:
            return None

        need_zip64 = compress_size == 0xFFFFFFFF or file_size == 0xFFFFFFFF
        z_uncompressed, z_compressed = _read_zip64_extra(extra, need_zip64)
        if z_uncompressed is not None:
            file_size = z_uncompressed
        if z_compressed is not None:
            compress_size = z_compressed

        name = name_bytes.decode("utf-8", errors="replace").replace("\\", "/")
        return ZipMemberInfo(
            name=name,
            header_offset=offset,
            data_offset=offset + _LOCAL_HEADER_SIZE + name_len + extra_len,
            compress_type=compress_type,
            compress_size=compress_size,
            file_size=file_size,
            crc32=crc32,
            flags=flags,
            is_dir=name.endswith("/"),
        )

    @log_call
    def probe(self) -> ArchiveSurvey:
        """Walk headers only. Reads no member data.

        Returns:
            ArchiveSurvey: members found, plus whether the archive is truncated.
        """
        survey = ArchiveSurvey(file_size=self.file_size)
        offset = 0

        with open(self.archive_path, "rb") as handle:
            while offset < self.file_size:
                member = self._read_local_header(handle, offset)
                if member is None:
                    handle.seek(offset)
                    signature = handle.read(4)
                    if signature == _CENTRAL_DIR_SIG:
                        survey.has_central_directory = True
                        survey.stopped_reason = "central_directory"
                    elif signature == _EOCD_SIG:
                        survey.stopped_reason = "eocd"
                    elif not signature:
                        survey.stopped_reason = "eof"
                    else:
                        survey.stopped_reason = f"unrecognized_signature:{signature!r}"
                    break

                if member.sizes_deferred and member.compress_size == 0:
                    # Size lives in a trailing data descriptor, so the next header's
                    # offset is unknown without scanning for it. Rare in publisher
                    # archives; unproven against real data, so refuse rather than
                    # guess and silently mis-walk the remainder.
                    survey.members.append(member)
                    survey.stopped_reason = "deferred_sizes_unsupported"
                    logger.warning(
                        "Member %s defers its sizes to a data descriptor; forward walk "
                        "cannot determine the next header offset. Stopping.",
                        member.name,
                    )
                    break

                survey.members.append(member)
                offset = member.data_offset + member.compress_size
                survey.declared_end = offset

                # A seek beyond EOF does not raise -- the next read simply returns
                # b"". Without this check the walk reports a clean "eof" while
                # sitting hundreds of megabytes past the end of the file.
                if offset > self.file_size:
                    survey.stopped_reason = "truncated"
                    break

        if survey.truncated:
            logger.warning(
                "%s is truncated: headers declare %d bytes, file holds %d (%d short). "
                "%d of %d members are recoverable.",
                self.archive_path.name,
                survey.declared_end,
                self.file_size,
                survey.overrun_bytes,
                len(survey.complete_members),
                len(survey.members),
            )
        return survey

    # -- extraction --------------------------------------------------------

    def _inflate_member(self, handle: BinaryIO, member: ZipMemberInfo, sink: BinaryIO) -> Tuple[int, int]:
        """Stream one member into ``sink``. Returns (bytes_written, crc)."""
        handle.seek(member.data_offset)
        remaining = member.compress_size
        if member.compress_type == _DEFLATED:
            decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
        elif member.compress_type == _DEFLATED64:
            decompressor = deflate64.Deflate64()
        else:
            decompressor = None
        crc = 0
        written = 0

        while remaining > 0:
            block = handle.read(min(self.chunk_size, remaining))
            if not block:
                raise EOFError(
                    f"{member.name}: archive ended {remaining} bytes early "
                    f"(member data begins at {member.data_offset})"
                )
            remaining -= len(block)
            self.stats.bytes_read += len(block)

            chunk = decompressor.decompress(block) if decompressor else block
            if chunk:
                crc = zlib.crc32(chunk, crc)
                sink.write(chunk)
                written += len(chunk)

        if decompressor:
            tail = decompressor.flush()
            if tail:
                crc = zlib.crc32(tail, crc)
                sink.write(tail)
                written += len(tail)

        return written, crc & 0xFFFFFFFF

    @log_call
    def walk(
        self,
        want: Optional[Callable[[ZipMemberInfo], bool]] = None,
        sink_factory: Optional[Callable[[ZipMemberInfo], Optional[BinaryIO]]] = None,
        survey: Optional[ArchiveSurvey] = None,
    ) -> Iterator[Tuple[ZipMemberInfo, bool]]:
        """Walk members, extracting the ones ``want`` accepts.

        ``want`` is evaluated **before** any member data is read, so selecting a
        handful of files from a 52 GB archive costs a header walk rather than a
        full read. That is why probe and extract are the same traversal.

        ``sink_factory`` returns a writable binary handle for a member, or None
        to skip it. Taking a factory rather than a destination directory keeps
        path policy -- flattening, projection, long-path budgets -- with the
        caller, where it belongs.

        Yields:
            (member, extracted) for every member considered. The flag makes a
            deliberate skip distinguishable from a member that could not be read;
            failures are recorded in :attr:`stats` either way.
        """
        survey = survey or self.probe()
        recoverable = {id(m) for m in survey.complete_members}

        with open(self.archive_path, "rb") as handle:
            for member in survey.members:
                if member.is_dir:
                    continue

                if id(member) not in recoverable:
                    self.stats.unreadable += 1
                    self.stats.failures.append((member.name, "truncated: data past end of archive"))
                    yield member, False
                    continue

                if want is not None and not want(member):
                    self.stats.skipped += 1
                    yield member, False
                    continue

                if member.compress_type not in self.supported_methods():
                    reason = (
                        "deflate64 (method 9) requires the optional 'zipfile-deflate64' "
                        "package, which is not installed"
                        if member.compress_type == _DEFLATED64
                        else f"unsupported compression method {member.compress_type}"
                    )
                    self.stats.unreadable += 1
                    self.stats.failures.append((member.name, reason))
                    yield member, False
                    continue

                sink = sink_factory(member) if sink_factory else None
                if sink is None:
                    self.stats.skipped += 1
                    yield member, False
                    continue

                try:
                    with sink:
                        written, crc = self._inflate_member(handle, member, sink)
                except (EOFError, zlib.error, OSError) as exc:
                    self.stats.unreadable += 1
                    self.stats.failures.append((member.name, f"{type(exc).__name__}: {exc}"))
                    yield member, False
                    continue

                self.stats.extracted += 1
                self.stats.bytes_written += written

                if member.crc32 and crc != member.crc32:
                    self.stats.crc_fail += 1
                    self.stats.failures.append(
                        (member.name, f"CRC mismatch: header {member.crc32:08x}, read {crc:08x}")
                    )
                elif member.crc32:
                    self.stats.crc_ok += 1

                if member.file_size and written != member.file_size:
                    self.stats.size_mismatch += 1
                    self.stats.failures.append(
                        (member.name, f"size mismatch: header {member.file_size}, wrote {written}")
                    )

                yield member, True
