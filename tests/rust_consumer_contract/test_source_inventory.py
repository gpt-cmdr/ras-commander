"""Static consumer-contract guard for the hardened engine-backed source.

Reads source only. Source registrations (including ``register(m)``
delegation and ``add_class``) are reconciled against the accepted runtime ABI
inventory when RAS_CONSUMER_ACCEPTANCE_RECEIPT is supplied; the expected set is
also frozen here so a dropped or renamed registration fails without it.
"""
import json
import re
from pathlib import Path

import pytest

from .contract import load_receipt
from .inventory import build

from .expected import EXPECTED
from .contract import engine_dependency


@pytest.fixture(scope="module")
def inventory():
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
    assert len(inventory["python_entry_points"]) == 33 == len(EXPECTED)  # explicit full-feature set, no duplicates


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
    deps = inventory["crate"]["git_dependencies"]
    if "ras-commander-rust" in deps:
        assert deps["ras-commander-rust"] == {k: engine_dependency()[k] for k in ("git", "rev")}
        assert "hdf5-reader" not in deps  # engine owns its generic reader pin
    else:
        assert deps["hdf5-reader"]["rev"] == "24ff6fcfcc79a35c30aa5d8cb3028ab4d9d00564"
    assert deps["freestiler-core"]["rev"] == "beb64b0d4414da895ec67d02b2f91db6ab6acc37"
    assert inventory["export_crate"]["git_dependencies"]["freestiler-core"]["rev"] == \
        deps["freestiler-core"]["rev"]
    features = inventory["crate"]["features"]
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
    free = ["src/fluvial.rs", "src/fluvial_geometry.rs", "src/fluvial_topology.rs",
            "src/analysis/mod.rs", "src/ras_text/geometry.rs", "src/ras_text/fixed_width.rs",
            "src/exports/contract.rs"]
    coupled = ["src/reader.rs", "src/mesh.rs", "src/tiles.rs", "src/fluvial_bindings.rs",
               "src/text_bindings.rs", "src/analysis/bindings.rs"]
    for rel in free:
        assert modules[rel]["coupling"]["pyo3"] == 0 and modules[rel]["coupling"]["numpy"] == 0, rel
    for rel in coupled:
        assert modules[rel]["coupling"]["pyo3"] > 0, rel
    assert modules["src/exports/lib.rs"]["coupling"]["filesystem"] > 0
    assert modules["src/ras_text/edit.rs"]["coupling"]["filesystem"] > 0
    assert inventory["crate"]["crate_types"] == ["cdylib", "rlib"]
