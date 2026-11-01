"""Static consumer-contract guard for the hardened engine-backed source.

Reads the extension source of a ras-commander-fast-hdf checkout named by
RAS_FAST_HDF_SOURCE (skips without it). Source registrations (including ``register(m)``
delegation and ``add_class``) are reconciled against the accepted runtime ABI
inventory when RAS_CONSUMER_ACCEPTANCE_RECEIPT is supplied; the expected set is
also frozen here so a dropped or renamed registration fails without it.
"""
import json
import re
from pathlib import Path

import pytest

from .contract import load_receipt
from .inventory import SOURCE_ENV, build, source_root

from .expected import EXPECTED


@pytest.fixture(scope="module")
def inventory():
    if source_root() is None:
        pytest.skip(f"{SOURCE_ENV} not set: point it at a ras-commander-fast-hdf checkout")
    return build()


def _names(signature):
    """Ordered parameter names of a pyo3 or inspect signature string."""
    if signature is None or signature.startswith("<"):
        return None
    text = signature.strip("()")
    names = []
    for part in text.split(","):
        part = part.strip()
        if part in {"", "*", "/", "self"}:
            continue
        names.append(re.split(r"[=:]", part)[0].strip())
    return names


def test_registrations_kinds_gates_and_delegation(inventory):
    found = {e["name"]: (e["kind"], e["feature"], e["registered_in"])
             for e in inventory["python_entry_points"]}
    assert found == EXPECTED
    assert len(inventory["python_entry_points"]) == 85 == len(EXPECTED)  # explicit full-feature set, no duplicates


def test_module_constants(inventory):
    for name in ("API_VERSION", "TEXT_API_VERSION", "UnsupportedError", "TopologyError",
                 "CorruptDataError", "ENGINE_COMMIT", "ENGINE_FEATURES",
                 "TextEditError", "TextNotFoundError", "TextParseError"):
        assert name in inventory["module_constants"]


def test_source_matches_accepted_runtime_abi(inventory):
    receipt = load_receipt()
    if receipt is None:
        pytest.skip("accepted runtime inventory not supplied (RAS_CONSUMER_ACCEPTANCE_RECEIPT)")
    runtime = json.loads(Path(receipt["runtime_inventory"]).read_text(encoding="utf-8"))
    entries = runtime["entrypoints"]
    assert set(entries) == set(EXPECTED)
    for item in inventory["python_entry_points"]:
        entry = entries[item["name"]]
        assert entry["kind"] == item["kind"], item["name"]
        static = _names(item["signature"])
        if static is not None:
            assert static == _names(entry["signature"]), item["name"]
        for method, sig in item.get("methods", {}).items():
            static = _names(sig)
            runtime_names = _names(entry["methods"][method])
            if static is not None:
                assert static == runtime_names, f"{item['name']}.{method}"
        if item["kind"] == "class":
            assert set(item["methods"]) == set(entry["methods"])


def test_dependency_pins_and_features(inventory):
    crate = inventory["crate"]
    # One crate (0.2+): the engine, bindings and export writers are features of
    # ras-commander-fast-hdf, with no git or path dependencies. freestiler-core
    # is an embedded source pinned in vendor/PROVENANCE.json; the HDF5 reader is
    # the exact-pinned crates.io crate hdf5-reader (no longer vendored, 0.2.5+).
    assert (crate["name"], crate["lib_name"]) == ("ras-commander-fast-hdf", "ras_commander_fast_hdf")
    assert crate["git_dependencies"] == {}
    assert crate["embedded"]["freestiler-core"]["commit"] == "beb64b0d4414da895ec67d02b2f91db6ab6acc37"
    assert not {"hdf5-reader", "hdf5-core"} & set(crate["embedded"])
    assert crate["hdf5_reader"] and crate["hdf5_reader"].startswith("=")
    build = inventory["python_build"]
    assert build["manifest_path"] == "../Cargo.toml" and build["module_name"] == "ras_commander_fast_hdf"
    assert {"python", "extension-module"} <= set(build["features"])
    features = crate["features"]
    receipt = load_receipt()
    for name in (receipt["features"] if receipt else ("extension-module", "exports-all", "exports-pmtiles")):
        assert name in features
    assert set(features["exports-all"]) == {
        "exports-geojson", "exports-flatgeobuf", "exports-geoparquet", "exports-geopackage"}


def test_binding_boundary(inventory):
    """Consumer boundary evidence: which domain cores are already binding-free.

    Fluvial graph/geometry/topology, the lossless text core, the analysis
    reduction core and the export crate carry no PyO3/NumPy; the numeric
    reader, mesh assembly, PMTiles writer and all *_bindings modules do. The
    binding-free modules are not thereby a qualified WASM contract: text/edit
    and the export crate still use filesystem paths.
    """
    modules = inventory["modules"]
    free = ["src/python/fluvial.rs", "src/python/fluvial_geometry.rs", "src/python/fluvial_topology.rs",
            "src/python/analysis/mod.rs", "src/python/ras_text/geometry.rs",
            "src/python/ras_text/fixed_width.rs", "src/exports/contract.rs"]
    coupled = ["src/python/reader.rs", "src/python/mesh.rs", "src/python/tiles.rs",
               "src/python/fluvial_bindings.rs", "src/python/text_bindings.rs",
               "src/python/analysis/bindings.rs"]
    for rel in free:
        assert modules[rel]["coupling"]["pyo3"] == 0 and modules[rel]["coupling"]["numpy"] == 0, rel
    for rel in coupled:
        assert modules[rel]["coupling"]["pyo3"] > 0, rel
    assert modules["src/exports/mod.rs"]["coupling"]["filesystem"] > 0
    assert modules["src/python/ras_text/edit.rs"]["coupling"]["filesystem"] > 0
