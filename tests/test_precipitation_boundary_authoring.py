"""Area-boundary authoring controls; native solver qualification is separate."""

from pathlib import Path
import os
import shutil

import pandas as pd
import pytest

from ras_commander import RasUnsteady


@pytest.fixture
def native_record_excerpt(tmp_path):
    # Exact record forms from the native Weise/Davis geometry and flow files;
    # truncated controls validate authoring, not hydraulic model validity.
    geometry = tmp_path / "Model.g01"
    geometry.write_text("Geom Title=Area authoring control\nStorage Area=2DArea          ,,\nStorage Area Is2D=-1\n")
    flow = tmp_path / "Model.u01"
    flow.write_text("Flow Title=Authoring control\nProgram Version=6.60\nUse Restart= 0\nPrecipitation Mode=Disable\n")
    return flow, geometry


def test_create_boundary_then_author_interval_depths_and_repeat_is_idempotent(native_record_excerpt):
    flow, geometry = native_record_excerpt
    created = RasUnsteady.ensure_2d_precipitation_boundary(flow, geometry, area_2d="2DArea")
    assert created["created"]
    records = flow.read_text().splitlines()
    assert sum(line.startswith("Boundary Location=") for line in records) == 1
    assert "Precipitation Hydrograph= 2" in records
    frame = pd.DataFrame({"hour": [.5, 1], "incremental_depth": [.1, .2], "cumulative_depth": [.1, .3]})
    RasUnsteady.set_precipitation_hyetograph(flow, frame, boundary_name="2DArea")
    before = flow.read_bytes()
    repeated = RasUnsteady.ensure_2d_precipitation_boundary(str(flow), str(geometry), area_2d="2DArea")
    assert not repeated["created"]
    assert flow.read_bytes() == before
    assert b"Interval=30MIN" in before
    assert b"Precipitation Mode=Disable" in before


@pytest.mark.parametrize("area", [None, "", " ", 7, "wrong", "2darea", "LongerThan16Characters", "area,name", "area\nname"])
def test_invalid_area_preserves_original_bytes(native_record_excerpt, area):
    flow, geometry = native_record_excerpt
    before = flow.read_bytes()
    with pytest.raises(ValueError):
        RasUnsteady.ensure_2d_precipitation_boundary(flow, geometry, area_2d=area)
    assert flow.read_bytes() == before


@pytest.mark.parametrize("geometry_text", [
    "Geom Title=Empty\n",
    "Storage Area=2DArea,,\nStorage Area Is2D=0\n",
    "Storage Area=2DArea,,\nStorage Area Is2D=-1\nStorage Area=2DArea,,\nStorage Area Is2D=-1\n",
])
def test_missing_traditional_or_duplicate_area_is_refused(native_record_excerpt, geometry_text):
    flow, geometry = native_record_excerpt
    geometry.write_text(geometry_text)
    before = flow.read_bytes()
    with pytest.raises(ValueError):
        RasUnsteady.ensure_2d_precipitation_boundary(flow, geometry, area_2d="2DArea")
    assert flow.read_bytes() == before


@pytest.mark.parametrize("encoding", ["utf-8", "cp1252"])
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_creation_preserves_text_encoding_and_normalizes_native_newlines(native_record_excerpt, encoding, newline):
    flow, geometry = native_record_excerpt
    text = "Flow Title=Río\nProgram Version=6.60\nUse Restart= 0\nPrecipitation Mode=Disable"
    flow.write_bytes(text.replace("\n", newline).encode(encoding))
    RasUnsteady.ensure_2d_precipitation_boundary(flow, geometry, area_2d="2DArea")
    after = flow.read_bytes()
    assert after.startswith("Flow Title=Río\r\n".encode(encoding))
    assert after.endswith(b"Precipitation Mode=Disable")
    assert b"\n" not in after.replace(b"\r\n", b"")


@pytest.mark.parametrize("change", ["dss", "other_type", "duplicate", "mixed_newlines", "mixed_type", "conflicting_location"])
def test_existing_conflicts_fail_without_mutation(native_record_excerpt, change):
    flow, geometry = native_record_excerpt
    RasUnsteady.ensure_2d_precipitation_boundary(flow, geometry, area_2d="2DArea")
    content = flow.read_bytes()
    if change == "dss":
        content = content.replace(b"Use DSS=False", b"Use DSS=True")
    elif change == "other_type":
        content = content.replace(b"Precipitation Hydrograph=", b"Flow Hydrograph=")
    elif change == "duplicate":
        first = content.index(b"Boundary Location=")
        last = content.index(b"Precipitation Mode=")
        content = content[:last] + content[first:last] + content[last:]
    elif change == "mixed_newlines":
        content = content.replace(b"\r\n", b"\n", 1)
    elif change == "mixed_type":
        content = content.replace(b"Interval=1HOUR", b"Flow Hydrograph= 1\r\n    0.00\r\nInterval=1HOUR")
    else:
        content = content.replace(b"Boundary Location=                ,", b"Boundary Location=River           ,")
    flow.write_bytes(content)
    with pytest.raises(ValueError):
        RasUnsteady.ensure_2d_precipitation_boundary(flow, geometry, area_2d="2DArea")
    assert flow.read_bytes() == content


def test_atomic_replace_failure_preserves_original(native_record_excerpt, monkeypatch):
    flow, geometry = native_record_excerpt
    before = flow.read_bytes()
    def fail(*args, **kwargs):
        raise PermissionError("controlled replacement failure")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(PermissionError):
        RasUnsteady.ensure_2d_precipitation_boundary(flow, geometry, area_2d="2DArea")
    assert flow.read_bytes() == before


def test_missing_header_preserves_original(native_record_excerpt):
    flow, geometry = native_record_excerpt
    flow.write_bytes(b"Unknown Header=1\r\n")
    before = flow.read_bytes()
    with pytest.raises(ValueError, match="header"):
        RasUnsteady.ensure_2d_precipitation_boundary(flow, geometry, area_2d="2DArea")
    assert flow.read_bytes() == before


@pytest.mark.parametrize("content", [
    b"Plan Title=Wrong file\r\nProgram Version=6.60\r\n",
    b"Geom Title=Wrong file\r\nProgram Version=6.60\r\n",
    b"Flow Title=One\r\nFlow Title=Two\r\n",
])
def test_wrong_file_or_duplicate_flow_title_is_never_modified(native_record_excerpt, content):
    flow, geometry = native_record_excerpt
    flow.write_bytes(content)
    with pytest.raises(ValueError, match="header"):
        RasUnsteady.ensure_2d_precipitation_boundary(flow, geometry, area_2d="2DArea")
    assert flow.read_bytes() == content


@pytest.mark.parametrize("old,new", [
    (b"Use DSS=False", b"Use DSS= True"),
    (b"Use DSS=False", b"Use DSS=Maybe"),
    (b"Use DSS=False", b"Use DSS=False\r\nUse DSS=False"),
    (b"Precipitation Hydrograph= 2", b"Precipitation Hydrograph= potato"),
    (b"Precipitation Hydrograph= 2", b"Precipitation Hydrograph= 2000000000"),
    (b"    0.00    0.00", b"    0.00"),
    (b"    0.00    0.00", b"     nan    0.00"),
    (b"    0.00    0.00", b"   -1.00    0.00"),
    (b"Interval=1HOUR", b"Interval=unknown"),
    (b"Interval=1HOUR", b"Interval=1HOURgarbage"),
    (b"    0.00    0.00", b"    0.00  BAD1.0"),
    (b"    0.00    0.00", b"    0.00    0.00    1.00"),
])
def test_malformed_existing_inline_state_is_refused(native_record_excerpt, old, new):
    flow, geometry = native_record_excerpt
    RasUnsteady.ensure_2d_precipitation_boundary(flow, geometry, area_2d="2DArea")
    content = flow.read_bytes().replace(old, new)
    flow.write_bytes(content)
    with pytest.raises(ValueError):
        RasUnsteady.ensure_2d_precipitation_boundary(flow, geometry, area_2d="2DArea")
    assert flow.read_bytes() == content


def test_real_si_project_authoring(tmp_path):
    configured = os.environ.get("RAS_PRECIP_WEISE_PROJECT")
    if not configured:
        pytest.skip("Set RAS_PRECIP_WEISE_PROJECT to a retained authentic Weise project")
    source = Path(configured)
    flow, geometry = tmp_path / "Weise.u01", source / "Weise.g08"
    shutil.copy2(source / "Weise.u01", flow)
    assert RasUnsteady.ensure_2d_precipitation_boundary(flow, geometry, area_2d="2DArea")["created"]
    before = flow.read_bytes()
    assert not RasUnsteady.ensure_2d_precipitation_boundary(flow, geometry, area_2d="2DArea")["created"]
    assert flow.read_bytes() == before
