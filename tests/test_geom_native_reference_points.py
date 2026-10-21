"""Portable native-point regressions on a public RasExamples geometry excerpt."""

import os
import shutil
from pathlib import Path

import numpy as np
import pytest
from pyproj import Transformer

from ras_commander import GeomBcLines, GeomLateral, GeomProjection, GeomReferenceFeatures


FIXTURE = Path(__file__).parent / "fixtures/reference_points/bald_eagle_connection.g09"
POINTS = [
    dict(name="RP_Upper", x=2000000.0, y=312250.0),
    dict(name="RP_Middle", x=2030250.0, y=335250.0),
    dict(name="RP_Lower", x=2063500.0, y=352250.0),
]


@pytest.fixture
def geometry(tmp_path):
    target = tmp_path / "model.g09"
    shutil.copyfile(FIXTURE, target)
    return target


def native_records(data):
    return b"".join(
        line for line in data.splitlines(keepends=True)
        if line.startswith((b"Reference Point Name=", b"Reference Point Position="))
    )


def without_native_records(data):
    return b"".join(
        line for line in data.splitlines(keepends=True)
        if not line.startswith((b"Reference Point Name=", b"Reference Point Position="))
    )


def test_native_write_read_keeps_literal_names_and_ic_records(geometry):
    assert GeomReferenceFeatures.get_reference_points(geometry) == POINTS
    before = without_native_records(geometry.read_bytes())
    geometry.write_bytes(before)
    assert GeomReferenceFeatures.get_reference_points(geometry) == []

    assert GeomReferenceFeatures.add_reference_points(geometry, POINTS) == 3

    after = geometry.read_bytes()
    assert GeomReferenceFeatures.get_reference_points(geometry) == POINTS
    expected = "".join(
        f"Reference Point Name={p['name']:<40}\r\n"
        f"Reference Point Position={p['x']},{p['y']}\r\n" for p in POINTS
    ).encode("utf-8")
    assert native_records(after) == expected
    assert without_native_records(after) == before
    assert b"IC Point Name=Reference Point RP_Upper" in after
    assert b"IC Point Elev=615.25\r\n" in after
    assert after.index(b"Reference Point Name=") < after.index(b"LCMann ")
    assert after.replace(b"\r\n", b"").find(b"\n") == -1
    assert Path(str(geometry) + ".bak").read_bytes() == before


@pytest.mark.parametrize("edit", ["delete", "rewrite", "profile", "culvert", "gate", "remap"])
def test_adjacent_native_points_survive_connection_edits(geometry, edit):
    original = geometry.read_bytes()
    before = GeomReferenceFeatures.get_reference_points(geometry)
    records = GeomLateral.get_connection_data(geometry)
    assert len(records) == 1
    assert "BC Line Name=" not in original.decode()
    assert "Reference Line Name=" not in original.decode()
    assert "Reference Point Name=" not in records.RawBlock.iloc[0]

    if edit == "delete":
        GeomLateral.delete_connection(geometry, "Sayers Dam")
        assert GeomLateral.get_connection_data(geometry).empty
    elif edit == "rewrite":
        GeomLateral.write_connection_data(geometry, records)
        assert GeomLateral.get_connection_data(geometry).Name.tolist() == ["Sayers Dam"]
    elif edit == "profile":
        profile = GeomLateral.get_connection_profile(geometry, "Sayers Dam")
        profile["Elevation"] += 0.25
        GeomLateral.set_connection_profile(geometry, "Sayers Dam", profile)
        actual = GeomLateral.get_connection_profile(geometry, "Sayers Dam")
        np.testing.assert_allclose(actual[["Station", "Elevation"]], profile[["Station", "Elevation"]])
    elif edit == "culvert":
        GeomLateral.set_connection_culverts(geometry, "Sayers Dam", [dict(
            Shape=2, Span=8.0, Rise=6.0, Length=60.0, ManningsN=0.024,
            UpstreamInvert=539.56, DownstreamInvert=539.06,
            barrels=[dict(name="Test barrel", us_xy=(2000000.0, 312250.0),
                          ds_xy=(2000060.0, 312250.0), us_station=0.0, ds_station=0.0)],
        )])
        assert len(GeomLateral.get_connection_culverts(geometry, "Sayers Dam")) == 1
    elif edit == "gate":
        gates = GeomLateral.get_connection_gates(geometry, "Sayers Dam")
        assert not gates.empty
        gates["GateName"] = "Updated gate"
        GeomLateral.set_connection_gates(geometry, "Sayers Dam", gates)
        actual = GeomLateral.get_connection_gates(geometry, "Sayers Dam")
        assert actual.GateName.tolist() == ["Updated gate"]
    else:
        remapped = GeomLateral.remap_connection_areas(geometry, {"BaldEagleCr": "RenamedArea"})
        # Remapping returns records without mutation; exercise the actual write too.
        GeomLateral.write_connection_data(geometry, remapped)
        actual = GeomLateral.get_connection_data(geometry)
        assert actual.From.tolist() == actual.To.tolist() == ["RenamedArea"]

    assert GeomReferenceFeatures.get_reference_points(geometry) == before
    assert native_records(geometry.read_bytes()) == native_records(original)


def test_bc_insertion_precedes_adjacent_native_points(geometry):
    original = geometry.read_bytes()
    result = GeomBcLines.add_bc_lines(geometry, [dict(
        name="Test boundary", storage_area="BaldEagleCr",
        coordinates=[(2002713.51, 323365.78), (2002741.38, 323338.79)],
    )])
    assert result["inserted"] == ["Test boundary"]
    after = geometry.read_bytes()
    assert after.index(b"Connection=Sayers Dam") < after.index(b"BC Line Name=")
    assert after.index(b"BC Line Text Position=") < after.index(b"Reference Point Name=")
    assert native_records(after) == native_records(original)
    assert GeomReferenceFeatures.get_reference_points(geometry) == POINTS


def test_author_reproject_readback_transforms_native_and_ic(geometry, tmp_path):
    geometry.write_bytes(without_native_records(geometry.read_bytes()))
    GeomReferenceFeatures.add_reference_points(geometry, POINTS)
    source = geometry.read_bytes()
    target = tmp_path / "projected.g09"
    result = GeomProjection.reproject_geometry(
        geometry, "EPSG:2272", "EPSG:32129", output_geom=target
    )
    transformer = Transformer.from_crs(2272, 32129, always_xy=True)
    actual = GeomReferenceFeatures.get_reference_points(target)
    assert [p["name"] for p in actual] == [p["name"] for p in POINTS]
    for point, original in zip(actual, POINTS):
        expected = transformer.transform(original["x"], original["y"])
        np.testing.assert_allclose([point["x"], point["y"]], expected, rtol=0, atol=1e-7)
    ic = next(line for line in target.read_text().splitlines() if line.startswith("IC Point Position="))
    expected_ic = transformer.transform(POINTS[0]["x"], POINTS[0]["y"])
    np.testing.assert_allclose(list(map(float, ic.split("=", 1)[1].split(","))), expected_ic, rtol=0, atol=1e-7)
    assert "IC Point Elev=615.25" in target.read_text()
    assert result["transformed"]["position_lines"] == 4
    assert geometry.read_bytes() == source


@pytest.mark.parametrize("bad", [
    dict(name="", x=1, y=2), dict(name="x" * 41, x=1, y=2),
    dict(name="bad\nInjected=", x=1, y=2), dict(name="bad", x=float("nan"), y=2),
    dict(name="bad", x=1, y=float("inf")), dict(name="Valid", x=1, y=2),
    dict(name="RP_Upper", x=1, y=2),
])
def test_invalid_batch_leaves_geometry_and_backups_untouched(geometry, bad):
    before = geometry.read_bytes()
    with pytest.raises(ValueError):
        GeomReferenceFeatures.add_reference_points(geometry, [dict(name="Valid", x=1, y=2), bad])
    assert geometry.read_bytes() == before
    assert not Path(str(geometry) + ".bak").exists()


@pytest.mark.parametrize("tail", [
    "Reference Point Name=Bad\n", "Reference Point Name=Bad\nReference Point Position=1,2,3\n",
    "Reference Point Name=Bad\nReference Point Position=nan,2\n",
])
def test_malformed_native_records_raise(geometry, tail):
    with geometry.open("a", encoding="utf-8") as stream:
        stream.write(tail)
    with pytest.raises(ValueError):
        GeomReferenceFeatures.get_reference_points(geometry)


def test_atomic_replace_failure_preserves_original_and_removes_temp(geometry, monkeypatch):
    original = geometry.read_bytes()

    def fail_replace(*args):
        raise PermissionError("injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(IOError, match="injected replace failure"):
        GeomReferenceFeatures.add_reference_points(geometry, [dict(name="Extra", x=1, y=2)])
    assert geometry.read_bytes() == original
    assert Path(str(geometry) + ".bak").read_bytes() == original
    assert not Path(str(geometry) + ".tmp").exists()
