"""Native engine text has platform-independent CRLF serialization."""

import builtins
import hashlib
import inspect
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from ras_commander import (
    RasCmdr,
    RasPlan,
    RasPreprocess,
    RasPrj,
    RasSteady,
    RasUnsteady,
)
from ras_commander._ras_text import (
    _normalize_ras_newlines,
    _write_ras_text,
    _write_ras_xml,
)
from ras_commander.geom.GeomParser import GeomParser
from ras_commander.RasPermutation import RasPermutation

CANARY = Path(__file__).parent / "fixtures" / "ras_text_crlf" / "canary_86.f01"


@pytest.mark.parametrize(
    "payload", [b"a\xff\nb\x81\r\nc\xfe\rd", b"\xff\n", b"\x81", b""]
)
def test_byte_newline_normalizer_preserves_unknown_encoding(payload):
    expected = (
        payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n").replace(b"\n", b"\r\n")
    )
    normalized = _normalize_ras_newlines(payload)
    assert normalized == expected
    assert _normalize_ras_newlines(normalized) == normalized


@pytest.mark.parametrize("encoding", ["utf-8", "unicode", "iso-8859-1"])
@pytest.mark.parametrize("declaration", [None, False, True])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_xml_writer_preserves_elementtree_serialization(
    tmp_path, encoding, declaration, newline
):
    root = ET.Element("RASMapper", {"name": "café & terrain"})
    root.text = f"{newline}first{newline}second{newline}"
    ET.SubElement(root, "Geometry", {"Filename": "Model.g01.hdf"})
    tree = ET.ElementTree(root)
    buffer = StringIO() if encoding == "unicode" else BytesIO()
    tree.write(buffer, encoding=encoding, xml_declaration=declaration)
    expected = _normalize_ras_newlines(buffer.getvalue())
    if isinstance(expected, str):
        # ElementTree.write(path, encoding="unicode") opens UTF-8, even when
        # the platform's default text encoding differs.
        expected = expected.encode("utf-8", errors="xmlcharrefreplace")
    path = tmp_path / "Model.rasmap"
    _write_ras_xml(tree, path, encoding=encoding, xml_declaration=declaration)
    assert assert_crlf(path) == expected
    _write_ras_xml(tree, path, encoding=encoding, xml_declaration=declaration)
    assert path.read_bytes() == expected


def test_native_linux_compute_still_converts_to_lf_by_default():
    assert (
        inspect.signature(RasCmdr.compute_plan_linux).parameters["dos2unix"].default
        is True
    )


def test_preprocessing_still_converts_to_lf_by_default():
    assert (
        inspect.signature(RasPreprocess.preprocess_plan)
        .parameters["fix_line_endings"]
        .default
        is True
    )


def test_native_linux_geometry_preprocessor_still_converts_to_lf_by_default():
    assert (
        inspect.signature(RasCmdr.preprocess_geometry_linux)
        .parameters["dos2unix"]
        .default
        is True
    )


@pytest.fixture(autouse=True)
def linux_text_writes(monkeypatch):
    """Simulate Linux text-mode writes even on a Windows test host.

    Changing os.linesep does not affect Python's text I/O. Force its default
    newline=None writes to newline='\n', while honoring explicit newline values.
    Cover builtins.open and Path.open (which uses io.open) independently.
    """
    real_open = builtins.open
    real_path_open = Path.open

    def linux_open(file, mode="r", *args, **kwargs):
        if (
            any(flag in mode for flag in "wax+")
            and "b" not in mode
            and len(args) < 4
            and kwargs.get("newline") is None
        ):
            kwargs["newline"] = "\n"
        return real_open(file, mode, *args, **kwargs)

    def linux_path_open(
        self, mode="r", buffering=-1, encoding=None, errors=None, newline=None
    ):
        if any(flag in mode for flag in "wax+") and "b" not in mode:
            newline = "\n" if newline is None else newline
        return real_path_open(self, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(builtins, "open", linux_open)
    monkeypatch.setattr(Path, "open", linux_path_open)


def assert_crlf(path):
    data = path.read_bytes()
    assert b"\r\n" in data
    without_crlf = data.replace(b"\r\n", b"")
    assert b"\r" not in without_crlf
    assert b"\n" not in without_crlf
    return data


def test_linux_write_simulation_honors_explicit_newlines(tmp_path):
    path = tmp_path / "control.txt"
    path.write_text("a\nb\n", encoding="utf-8")
    assert path.read_bytes() == b"a\nb\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("a\nb\n")
    assert path.read_bytes() == b"a\nb\n"
    with open(path, "w", encoding="utf-8", newline="\r\n") as handle:
        handle.write("a\nb\n")
    assert path.read_bytes() == b"a\r\nb\r\n"


@pytest.mark.parametrize(
    "extension",
    ["prj", "g01", "f01", "u01", "p01", "q01", "b01", "c01", "x01", "rasmap"],
)
@pytest.mark.parametrize(
    "text", ["a\nb\n", "a\r\nb\r\n", "a\rb\r", "a\nb\r\nc\rd", "no newline", ""]
)
def test_shared_writer_exact_bytes(tmp_path, extension, text):
    path = tmp_path / f"Model.{extension}"
    _write_ras_text(path, text, encoding="utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    assert path.read_bytes() == normalized.replace("\n", "\r\n").encode()
    assert path.read_text(encoding="utf-8") == normalized
    original = path.read_bytes()
    _write_ras_text(path, path.read_text(encoding="utf-8"), encoding="utf-8")
    assert path.read_bytes() == original


def test_shared_writer_encoding_and_error_policy(tmp_path):
    path = tmp_path / "Model.prj"
    _write_ras_text(path, "Title=default encoding\n")
    assert path.read_bytes() == b"Title=default encoding\r\n"
    _write_ras_text(path, "Titre=café\n", encoding="cp1252")
    assert path.read_bytes() == b"Titre=caf\xe9\r\n"
    _write_ras_text(path, "Title=\udcff\n", encoding="utf-8", errors="surrogateescape")
    assert path.read_bytes() == b"Title=\xff\r\n"


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_real_86_profile_canary_round_trip(tmp_path, newline):
    retained = CANARY.read_bytes()
    assert hashlib.sha256(retained).hexdigest() == (
        "b0f0ae06953c12d6673090f79ece99785f61e525ef39d6090d64c95b79a6a5c1"
    )
    source = tmp_path / "source.f01"
    source.write_bytes(retained.replace(b"\r\n", newline))
    parsed = RasSteady.read_flow_file(source)
    assert len(parsed["profile_names"]) == 86
    output = tmp_path / "output.f01"
    RasSteady.write_flow_file(output, parsed)
    canonical = assert_crlf(output)
    assert RasSteady.read_flow_file(output) == parsed
    RasSteady.update_flow_file(output, flow_title=parsed["flow_title"])
    assert output.read_bytes() == canonical
    other = tmp_path / "other.f01"
    RasSteady.write_flow_file(other, RasSteady.read_flow_file(CANARY))
    assert other.read_bytes() == canonical


@pytest.mark.parametrize("count", [7, 76, 86])
def test_steady_create_profile_ladders(tmp_path, count):
    parsed = RasSteady.read_flow_file(CANARY)
    path = tmp_path / "created.f01"
    RasSteady.create_flow_file(
        path,
        profile_names=parsed["profile_names"][:count],
        flow_changes=[
            {**item, "flows": item["flows"][:count]} for item in parsed["flow_changes"]
        ],
    )
    assert_crlf(path)
    assert len(RasSteady.read_flow_file(path)["profile_names"]) == count


def test_plan_public_writer(tmp_path):
    path = tmp_path / "Model.p01"
    path.write_bytes(b"Plan Title=CRLF\nSimulation Date=01JAN2000,0000,02JAN2000,2359")
    RasPlan.update_simulation_date(
        path,
        datetime(2026, 10, 1, tzinfo=timezone.utc),
        datetime(2026, 10, 2, tzinfo=timezone.utc),
    )
    assert assert_crlf(path) == (
        b"Plan Title=CRLF\r\nSimulation Date=01OCT2026,0000,02OCT2026,0000"
    )


def test_project_public_writer(tmp_path):
    path = tmp_path / "Model.prj"
    path.write_bytes(b"Proj Title=CRLF\nCurrent Plan=p01\nPlan File=p02\n")
    project = SimpleNamespace(
        prj_file=path,
        plan_df=pd.DataFrame({"plan_number": ["02"]}),
        check_initialized=lambda: None,
    )
    RasPrj.set_current_plan(project, "02")
    assert (
        assert_crlf(path) == b"Proj Title=CRLF\r\nCurrent Plan=p02\r\nPlan File=p02\r\n"
    )


def test_geometry_atomic_writer_real_template(tmp_path):
    import ras_commander

    template = (
        Path(ras_commander.__file__).parent / "resources/templates/RAS_6.6/TEMPLATE.g01"
    )
    text = template.read_text(encoding="utf-8")
    path = tmp_path / "Model.g01"
    path.write_bytes(text.encode())
    backup = GeomParser.safe_write_geometry(path, text.splitlines(keepends=True))
    assert_crlf(path)
    assert path.read_text(encoding="utf-8") == text
    assert backup.read_bytes() == text.encode()


def test_unsteady_public_boundary_writer(tmp_path):
    path = tmp_path / "Model.u01"
    path.write_bytes(
        b"Flow Title=1D\nProgram Version=6.60\n"
        b"Boundary Location=White,Muncie,15696.24,,,,,,\n"
        b"Friction Slope=0.003,0\n"
    )
    RasUnsteady.set_normal_depth_boundary(
        path,
        0.004,
        river="White",
        reach="Muncie",
        station="15696.24",
    )
    assert_crlf(path)
    assert "Friction Slope=0.004,0" in path.read_text()


def test_permutation_metadata_writer(tmp_path):
    path = tmp_path / "Model.p01"
    path.write_bytes(b"Plan Title=Old\nShort Identifier=Old\nGeom File=g01\n")
    RasPermutation._update_plan_metadata(path, "Permutation", "P00001")
    assert assert_crlf(path) == (
        b"Plan Title=Permutation\r\nShort Identifier=P00001\r\nGeom File=g01\r\n"
    )
