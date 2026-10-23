"""Real-model qualification for the lossless Rust text core (rust/fast-hdf/src/ras_text).

The Rust module is compiled in place by the standalone crate next to this file
(no shared Cargo.toml/lib.rs edits) and driven through its ``ras_text_probe``
binary. Projects come from RasExamples, are extracted into pytest temp folders
and resolved through RasPrj DataFrames; the example ZIPs are only read.

Checks:
- every project/plan/geometry/steady/unsteady file round-trips byte-exact
  (identity, span coverage, empty batch, atomic copy);
- the Rust geometry index agrees with the current Python readers;
- batch edits change only their reported spans and reopen through the
  current Python APIs; malformed real derivatives are diagnosed.

Skips (never weakens) when cargo or the example archives are unavailable.
Environment:
  RAS_TEXT_VERSIONS   comma list of RasExamples versions (default "6.6,7.0")
  RAS_TEXT_REPORT     optional path for a JSON evidence report
  CARGO               cargo executable (default: PATH or ~/.cargo/bin)
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

import pytest

import ras_commander
from ras_commander import RasExamples, RasPrj, init_ras_project
from ras_commander.geom import GeomCrossSection

CRATE = Path(__file__).resolve().parent
CHECKOUT = CRATE.parents[1]

PROJECTS = {
    "6.6": [
        "Muncie", "BaldEagleCrkMulti2D", "Balde Eagle Creek", "Bridge Hydraulics",
        "Culvert Hydraulics", "Davis", "Example 2 - Beaver Creek",
        "Example 4 - Multiple Culverts", "Example 5 - Multiple Openings",
        "Lateral Structure with Culverts and Gates", "Storage Area Hydraulic Connection",
        "Example 16 - Channel Modification", "Chippewa_2D", "Example 8 - Looped Network",
        "Inline Structure with Gated Spillways", "Example 13 - Singler Bridge (WSPRO)",
        "Pumping Station", "Levee Breaching", "Example 1 - Critical Creek",
        "Example 6 - Floodway Determination",
    ],
    "7.0": ["Muncie", "BaldEagleCrkMulti2D", "Davis", "Example 2 - Beaver Creek", "Bridge Hydraulics"],
}
VERSIONS = [v.strip() for v in os.environ.get("RAS_TEXT_VERSIONS", "6.6,7.0").split(",") if v.strip()]
TEXT_SUFFIX = re.compile(r"^\.(prj|[pgfu]\d\d)$", re.IGNORECASE)
REPORT: dict = {"versions": {}, "edits": [], "malformed": []}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _cargo() -> str | None:
    if os.environ.get("CARGO"):
        return os.environ["CARGO"]
    found = shutil.which("cargo")
    if found:
        return found
    home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo")) / "bin" / "cargo.exe"
    return str(home) if home.exists() else None


@pytest.fixture(scope="session")
def probe() -> Path:
    cargo = _cargo()
    if not cargo:
        pytest.skip("cargo unavailable; set CARGO to build the ras_text conformance crate")
    target = Path(os.environ.get("CARGO_TARGET_DIR", CRATE / "target"))
    t0 = time.perf_counter()
    subprocess.run(
        [cargo, "build", "--release", "--quiet", "--manifest-path", str(CRATE / "Cargo.toml")],
        check=True,
        env={**os.environ, "CARGO_TARGET_DIR": str(target)},
    )
    REPORT["build_seconds"] = round(time.perf_counter() - t0, 2)
    exe = target / "release" / ("ras_text_probe.exe" if os.name == "nt" else "ras_text_probe")
    assert exe.is_file()
    return exe


def run_probe(exe: Path, *args: str | Path) -> object:
    proc = subprocess.run([str(exe), *map(str, args)], capture_output=True, check=False)
    payload = json.loads(proc.stdout)
    if proc.returncode:
        raise AssertionError(payload)
    return payload


def _project_files(folder: Path, version: str) -> tuple[RasPrj, list[Path]]:
    """Resolve text files through RasPrj DataFrames, not ad hoc globbing."""
    ras = RasPrj()
    init_ras_project(folder, version, ras_object=ras)
    files = [Path(ras.prj_file)]
    for frame in (ras.plan_df, ras.geom_df, ras.flow_df, ras.unsteady_df):
        if len(frame) and "full_path" in frame:
            files += [Path(p) for p in frame["full_path"] if isinstance(p, str) and p]
    return ras, sorted({f for f in files if f.is_file() and TEXT_SUFFIX.match(f.suffix)})


@pytest.fixture(scope="session", params=VERSIONS)
def corpus(request, tmp_path_factory):
    version = request.param
    try:
        RasExamples.get_example_projects(version)
    except Exception as exc:  # offline, missing optional download deps
        pytest.skip(f"RasExamples {version} unavailable: {exc}")
    archive = Path(RasExamples._zip_file_path)
    root = tmp_path_factory.mktemp(f"ras_text_{version.replace('.', '_')}")
    t0 = time.perf_counter()
    folders = RasExamples.extract_project(PROJECTS[version], output_path=root)
    extract_s = time.perf_counter() - t0
    folders = folders if isinstance(folders, list) else [folders]
    t1 = time.perf_counter()
    projects = {Path(f).name: _project_files(Path(f), version) for f in folders}
    init_s = time.perf_counter() - t1
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        member_hashes = {}
        for _, files in projects.values():
            for f in files:
                # Name collisions across projects are disambiguated by folder.
                matches = [n for n in names if n.endswith(f"{f.parent.name}/{f.name}")]
                if len(matches) == 1:
                    member_hashes[f] = sha256(zf.read(matches[0]))
    REPORT["versions"][version] = {
        "archive": archive.name,
        "archive_sha256": sha256(archive.read_bytes()),
        "extract_seconds": round(extract_s, 2),
        "init_seconds": round(init_s, 2),
        "projects": sorted(projects),
    }
    return version, projects, member_hashes


def test_provenance_is_this_checkout():
    assert Path(ras_commander.__file__).resolve().is_relative_to(CHECKOUT)
    assert Path.cwd().resolve().is_relative_to(CHECKOUT), "run pytest from the checkout"
    spec = importlib.util.find_spec("ras_commander_fast_hdf")
    # ras_text is not bound into the extension yet (integrator patch); when an
    # extension is present it must belong to this checkout's environment.
    if spec is not None:
        import sys
        assert Path(spec.origin).resolve().is_relative_to(Path(sys.prefix).resolve())
    REPORT["provenance"] = {
        "ras_commander": str(Path(ras_commander.__file__).resolve()),
        "version": ras_commander.__version__,
        "native_extension": spec.origin if spec else None,
        "ras_text_source": str(CHECKOUT / "rust/fast-hdf/src/ras_text"),
    }


def test_unchanged_roundtrip_is_byte_exact(probe, corpus, tmp_path):
    version, projects, member_hashes = corpus
    files = [f for _, fs in projects.values() for f in fs]
    assert len(files) >= 10, "corpus unexpectedly small"
    scan = run_probe(probe, "scan", *files)
    kinds, versions, failures = {}, {}, []
    for entry, path in zip(scan, files):
        data = path.read_bytes()
        assert entry["bytes"] == len(data)
        if path in member_hashes:
            assert member_hashes[path] == sha256(data), f"extracted copy differs from archive: {path}"
        ok = entry["identity_roundtrip"] and entry["span_roundtrip"] and entry["empty_batch_roundtrip"]
        # Atomic copy through write_atomic with an empty batch.
        out = tmp_path / f"{len(kinds)}_{path.name}"
        if path.suffix.lower().startswith(".g"):
            spec = tmp_path / "empty.json"
            spec.write_text('{"ops": []}')
            run_probe(probe, "edit", path, out, spec)
            ok = ok and out.read_bytes() == data
        if not ok:
            failures.append(str(path))
        kind = path.suffix.lower() if path.suffix.lower() == ".prj" else path.suffix[:2].lower()
        kinds[kind] = kinds.get(kind, 0) + 1
        geo = entry.get("geometry")
        if geo:
            versions[geo["program_version"]] = versions.get(geo["program_version"], 0) + 1
            errors = [d for d in geo["diagnostics"] if d["severity"] == "error"]
            assert not errors, f"{path}: {errors[:3]}"
        assert entry["lines"] == len(data.splitlines()), path  # independent line split
    assert not failures
    for needed in (".prj", ".p", ".g"):
        assert needed in kinds, f"no {needed} files in {version} corpus"
    REPORT["versions"][version].update(
        files=len(files), kinds=kinds, bytes=sum(e["bytes"] for e in scan),
        geometry_program_versions=versions,
        rust_parse_ms=round(sum(e["parse_ns"] + e.get("geometry", {}).get("parse_ns", 0) for e in scan) / 1e6, 2),
        file_sha256={str(p.relative_to(p.parents[1])): sha256(p.read_bytes()) for p in files},
    )


def test_geometry_index_matches_python_readers(probe, corpus):
    version, projects, _ = corpus
    compared = {"files": 0, "nodes": 0, "xs_sta_elev": 0, "xs_mann": 0, "xs_bank": 0}
    py_s = rust_ms = 0.0
    for name, (ras, files) in projects.items():
        geoms = [f for f in files if f.suffix.lower().startswith(".g")]
        if not geoms:
            continue
        scans = run_probe(probe, "scan", *geoms)
        for path, entry in zip(geoms, scans):
            geo = entry["geometry"]
            rust_ms += (entry["parse_ns"] + geo["parse_ns"]) / 1e6
            t0 = time.perf_counter()
            df = GeomCrossSection.get_cross_sections(path)
            py_s += time.perf_counter() - t0
            rust_nodes = [n for n in geo["nodes"] if n["river"] is not None]
            assert len(df) == len(rust_nodes), path
            for row, node in zip(df.itertuples(index=False), rust_nodes):
                assert (row.River, row.Reach, row.RS, row.Type) == (
                    node["river"], node["reach"], node["rs"], node["type"]
                ), path
                assert [row.Length_Left, row.Length_Channel, row.Length_Right] == node["lengths"]
                assert row.NodeName == node["node_name"], (path, node["rs"])
            # Text-sourced geom_df.num_cross_sections is len(get_cross_sections()),
            # i.e. every node type (bridges/culverts included), not only type 1.
            row = ras.geom_df[ras.geom_df["full_path"].map(lambda p: Path(p) == path)]
            if len(row) and row.iloc[0]["geometry_metadata_source"] == "text":
                assert int(row.iloc[0]["num_cross_sections"]) == len(rust_nodes), path
            for node in rust_nodes:
                if node["type"] != 1:
                    continue
                key = (path, node["river"], node["reach"], node["rs"])
                t0 = time.perf_counter()
                se = GeomCrossSection.get_station_elevation(*key)
                py_s += time.perf_counter() - t0
                assert [[a, b] for a, b in zip(se["Station"], se["Elevation"])] == node["sta_elev"], key
                compared["xs_sta_elev"] += 1
                if node["mann"]:
                    mn = GeomCrossSection.get_mannings_n(*key)
                    assert [[a, b] for a, b in zip(mn["Station"], mn["n_value"])] == [r[:2] for r in node["mann"]], key
                    compared["xs_mann"] += 1
                if node["bank"]:
                    assert list(GeomCrossSection.get_bank_stations(*key)) == node["bank"], key
                    compared["xs_bank"] += 1
            compared["files"] += 1
            compared["nodes"] += len(rust_nodes)
    assert compared["xs_sta_elev"] > 0
    REPORT["versions"][version]["python_parity"] = {
        **compared, "python_reader_seconds": round(py_s, 2), "rust_geometry_parse_ms": round(rust_ms, 2),
    }


def _edit_targets(scan_entry):
    xs = [n for n in scan_entry["geometry"]["nodes"] if n["type"] == 1 and n["sta_elev"] and n["mann"] and n["bank"]]
    return xs[0], xs[len(xs) // 2], xs[-1]


def test_batch_edits_limited_to_intended_spans(probe, corpus, tmp_path):
    version, projects, _ = corpus
    ras, files = projects["Muncie"]
    source = next(f for f in files if f.suffix.lower() == ".g01")
    original = source.read_bytes()
    edited_project = tmp_path / "Muncie_edited"
    shutil.copytree(source.parent, edited_project)
    target = edited_project / source.name
    entry = run_probe(probe, "scan", source)[0]
    a, b, c = _edit_targets(entry)
    new_points = [[s, e + 0.5] for s, e in a["sta_elev"]]
    new_mann = [[m[0], round(m[1] * 1.1, 3), m[2]] for m in b["mann"]]
    (left, right) = c["bank"]
    stations = [p[0] for p in c["sta_elev"]]
    new_left = next(s for s in stations if s > left)
    ops = [
        {"op": "sta_elev", "river": a["river"], "reach": a["reach"], "rs": a["rs"], "points": new_points},
        {"op": "mann", "river": b["river"], "reach": b["reach"], "rs": b["rs"], "triplets": new_mann},
        {"op": "bank", "river": c["river"], "reach": c["reach"], "rs": c["rs"], "left": new_left, "right": right},
    ]
    spec = tmp_path / "ops.json"
    spec.write_text(json.dumps({"ops": ops}))
    t0 = time.perf_counter()
    report = run_probe(probe, "edit", source, target, spec)
    wall = time.perf_counter() - t0
    out = target.read_bytes()
    assert source.read_bytes() == original, "original must stay immutable"
    assert report["reparse_errors"] == 0
    # Independent raw-byte check: outside reported spans, bytes are identical.
    src_cur = out_cur = 0
    for span in sorted(report["spans"], key=lambda s: s["original"][0]):
        assert original[src_cur:span["original"][0]] == out[out_cur:span["updated"][0]]
        src_cur, out_cur = span["original"][1], span["updated"][1]
    assert original[src_cur:] == out[out_cur:]
    assert {s["label"].split(":")[0] for s in report["spans"]} == {"sta_elev", "mann", "bank_sta"}
    assert len(report["spans"]) == 6  # count+data, count+data, two bank tokens
    # Raw text: the count line is unchanged when the point count is unchanged.
    changed = [l for l, m in zip(original.splitlines(), out.splitlines()) if l != m]
    assert all(not l.startswith(b"#Sta/Elev=") and not l.startswith(b"#Mann=") for l in changed)
    # Reopen through current Python APIs.
    key = lambda n: (target, n["river"], n["reach"], n["rs"])
    se = GeomCrossSection.get_station_elevation(*key(a))
    flat = lambda rows: [v for r in rows for v in r]
    assert flat(zip(se["Station"], se["Elevation"])) == pytest.approx(flat(new_points))
    mn = GeomCrossSection.get_mannings_n(*key(b))
    assert flat(zip(mn["Station"], mn["n_value"])) == pytest.approx(flat(m[:2] for m in new_mann))
    assert list(GeomCrossSection.get_bank_stations(*key(c))) == pytest.approx([new_left, right])
    before = GeomCrossSection.get_cross_sections(source)
    after = GeomCrossSection.get_cross_sections(target)
    assert before.equals(after)
    reopened = RasPrj()
    init_ras_project(edited_project, version, ras_object=reopened)
    assert any(Path(p) == target for p in reopened.geom_df["full_path"])
    REPORT["edits"].append({
        "version": version, "file": source.name, "ops": len(ops), "spans": report["spans"],
        "rust_edit_ms": report["edit_ns"] / 1e6, "probe_wall_s": round(wall, 3),
        "changed_lines": len(changed), "output_sha256": sha256(out), "input_sha256": sha256(original),
    })


def test_malformed_real_derivative_is_diagnosed(probe, corpus, tmp_path):
    version, projects, _ = corpus
    _, files = projects["Muncie"]
    source = next(f for f in files if f.suffix.lower() == ".g01")
    data = source.read_bytes()
    match = re.search(rb"#Sta/Elev= *(\d+)", data)
    bad = data[: match.start(1)] + str(int(match.group(1)) + 1).encode() + data[match.end(1):]
    broken = tmp_path / source.name
    broken.write_bytes(bad)
    entry = run_probe(probe, "scan", broken)[0]
    assert entry["identity_roundtrip"] and entry["span_roundtrip"]
    codes = {d["code"] for d in entry["geometry"]["diagnostics"] if d["severity"] == "error"}
    assert codes, "count corruption must be diagnosed"
    line = bad[: match.start(1)].count(b"\n")
    # Reported at the header (count mismatch) or within its payload (blank slot).
    assert any(line <= d["line"] <= line + 60 for d in entry["geometry"]["diagnostics"])
    REPORT["malformed"].append({"version": version, "codes": sorted(codes), "line": line})


def teardown_module(module):
    path = os.environ.get("RAS_TEXT_REPORT")
    if path:
        Path(path).write_text(json.dumps(REPORT, indent=1, default=str))
