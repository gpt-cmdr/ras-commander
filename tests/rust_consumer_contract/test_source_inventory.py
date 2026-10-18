"""Static consumer-contract guard at the 89b4ace baseline.

These tests read source only. They pin what consumers may bind to and record
which entry points are not reusable outside CPython (PyO3/NumPy/path coupled).
Native/installed-wheel acceptance lives in test_native_gate.py and is blocked
until accepted source pins and a reviewed portable-build receipt exist.
"""
import pytest

from .inventory import build

EXPECTED_ENTRY_POINTS = {
    # name: feature gate (None = always compiled)
    "read_numeric": None,
    "read_numeric_batch": None,
    "numeric_capability": None,
    "assemble_cells": None,
    "write_pmtiles": None,
    "export_ipc_file": "exports-arrow",
    "validate_export_wkb": "exports-arrow",
    "export_pmtiles_ipc_file": "exports-pmtiles",
}


@pytest.fixture(scope="module")
def inventory():
    return build()


def test_python_entry_points_and_feature_gates(inventory):
    found = {e["name"]: e["feature"] for e in inventory["python_entry_points"]}
    assert found == EXPECTED_ENTRY_POINTS


def test_every_entry_point_signature_is_recorded(inventory):
    missing = [e["name"] for e in inventory["python_entry_points"] if not e["signature"]]
    assert missing == []


def test_dependency_pins_match_contract(inventory):
    deps = inventory["crate"]["git_dependencies"]
    assert deps["hdf5-reader"]["rev"] == "24ff6fcfcc79a35c30aa5d8cb3028ab4d9d00564"
    assert deps["freestiler-core"]["rev"] == "beb64b0d4414da895ec67d02b2f91db6ab6acc37"
    assert inventory["export_crate"]["git_dependencies"]["freestiler-core"]["rev"] == \
        deps["freestiler-core"]["rev"]


def test_build_features_cover_main_build(inventory):
    features = inventory["crate"]["features"]
    for name in ("extension-module", "exports-all", "exports-pmtiles"):
        assert name in features
    assert set(features["exports-all"]) == {
        "exports-geojson", "exports-flatgeobuf", "exports-geoparquet", "exports-geopackage"}


def test_domain_kernels_are_python_coupled(inventory):
    # The RAS domain kernels (numeric reads, mesh assembly, PMTiles writer) are
    # currently PyO3-bound. This is the documented gap: they are NOT a
    # pure-Rust/WASM consumer contract until a binding-free layer is extracted.
    modules = inventory["modules"]
    for rel in ("src/reader.rs", "src/mesh.rs", "src/tiles.rs"):
        assert modules[rel]["coupling"]["pyo3"] > 0, rel
    assert inventory["crate"]["crate_types"] == ["cdylib", "rlib"]


def test_export_crate_is_binding_free_but_path_based(inventory):
    pure = inventory["pure_rust_public_api"]
    assert {"export_ipc", "export_batches", "Format"} <= set(pure["src/exports/lib.rs"])
    assert {"validate_wkb", "Contract", "Crs"} <= set(pure["src/exports/contract.rs"])
    # Binding-free, yet filesystem-path based: not browser/range ready as-is.
    assert inventory["modules"]["src/exports/lib.rs"]["coupling"]["filesystem"] > 0
