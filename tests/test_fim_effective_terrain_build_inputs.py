"""Build-input identities are captured before staging and compared before publishing."""

import os

from ras_commander.fim import _effective_terrain as et


def _info(tmp_path):
    hdf = tmp_path / "Terrain.hdf"
    src = tmp_path / "Terrain.source.tif"
    hdf.write_bytes(b"h" * 8)
    src.write_bytes(b"s" * 16)
    return {"terrain_hdf": str(hdf), "sources": [src.name]}, src


def test_build_inputs_record_terrain_hdf_and_sources(tmp_path):
    info, src = _info(tmp_path)
    inputs = et._build_inputs(info)
    assert inputs["terrain_hdf"]["size"] == 8
    assert [s["size"] for s in inputs["sources"]] == [16]
    assert inputs["sources"][0]["path"] == str(src.resolve())


def test_build_inputs_detect_a_source_edited_during_the_build(tmp_path):
    info, src = _info(tmp_path)
    before = et._build_inputs(info)
    assert et._build_inputs(info) == before
    stat = src.stat()
    src.write_bytes(b"s" * 17)
    os.utime(src, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert et._build_inputs(info) != before
