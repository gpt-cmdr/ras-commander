"""StreamingZipReader: recovering archives that ``zipfile`` refuses.

Modelled on FEMA eBFE HUC 12100302 (Medina), a 52.09 GB published object whose
local headers declare 53.02 GB of member data. Its last member runs 935,101,777
bytes past the end of the file and the central directory -- which would have
followed it -- was never written. The object matches its published
``Content-Length`` and ETag, so the truncation is at the publisher.

These build the same shape at a size that fits in a test.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from ras_commander.sources.federal.ebfe_extract import StreamingZipReader

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
    assert any("truncated" in reason for _, reason in reader.stats.failures)


def test_projected_bytes_counts_only_recoverable_members(truncated_archive):
    survey = StreamingZipReader(truncated_archive).probe()
    assert survey.projected_bytes == sum(
        m.file_size for m in survey.complete_members if not m.is_dir
    )
    assert survey.projected_bytes < sum(len(d) for d in PAYLOAD.values())


def test_missing_archive_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        StreamingZipReader(tmp_path / "nope.zip")
