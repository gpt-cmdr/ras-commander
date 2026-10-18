"""Real-file qualification of the native text bindings and public adapter.

Requires ``RAS_TEXT_CORPUS`` (see ``conftest.py``). Every corpus file is a
local RasExamples extraction recorded in ``corpus-manifest.json`` with its
SHA256; tests assert those hashes are unchanged afterwards. Python reference
values are computed first with the existing ``GeomCrossSection`` readers;
native values are then computed with every Python reader patched to fail.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ras_commander import RasExamples, RasPrj, init_ras_project
from ras_commander.fast_text import FastText, FastTextParseError
from ras_commander.geom.GeomCrossSection import GeomCrossSection
from ras_commander.geom.GeomStorage import GeomStorage

from .conftest import record

FAMILY_TEXT = re.compile(r"\.(prj|[gpfu]\d\d)$", re.IGNORECASE)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def major(version):
    return "none" if version is None else version.split(".")[0] + ".x"


def find(corpus, archive, name):
    hits = [f for f in corpus if f["archive"] == archive and f["full"].name == name]
    if not hits:
        pytest.fail(f"fixture {name} missing from {archive} corpus (unavailable, not a pass)")
    return hits[0]


def outcome(call):
    """Normalize a reader result for exact comparison."""
    try:
        value = call()
    except FastTextParseError as exc:
        return ("malformed", str(exc))
    except ValueError as exc:
        return ("ValueError", None)
    if isinstance(value, pd.DataFrame):
        return ("frame", value)
    return ("value", value)


def same(py, nat):
    if py[0] != nat[0]:
        return False
    if py[0] == "frame":
        try:
            pd.testing.assert_frame_equal(py[1], nat[1], check_exact=True)
        except AssertionError:
            return False
        return True
    return py[1] == nat[1]


@pytest.fixture(scope="session")
def geometry_files(corpus):
    return [f for f in corpus if f["family"] == "g"]


@pytest.fixture(scope="session")
def python_reference(geometry_files):
    """Python-reader outputs for every geometry node (computed once, first)."""
    reference = {}
    for f in geometry_files:
        path = f["full"]
        try:
            xs = GeomCrossSection.get_cross_sections(path)
        except Exception as exc:  # recorded and compared, not hidden
            reference[f["path"]] = {"xs": ("error", type(exc).__name__), "nodes": {}}
            continue
        nodes = {}
        if not xs.empty:
            for river, reach, rs in xs[["River", "Reach", "RS"]].drop_duplicates().itertuples(index=False):
                nodes[(river, reach, rs)] = {
                    "sta": outcome(lambda: GeomCrossSection.get_station_elevation(path, river, reach, rs)),
                    "mann": outcome(lambda: GeomCrossSection.get_mannings_n(path, river, reach, rs)),
                    "bank": outcome(lambda: GeomCrossSection.get_bank_stations(path, river, reach, rs)),
                }
        reference[f["path"]] = {"xs": ("frame", xs), "nodes": nodes}
    return reference


def test_every_text_file_round_trips_byte_exact(native, corpus):
    totals = Counter()
    by_version = Counter()
    failures = []
    diag_files = Counter()
    for f in corpus:
        path = f["full"]
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == f["sha256"], f"fixture changed: {path}"
        index = FastText.document_index(data)
        lines = index["lines"]
        tiles = len(data) == 0 or (
            lines[0, 0] == 0
            and lines[-1, 2] == len(data)
            and bool((lines[1:, 0] == lines[:-1, 2]).all())
        )
        identity, spans = FastText.apply_edits(data, [])
        if not tiles or identity != data or spans or len(lines) != max(1, len(data.splitlines())) and data:
            failures.append(f["path"])
        if f["family"] == "g":
            g = FastText.geometry_index(data, tables=False)
            if g.error_count:
                diag_files[f["path"]] = g.error_count
        totals[f["family"]] += 1
        totals["bytes"] += len(data)
        by_version[f"{f['family']}:{major(f['stored_version'])}"] += 1
    record("roundtrip", "files", len(corpus))
    record("roundtrip", "by_family", dict(totals))
    record("roundtrip", "by_family_stored_major", dict(sorted(by_version.items())))
    record("roundtrip", "resolved_by_ras_prj", sum(f["resolved_by_ras_prj"] for f in corpus))
    special = set(RasExamples.SPECIAL_PROJECTS)
    record("roundtrip", "special_download_files", sum(f["project"] in special for f in corpus))
    record("roundtrip", "zip_member_mismatch_non_special",
           [f["path"] for f in corpus if f["project"] not in special and not f["zip_member_match"]])
    record("roundtrip", "failures", failures)
    record("roundtrip", "geometry_files_with_error_diagnostics", dict(diag_files))
    assert not failures
    # Special projects are separate RasExamples downloads, not ZIP members.
    assert all(f["zip_member_match"] for f in corpus if f["project"] not in special)


def test_geometry_typed_parity_with_python_readers(python_reference, geometry_files, required_native):
    stats = Counter()
    by_version = defaultdict(Counter)
    mismatches = []
    divergences = defaultdict(list)
    for f in geometry_files:
        path = f["full"]
        ref = python_reference[f["path"]]
        version = major(f["stored_version"])
        try:
            native_xs = ("frame", FastText.get_cross_sections(path))
        except Exception as exc:
            native_xs = ("error", type(exc).__name__)
        if ref["xs"][0] == "error" or native_xs[0] == "error":
            if ref["xs"] != native_xs:
                mismatches.append((f["path"], "get_cross_sections", ref["xs"][1], native_xs[1]))
            continue
        if not same(ref["xs"], native_xs):
            mismatches.append((f["path"], "get_cross_sections"))
            continue
        stats["files"] += 1
        stats["nodes"] += len(native_xs[1])
        by_version[version]["files"] += 1
        by_version[version]["nodes"] += len(native_xs[1])
        index = FastText.geometry_index(path)
        for key, py in ref["nodes"].items():
            node = index.find_node(*key)
            native = {
                "sta": outcome(lambda: FastText.get_station_elevation(path, *key)),
                "mann": outcome(lambda: FastText.get_mannings_n(path, *key)),
                "bank": outcome(lambda: FastText.get_bank_stations(path, *key)),
            }
            for kind in ("sta", "mann", "bank"):
                if same(py[kind], native[kind]):
                    stats[f"{kind}_{py[kind][0]}"] += 1
                    by_version[version][f"{kind}_{py[kind][0]}"] += 1
                    continue
                # Classified, reported divergences: Python per-XS lookup only
                # tracks "River Reach=" (legacy "Reach=" files are not found);
                # native refuses malformed blocks Python would salvage.
                legacy = py[kind][0] == "ValueError" and node is not None and any(
                    r[2] for r in index.raw["reaches"]
                )
                label = "legacy_reach" if legacy else "malformed" if native[kind][0] == "malformed" else None
                if label:
                    divergences[label].append((f["path"], *key, kind))
                else:
                    mismatches.append((f["path"], *key, kind, py[kind][0], native[kind][0]))
    record("typed_parity", "totals", dict(stats))
    record("typed_parity", "by_stored_major", {k: dict(v) for k, v in sorted(by_version.items())})
    record("typed_parity", "classified_divergences", {k: len(v) for k, v in divergences.items()})
    record("typed_parity", "divergence_examples", {k: v[:5] for k, v in divergences.items()})
    record("typed_parity", "mismatches", mismatches[:50])
    assert stats["files"] > 0 and stats["sta_frame"] > 0, "empty parity corpus is not a pass"
    assert not mismatches
    assert {"5.x", "6.x"} <= set(by_version), "stored 5.x and 6.x coverage required"


def copy_project_text(source_geom: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True)
    for p in source_geom.parent.iterdir():
        if p.is_file() and FAMILY_TEXT.search(p.name):
            shutil.copy2(p, dest_dir / p.name)
    return dest_dir / source_geom.name


@pytest.mark.parametrize(
    "archive, name",
    [("6.6", "Muncie.g01"), ("6.6", "MULTOPEN.g02"), ("7.0", "BaldEagleDamBrk.g06")],
)
def test_real_batch_edits_touch_only_intended_spans(corpus, required_native, monkeypatch, tmp_path, archive, name):
    f = find(corpus, archive, name)
    source = f["full"]
    original = source.read_bytes()
    index = FastText.geometry_index(source)
    nodes = index.nodes
    candidates = [
        i for i in nodes.index[nodes["Type"] == 1]
        if index.raw["station_elevation"]["status"][i] == 1
        and index.raw["mannings_n"]["status"][i] == 1
        and index.raw["bank_stations"]["status"][i] == 1
        and index.find_node(nodes.at[i, "River"], nodes.at[i, "Reach"], nodes.at[i, "RS"]) == i
    ][:3]
    assert len(candidates) == 3
    edits, expected = [], {}
    for k, i in enumerate(candidates):
        key = dict(river=nodes.at[i, "River"], reach=nodes.at[i, "Reach"], rs=nodes.at[i, "RS"])
        se = index.station_elevation(i)
        mn = index.mannings_n(i)
        left, right = index.bank_stations(i)
        if k == 0:
            values = se.copy()
            values[:, 1] = np.round(values[:, 1] + 0.5, 2)
            edits.append({"op": "station_elevation", **key, "values": values})
            expected[i] = ("sta", values)
        elif k == 1:
            values = mn.copy()
            values[:, 1] = np.round(values[:, 1] * 1.1, 3)
            edits.append({"op": "mannings_n", **key, "values": values})
            expected[i] = ("mann", values)
        else:
            stations = se[:, 0]
            new_left = float(stations[stations > left][0]) if (stations > left).any() else left
            new_left = min(new_left, right)
            edits.append({"op": "bank_stations", **key, "values": (new_left, right)})
            expected[i] = ("bank", (new_left, right))
    dest = copy_project_text(source, tmp_path / "project")
    result = FastText.edit_geometry(source, dest, edits, overwrite=True)
    assert sha(source) == f["sha256"] == result["source_sha256"]
    edited = dest.read_bytes()
    # Independent byte oracle: everything outside the reported spans is verbatim.
    rebuilt, pos = bytearray(), 0
    for _, start, end, new_start, new_end in sorted(result["spans"], key=lambda s: s[1]):
        rebuilt += original[pos:start]
        assert len(rebuilt) == new_start
        rebuilt += edited[new_start:new_end]
        pos = end
    rebuilt += original[pos:]
    assert bytes(rebuilt) == edited
    changed = sum(1 for a, b in zip(original.splitlines(), edited.splitlines()) if a != b)
    monkeypatch.undo()  # independent read-back with the Python readers
    for i, (kind, values) in expected.items():
        r, h, s = nodes.at[i, "River"], nodes.at[i, "Reach"], nodes.at[i, "RS"]
        if kind == "sta":
            got = GeomCrossSection.get_station_elevation(dest, r, h, s).to_numpy()
            np.testing.assert_array_equal(got, values)
        elif kind == "mann":
            got = GeomCrossSection.get_mannings_n(dest, r, h, s)[["Station", "n_value"]].to_numpy()
            np.testing.assert_array_equal(got, values[:, :2])
        else:
            assert GeomCrossSection.get_bank_stations(dest, r, h, s) == values
    pd.testing.assert_frame_equal(
        GeomCrossSection.get_cross_sections(dest), GeomCrossSection.get_cross_sections(source)
    )
    ras = init_ras_project(dest.parent, ras_object=RasPrj(), load_results_summary=False,
                           hide_intro=True, load_hdf_metadata=False)
    assert dest.resolve() in {Path(p).resolve() for p in ras.geom_df["full_path"]}
    record("real_edits", f"{archive}/{name}", {
        "source_sha256": result["source_sha256"],
        "output_sha256": result["output_sha256"],
        "spans": len(result["spans"]),
        "changed_lines": changed,
        "stored_version": f["stored_version"],
    })


def raw_ineffective(path: Path, rs: str):
    """Independent oracle: 8-wide slots, 9 per line, from raw bytes."""
    lines = path.read_bytes().decode("latin-1").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("Type RM Length L Ch R") and line.split(",")[1].strip() == rs:
            j = next(k for k in range(i, len(lines)) if lines[k].startswith("#XS Ineff="))
            count = int(lines[j].split("=")[1].split(",")[0])
            slots = []
            k = j + 1
            while len(slots) < count * 3:
                text = lines[k]
                take = min(9, count * 3 - len(slots))
                slots += [float(text[c * 8:(c + 1) * 8]) for c in range(take)]
                k += 1
            return np.array(slots).reshape(count, 3)
    raise AssertionError(rs)


@pytest.mark.parametrize(
    "archive, name, key",
    [
        ("6.6", "BaldEagleDamBrk.g06", ("Bald Eagle Cr.", "Lock Haven", "36808")),
        ("6.6", "MULTOPEN.g02", ("Beaver Creek", "Kentwood", "5.41")),
    ],
)
def test_text001_ineffective_flow_nine_value_wrap(corpus, tmp_path, archive, name, key):
    f = find(corpus, archive, name)
    path = f["full"]
    frame, fmt, flags = GeomCrossSection.get_ineffective_flow(path, *key)
    oracle = raw_ineffective(path, key[2])
    assert len(frame) == len(oracle) > 3
    np.testing.assert_array_equal(frame.to_numpy(), oracle)
    copy = tmp_path / path.name
    shutil.copy2(path, copy)
    GeomCrossSection.set_ineffective_flow(copy, *key, frame, fmt, flags)
    assert copy.read_bytes() == path.read_bytes(), "unchanged write must be a no-op"
    edited = frame.copy()
    edited.loc[0, "elevation"] = edited.loc[0, "elevation"] + 1.0
    GeomCrossSection.set_ineffective_flow(copy, *key, edited, fmt, flags)
    again, _, _ = GeomCrossSection.get_ineffective_flow(copy, *key)
    np.testing.assert_allclose(again.to_numpy(), edited.to_numpy(), atol=0.005)
    assert sha(path) == f["sha256"]
    record("defects", f"TEXT-001/{name}", {"rows": len(frame), "format_flag": fmt})


def test_text002_bank_station_precision(corpus, tmp_path):
    f = find(corpus, "6.6", "Muncie.g01")
    copy = tmp_path / "Muncie.g01"
    shutil.copy2(f["full"], copy)
    key = ("White", "Muncie", "237.6455")
    left, right = GeomCrossSection.get_bank_stations(copy, *key)
    GeomCrossSection.set_bank_stations(copy, *key, 1528.91, right, create_backup=False)
    assert GeomCrossSection.get_bank_stations(copy, *key) == (1528.91, right)
    stations = GeomCrossSection.get_station_elevation(copy, *key)["Station"].to_numpy()
    assert 1528.91 in stations
    assert sha(f["full"]) == f["sha256"]
    record("defects", "TEXT-002", {"before": [left, right], "after": [1528.91, right]})


def test_text003_blank_elevation_slot_semantics_evidence(corpus, native):
    """Evidence only: no behavior change without an owner decision."""
    f = find(corpus, "6.6", "LeveeBreach.g01")
    path = f["full"]
    index = FastText.geometry_index(path)
    blocks = index.blocks[index.blocks["key"] == "Storage Area Vol Elev"]
    raw_lines = path.read_bytes().decode("latin-1").splitlines()
    header = raw_lines.index("Storage Area Vol Elev= 1 ")
    payload = raw_lines[header + 1]
    try:
        GeomStorage.get_elevation_volume(path, "City Storage")
        python = "returned"
    except ValueError as exc:
        python = f"ValueError: {exc}"
    record("defects", "TEXT-003", {
        "payload_repr": repr(payload),
        "native_blocks_malformed": blocks["malformed"].tolist(),
        "python_get_elevation_volume": python,
        "status": "unresolved: blank elevation slot meaning needs owner/HEC evidence",
    })
    assert payload[:8].strip() == "" and payload[8:16].strip() == "0"
    assert not blocks["malformed"].any()  # native treats the blank slot as missing


def test_text004_blank_mannings_slots_evidence(corpus, native):
    """Evidence only: Python misaligns blank #Mann slots; native refuses."""
    f = find(corpus, "6.6", "MIXED.g01")
    path = f["full"]
    key = ("Mixed Reach", "Mixed Reach", "0.5682")
    lines = path.read_bytes().decode("latin-1").splitlines()
    node = next(i for i, line in enumerate(lines)
                if line.startswith("Type RM Length L Ch R") and line.split(",")[1].strip() == key[2])
    header = next(i for i in range(node, len(lines)) if lines[i].startswith("#Mann="))
    payload = lines[header + 1]
    slots = [payload[c * 8:(c + 1) * 8] for c in range(9)]
    python = GeomCrossSection.get_mannings_n(path, *key)
    with pytest.raises(FastTextParseError):
        FastText.get_mannings_n(path, *key, backend="rust")
    record("defects", "TEXT-004", {
        "file": f["path"], "node": key, "header": lines[header], "slots": slots,
        "python_rows": python.to_dict("records"),
        "status": "Python skips blank slots and shifts triplets; native refuses; blank n semantics unresolved",
    })
    assert any(not s.strip() for s in slots)
    assert len(python) < 3  # Python silently lost a segment
