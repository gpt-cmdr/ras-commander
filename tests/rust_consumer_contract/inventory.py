"""Static consumer-contract inventory of the optional native backend.

Reads source only: no build, no import of the native module, no HDF access.
Records what a Python, terrio or RustGIS consumer can bind to at the checked
out revision, including registrations delegated to ``module::register(m)``
helpers and ``add_class`` types, and which modules are coupled to PyO3, NumPy
or filesystem paths (and therefore are not a pure-Rust/WASM contract).

    python tests/rust_consumer_contract/inventory.py [--output inventory.json]
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CRATE = ROOT / "rust" / "fast-hdf"
SCHEMA = "ras-commander/consumer-contract-inventory/v2"

COUPLING = {
    "pyo3": re.compile(r"\bPy(?:Result|Any|Dict|List|Module|ValueError|ReadonlyArray\d?|Bytes|Tuple)\b|Python<|Bound<|#\[pyfunction\]|#\[pyclass"),
    "numpy": re.compile(r"\bnumpy::|PyReadonlyArray|PyArray|IntoPyArray"),
    "filesystem": re.compile(r"std::fs|File::(?:open|create)|tempfile|Hdf5File::open|&Path\b|PathBuf"),
    "rayon": re.compile(r"\brayon::|\.install\(|par_iter"),
}
CFG = re.compile(r'#\[cfg\(feature\s*=\s*"([^"]+)"\)\]')
FUNCTION = re.compile(r"wrap_pyfunction!\(([\w:]+)")
CLASS = re.compile(r"add_class::<(\w+)>")
DELEGATE = re.compile(r"\b(\w+)::register\(m\)")
REGISTER_FN = re.compile(r"fn register\([^)]*\)[^{]*\{(.*?)\n\}", re.S)
SIGNATURE = re.compile(r"#\[pyo3\(signature\s*=\s*\((.*?)\)\)\]", re.S)
METHOD = re.compile(r"(?:#\[pyo3\(signature\s*=\s*\((.*?)\)\)\]\s*)?fn\s+(\w+)\(", re.S)


def _git(*args):
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _line_registrations(line, gate, rel):
    found = []
    match = FUNCTION.search(line)
    if match:
        found.append({"name": match.group(1).split("::")[-1], "rust_path": match.group(1),
                      "kind": "function", "feature": gate, "registered_in": rel})
    match = CLASS.search(line)
    if match:
        found.append({"name": match.group(1), "rust_path": match.group(1),
                      "kind": "class", "feature": gate, "registered_in": rel})
    return found


def _registered(lib_rs, sources):
    body = lib_rs.split("#[pymodule]", 1)[1]
    out, pending, block_gate, depth = [], None, None, 0
    for line in body.splitlines():
        stripped = line.strip()
        cfg = CFG.match(stripped)
        if cfg:
            pending = cfg.group(1)
            continue
        if pending and stripped == "{":
            block_gate, depth, pending = pending, 1, None
            continue
        gate = pending or block_gate
        out.extend(_line_registrations(stripped, gate, "src/lib.rs"))
        delegated = DELEGATE.search(stripped)
        if delegated:
            rel = f"src/{delegated.group(1)}.rs"
            fn = REGISTER_FN.search(sources.get(rel, ""))
            if fn is None:
                raise ValueError(f"delegated registration not found in {rel}")
            for inner in fn.group(1).splitlines():
                out.extend(_line_registrations(inner.strip(), gate, rel))
        pending = None
        if block_gate:
            depth += stripped.count("{") - stripped.count("}")
            if depth <= 0:
                block_gate = None
    return out


def _signatures(text):
    sigs = {}
    # Attributes/comments may sit between the signature and `fn`; take the next fn.
    for match in SIGNATURE.finditer(text):
        name = re.search(r"\bfn\s+(\w+)", text[match.end():])
        if name:
            sigs.setdefault(name.group(1), " ".join(match.group(1).split()))
    for name in re.findall(r"#\[pyfunction\]\s*\n(?:\s*#\[[^\n]*\n)*\s*(?:pub(?:\(crate\))?\s+)?fn\s+(\w+)", text):
        sigs.setdefault(name, "<positional; no #[pyo3(signature)]>")
    return sigs


def _methods(text):
    """``#[pymethods]`` names (constructor excluded) with pyo3 signatures."""
    if "#[pymethods]" not in text:
        return {}
    block = text.split("#[pymethods]", 1)[1]
    block = block[:block.find("\n}\n") + 2] if "\n}\n" in block else block
    return {m.group(2): (" ".join(m.group(1).split()) if m.group(1) else "<positional>")
            for m in METHOD.finditer(block) if m.group(2) != "new"}


def _features(cargo):
    section = cargo.split("[features]", 1)[1].split("\n[", 1)[0]
    features = {}
    for line in section.splitlines():
        match = re.match(r'\s*([\w-]+)\s*=\s*\[(.*)\]', line)
        if match:
            features[match.group(1)] = re.findall(r'"([^"]+)"', match.group(2))
    return features


def _git_deps(cargo):
    return {name: {"git": git, "rev": rev} for name, git, rev in re.findall(
        r'^([\w-]+)\s*=\s*\{[^}]*git\s*=\s*"([^"]+)"[^}]*rev\s*=\s*"([0-9a-f]+)"', cargo, re.M)}


def build():
    lib_rs = (CRATE / "src" / "lib.rs").read_text(encoding="utf-8")
    texts = {p.relative_to(CRATE).as_posix(): p.read_text(encoding="utf-8")
             for p in sorted((CRATE / "src").rglob("*.rs"))}
    signatures = {}
    for text in texts.values():
        for name, sig in _signatures(text).items():
            signatures.setdefault(name, sig)
    registrations = _registered(lib_rs, texts)
    for item in registrations:
        if item["kind"] == "class":
            item["methods"] = _methods(texts.get(item["registered_in"], ""))
            item["signature"] = "<constructor>"
        else:
            item["signature"] = signatures.get(item["name"])
    modules = {rel: {"lines": text.count("\n") + 1,
                     "coupling": {k: len(rx.findall(text)) for k, rx in COUPLING.items()},
                     "pub_items": re.findall(r"^pub (?:fn|struct|enum|trait) (\w+)", text, re.M)}
               for rel, text in texts.items()}
    main_cargo = (CRATE / "Cargo.toml").read_text(encoding="utf-8")
    export_cargo = (CRATE / "src" / "exports" / "Cargo.toml").read_text(encoding="utf-8")
    pure = {rel: m["pub_items"] for rel, m in modules.items()
            if m["pub_items"] and m["coupling"]["pyo3"] == 0 and m["coupling"]["numpy"] == 0}
    return {
        "schema": SCHEMA,
        "source": {"commit": _git("rev-parse", "HEAD"), "tree": _git("rev-parse", "HEAD^{tree}"),
                   "dirty_paths": (_git("status", "--porcelain") or "").splitlines()},
        "crate": {"name": "ras-commander-fast-hdf",
                  "crate_types": re.findall(r'"(cdylib|rlib)"', main_cargo),
                  "features": _features(main_cargo), "git_dependencies": _git_deps(main_cargo)},
        "export_crate": {"name": "ras-export", "features": _features(export_cargo),
                         "git_dependencies": _git_deps(export_cargo)},
        "module_constants": re.findall(r'm\.add\(\s*"(\w+)"', "\n".join(texts.values())),
        "python_entry_points": registrations,
        "modules": modules,
        "pure_rust_public_api": pure,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = json.dumps(build(), indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
