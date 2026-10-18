"""Extract the RasExamples text qualification corpus and write a hash manifest.

Every project of each requested RasExamples archive is extracted with
``RasExamples.extract_project`` into ``<out>/<version>/``. Project files are
resolved with ``init_ras_project`` DataFrames (``prj_file``, ``plan_df``,
``geom_df``, ``flow_df``, ``unsteady_df`` ``full_path``); every other
``.g##/.p##/.f##/.u##`` text file in the extracted folders is recorded as a
survey file. Each file records its SHA256, the matching ZIP member SHA256 and
its stored ``Program Version=`` (stored version, not the archive label).

The cached ZIPs are only read. No HEC-RAS executable is invoked.

Usage::

    python scripts/benchmarks/rust_text_public/prepare_corpus.py --out <dir> --versions 6.6 7.0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import zipfile
from pathlib import Path

from ras_commander import RasExamples, RasPrj, init_ras_project

FAMILY = re.compile(r"\.(prj|[gpfu]\d\d)$", re.IGNORECASE)
VERSION = re.compile(rb"^Program Version=\s*([0-9.]+)", re.MULTILINE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def family(path: Path) -> str:
    suffix = path.suffix.lower()
    return "prj" if suffix == ".prj" else suffix[1]


def resolved_paths(folder: Path) -> tuple[set[Path], str | None]:
    """Text files referenced by the project, via ras-commander DataFrames."""
    try:
        ras = init_ras_project(folder, ras_object=RasPrj(), load_results_summary=False,
                               hide_intro=True, load_hdf_metadata=False)
    except Exception as exc:  # recorded, not hidden
        return set(), f"{type(exc).__name__}: {exc}"
    paths = {Path(ras.prj_file)}
    for frame in (ras.plan_df, ras.geom_df, ras.flow_df, ras.unsteady_df):
        if frame is not None and "full_path" in frame.columns:
            paths.update(Path(p) for p in frame["full_path"].dropna() if Path(p).is_file())
    return {p.resolve() for p in paths}, None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--versions", nargs="+", default=["6.6", "7.0"])
    args = parser.parse_args()
    manifest = {"archives": {}, "files": []}
    for version in args.versions:
        RasExamples.get_example_projects(version)
        zip_path = Path(RasExamples._zip_file_path)
        projects = list(RasExamples.list_projects())
        dest = args.out / version
        started = time.perf_counter()
        extracted = RasExamples.extract_project(projects, output_path=dest)
        extracted = extracted if isinstance(extracted, list) else [extracted]
        seconds = time.perf_counter() - started
        with zipfile.ZipFile(zip_path) as zf:
            members = {
                info.filename.replace("\\", "/"): hashlib.sha256(zf.read(info)).hexdigest()
                for info in zf.infolist()
                if not info.is_dir() and FAMILY.search(info.filename)
            }
        by_tail = {}
        for name, digest in members.items():
            parts = name.split("/")
            by_tail.setdefault("/".join(parts[-2:]).lower(), []).append(digest)
        manifest["archives"][version] = {
            "zip": zip_path.name,
            "zip_sha256": sha256(zip_path),
            "projects": len(projects),
            "extract_seconds": round(seconds, 2),
            "text_members": len(members),
        }
        for folder in extracted:
            folder = Path(folder)
            resolved, init_error = resolved_paths(folder)
            for path in sorted(p for p in folder.rglob("*") if p.is_file() and FAMILY.search(p.name)):
                data = path.read_bytes()
                stored = VERSION.search(data)
                tail = f"{path.parent.name}/{path.name}".lower()
                manifest["files"].append({
                    "archive": version,
                    "project": folder.name,
                    "path": str(path.relative_to(args.out)),
                    "family": family(path),
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "zip_member_match": hashlib.sha256(data).hexdigest() in by_tail.get(tail, []),
                    "stored_version": stored.group(1).decode() if stored else None,
                    "resolved_by_ras_prj": path.resolve() in resolved,
                    "init_error": init_error,
                })
    out = args.out / "corpus-manifest.json"
    out.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    files = manifest["files"]
    print(json.dumps({
        "manifest": str(out),
        "files": len(files),
        "resolved": sum(f["resolved_by_ras_prj"] for f in files),
        "zip_mismatch": sum(not f["zip_member_match"] for f in files),
        "archives": manifest["archives"],
    }, indent=1))


if __name__ == "__main__":
    main()
