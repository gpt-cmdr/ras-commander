"""Generate THIRD-PARTY-NOTICES.md for the crates statically linked into a Rust artifact.

Standard library only, so it adds no tool to the supply chain. It reads the locked graph
from `cargo metadata --locked` and keeps normal (linked) dependencies for every target
platform. Proc-macro crates (and their dependencies) are listed too, marked compile time
only; build scripts and dev-dependencies are excluded. For each crate it embeds the licence files the crate ships (LICENSE*, LICENCE*,
COPYING*, NOTICE*, COPYRIGHT*, UNLICENSE, plus the manifest's `license-file`). Identical
texts are printed once, with every crate that uses them. Bundled C sources (zstd in
zstd-sys) are reported with their own licence files.

Usage (from the repository root):

    python scripts/generate_third_party_notices.py                 # write THIRD-PARTY-NOTICES.md
    python scripts/generate_third_party_notices.py --check         # exit 1 if it is out of date
    python scripts/generate_third_party_notices.py --manifest-path rust/fast-hdf/Cargo.toml \
        --package ras-commander-fast-hdf --features extension-module --output rust/fast-hdf/THIRD-PARTY-NOTICES.md

Output is deterministic: sorted, with no timestamps. Regenerate after any Cargo.lock change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

LICENSE_FILE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|COPYRIGHT|UNLICENSE)([-_.].*)?$", re.I)
# C/C++ sources compiled into -sys crates that carry their own licence files.
BUNDLED_C = {
    "zstd-sys": ("zstd (C library, bundled by zstd-sys)", "zstd"),
}


def cargo_metadata(manifest: Path | None, features: list[str], all_features: bool) -> dict:
    cmd = ["cargo", "metadata", "--format-version", "1", "--locked"]
    if manifest:
        cmd += ["--manifest-path", str(manifest)]
    if all_features:
        cmd.append("--all-features")
    elif features:
        cmd += ["--features", ",".join(features)]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def linked_packages(meta: dict, roots: list[str], proc_macros: bool = False) -> list[dict]:
    """Packages reachable from `roots` through normal dependency edges.

    With `proc_macros`, also follow proc-macro crates (compiled for the host and
    run at build time, never linked) and their dependencies.
    """
    pkgs = {p["id"]: p for p in meta["packages"]}
    nodes = {n["id"]: n for n in meta["resolve"]["nodes"]}
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        for dep in nodes[pid]["deps"]:
            kinds = {k["kind"] for k in dep["dep_kinds"]}
            if None not in kinds:  # build/dev only
                continue
            target = pkgs[dep["pkg"]]
            if not proc_macros and any(t.get("kind") == ["proc-macro"] for t in target["targets"]):
                continue
            stack.append(dep["pkg"])
    return sorted((pkgs[i] for i in seen), key=lambda p: (p["name"], p["version"]))


def licence_texts(pkg: dict) -> list[tuple[str, str]]:
    root = Path(pkg["manifest_path"]).parent
    found: dict[str, Path] = {}
    if pkg.get("license_file"):
        lf = (root / pkg["license_file"]).resolve()
        if lf.is_file():
            found[lf.name] = lf
    for entry in sorted(root.iterdir()):
        if entry.is_file() and LICENSE_FILE.match(entry.name):
            found.setdefault(entry.name, entry)
    # Crates whose published package ships no licence file: texts copied from the
    # crate's upstream repository at the released tag (see SOURCE.txt there).
    fallback = Path(__file__).resolve().parent / "licence-fallbacks" / f"{pkg['name']}-{pkg['version']}"
    if not found and fallback.is_dir():
        for entry in sorted(fallback.iterdir()):
            if entry.is_file() and LICENSE_FILE.match(entry.name):
                found.setdefault(entry.name, entry)
    # Path dependencies (the vendored reader) keep their licences one level up;
    # crates inside a Git dependency's workspace keep them at the checkout root.
    for parent in [] if found else licence_parents(pkg, root):
        for entry in sorted(parent.iterdir()):
            if entry.is_file() and LICENSE_FILE.match(entry.name):
                found.setdefault(entry.name, entry)
        if found:
            break
    return [(name, read_text(path)) for name, path in sorted(found.items())]


def licence_parents(pkg: dict, root: Path) -> list[Path]:
    """Directories above a crate that may hold its workspace licence, nearest first."""
    source = pkg.get("source")
    if source is None:
        return [root.parent]
    if not source.startswith("git+"):
        return []  # registry packages are self-contained
    # Cargo Git checkouts live at .../git/checkouts/<repo>-<hash>/<rev>/<crate path>.
    parts = [p.lower() for p in root.parts]
    if "checkouts" not in parts:
        return []
    top = Path(*root.parts[: parts.index("checkouts") + 3])
    return [p for p in root.parents if p == top or top in p.parents]


def bundled_c(pkg: dict) -> list[tuple[str, str, list[tuple[str, str]]]]:
    if pkg["name"] not in BUNDLED_C:
        return []
    label, sub = BUNDLED_C[pkg["name"]]
    d = Path(pkg["manifest_path"]).parent / sub
    texts = []
    if d.is_dir():
        for entry in sorted(d.iterdir()):
            if entry.is_file() and LICENSE_FILE.match(entry.name):
                texts.append((entry.name, read_text(entry)))
    return [(label, f"{pkg['name']} {pkg['version']}/{sub}", texts)]


def read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n").strip() + "\n"


def render(title: str, root_names: list[str], pkgs: list[dict], own_licence: Path | None,
           compile_time: frozenset = frozenset()) -> str:
    groups: dict[str, dict] = {}
    rows = []
    missing = []

    def add(owner: str, name: str, text: str) -> str:
        key = hashlib.sha256(text.encode()).hexdigest()[:12]
        g = groups.setdefault(key, {"text": text, "names": set(), "users": []})
        g["names"].add(name)
        g["users"].append(owner)
        return key

    for pkg in pkgs:
        owner = f"{pkg['name']} {pkg['version']}"
        texts = licence_texts(pkg)
        keys = [add(owner, n, t) for n, t in texts]
        if not texts:
            missing.append(owner)
        name = pkg["name"] + (" (compile time only)" if pkg["id"] in compile_time else "")
        rows.append((name, pkg["version"], pkg.get("license") or "(see licence file)",
                     pkg.get("repository") or "", keys))
        for label, where, ctexts in bundled_c(pkg):
            ckeys = [add(f"{label} ({where})", n, t) for n, t in ctexts]
            rows.append((label, pkg["version"], "BSD-3-Clause OR GPL-2.0 (BSD-3-Clause elected)",
                         "https://github.com/facebook/zstd", ckeys))

    out = [f"# Third-party notices: {title}", ""]
    out.append(
        "Generated by `scripts/generate_third_party_notices.py` from the locked Cargo graph. "
        "Do not edit by hand; regenerate after any `Cargo.lock` change. "
        f"Root crate(s): {', '.join(root_names)}. Listed: every crate statically linked "
        "for any target platform (normal dependencies) and bundled C libraries. Proc-macro "
        "crates and their dependencies run only at build time and are not linked; they are "
        "listed too, marked \"compile time only\". Build scripts and dev-dependencies are omitted.")
    out.append("")
    if own_licence:
        out += ["## Licence of this software", "", "```text", read_text(own_licence).rstrip(), "```", ""]
    out += ["## Components", "", f"{len(rows)} components.", "",
            "| Component | Version | Licence (SPDX, as declared) | Source | Licence texts |",
            "|---|---|---|---|---|"]
    for name, version, lic, repo, keys in rows:
        refs = ", ".join(f"[{k}](#licence-{k})" for k in keys) or "**none shipped**"
        out.append(f"| {name} | {version} | {lic} | {repo} | {refs} |")
    out.append("")
    if missing:
        raise SystemExit(
            "no licence text for: " + ", ".join(missing)
            + "; add the upstream texts under scripts/licence-fallbacks/<crate>-<version>/")
    out += ["## Licence texts", ""]
    for key in sorted(groups, key=lambda k: (sorted(groups[k]["names"])[0], k)):
        g = groups[key]
        out.append(f"### licence-{key}")
        out.append("")
        out.append(f"File(s): {', '.join(sorted(g['names']))}. Used by: {', '.join(sorted(set(g['users'])))}.")
        out += ["", "```text", g["text"].rstrip(), "```", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest-path", type=Path)
    ap.add_argument("--package", action="append", help="root package name(s); default: workspace members")
    ap.add_argument("--features", default="", help="comma-separated features of the root package")
    ap.add_argument("--all-features", action="store_true", help="resolve with all features (default when no --features)")
    ap.add_argument("--own-licence", type=Path, default=Path("LICENSE"))
    ap.add_argument("--title", default=None)
    ap.add_argument("--output", type=Path, default=Path("THIRD-PARTY-NOTICES.md"))
    ap.add_argument("--check", action="store_true", help="fail if the output is not up to date")
    a = ap.parse_args()

    features = [f for f in a.features.split(",") if f]
    meta = cargo_metadata(a.manifest_path, features, a.all_features or not features)
    by_name = {p["name"]: p["id"] for p in meta["packages"] if p["id"] in meta["workspace_members"]}
    roots = [by_name[n] for n in a.package] if a.package else list(meta["workspace_members"])
    root_names = sorted(p["name"] for p in meta["packages"] if p["id"] in roots)
    linked = {p["id"] for p in linked_packages(meta, roots)}
    pkgs = [p for p in linked_packages(meta, roots, proc_macros=True) if p["id"] not in roots]
    compile_time = frozenset(p["id"] for p in pkgs if p["id"] not in linked)
    text = render(a.title or ", ".join(root_names), root_names, pkgs,
                  a.own_licence if a.own_licence and a.own_licence.is_file() else None,
                  compile_time)
    if a.check:
        current = a.output.read_text(encoding="utf-8") if a.output.is_file() else ""
        if current.replace("\r\n", "\n") != text:
            print(f"{a.output} is out of date; run {Path(sys.argv[0]).as_posix()}", file=sys.stderr)
            return 1
        print(f"{a.output} is up to date ({len(pkgs) - len(compile_time)} linked, "
              f"{len(compile_time)} compile-time crates)")
        return 0
    a.output.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {a.output} ({len(pkgs) - len(compile_time)} linked, "
          f"{len(compile_time)} compile-time crates)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
