"""Native breakline Boolean encodings and NumPy 2 control validation (#550)."""

import copy
import hashlib
from pathlib import Path
from shutil import copyfile

import h5py
import numpy as np
import pytest

from ras_commander import RasExamples
from ras_commander.geom.GeomMesh import _sync_breakline_spacing_text_to_hdf
from ras_commander.geom._preprocess_contract import _feature_issues, _text_features

BL = "Geometry/2D Flow Area Break Lines"


@pytest.fixture(scope="module")
def native_breaklines(tmp_path_factory):
    folder = RasExamples.extract_project(
        "BaldEagleCrkMulti2D",
        output_path=tmp_path_factory.mktemp("native_breaklines"),
        suffix="control_contract",
    )
    geom = Path(folder) / "BaldEagleDamBrk.g03"
    features = _text_features(
        geom.read_text(errors="replace").splitlines(),
        "BreakLine Name=",
        "BreakLine Polyline=",
    )
    return geom, Path(str(geom) + ".hdf"), features


def _variant(native_breaklines, tmp_path, field, authored, stored=None):
    geom, source, features = native_breaklines
    path = tmp_path / source.name
    copyfile(source, path)
    features = copy.deepcopy(features)
    features[0]["controls"][field] = authored
    if stored is not None:
        with h5py.File(path, "r+") as hdf:
            attrs = hdf[f"{BL}/Attributes"][:]
            attrs[field][0] = stored
            hdf[f"{BL}/Attributes"][:] = attrs
    return path, features


def test_real_enabled_breaklines_match_without_mutation(native_breaklines):
    _, path, features = native_breaklines
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with h5py.File(path, "r") as hdf:
        assert len(features) == 3
        assert all(f["controls"]["Protection Radius"] == -1 for f in features)
        assert hdf[f"{BL}/Attributes"].dtype["Protection Radius"] == np.dtype("u1")
        assert hdf[f"{BL}/Attributes"]["Protection Radius"].tolist() == [1, 1, 1]
        assert _feature_issues(hdf, BL, features) == []
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("authored", [-1, 0, 1])
@pytest.mark.parametrize("stored", [0, 1, 255])
def test_protection_boolean_matches_only_correct_native_flag(
    native_breaklines, tmp_path, authored, stored
):
    path, features = _variant(
        native_breaklines, tmp_path, "Protection Radius", authored, stored
    )
    with h5py.File(path, "r") as hdf:
        issues = _feature_issues(hdf, BL, features)
    assert issues == (
        []
        if stored == int(authored != 0)
        else [f"{BL}/0: authored Protection Radius changed"]
    )


@pytest.mark.parametrize(
    "field,authored",
    [
        ("Protection Radius", -2),
        ("Protection Radius", 2),
        ("Protection Radius", 0.5),
        ("Protection Radius", np.nan),
        ("Protection Radius", np.inf),
        ("Near Repeats", -1),
        ("Near Repeats", 256),
        ("Near Repeats", 0.5),
        ("Near Repeats", np.nan),
        ("Near Repeats", np.inf),
        ("Near Repeats", 1e40),
        ("Cell Spacing Near", np.inf),
        ("Cell Spacing Near", 1e40),
    ],
)
def test_invalid_controls_produce_issues_without_wrapping_or_truncation(
    native_breaklines, tmp_path, field, authored
):
    path, features = _variant(native_breaklines, tmp_path, field, authored)
    with h5py.File(path, "r") as hdf:
        assert f"{BL}/0: authored {field} changed" in _feature_issues(hdf, BL, features)


@pytest.mark.parametrize(
    "authored,stored,matches", [(0, 0, True), (255, 255, True), (1, 0, False)]
)
def test_non_boolean_integer_controls_remain_exact(
    native_breaklines, tmp_path, authored, stored, matches
):
    path, features = _variant(
        native_breaklines, tmp_path, "Near Repeats", authored, stored
    )
    with h5py.File(path, "r") as hdf:
        assert (_feature_issues(hdf, BL, features) == []) == matches


def test_float_controls_retain_native_field_precision(native_breaklines, tmp_path):
    authored = 123.456
    path, features = _variant(
        native_breaklines, tmp_path, "Cell Spacing Near", authored, authored
    )
    with h5py.File(path, "r") as hdf:
        assert _feature_issues(hdf, BL, features) == []


@pytest.mark.parametrize("authored", [-1, 0, 1])
def test_sync_protection_matches_validation_and_preserves_text(
    native_breaklines, tmp_path, authored
):
    geom, _, _ = native_breaklines
    path, _ = _variant(
        native_breaklines, tmp_path, "Protection Radius", -1, int(authored == 0)
    )
    text_path = tmp_path / geom.name
    text_path.write_text(
        geom.read_text().replace(
            "BreakLine Protection Radius=-1", f"BreakLine Protection Radius={authored}"
        )
    )
    before = text_path.read_bytes()
    _sync_breakline_spacing_text_to_hdf(text_path, path)
    with h5py.File(path, "r") as hdf:
        assert (
            hdf[f"{BL}/Attributes"]["Protection Radius"].tolist()
            == [int(authored != 0)] * 3
        )
        features = _text_features(
            text_path.read_text().splitlines(), "BreakLine Name=", "BreakLine Polyline="
        )
        assert _feature_issues(hdf, BL, features) == []
    assert text_path.read_bytes() == before


def test_invalid_protection_sync_warns_without_mutating_hdf(
    native_breaklines, tmp_path, caplog
):
    geom, _, _ = native_breaklines
    path, _ = _variant(native_breaklines, tmp_path, "Protection Radius", -1, 0)
    text_path = tmp_path / geom.name
    text_path.write_text(
        geom.read_text().replace(
            "BreakLine Protection Radius=-1", "BreakLine Protection Radius=-2"
        )
    )
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    _sync_breakline_spacing_text_to_hdf(text_path, path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert "Protection Radius must be -1, 0, or 1" in caplog.text
