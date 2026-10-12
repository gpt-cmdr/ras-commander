"""PR 514 gate reproductions: text bytes, empty sidecars and failed application."""

import hashlib
import os
import random
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import RasUnsteady
from ras_commander._ras_text import _normalize_ras_newlines, _split_ras_records

PUBLIC_FLOW = (
    Path(__file__).parents[1]
    / "research/fixtures/met_data/precip_06_gridded_dss_official_baldeagle.u03"
)


def _flow(path, newline=b"\r\n", filename=b"boundary.dss"):
    path.write_bytes(
        newline.join(
            [
                b"Flow Title=Clone",
                b"Program Version=6.60",
                b"Boundary Location=,,,,,Area,,Inlet,",
                b"DSS File=" + filename,
                b"DSS Path=/A/B/FLOW//1HOUR/F/",
                b"Use DSS=True",
                b"Precipitation Mode=Enable",
                b"Met BC=Precipitation|Mode=Gridded",
                b"Met BC=Precipitation|Gridded DSS Filename=rain.dss",
                b"Met BC=Precipitation|Gridded DSS Pathname=/A/B/PRECIP//1HOUR/F/",
                b"",
            ]
        )
    )
    return path


def _sidecar(flow):
    path = Path(str(flow) + ".hdf")
    with h5py.File(path, "w") as hdf:
        rain = hdf.create_group("Event Conditions/Meteorology/Precipitation")
        rain.attrs["Enabled"] = np.uint8(1)
        rain.create_dataset("Values", data=[1.0, 2.0])
        hdf.create_dataset("Event Conditions/Boundary/Values", data=[3.0, 4.0])
    return path


@pytest.mark.parametrize("separator", [b"\xc2\x85", b"\xe2\x80\xa8"])
@pytest.mark.parametrize("remove", [False, True])
def test_unicode_separator_in_boundary_filename_gate(tmp_path, separator, remove):
    # GB reproduction: the apparent Wind Mode is inside the last physical record.
    filename = b"caf" + separator + b"Wind Mode=rain.dss"
    (tmp_path / filename.decode("utf-8")).touch()
    boundary = b"Boundary Location=,,,,,Area,,Inlet,\r\nDSS File=" + filename + b"\r\n"
    flow = tmp_path / "Model.u01"
    flow.write_bytes(
        b"Flow Title=Clone\r\nProgram Version=6.60\r\n"
        + boundary
        + b"Precipitation Mode=Enable\r\nMet BC=Precipitation|Mode=Gridded\r\n"
    )
    result = RasUnsteady.disable_meteorology(flow, remove_source_references=remove)
    # Independent byte slice, with no calls to the implementation's boundary parser.
    after = flow.read_bytes()
    start = after.index(b"Boundary Location=")
    assert after[start : start + len(boundary)] == boundary
    assert result["boundary_conditions_unchanged"]
    assert result["boundary_conditions_byte_identical"]


def test_record_tokenizer_fuzz_round_trips_arbitrary_bytes():
    rng = random.Random(51403)
    cases = [b"", bytes(range(256)), b"\r\n\r\n\n\r", b"last\r", b"no newline"]
    cases += [rng.randbytes(rng.randrange(512)) for _ in range(256)]
    for raw in cases:
        # bytes.splitlines also recognizes VT/FF; scan CR/LF independently.
        expected = []
        start = index = 0
        while index < len(raw):
            if raw[index] in (10, 13):
                index += 2 if raw[index : index + 2] == b"\r\n" else 1
                expected.append(raw[start:index])
                start = index
            else:
                index += 1
        if start < len(raw):
            expected.append(raw[start:])
        assert _split_ras_records(raw) == expected
        assert b"".join(_split_ras_records(raw)) == raw
        assert _split_ras_records(raw, keepends=False) == [
            record.rstrip(b"\r\n") for record in expected
        ]
        decoded = raw.decode("utf-8", "surrogateescape")
        assert _split_ras_records(decoded) == [
            record.decode("utf-8", "surrogateescape") for record in expected
        ]
        assert (
            "".join(_split_ras_records(decoded)).encode("utf-8", "surrogateescape")
            == raw
        )


@pytest.mark.parametrize("newline", [b"\r\n", b"\n", b"\r"])
@pytest.mark.parametrize("remove", [False, True])
def test_boundary_record_fuzz_preserves_bytes_and_reports_exact_flags(
    tmp_path, newline, remove
):
    rng = random.Random(51403)
    separators = [
        b"\xc2\x85",
        b"\xe2\x80\xa8",
        b"\xe2\x80\xa9",
        b"\x85",
        b"\x0c",
        b"\x0b",
        b"\x1c",
        b"\x1d",
        b"\x1e",
        b"\xff",
    ]
    apparent_keys = [
        b"Wind Mode=rain.dss",
        b"Met Station=rain.dss",
        b"Met BC=Precipitation|Gridded DSS Filename=rain.dss",
    ]
    for index in range(64):
        # NUL is rejected by the flow API; test transport of NUL in the tokenizer test.
        payload = rng.randbytes(rng.randrange(256)).translate(None, b"\x00\r\n")
        payload += (
            separators[index % len(separators)]
            + apparent_keys[index % len(apparent_keys)]
        )
        terminal = newline if index % 2 else b""
        records = [
            b"Boundary Location=,,,,,Area,,Inlet,",
            b"DSS File=" + payload,
            b"DSS Path=/A/B/FLOW//1HOUR/F/",
            b"Use DSS=True",
        ]
        boundary = newline.join(records) + terminal
        # Independent expected byte slice; normalize physical separators only.
        expected = b"\r\n".join(records) + (b"\r\n" if terminal else b"")
        flow = tmp_path / "Model.u01"
        flow.write_bytes(
            newline.join(
                [
                    b"Flow Title=Clone",
                    b"Program Version=6.60",
                    b"Precipitation Mode=Enable",
                    b"Met BC=Precipitation|Mode=Gridded",
                    b"Met BC=Precipitation|Gridded DSS Filename=rain.dss",
                    b"",
                ]
            )
            + boundary
        )
        before = flow.read_bytes()
        result = RasUnsteady.disable_meteorology(flow, remove_source_references=remove)
        after = flow.read_bytes()
        actual = after[after.index(b"Boundary Location=") :]
        assert actual == expected
        assert result["boundary_conditions_unchanged"] == (actual == expected)
        assert result["boundary_conditions_byte_identical"] == (actual == boundary)
        assert result["unsteady_sha256_before"] == hashlib.sha256(before).hexdigest()
        assert result["unsteady_sha256_after"] == hashlib.sha256(after).hexdigest()
        assert result["removed_source_keys"] == [
            "Met BC=Precipitation|Gridded DSS Filename"
        ]
        assert RasUnsteady._meteorology_boundary_bytes(before, normalize=False) == [
            boundary
        ]
        assert RasUnsteady._meteorology_boundary_bytes(after, normalize=False) == [
            actual
        ]
        assert RasUnsteady._meteorology_boundary_bytes(before) == [expected]


@pytest.mark.parametrize("remove", [False, True])
def test_boundary_fuzz_corruption_never_returns_unchanged(
    tmp_path, monkeypatch, remove
):
    rng = random.Random(51403)
    update = RasUnsteady._updated_met_precipitation_lines
    for index in range(16):
        payload = (
            rng.randbytes(64).translate(None, b"\x00\r\n")
            + b"\xc2\x85Wind Mode=rain.dss"
        )
        flow = _flow(tmp_path / "Model.u01", filename=payload)
        before = flow.read_bytes()

        def corrupt(lines, entries, case_index=index):
            lines, completed = update(lines, entries)
            return [
                line.replace("Wind Mode=rain.dss", f"Wind Mode=changed{case_index}.dss")
                for line in lines
            ], completed

        monkeypatch.setattr(
            RasUnsteady, "_updated_met_precipitation_lines", staticmethod(corrupt)
        )
        with pytest.raises(RuntimeError, match="changed boundary condition records"):
            RasUnsteady.disable_meteorology(flow, remove_source_references=remove)
        assert flow.read_bytes() == before


@pytest.mark.parametrize("newline", [b"\n", b"\r", b"\r\n"])
@pytest.mark.parametrize("remove", [False, True])
@pytest.mark.parametrize("public", [False, True])
def test_universal_newline_boundary_input_succeeds(tmp_path, newline, remove, public):
    flow = _flow(tmp_path / "Model.u01", newline)
    if public:
        flow.write_bytes(
            _normalize_ras_newlines(PUBLIC_FLOW.read_bytes()).replace(b"\r\n", newline)
        )
    before = flow.read_bytes()
    _sidecar(flow)
    result = RasUnsteady.disable_meteorology(flow, remove_source_references=remove)
    after = flow.read_bytes()
    assert result["boundary_conditions_unchanged"]
    assert result["boundary_comparison"] == "bytes_normalized_crlf"
    assert result["boundary_conditions_byte_identical"] == (newline == b"\r\n")
    assert RasUnsteady._meteorology_boundary_bytes(before) == (
        RasUnsteady._meteorology_boundary_bytes(after)
    )
    assert b"Precipitation Mode=Disable\r\n" in after
    with h5py.File(Path(str(flow) + ".hdf"), "r") as hdf:
        assert hdf["Event Conditions/Meteorology/Precipitation"].attrs["Enabled"] == 0


@pytest.mark.parametrize("remove", [False, True])
def test_legacy_dss_filename_bytes_are_preserved(tmp_path, remove):
    flow = _flow(tmp_path / "Model.u01", filename=b"caf\xe9.dss")
    before = RasUnsteady._meteorology_boundary_bytes(flow.read_bytes(), normalize=False)
    result = RasUnsteady.disable_meteorology(flow, remove_source_references=remove)
    assert b"DSS File=caf\xe9.dss\r\n" in flow.read_bytes()
    assert b"\xef\xbf\xbd" not in flow.read_bytes()
    assert before == RasUnsteady._meteorology_boundary_bytes(
        flow.read_bytes(), normalize=False
    )
    assert result["boundary_conditions_byte_identical"]


def test_corrupted_boundary_is_rejected_before_any_application(tmp_path, monkeypatch):
    flow = _flow(tmp_path / "Model.u01", filename=b"caf\xe9.dss")
    sidecar = _sidecar(flow)
    original = {path: path.read_bytes() for path in [flow, sidecar]}
    update = RasUnsteady._updated_met_precipitation_lines

    def corrupt(lines, entries):
        lines, completed = update(lines, entries)
        return [
            line.replace("caf\udce9.dss", "caf\ufffd.dss") for line in lines
        ], completed

    monkeypatch.setattr(
        RasUnsteady, "_updated_met_precipitation_lines", staticmethod(corrupt)
    )
    with pytest.raises(RuntimeError, match="changed boundary condition records"):
        RasUnsteady.disable_meteorology(flow)
    assert all(path.read_bytes() == raw for path, raw in original.items())


@pytest.mark.parametrize("remove", [False, True])
def test_valid_empty_sidecar_initializes_disabled_state(tmp_path, remove):
    flow = _flow(tmp_path / "Model.u01")
    sidecar = Path(str(flow) + ".hdf")
    with h5py.File(sidecar, "w"):
        pass
    assert sidecar.stat().st_size == 800
    result = RasUnsteady.disable_meteorology(flow, remove_source_references=remove)
    assert result["hdf_targets"][0]["representation"] == "unsteady_sidecar"
    with h5py.File(sidecar, "r") as hdf:
        met = hdf["Event Conditions/Meteorology"]
        assert all(int(item.attrs["Enabled"]) == 0 for item in met.values())
        assert "Precipitation" in met and "Evapotranspiration" in met


@pytest.mark.parametrize("failure_at", [1, 2, 3])
@pytest.mark.parametrize("remove", [False, True])
def test_failed_application_restores_entire_owned_input_set(
    tmp_path, monkeypatch, failure_at, remove
):
    flow = _flow(tmp_path / "Model.u01")
    flow.write_bytes(PUBLIC_FLOW.read_bytes())
    sidecar = _sidecar(flow)
    compiled = tmp_path / "Model.p01.tmp.hdf"
    compiled.write_bytes(sidecar.read_bytes())
    paths = [flow, sidecar, compiled]
    originals = {path: path.read_bytes() for path in paths}
    modes = {path: path.stat().st_mode for path in paths}
    identities = {path: path.stat().st_ino for path in paths}
    copy_file = RasUnsteady._copy_meteorology_file
    calls = 0

    def fail_copy(source, target):
        nonlocal calls
        calls += 1
        if calls == failure_at:
            target.seek(0)
            target.write(b"partially written")
            target.flush()
            raise PermissionError("injected application failure")
        return copy_file(source, target)

    monkeypatch.setattr(RasUnsteady, "_copy_meteorology_file", staticmethod(fail_copy))
    with pytest.raises(PermissionError, match="injected application failure"):
        RasUnsteady.disable_meteorology(
            flow, compiled_plan_hdf=compiled, remove_source_references=remove
        )
    assert all(path.read_bytes() == raw for path, raw in originals.items())
    assert all(path.stat().st_mode == mode for path, mode in modes.items())
    assert all(path.stat().st_ino == identity for path, identity in identities.items())
    assert set(tmp_path.iterdir()) == set(paths)


@pytest.mark.parametrize("remove", [False, True])
@pytest.mark.parametrize(
    "bad",
    [
        "event_dataset",
        "sidecar_met_dataset",
        "compiled_met_dataset",
        "variable_dataset",
        "not_hdf",
    ],
)
def test_malformed_hdf_never_mutates_any_input(tmp_path, remove, bad):
    flow = _flow(tmp_path / "Model.u01")
    sidecar = _sidecar(flow)
    compiled = tmp_path / "Model.p01.tmp.hdf"
    compiled.write_bytes(sidecar.read_bytes())
    target = compiled if bad == "compiled_met_dataset" else sidecar
    if bad == "not_hdf":
        target.write_bytes(b"not an HDF file")
    else:
        with h5py.File(target, "r+") as hdf:
            key = {
                "event_dataset": "Event Conditions",
                "sidecar_met_dataset": "Event Conditions/Meteorology",
                "compiled_met_dataset": "Event Conditions/Meteorology",
                "variable_dataset": "Event Conditions/Meteorology/Precipitation",
            }[bad]
            del hdf[key]
            hdf.create_dataset(key, data=[1])
    originals = {path: path.read_bytes() for path in [flow, sidecar, compiled]}
    with pytest.raises((ValueError, OSError)):
        RasUnsteady.disable_meteorology(
            flow, compiled_plan_hdf=compiled, remove_source_references=remove
        )
    assert all(path.read_bytes() == raw for path, raw in originals.items())
    assert set(tmp_path.iterdir()) == set(originals)


@pytest.mark.parametrize(
    "raw", [b"arbitrary\x00non-flow", b"Flow Title=Clone\r\n\x00", b"arbitrary text\n"]
)
def test_invalid_flow_text_is_rejected_without_mutation(tmp_path, raw):
    flow = tmp_path / "Model.u01"
    flow.write_bytes(raw)
    sidecar = _sidecar(flow)
    original_hdf = sidecar.read_bytes()
    with pytest.raises(ValueError, match="Invalid unsteady-flow text"):
        RasUnsteady.disable_meteorology(flow)
    assert flow.read_bytes() == raw
    assert sidecar.read_bytes() == original_hdf


@pytest.mark.parametrize(
    "source_keys",
    [
        ["Constant Value", "Constant Units"],
        ["Point Interpolation"],
        ["Gridded Source", "Gridded DSS Filename", "Gridded DSS Pathname"],
        [
            "Gridded GDAL Filename",
            "Gridded GDAL Group",
            "Gridded GDAL Folder",
            "Gridded GDAL Filter",
            "Gridded GDAL Datasetname",
        ],
    ],
)
def test_primary_precipitation_keys_are_in_removal_audit(tmp_path, source_keys):
    flow = tmp_path / "Model.u01"
    full_keys = [f"Met BC=Precipitation|{key}" for key in source_keys]
    flow.write_bytes(
        (
            "Flow Title=Clone\r\n"
            + "".join(f"{key}=source=with_equals\r\n" for key in full_keys)
        ).encode()
    )
    result = RasUnsteady.disable_meteorology(flow, remove_source_references=True)
    assert set(result["removed_source_keys"]) == set(full_keys)
    assert all(key.encode() + b"=" not in flow.read_bytes() for key in full_keys)


def test_successful_application_preserves_permissions(tmp_path):
    flow = _flow(tmp_path / "Model.u01")
    sidecar = _sidecar(flow)
    os.chmod(flow, 0o640)
    os.chmod(sidecar, 0o600)
    modes = {path: path.stat().st_mode for path in [flow, sidecar]}
    identities = {path: path.stat().st_ino for path in [flow, sidecar]}
    RasUnsteady.disable_meteorology(flow)
    assert all(path.stat().st_mode == mode for path, mode in modes.items())
    assert all(path.stat().st_ino == identity for path, identity in identities.items())


def test_original_second_replace_failure_reproduction_no_longer_replaces_inputs(
    tmp_path, monkeypatch
):
    flow = _flow(tmp_path / "Model.u01")
    flow.write_bytes(PUBLIC_FLOW.read_bytes())
    _sidecar(flow)
    replace = os.replace
    calls = 0

    def fail_second_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("injected second replacement failure")
        return replace(source, target)

    monkeypatch.setattr(os, "replace", fail_second_replace)
    result = RasUnsteady.disable_meteorology(flow)
    assert calls == 0
    assert result["boundary_conditions_unchanged"]


@pytest.mark.parametrize("newline", [b"\r\n", b"\n", b"\r"])
def test_legacy_boundary_location_nul_padding_is_retained(tmp_path, newline):
    flow = tmp_path / "Model.u01"
    flow.write_bytes(
        newline.join(
            [
                b"Flow Title=Legacy",
                b"Program Version=4.01",
                b"Boundary Location=Split,Upper,101," + b"\x00" * 8 + b",,,,",
                b"Use DSS=False",
                b"",
            ]
        )
    )
    before = RasUnsteady._meteorology_boundary_bytes(flow.read_bytes())
    RasUnsteady.disable_meteorology(flow)
    assert RasUnsteady._meteorology_boundary_bytes(flow.read_bytes()) == before


@pytest.mark.parametrize("remove", [False, True])
def test_native_meteorology_attributes_dataset_is_supported(tmp_path, remove):
    flow = _flow(tmp_path / "Model.u01")
    sidecar = _sidecar(flow)
    with h5py.File(sidecar, "r+") as hdf:
        hdf.create_dataset("Event Conditions/Meteorology/Attributes", data=[1, 2])
    RasUnsteady.disable_meteorology(flow, remove_source_references=remove)
    with h5py.File(sidecar, "r") as hdf:
        if remove:
            assert "Event Conditions/Meteorology/Attributes" not in hdf
        else:
            assert list(hdf["Event Conditions/Meteorology/Attributes"][:]) == [1, 2]


def test_application_retains_hard_links_and_file_identity(tmp_path):
    flow = _flow(tmp_path / "Model.u01")
    sidecar = _sidecar(flow)
    aliases = {path: tmp_path / (path.name + ".alias") for path in [flow, sidecar]}
    for path, alias in aliases.items():
        os.link(path, alias)
    RasUnsteady.disable_meteorology(flow)
    assert all(os.path.samefile(path, alias) for path, alias in aliases.items())
    assert all(
        path.read_bytes() == alias.read_bytes() for path, alias in aliases.items()
    )


@pytest.mark.parametrize("newline", [b"\r\n", b"\n", b"\r"])
@pytest.mark.parametrize(
    "filename,expected_sha256",
    [
        (
            "precip_00_disabled_official_davis.u01",
            "1b1cf6fb13a2a56f7d08744a4f36cee36ef7ed346e2d5f54babbf38f93945082",
        ),
        (
            "precip_01_enabled_none_gui_davis.u01",
            "a2faebaf82038a7e2fd4bd5a5ae65ee3bbee68c4fe49d8698a727e5f68677dfd",
        ),
        (
            "precip_02_constant_gui_davis.u01",
            "a2faebaf82038a7e2fd4bd5a5ae65ee3bbee68c4fe49d8698a727e5f68677dfd",
        ),
        (
            "precip_03_point_thiessen_gui_davis.u01",
            "a2faebaf82038a7e2fd4bd5a5ae65ee3bbee68c4fe49d8698a727e5f68677dfd",
        ),
        (
            "precip_04_gridded_dss_gui_davis.u01",
            "a2faebaf82038a7e2fd4bd5a5ae65ee3bbee68c4fe49d8698a727e5f68677dfd",
        ),
        (
            "precip_05_gridded_gdal_gui_davis.u01",
            "a2faebaf82038a7e2fd4bd5a5ae65ee3bbee68c4fe49d8698a727e5f68677dfd",
        ),
        (
            "precip_06_gridded_dss_official_baldeagle.u03",
            "f83ee705d7735424830f24ae94f551a31afa2ad5e14b6694d1c8098a9071521f",
        ),
    ],
)
def test_default_output_matches_main_for_official_and_gui_flows(
    tmp_path, newline, filename, expected_sha256
):
    # Expected default output hashes come from main at 08d7226c, before PR 514.
    source = PUBLIC_FLOW.parent / filename
    raw = _normalize_ras_newlines(source.read_bytes()).replace(b"\r\n", newline)
    flow = tmp_path / "Model.u01"
    flow.write_bytes(raw)
    RasUnsteady.disable_meteorology(flow)
    assert hashlib.sha256(flow.read_bytes()).hexdigest() == expected_sha256


def test_corrupted_application_cannot_return_boundary_integrity_evidence(
    tmp_path, monkeypatch
):
    flow = _flow(tmp_path / "Model.u01", filename=b"caf\xe9.dss")
    sidecar = _sidecar(flow)
    originals = {path: path.read_bytes() for path in [flow, sidecar]}
    copy_file = RasUnsteady._copy_meteorology_file

    def corrupt(source, destination):
        copy_file(source, destination)
        if source.name == flow.name:
            raw = source.read_bytes().replace(b"caf\xe9.dss", b"caf?.dss")
            destination.seek(0)
            destination.write(raw)
            destination.truncate()

    monkeypatch.setattr(RasUnsteady, "_copy_meteorology_file", staticmethod(corrupt))
    with pytest.raises(RuntimeError, match="output differs from staging"):
        RasUnsteady.disable_meteorology(flow)
    assert all(path.read_bytes() == raw for path, raw in originals.items())


def test_cleanup_failure_retains_staging_and_reports_success(
    tmp_path, monkeypatch, caplog
):
    import shutil

    flow = _flow(tmp_path / "Model.u01")
    _sidecar(flow)

    def fail_cleanup(*args, **kwargs):
        raise PermissionError("injected cleanup failure")

    monkeypatch.setattr(shutil, "rmtree", fail_cleanup)
    result = RasUnsteady.disable_meteorology(flow)
    assert result["boundary_conditions_unchanged"]
    assert "Meteorology staging retained" in caplog.text
    assert len(list(tmp_path.glob(".*.meteorology-*"))) == 2
