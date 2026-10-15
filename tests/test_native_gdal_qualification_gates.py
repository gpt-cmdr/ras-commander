"""Prevent completed native-import runs with incorrect rainfall from passing."""

import json
import pytest
from pathlib import Path

from scripts.qualification.native_gdal_precipitation_matrix import assess


def test_completed_vendor_run_with_excess_rain_fails_parity():
    path = (
        Path(__file__).parent
        / "fixtures/precipitation/native_gdal_semantics_failure.json"
    )
    report = json.loads(path.read_text())
    result = assess(report)
    # This real Wine run completed through the solver and delivered positive
    # rainfall. Those facts alone hid a missing cumulative-metadata contract.
    assert result["checks"]["vendor_compute_verified"] is True
    assert result["checks"]["positive_cell_rainfall"] is True
    assert result["checks"]["after_import_exact_parity"] is False
    assert result["checks"]["final_exact_parity"] is False
    assert result["passed"] is False


def test_missing_native_import_evidence_cannot_pass():
    result = assess({"routes": {}})
    assert result["checks"]["native_import_recorded"] is False
    assert result["checks"]["native_started_without_payload"] is False
    assert result["passed"] is False


def test_completed_run_with_exact_rain_but_divergent_hydraulics_fails():
    path = (
        Path(__file__).parent
        / "fixtures/precipitation/native_gdal_hydraulic_failure.json"
    )
    result = assess(json.loads(path.read_text()))
    assert result["checks"]["vendor_compute_verified"] is True
    assert result["checks"]["temporary_exact_parity"] is True
    assert result["checks"]["positive_cell_rainfall"] is True
    assert result["checks"]["nonempty_hydraulics"] is True
    assert result["checks"]["final_exact_parity"] is False
    assert result["passed"] is False


def test_private_volume_identity_mismatch_fails_before_model_work(monkeypatch):
    import pytest
    from scripts.qualification import native_gdal_windows_versions as driver

    monkeypatch.setattr(driver, "_windows_volume_guid", lambda root: "other-volume")
    with pytest.raises(RuntimeError, match="volume mismatch"):
        driver._verify_root_volume(Path("T:/"), "task-volume")


def test_private_volume_identity_receipt_is_case_insensitive(monkeypatch):
    from scripts.qualification import native_gdal_windows_versions as driver

    monkeypatch.setattr(driver, "_windows_volume_guid", lambda root: "TASK-VOLUME")
    assert driver._verify_root_volume(Path("U:/"), "task-volume")["verified"]


def test_inspector_retains_compiled_core_count_evidence(tmp_path):
    import h5py
    from ras_commander import RasPrecipHdf

    path = tmp_path / "compiled.tmp.hdf"
    with h5py.File(path, "w") as hdf:
        parameters = hdf.create_group("Plan Data/Plan Parameters")
        parameters.attrs["1D Cores"] = 1
        parameters.attrs["2D Cores (per mesh)"] = [1, 1]
    report = RasPrecipHdf.inspect_gridded_precipitation(path)
    assert report["solver_core_settings"] == {
        "1D Cores": 1,
        "2D Cores (per mesh)": [1, 1],
    }


def test_v2_requires_same_compiled_geometry_and_keeps_original_hydraulic_gate():
    import copy

    path = (
        Path(__file__).parent
        / "fixtures/precipitation/native_gdal_hydraulic_failure.json"
    )
    report = json.loads(path.read_text())
    report["qualification_protocol"] = "native-gdal-v2-model-inputs"
    result = assess(report)
    assert result["checks"]["compiled_geometry_exact_parity"] is False
    geometry = {
        "groups": {"/Geometry": {"attributes": {"SI Units": False}}},
        "datasets": {
            "/Geometry/Manning": {
                "shape": [1],
                "dtype": "float32",
                "sha256": "same",
                "attributes": {},
            }
        },
    }
    for route in ["python_hdf", "vendor_gdal"]:
        report["routes"][route]["model_inputs"] = copy.deepcopy(geometry)
    result = assess(report)
    assert result["checks"]["compiled_geometry_exact_parity"] is True
    assert result["checks"]["final_exact_parity"] is False
    assert result["passed"] is False
    report["routes"]["vendor_gdal"]["model_inputs"]["datasets"]["/Geometry/Manning"][
        "sha256"
    ] = "changed"
    assert assess(report)["checks"]["compiled_geometry_exact_parity"] is False


def test_geometry_comparison_excludes_only_named_audit_dates():
    from scripts.qualification.native_gdal_precipitation_matrix import (
        _geometry_comparison_record,
    )
    import copy

    left = {
        "groups": {
            "/Geometry": {
                "attributes": {
                    "Data Date": "earlier",
                    "Land Cover Filename": "land.hdf",
                }
            }
        },
        "datasets": {"/Geometry/Cells": {"sha256": "same", "attributes": {}}},
    }
    right = copy.deepcopy(left)
    right["groups"]["/Geometry"]["attributes"]["Data Date"] = "later"
    assert _geometry_comparison_record(left) == _geometry_comparison_record(right)
    del right["groups"]["/Geometry"]["attributes"]["Land Cover Filename"]
    assert _geometry_comparison_record(left) != _geometry_comparison_record(right)


@pytest.mark.parametrize("expected", [{}, None, {"unrecognized": "value"}])
def test_source_association_gate_rejects_invalid_baseline(expected):
    import copy

    report = json.loads(
        (
            Path(__file__).parent
            / "fixtures/precipitation/native_gdal_hydraulic_failure.json"
        ).read_text()
    )
    report["qualification_protocol"] = "native-gdal-v2-model-inputs"
    report["source_geometry_associations"] = expected
    geometry = {
        "groups": {"/Geometry": {"attributes": {"Terrain Filename": "terrain.hdf"}}},
        "datasets": {"/Geometry/Manning": {"sha256": "same"}},
    }
    for route in ("python_hdf", "vendor_gdal"):
        report["routes"][route]["model_inputs"] = copy.deepcopy(geometry)
    assert assess(report)["checks"]["compiled_geometry_exact_parity"] is False


def test_matching_fallback_inputs_in_both_routes_cannot_hide_lost_source_layers():
    import copy

    report = json.loads(
        (
            Path(__file__).parent
            / "fixtures/precipitation/native_gdal_hydraulic_failure.json"
        ).read_text()
    )
    report["qualification_protocol"] = "native-gdal-v2-model-inputs"
    expected = {"Terrain Filename": "terrain.hdf", "Land Cover Filename": "land.hdf"}
    report["source_geometry_associations"] = expected
    geometry = {
        "groups": {"/Geometry": {"attributes": dict(expected)}},
        "datasets": {"/Geometry/Manning": {"sha256": "same"}},
    }
    for route in ("python_hdf", "vendor_gdal"):
        report["routes"][route]["model_inputs"] = copy.deepcopy(geometry)
    assert assess(report)["checks"]["compiled_geometry_exact_parity"] is True
    for route in ("python_hdf", "vendor_gdal"):
        attributes = report["routes"][route]["model_inputs"]["groups"]["/Geometry"][
            "attributes"
        ]
        del attributes["Land Cover Filename"]
    assert assess(report)["checks"]["compiled_geometry_exact_parity"] is False


def test_geometry_process_audit_requires_exact_known_schema():
    import copy
    from scripts.qualification.native_gdal_precipitation_matrix import (
        _geometry_comparison_record,
    )

    fields = [
        ("Process", "S22"),
        ("Filename", "S64"),
        ("File Date", "S21"),
        ("File Size", "<i4"),
        ("File Version", "S7"),
        ("Arguments", "S163"),
        ("Compute Time", "S12"),
        ("Compute Time (ms)", "<i4"),
    ]
    left = {
        "groups": {"/Geometry": {}},
        "datasets": {
            "/Geometry/Cells": {"sha256": "physical"},
            "/Geometry/Compute Processes": {
                "dtype": str(fields),
                "sha256": "old history",
            },
        },
    }
    right = copy.deepcopy(left)
    right["datasets"]["/Geometry/Compute Processes"]["sha256"] = "new history"
    assert _geometry_comparison_record(left) == _geometry_comparison_record(right)
    right["datasets"]["/Geometry/Compute Processes"]["dtype"] = (
        "[('Hydraulic Coefficient', '<f8')]"
    )
    assert _geometry_comparison_record(left) != _geometry_comparison_record(right)
    right = copy.deepcopy(left)
    right["datasets"]["/Geometry/Cells"]["sha256"] = "changed physical input"
    assert _geometry_comparison_record(left) != _geometry_comparison_record(right)


def test_keyed_mannings_mapping_compares_pairs_without_losing_duplicates():
    import copy
    from scripts.qualification.native_gdal_precipitation_matrix import (
        _MANNING_MAPPING,
        _canonical_mapping_record,
        _geometry_comparison_record,
    )

    def receipt(rows, raw_hash):
        raw = {
            "shape": [len(rows)],
            "dtype": "[('Region ID', '<i4'), ('Cell Index', '<i4')]",
            "sha256": raw_hash,
            "attributes": {},
        }
        return {
            "groups": {"/Geometry": {}},
            "datasets": {_MANNING_MAPPING: raw},
            "canonical_tables": {
                _MANNING_MAPPING: _canonical_mapping_record(raw, rows)
            },
        }

    left = receipt([[0, 3], [1, 8], [0, 3]], "raw A")
    reordered = receipt([[0, 3], [0, 3], [1, 8]], "raw B")
    assert _geometry_comparison_record(left) == _geometry_comparison_record(reordered)
    changed = receipt([[0, 3], [1, 8], [1, 8]], "raw C")
    assert _geometry_comparison_record(left) != _geometry_comparison_record(changed)
    forged = copy.deepcopy(reordered)
    forged["datasets"][_MANNING_MAPPING]["sha256"] = "unwitnessed raw hash"
    assert _geometry_comparison_record(forged) is None


def test_qualification_driver_does_not_seed_terms_without_explicit_assent(monkeypatch):
    from ras_commander import RasTcu
    from ras_commander.RasTcu import TcuStatus
    from scripts.qualification.native_gdal_windows_versions import _provision_tcu

    state = TcuStatus(False, "6.6", None, None, "unaccepted")
    calls = []
    monkeypatch.setattr(RasTcu, "status", staticmethod(lambda **kw: state))
    monkeypatch.setattr(
        RasTcu, "accept", staticmethod(lambda **kw: calls.append("accept") or state)
    )
    monkeypatch.setattr(
        RasTcu,
        "import_acceptance",
        staticmethod(lambda *a, **kw: calls.append("import") or state),
    )
    assert _provision_tcu(Path("vendor/Ras.exe"))["tcu"]["accepted"] is False
    assert calls == []
    _provision_tcu(Path("vendor/Ras.exe"), operator_acceptance=True)
    assert calls == ["accept"]


def test_driver_source_provenance_is_independent_of_output_directory(
    tmp_path, monkeypatch
):
    from scripts.qualification.native_gdal_windows_versions import (
        _implementation_hashes,
    )

    monkeypatch.chdir(tmp_path)
    hashes = _implementation_hashes()
    assert "scripts/qualification/native_gdal_windows_versions.py" in hashes
    assert "ras_commander/native/RasMetImportHelper.cs" in hashes
    assert all(len(value) == 64 for value in hashes.values())


def test_qualification_driver_provisions_only_explicit_trusted_export(
    monkeypatch, tmp_path
):
    from ras_commander import RasTcu
    from ras_commander.RasTcu import TcuStatus
    from scripts.qualification.native_gdal_windows_versions import _provision_tcu

    state = TcuStatus(False, "6.6", None, None, "unaccepted")
    accepted = TcuStatus(True, "6.6", None, None, "accepted")
    calls = []
    monkeypatch.setattr(RasTcu, "status", staticmethod(lambda **kw: state))
    monkeypatch.setattr(
        RasTcu,
        "accept",
        staticmethod(
            lambda **kw: pytest.fail("No blanket registry seeding authorized")
        ),
    )
    monkeypatch.setattr(
        RasTcu,
        "import_acceptance",
        staticmethod(lambda record, **kw: calls.append(record) or accepted),
    )
    export = tmp_path / "operator-export.json"
    export.write_text('{"trusted": "operator configuration"}')
    result = _provision_tcu(Path("vendor/Ras.exe"), acceptance_export=export)
    assert calls == [{"trusted": "operator configuration"}]
    assert result["tcu"]["accepted"] is True
    assert len(result["tcu_export_sha256"]) == 64


def test_input_gate_rejects_unknown_mapping_columns_and_audit_only_geometry():
    from scripts.qualification.native_gdal_precipitation_matrix import (
        _MANNING_MAPPING,
        _canonical_mapping_record,
        _geometry_comparison_record,
        _is_geometry_process_audit,
    )

    raw = {
        "shape": [1],
        "dtype": "[('Region ID', '<i4'), ('Cell Index', '<i4'), ('Weight', '<f8')]",
        "sha256": "raw",
    }
    receipt = {
        "groups": {"/Geometry": {}},
        "datasets": {_MANNING_MAPPING: raw},
        "canonical_tables": {
            _MANNING_MAPPING: _canonical_mapping_record(raw, [[0, 3]])
        },
    }
    assert _geometry_comparison_record(receipt) is None
    fields = [
        ("Process", "S22"),
        ("Filename", "S64"),
        ("File Date", "S21"),
        ("File Size", "<i4"),
        ("File Version", "S7"),
        ("Arguments", "S163"),
        ("Compute Time", "S12"),
        ("Compute Time (ms)", "<i4"),
    ]
    audit = {"dtype": str(fields), "sha256": "audit"}
    assert (
        _geometry_comparison_record(
            {
                "groups": {"/Geometry": {}},
                "datasets": {"/Geometry/Compute Processes": audit},
            }
        )
        is None
    )
    fields[0] = ("Process", "<f8")
    assert not _is_geometry_process_audit(
        "/Geometry/Compute Processes", {"dtype": str(fields)}
    )
