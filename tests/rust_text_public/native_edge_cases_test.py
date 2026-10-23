"""Synthetic edge and corruption cases for the native text bindings.

These supplement (never replace) the real-corpus tests in
``real_corpus_test.py``. Every test here requires the native extension.
"""

from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest

from ras_commander import fast_text
from ras_commander.fast_text import FastText, FastTextError, FastTextParseError
from ras_commander.geom.GeomCrossSection import GeomCrossSection

from .conftest import record


def slots(values, width=8):
    return "".join(f"{v:>{width}}" for v in values)


def geometry(newline="\r\n", final=True, sta_count=None, sta_values=None, extra=""):
    sta_values = sta_values or [0, 100, 50, 90, 100, 100]
    sta_count = len(sta_values) // 2 if sta_count is None else sta_count
    lines = [
        "Geom Title=Synthetic",
        "Program Version=6.60",
        "River Reach=Creek,Main",
        "Type RM Length L Ch R = 1 ,100     ,50,50,50",
        "Node Name=Upper",
        "BEGIN DESCRIPTION:",
        "Note: a=b with equals",
        "END DESCRIPTION:",
        f"#Sta/Elev= {sta_count} ",
        slots(sta_values),
        "#Mann= 3 ,0 ,0 ",
        slots([0, ".06", 0, 40, ".04", 0, 60, ".06", 0]),
        "Bank Sta=40,60",
        "Type RM Length L Ch R = 1 ,50      ,0,0,0",
        "#Sta/Elev= 2 ",
        slots([0, 95, 10, 96]),
        "Bank Sta=0,10",
    ]
    text = newline.join(lines) + extra
    return (text + (newline if final else "")).encode("latin-1")


@pytest.fixture
def geom_file(tmp_path):
    def write(data: bytes, name="synthetic.g01"):
        path = tmp_path / name
        path.write_bytes(data)
        return path

    return write


@pytest.mark.parametrize("newline", ["\r\n", "\n", "\r"])
@pytest.mark.parametrize("final", [True, False])
def test_index_spans_cover_bytes_exactly(native, newline, final):
    data = b"\xef\xbb\xbf" + geometry(newline, final) + b"Junk=\xe9\x00\xff"
    index = FastText.document_index(data)
    lines = index["lines"]
    assert lines[0, 0] == 0 and lines[-1, 2] == len(data)
    assert (lines[1:, 0] == lines[:-1, 2]).all(), "lines must tile the buffer"
    assert b"".join(data[s:e] for s, _, e in lines) == data
    enc = index["encoding"]
    assert enc["utf8_bom"] is True and enc["nul_bytes"] == 1 and enc["non_ascii_bytes"] >= 5
    assert enc["final_newline"] is False  # the appended junk line is unterminated
    key_names = {data[k[1]:k[2]] for k in index["keys"]}
    assert b"Note: a" not in key_names, "'=' inside a description is not a key"
    out, spans = FastText.apply_edits(data, [])
    assert out == data and spans == []


def test_mixed_newlines_and_duplicate_keys(native):
    data = b"A=1\nA=2\r\nB=3\rC=4"
    index = FastText.document_index(data)
    enc = index["encoding"]
    assert (enc["lf"], enc["crlf"], enc["cr"], enc["final_newline"]) == (1, 1, 1, False)
    assert dict(index["key_counts"])[b"A"] == 2


def test_raw_batch_edits_are_atomic(native):
    data = b"0123456789"
    out, spans = FastText.apply_edits(data, [(6, 8, b"XY-", "b"), (0, 2, b"", "a")])
    assert out == b"2345XY-89"
    assert spans == [("a", 0, 2, 0, 0), ("b", 6, 8, 4, 7)]
    for bad in (
        [(0, 4, b"x", "a"), (3, 5, b"y", "b")],  # overlap
        [(4, 4, b"x", "a"), (4, 6, b"y", "b")],  # ambiguous same-offset insert
        [(8, 11, b"x", "a")],  # out of range
        [(5, 3, b"x", "a")],  # reversed
    ):
        with pytest.raises(ValueError) as err:
            FastText.apply_edits(data, bad)
        assert type(err.value).__name__ == "TextEditError"


def test_typed_reads_match_python_reference(required_native, geom_file, monkeypatch):
    path = geom_file(geometry())
    native_xs = FastText.get_cross_sections(path)
    native_se = FastText.get_station_elevation(path, "Creek", "Main", "100")
    native_mn = FastText.get_mannings_n(path, "Creek", "Main", "100")
    native_bank = FastText.get_bank_stations(path, "Creek", "Main", "100")
    monkeypatch.undo()  # explicit Python reference after native results exist
    pd.testing.assert_frame_equal(native_xs, GeomCrossSection.get_cross_sections(path))
    pd.testing.assert_frame_equal(
        native_se, GeomCrossSection.get_station_elevation(path, "Creek", "Main", "100")
    )
    pd.testing.assert_frame_equal(
        native_mn, GeomCrossSection.get_mannings_n(path, "Creek", "Main", "100")
    )
    assert native_bank == GeomCrossSection.get_bank_stations(path, "Creek", "Main", "100")
    assert native_xs.loc[0, "NodeName"] == "Upper"


@pytest.mark.parametrize("declared", [5, 15])  # short last line / payload cut by next key
def test_truncated_block_raises_instead_of_partial(required_native, geom_file, monkeypatch, declared):
    path = geom_file(geometry(sta_count=declared))  # payload has only 3 pairs
    index = FastText.geometry_index(path)
    codes = set(index.diagnostics["code"])
    assert codes & {"count-mismatch", "blank-slot"}, codes
    record("edge_cases", f"truncated_{declared}_codes", sorted(codes))
    assert bool(index.blocks["malformed"].iloc[0])
    with pytest.raises(FastTextParseError):
        FastText.get_station_elevation(path, "Creek", "Main", "100")
    assert FastText.document_index(path)["lines"][-1, 2] == path.stat().st_size
    monkeypatch.undo()
    partial = GeomCrossSection.get_station_elevation(path, "Creek", "Main", "100")
    record("edge_cases", f"python_truncated_{declared}_rows", len(partial))  # Python salvages


@pytest.mark.parametrize("count", ["4000000000", "18446744073709551616", "-3", "x"])
def test_huge_or_invalid_counts_are_diagnosed(native, geom_file, count):
    data = geometry().replace(b"#Sta/Elev= 3 ", f"#Sta/Elev= {count} ".encode())
    index = FastText.geometry_index(geom_file(data))
    assert index.error_count >= 1
    assert FastText.document_index(data)["lines"][-1, 2] == len(data)


def test_blank_slot_is_an_error_not_a_guess(native, geom_file):
    data = geometry(sta_values=[0, 100, 50, " ", 100, 100])
    index = FastText.geometry_index(geom_file(data))
    assert "blank-slot" in set(index.diagnostics["code"])
    with pytest.raises(FastTextParseError):
        index.station_elevation(0)


def test_duplicate_node_first_wins(native, geom_file):
    data = geometry().replace(b",50      ,0,0,0", b",100     ,0,0,0")
    index = FastText.geometry_index(geom_file(data))
    assert "duplicate-node-id" in set(index.diagnostics["code"])
    assert index.find_node("Creek", "Main", "100") == 0


def test_edit_preserves_newlines_and_unedited_bytes(required_native, geom_file, tmp_path):
    source = geom_file(geometry("\n", final=False))
    original = source.read_bytes()
    dest = tmp_path / "out" / "edited.g01"
    result = FastText.edit_geometry(
        source,
        dest,
        [
            {"op": "station_elevation", "river": "Creek", "reach": "Main", "rs": "50",
             "values": [[0, 94.5], [5, 94.0], [10, 96.25]]},
            {"op": "bank_stations", "river": "Creek", "reach": "Main", "rs": "100",
             "values": (40.25, 60)},
        ],
    )
    assert source.read_bytes() == original
    out = dest.read_bytes()
    assert b"\r" not in out and not out.endswith(b"\n")
    rebuilt, pos = bytearray(), 0
    for _, start, end, new_start, new_end in sorted(result["spans"], key=lambda s: s[1]):
        rebuilt += original[pos:start]
        assert len(rebuilt) == new_start
        rebuilt += out[new_start:new_end]
        pos = end
    assert bytes(rebuilt) + original[pos:] == out
    se = FastText.get_station_elevation(dest, "Creek", "Main", "50")
    assert se.to_numpy().tolist() == [[0, 94.5], [5, 94.0], [10, 96.25]]
    assert FastText.get_bank_stations(dest, "Creek", "Main", "100") == (40.25, 60.0)


@pytest.mark.parametrize(
    "edits, error",
    [
        ([{"op": "bank_stations", "river": "Creek", "reach": "Main", "rs": "100",
           "values": (40, 200)}], ValueError),  # outside station range
        ([{"op": "station_elevation", "river": "Creek", "reach": "Main", "rs": "100",
           "values": [[0, np.nan]]}], ValueError),  # non-finite
        ([{"op": "station_elevation", "river": "Creek", "reach": "Main", "rs": "100",
           "values": [[10, 1], [0, 1]]}], ValueError),  # decreasing stations
        ([{"op": "mannings_n", "river": "Creek", "reach": "Main", "rs": "100",
           "values": [[0, 0.05, 0]] * 21}], ValueError),  # > 20 blocks
        ([{"op": "bank_stations", "river": "Creek", "reach": "Main", "rs": "100",
           "values": (40, 60)}] * 2, ValueError),  # same node twice -> overlap
        ([{"op": "mannings_n", "river": "Creek", "reach": "Main", "rs": "999",
           "values": [[0, 0.05, 0]]}], ValueError),  # not found
        ([{"op": "levee", "river": "Creek", "reach": "Main", "rs": "100",
           "values": [[0, 1]]}], ValueError),  # unsupported family
    ],
)
def test_invalid_batches_write_nothing(native, geom_file, tmp_path, edits, error):
    source = geom_file(geometry())
    dest = tmp_path / "edited.g01"
    with pytest.raises(error):
        FastText.edit_geometry(source, dest, edits)
    assert not dest.exists()


def test_edit_refuses_malformed_block_and_source_overwrite(native, geom_file, tmp_path):
    source = geom_file(geometry(sta_count=5))
    edit = [{"op": "station_elevation", "river": "Creek", "reach": "Main", "rs": "100",
             "values": [[0, 1], [1, 2]]}]
    with pytest.raises(FastTextParseError):
        FastText.edit_geometry(source, tmp_path / "x.g01", edit)
    with pytest.raises(ValueError):
        FastText.edit_geometry(source, source, edit)
    existing = tmp_path / "exists.g01"
    existing.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        FastText.edit_geometry(geom_file(geometry(), "ok.g01"), existing, [])
    assert existing.read_bytes() == b"keep"


def test_non_ascii_identifiers_decode_like_python(required_native, geom_file, monkeypatch):
    data = geometry().replace(b"Creek,Main", "Crëek,Mäin".encode("utf-8"))
    data = data.replace(b"Node Name=Upper", b"Node Name=Up\xe9r")  # invalid UTF-8
    path = geom_file(data)
    native_xs = FastText.get_cross_sections(path)
    monkeypatch.undo()
    pd.testing.assert_frame_equal(native_xs, GeomCrossSection.get_cross_sections(path))
    assert native_xs.loc[0, "River"] == "Crëek"


def test_backend_selection_and_unavailable_native(geom_file, monkeypatch):
    path = geom_file(geometry())
    real_import = importlib.import_module

    def no_native(name, *args, **kwargs):
        if name == "ras_commander_fast_hdf":
            raise ImportError("simulated missing extension")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(fast_text.importlib, "import_module", no_native)
    with pytest.raises(FastTextError):
        FastText.get_cross_sections(path, backend="rust")
    monkeypatch.setenv("RAS_COMMANDER_FAST_TEXT", "required")
    with pytest.raises(FastTextError):
        FastText.get_cross_sections(path)
    monkeypatch.delenv("RAS_COMMANDER_FAST_TEXT")
    before = sum(fast_text.NATIVE_CALLS.values())
    auto = FastText.get_cross_sections(path)  # auto -> explicit Python reference
    assert sum(fast_text.NATIVE_CALLS.values()) == before
    pd.testing.assert_frame_equal(auto, GeomCrossSection.get_cross_sections(path))
    with pytest.raises(ValueError):
        FastText.get_cross_sections(path, backend="fortran")
