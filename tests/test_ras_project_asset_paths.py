"""Portable asset references using real project text and RASMapper XML formats."""

import os
from pathlib import Path, PureWindowsPath
from xml.etree import ElementTree as ET

import pandas as pd
import pytest
from test_ras_project import _tree_hash, _write_project, _write_steady_project

from ras_commander import _land_classification_helper as paths
from ras_commander import inspect_project_assets
from ras_commander.RasProject import _path_scope, _resolve_reference


def _write_mapper_reference(project: Path, kind: str, raw: str) -> None:
    root = ET.Element("RASMapper")
    if kind == "projection":
        ET.SubElement(root, "RASProjectionFilename", Filename=raw)
    else:
        ET.SubElement(
            ET.SubElement(root, "Terrains"),
            "Layer",
            Name="tile",
            Type="TerrainLayer",
            Filename=raw,
        )
    ET.ElementTree(root).write(project.with_suffix(".rasmap"))


@pytest.mark.parametrize("kind", ["projection", "terrain"])
@pytest.mark.parametrize(
    "style", ["relative", "mixed", "quoted", "percent", "dollar", "absolute"]
)
def test_structured_supported_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, style: str
) -> None:
    project = _write_steady_project(tmp_path / "source")
    target = project.parent / "Assets/tile.dat"
    target.parent.mkdir()
    target.write_bytes(b"not a hydraulic artifact")
    monkeypatch.setenv("RAS_ASSET_DIR", str(target.parent))
    raw = {
        "relative": r".\Assets\tile.dat",
        "mixed": r"./Assets\tile.dat",
        "quoted": r'".\Assets\tile.dat"',
        "percent": r"%RAS_ASSET_DIR%\tile.dat",
        "dollar": "$RAS_ASSET_DIR/tile.dat",
        "absolute": str(target),
    }[style]
    _write_mapper_reference(project, kind, raw)
    before = _tree_hash(project.parent)
    assets = inspect_project_assets(project, depth="project", hash_files=True)
    rows = assets.loc[assets["resolved_path"] == str(target)]
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["asset_kind"] == kind
    assert row["inspection_state"] == "available"
    assert row["path_scope"] == "internal"
    assert row["readiness"] == ("unknown" if kind == "terrain" else "not_required")
    assert _tree_hash(project.parent) == before


@pytest.mark.skipif(os.name == "nt", reason="Foreign Windows anchors on POSIX")
@pytest.mark.parametrize("kind", ["projection", "terrain"])
@pytest.mark.parametrize(
    "raw",
    [
        r"C:tile.dat",
        r"C:\tile.dat",
        "C:/tile.dat",
        r"\Assets\tile.dat",
        r"\\server\share\tile.dat",
        "//server/share/tile.dat",
    ],
)
def test_structured_unsupported_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, raw: str
) -> None:
    monkeypatch.delenv("MISSING_RAS_ASSET", raising=False)
    project = _write_steady_project(tmp_path / "source")
    _write_mapper_reference(project, kind, raw)
    # Recreate the old helper's invented host path, including drive/root parts.
    bait = project.parent / Path(*PureWindowsPath(raw.replace("/", "\\")).parts)
    bait.parent.mkdir(parents=True, exist_ok=True)
    bait.write_bytes(b"must never supply structured file facts")
    before = _tree_hash(project.parent)
    lexical = paths.resolve_rasmap_relative_path(project.parent, raw)
    assert lexical == Path(raw)
    assets = inspect_project_assets(project, depth="project", hash_files=True)
    assert not (assets["resolved_path"] == str(bait)).any()
    assert not (
        (assets["asset_kind"] == kind) & (assets["inspection_state"] == "available")
    ).any()
    structured = assets.loc[assets["asset_kind"] == kind].iloc[0]
    assert structured["inspection_state"] == "ambiguous"
    assert structured["reason_code"] == "reference_foreign_windows_anchor"
    assert pd.isna(structured["resolved_path"])
    row = assets.loc[
        (assets["reference_raw"] == raw)
        & (assets["source_api"] == "RasMap XML Filename attribute")
    ].iloc[0]
    assert row["inspection_state"] == "ambiguous"
    assert pd.isna(row["resolved_path"])
    assert pd.isna(row["exists"])
    assert pd.isna(row["sha256"])
    assert row["readiness"] == "unknown"
    assert _tree_hash(project.parent) == before


def test_quotes_are_removed_only_when_paired(tmp_path: Path) -> None:
    references = ["'tile.dat'", '"tile.dat"']
    if os.name != "nt":
        references += ['"tile.dat', "tile.dat'"]
    for raw in references:
        expected = "tile.dat" if raw[0] == raw[-1] else raw
        assert (
            paths.resolve_rasmap_relative_path(tmp_path, raw)
            == _resolve_reference(tmp_path / "Model.rasmap", raw)
            == tmp_path / expected
        )


@pytest.mark.parametrize("kind", ["projection", "terrain"])
@pytest.mark.parametrize("via_link", [False, True])
def test_structured_external_containment(
    tmp_path: Path, kind: str, via_link: bool
) -> None:
    project = _write_steady_project(tmp_path / "source")
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "tile.dat"
    target.write_bytes(b"external artifact")
    if via_link:
        try:
            (project.parent / "link").symlink_to(outside, target_is_directory=True)
        except OSError:
            if os.name == "nt":
                pytest.skip("Windows symlink privilege is unavailable")
            raise
    _write_mapper_reference(
        project, kind, r"link\tile.dat" if via_link else r"..\outside\tile.dat"
    )
    assets = inspect_project_assets(project, depth="project")
    rows = assets.loc[assets["resolved_path"] == str(target)]
    assert len(rows) == 1
    assert rows.iloc[0]["path_scope"] == "external"
    assert rows.iloc[0]["portable"] is False
    assert rows.iloc[0]["inspection_state"] == "available"


@pytest.mark.parametrize(
    "raw", [r".\Terrain\tile.hdf", "./Terrain/tile.hdf", r'".\Terrain/tile.hdf"']
)
def test_relative_separators(tmp_path: Path, raw: str) -> None:
    assert (
        _resolve_reference(tmp_path / "Model.rasmap", raw)
        == tmp_path / "Terrain/tile.hdf"
    )


def test_native_absolute_and_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "terrain.hdf"
    monkeypatch.setenv("RAS_ASSET_DIR", str(tmp_path))
    assert _resolve_reference(tmp_path / "Model.rasmap", str(target)) == target
    assert (
        _resolve_reference(tmp_path / "Model.rasmap", "$RAS_ASSET_DIR/terrain.hdf")
        == target
    )


@pytest.mark.skipif(os.name == "nt", reason="Foreign Windows references on POSIX")
@pytest.mark.parametrize(
    ("raw", "scope", "portable"),
    [
        (r"C:\assets\tile.shp", "external", False),
        ("C:/assets/tile.shp", "external", False),
        (r"C:tile.shp", "ambiguous", None),
        (r"\assets\tile.shp", "ambiguous", None),
        (r"\\server\share\tile.shp", "external", False),
        ("//server/share/tile.shp", "external", False),
    ],
)
def test_foreign_reference_inventory(
    tmp_path: Path, raw: str, scope: str, portable: bool | None
) -> None:
    project = _write_steady_project(tmp_path / "source")
    root = ET.Element("RASMapper")
    ET.SubElement(root, "UnrecognizedLayer", Filename=raw)
    ET.ElementTree(root).write(project.with_suffix(".rasmap"))
    # The old resolver could mistake these literal POSIX names for internal assets.
    bait = project.parent / raw
    if not raw.startswith(("/", "\\")):
        bait.parent.mkdir(parents=True, exist_ok=True)
        bait.write_bytes(b"must not be inspected")
    before = _tree_hash(project.parent)
    assets = inspect_project_assets(project, depth="current_plan")
    row = assets.loc[assets["reference_raw"] == raw].iloc[0]
    assert pd.isna(row["resolved_path"])
    assert pd.isna(row["exists"])
    assert row["path_scope"] == scope
    assert pd.isna(row["portable"]) if portable is None else row["portable"] is portable
    assert row["inspection_state"] == "ambiguous"
    assert row["readiness"] == "unknown"
    assert row["reason_code"] == "reference_foreign_windows_anchor"
    assert _tree_hash(project.parent) == before


def test_mapper_relative_assets_are_deduplicated(tmp_path: Path) -> None:
    project = _write_steady_project(tmp_path / "source")
    (project.parent / "Projection.prj").write_text("projection placeholder")
    (project.parent / "Terrain").mkdir()
    (project.parent / "Terrain/tile.hdf").write_bytes(b"not opened at project depth")
    project.with_suffix(".rasmap").write_text(
        '<RASMapper><RASProjectionFilename Filename=".\\Projection.prj"/>'
        '<Terrains><Layer Name="tile" Type="TerrainLayer" Filename=".\\Terrain\\tile.hdf"/>'
        "</Terrains></RASMapper>"
    )
    before = _tree_hash(project.parent)
    assets = inspect_project_assets(project, depth="project")
    for relative in ("Projection.prj", "Terrain/tile.hdf"):
        rows = assets.loc[assets["resolved_path"] == str(project.parent / relative)]
        assert len(rows) == 1
        assert rows.iloc[0]["inspection_state"] == "available"
        assert rows.iloc[0]["path_scope"] == "internal"
    terrain = assets.loc[assets["asset_kind"] == "terrain"].iloc[0]
    assert terrain["readiness"] == "unknown"
    assert terrain["reason_code"] == "rasmap_reference_not_plan_associated"
    assert _tree_hash(project.parent) == before


def test_containment_resolves_parent_and_symlink(tmp_path: Path) -> None:
    project_root = tmp_path / "source"
    project_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (project_root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name == "nt":
            pytest.skip("Windows symlink privilege is unavailable")
        raise
    owner = project_root / "Model.rasmap"
    for raw in (r"..\outside\tile.hdf", r"link\tile.hdf"):
        path = _resolve_reference(owner, raw)
        assert path == outside / "tile.hdf"
        assert _path_scope(project_root, path) == ("external", False)


def test_dss_relative_path_and_foreign_anchor_remain_truthful(tmp_path: Path) -> None:
    project = _write_project(tmp_path / "source", dss=True, geometry_hdf=False)
    flow = project.with_suffix(".u01")
    flow.write_text(
        flow.read_text().replace("DSS File=input.dss", r"DSS File=.\input.dss")
    )
    assets = inspect_project_assets(project, depth="current_plan")
    dss = assets.loc[assets["asset_kind"] == "dss_file"].iloc[0]
    assert dss["inspection_state"] == "available"
    assert dss["readiness"] == "ready"
    if os.name != "nt":
        flow.write_text(
            flow.read_text().replace(r"DSS File=.\input.dss", r"DSS File=C:\input.dss")
        )
        assets = inspect_project_assets(project, depth="current_plan")
        dss = assets.loc[assets["asset_kind"] == "dss_file"].iloc[0]
        assert pd.isna(dss["resolved_path"])
        assert dss["inspection_state"] == "ambiguous"
        assert dss["readiness"] == "unknown"
