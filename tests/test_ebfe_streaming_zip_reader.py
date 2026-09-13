"""StreamingZipReader: recovering archives that ``zipfile`` refuses.

Modelled on FEMA eBFE HUC 12100302 (Medina), a 52.09 GB published object whose
local headers declare 53.02 GB of member data. Its last member runs 935,101,777
bytes past the end of the file and the central directory -- which would have
followed it -- was never written. The object matches its published
``Content-Length`` and ETag, so the truncation is at the publisher.

These build the same shape at a size that fits in a test.
"""

from __future__ import annotations

import io
import os
import struct
import zipfile
import zlib
from pathlib import Path

import pytest

from ras_commander.sources.federal import ebfe_extract as ebfe_extract_module
from ras_commander.sources.federal.ebfe_extract import StreamingZipReader
from ras_commander.sources.federal.ebfe_extract import _read_zip64_extra

PAYLOAD = {
    "model/project.prj": b"Proj Title=Test\n" * 400,
    "model/terrain.bin": os.urandom(250_000),
    "docs/readme.txt": b"delivered documentation",
}


@pytest.fixture
def intact_archive(tmp_path: Path) -> Path:
    path = tmp_path / "delivery.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in PAYLOAD.items():
            archive.writestr(name, data)
    return path


@pytest.fixture
def truncated_archive(intact_archive: Path, tmp_path: Path) -> Path:
    """Cut mid-member, so the central directory and the tail are both gone."""
    raw = intact_archive.read_bytes()
    path = tmp_path / "truncated.zip"
    path.write_bytes(raw[: int(len(raw) * 0.55)])
    return path


def sink_factory(destination: Path):
    def make(member):
        target = destination / member.name
        target.parent.mkdir(parents=True, exist_ok=True)
        return open(target, "wb")

    return make


# -- intact archives ------------------------------------------------------

def test_probe_reports_intact_archive(intact_archive):
    survey = StreamingZipReader(intact_archive).probe()
    assert len(survey.members) == len(PAYLOAD)
    assert not survey.truncated
    assert survey.overrun_bytes == 0
    assert survey.has_central_directory


def test_extraction_is_byte_identical_and_crc_verified(intact_archive, tmp_path):
    out = tmp_path / "out"
    reader = StreamingZipReader(intact_archive)
    list(reader.walk(sink_factory=sink_factory(out)))

    assert reader.stats.extracted == len(PAYLOAD)
    assert reader.stats.crc_ok == len(PAYLOAD)
    assert reader.stats.crc_fail == 0
    assert reader.stats.size_mismatch == 0
    for name, data in PAYLOAD.items():
        assert (out / name).read_bytes() == data


def test_want_is_evaluated_before_member_data_is_read(intact_archive, tmp_path):
    """Selecting a few files from a huge archive must not read the whole thing.

    This is why probe and extract are one traversal rather than two.
    """
    reader = StreamingZipReader(intact_archive)
    extracted = [
        member.name
        for member, took in reader.walk(
            want=lambda m: m.name.endswith(".prj"),
            sink_factory=sink_factory(tmp_path / "sel"),
        )
        if took
    ]
    assert extracted == ["model/project.prj"]
    assert reader.stats.skipped == len(PAYLOAD) - 1
    # Far less than the whole archive: the skipped members were never inflated.
    assert reader.stats.bytes_read < intact_archive.stat().st_size // 2


# -- truncated archives ---------------------------------------------------

def test_zipfile_cannot_open_what_this_reader_recovers(truncated_archive):
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(truncated_archive)

    survey = StreamingZipReader(truncated_archive).probe()
    assert survey.complete_members, "forward walk should still recover leading members"


def test_probe_detects_truncation_rather_than_reporting_clean_eof(truncated_archive):
    """A seek past EOF does not raise -- the next read just returns b"".

    Without an explicit check the walk reports a tidy "eof" while positioned
    far beyond the end of the file, which is how a truncated 52 GB delivery
    looks like a healthy one.
    """
    survey = StreamingZipReader(truncated_archive).probe()
    assert survey.truncated
    assert survey.overrun_bytes > 0
    assert survey.declared_end > survey.file_size
    assert survey.stopped_reason == "truncated"
    assert not survey.has_central_directory


def test_truncated_members_are_unreadable_not_silently_short(truncated_archive, tmp_path):
    reader = StreamingZipReader(truncated_archive)
    results = list(reader.walk(sink_factory=sink_factory(tmp_path / "partial")))

    recovered = [m.name for m, took in results if took]
    assert recovered, "complete members must still be recovered"
    assert reader.stats.unreadable >= 1
    assert reader.stats.crc_fail == 0, "recovered members must verify, or not count as recovered"
    assert reader.stats.failures_of("truncated"), "truncation must be reported by kind"
    assert reader.stats.truncated >= 1


def test_failure_kinds_do_not_conflate_truncation_with_crc(truncated_archive, tmp_path):
    """Truncated members are never read, so they can never fail a CRC.

    Counting them as CRC failures -- or counting both ``stats.truncated`` and
    ``survey.truncated_members`` -- misstates integrity in opposite directions.
    """
    reader = StreamingZipReader(truncated_archive)
    survey = reader.probe()
    list(reader.walk(sink_factory=sink_factory(tmp_path / "kinds"), survey=survey))

    assert reader.stats.crc_fail == 0
    assert reader.stats.truncated == len(survey.truncated_members)
    assert reader.stats.truncated <= reader.stats.unreadable
    assert not reader.stats.failures_of("crc")
    assert {f[1] for f in reader.stats.failures} <= {
        "truncated", "unsupported", "read", "crc", "size",
    }


def test_verified_is_an_alias_for_crc_ok(intact_archive, tmp_path):
    """A silent zero here would be the worst possible failure -- it stands in for hashing."""
    reader = StreamingZipReader(intact_archive)
    list(reader.walk(sink_factory=sink_factory(tmp_path / "alias")))
    assert reader.stats.verified == reader.stats.crc_ok == len(PAYLOAD)


def test_projected_bytes_counts_only_recoverable_members(truncated_archive):
    survey = StreamingZipReader(truncated_archive).probe()
    assert survey.projected_bytes == sum(
        m.file_size for m in survey.complete_members if not m.is_dir
    )
    assert survey.projected_bytes < sum(len(d) for d in PAYLOAD.values())


def test_truncated_local_header_is_reported_as_truncated(intact_archive, tmp_path):
    with zipfile.ZipFile(intact_archive) as archive:
        second_header = archive.infolist()[1].header_offset
    cut = tmp_path / "header_cut.zip"
    cut.write_bytes(intact_archive.read_bytes()[: second_header + 10])

    survey = StreamingZipReader(cut).probe()

    assert survey.truncated
    assert survey.stopped_reason == "truncated_header"


def test_crc_mismatch_is_not_success_and_clears_seekable_output(tmp_path):
    archive_path = tmp_path / "stored.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("payload.bin", b"correct payload")
    survey = StreamingZipReader(archive_path).probe()
    raw = bytearray(archive_path.read_bytes())
    raw[survey.members[0].data_offset] ^= 0x01
    archive_path.write_bytes(raw)

    out = tmp_path / "crc_out"
    reader = StreamingZipReader(archive_path)
    results = list(reader.walk(sink_factory=sink_factory(out)))

    assert results == [(reader.probe().members[0], False)]
    assert reader.stats.extracted == 0
    assert reader.stats.unreadable == 1
    assert reader.stats.crc_fail == 1
    assert (out / "payload.bin").read_bytes() == b""


def test_zero_declared_size_is_still_validated(intact_archive, tmp_path):
    reader = StreamingZipReader(intact_archive)
    survey = reader.probe()
    member = survey.members[0]
    member.file_size = 0
    out = tmp_path / "size_out"

    results = list(
        reader.walk(
            want=lambda candidate: candidate is member,
            sink_factory=sink_factory(out),
            survey=survey,
        )
    )

    assert results[0] == (member, False)
    assert reader.stats.size_mismatch == 1
    assert reader.stats.extracted == 0
    assert (out / member.name).read_bytes() == b""


def test_missing_archive_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        StreamingZipReader(tmp_path / "nope.zip")


@pytest.mark.parametrize(
    "need_uncompressed, need_compressed, expected",
    [
        (True, False, (123, None)),
        (False, True, (None, 123)),
    ],
)
def test_zip64_extra_honors_one_sided_size_fields(
    need_uncompressed, need_compressed, expected
):
    extra = struct.pack("<HHQ", 0x0001, 8, 123)
    assert _read_zip64_extra(extra, need_uncompressed, need_compressed) == expected


def test_local_header_uses_cp437_when_utf8_flag_is_absent(tmp_path):
    payload = b"legacy filename"
    name = "caf\u00e9.txt"
    name_bytes = name.encode("cp437")
    header = struct.pack(
        "<IHHHHHIIIHH",
        0x04034B50,
        20,
        0,
        zipfile.ZIP_STORED,
        0,
        0,
        zlib.crc32(payload) & 0xFFFFFFFF,
        len(payload),
        len(payload),
        len(name_bytes),
        0,
    )
    archive_path = tmp_path / "cp437.zip"
    archive_path.write_bytes(header + name_bytes + payload)

    survey = StreamingZipReader(archive_path).probe()

    assert [member.name for member in survey.members] == [name]


# -- data-descriptor members: the central directory must win -----------------

class _NonSeekable(io.BytesIO):
    """Force zipfile to defer sizes to data descriptors (flag bit 3).

    zipfile decides by *attempting* a seek and catching the error, not by
    asking ``seekable()`` -- so the seek itself has to fail.
    """

    def seekable(self) -> bool:
        return False

    def seek(self, *args, **kwargs):
        raise io.UnsupportedOperation("non-seekable test stream")


@pytest.fixture
def descriptor_archive(tmp_path: Path) -> Path:
    """Every member carries flag bit 3: sizes and CRC live after the data.

    zipfile writes archives this way whenever its output is not seekable --
    streamed uploads, pipes, some publisher tooling. A healthy archive, with a
    central directory, that a forward header walk cannot get past.
    """
    buffer = _NonSeekable()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in PAYLOAD.items():
            archive.writestr(name, data)
    path = tmp_path / "descriptor.zip"
    path.write_bytes(buffer.getvalue())
    with zipfile.ZipFile(path) as check:
        assert all(info.flag_bits & 0x08 for info in check.infolist()), "fixture must defer sizes"
    return path


def test_probe_uses_central_directory_past_deferred_size_members(descriptor_archive):
    """Regression: two eBFE studies were scored against a one-member index.

    The forward walk stops at the first deferred-size member. With a central
    directory available that is the wrong tool -- the directory has every
    member with authoritative sizes.
    """
    survey = StreamingZipReader(descriptor_archive).probe()
    assert survey.has_central_directory
    assert survey.stopped_reason == "central_directory"
    assert len(survey.members) == len(PAYLOAD)
    assert not survey.truncated
    assert all(m.compress_size > 0 and m.file_size > 0 for m in survey.members if not m.is_dir)


def test_walk_extracts_deferred_size_members_byte_identical(descriptor_archive, tmp_path):
    out = tmp_path / "desc_out"
    reader = StreamingZipReader(descriptor_archive)
    list(reader.walk(sink_factory=sink_factory(out)))
    assert reader.stats.extracted == len(PAYLOAD)
    assert reader.stats.crc_fail == 0 and reader.stats.size_mismatch == 0
    for name, data in PAYLOAD.items():
        assert (out / name).read_bytes() == data


def test_forward_walk_is_still_used_when_directory_is_absent(truncated_archive):
    """The Medina path is untouched: no directory means the forward walk, with truncation detected."""
    survey = StreamingZipReader(truncated_archive).probe()
    assert not survey.has_central_directory
    assert survey.stopped_reason == "truncated"


# -- deflate64 decompressors have no flush() ---------------------------------

def test_finish_decompressor_tolerates_a_decompressor_without_flush():
    """``zipfile_deflate64.Deflate64`` returns everything from ``decompress()`` and
    has no ``flush``. Middle Guadalupe (12100202) ships 343 of 386 members as
    deflate64; on an EOCD-less archive the forward walk would have aborted on
    the first of them with an ``AttributeError`` the walk does not catch."""

    class NoFlush:
        def decompress(self, block):
            return block

    assert StreamingZipReader._finish_decompressor(NoFlush()) == b""

    import zlib
    assert StreamingZipReader._finish_decompressor(zlib.decompressobj(-zlib.MAX_WBITS)) == b""


def test_deflate64_value_error_is_reported_as_unreadable(monkeypatch, tmp_path):
    class InvalidDeflate64:
        def decompress(self, block):
            raise ValueError("Bad Deflate64 data")

    name_bytes = b"payload.bin"
    compressed = b"bad"
    header = struct.pack(
        "<IHHHHHIIIHH",
        0x04034B50,
        20,
        0,
        9,
        0,
        0,
        0,
        len(compressed),
        1,
        len(name_bytes),
        0,
    )
    archive_path = tmp_path / "invalid_deflate64.zip"
    archive_path.write_bytes(header + name_bytes + compressed)
    monkeypatch.setattr(ebfe_extract_module, "_DEFLATE64_AVAILABLE", True)
    monkeypatch.setattr(
        ebfe_extract_module,
        "deflate64",
        type("Deflate64Module", (), {"Deflate64": InvalidDeflate64}),
    )

    reader = StreamingZipReader(archive_path)
    results = list(reader.walk(sink_factory=sink_factory(tmp_path / "invalid_out")))

    assert results[0][1] is False
    assert reader.stats.extracted == 0
    assert reader.stats.unreadable == 1
    assert reader.stats.failures_of("read")


# -- streamed archives with no central directory (Little Red) ------------------

def _strip_central_directory(path: Path) -> Path:
    """Cut the archive at the start of its central directory: a streamed zip
    truncated at the publisher, exactly Little Red (11010014)."""
    with zipfile.ZipFile(path) as archive:
        start = archive.start_dir
    raw = path.read_bytes()[:start]
    out = path.with_name("streamed_no_cd.zip")
    out.write_bytes(raw)
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(out)
    return out


def test_deferred_size_members_are_walked_without_a_central_directory(descriptor_archive):
    """Little Red: 37 GB, every member deferred, no directory, no EOCD. The
    walk must recover every member by inflating to end-of-stream, not stop at
    the first one and audit zero bytes."""
    streamed = _strip_central_directory(descriptor_archive)
    survey = StreamingZipReader(streamed).probe()
    assert not survey.has_central_directory
    assert survey.stopped_reason in ("eof", "clean")   # the walk ends exactly at EOF
    assert [m.name for m in survey.members] == list(PAYLOAD)
    assert not survey.truncated
    for m in survey.members:
        assert m.file_size == len(PAYLOAD[m.name])
        assert m.compress_size > 0
        assert m.crc32 == zlib.crc32(PAYLOAD[m.name]) & 0xFFFFFFFF


def test_deferred_size_members_extract_byte_identical_without_a_central_directory(descriptor_archive, tmp_path):
    streamed = _strip_central_directory(descriptor_archive)
    out = tmp_path / "streamed_out"
    reader = StreamingZipReader(streamed)
    list(reader.walk(sink_factory=sink_factory(out)))
    assert reader.stats.extracted == len(PAYLOAD)
    assert reader.stats.crc_fail == 0 and reader.stats.size_mismatch == 0
    for name, data in PAYLOAD.items():
        assert (out / name).read_bytes() == data


def test_probe_limit_stops_deferred_member_scan(descriptor_archive):
    streamed = _strip_central_directory(descriptor_archive)
    survey = StreamingZipReader(streamed, max_probe_member_size=10).probe()

    assert survey.stopped_reason == "deferred_sizes_unsupported"
    assert not survey.complete_members


def test_unresolved_deferred_stored_member_is_not_an_empty_success(tmp_path):
    buffer = _NonSeekable()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("payload.bin", b"nonempty")
    complete = tmp_path / "streamed_stored_complete.zip"
    complete.write_bytes(buffer.getvalue())
    streamed = _strip_central_directory(complete)

    reader = StreamingZipReader(streamed)
    survey = reader.probe()
    results = list(reader.walk(sink_factory=sink_factory(tmp_path / "stored_out"), survey=survey))

    assert survey.stopped_reason == "deferred_sizes_unsupported"
    assert not survey.complete_members
    assert results == [(survey.members[0], False)]
    assert reader.stats.extracted == 0
    assert reader.stats.unreadable == 1
    assert reader.stats.failures_of("unsupported")


def test_streamed_archive_truncated_mid_member_reports_truncation(descriptor_archive, tmp_path):
    streamed = _strip_central_directory(descriptor_archive)
    raw = streamed.read_bytes()
    cut = streamed.with_name("streamed_truncated.zip")
    cut.write_bytes(raw[: int(len(raw) * 0.6)])
    survey = StreamingZipReader(cut).probe()
    assert survey.truncated
    assert survey.stopped_reason == "truncated"
    assert survey.complete_members, "leading members must still be recovered"
    assert len(survey.complete_members) < len(PAYLOAD)
    reader = StreamingZipReader(cut)
    results = list(reader.walk(sink_factory=sink_factory(tmp_path / "cut_out"), survey=survey))
    assert reader.stats.truncated >= 1 and reader.stats.crc_fail == 0
    assert [m.name for m, took in results if took] == [m.name for m in survey.complete_members if not m.is_dir]
