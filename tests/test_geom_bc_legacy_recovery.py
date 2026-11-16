"""Authored BC inventory and clone-only removal regressions."""

from pathlib import Path

import pytest

module = __import__("ras_commander.geom.GeomBcLines", fromlist=["*"])


def block(name="Inlet", area="Area", points=((1, 2), (3, 4))):
    numbers = [value for point in points for value in point]
    return (
        "BC Line Name="
        + name
        + "\nBC Line Storage Area="
        + area
        + "\nBC Line Arc= "
        + str(len(points))
        + "\n"
        + "".join(f"{x:16g}" for x in numbers)
        + "\nBC Line Text Position= 0,0\n"
    )


def test_preserves_exact_names_areas_coordinates_without_hdf(tmp_path):
    p = tmp_path / "model.g01"
    p.write_text(block() + block("Area Main Outlet", points=((5, 6), (7, 8))))
    before = p.read_bytes()
    frame = module.GeomBcLines.inspect_bc_line_blocks(p)
    assert frame["name"].tolist() == ["Inlet", "Area Main Outlet"]
    assert frame.iloc[0]["coordinates"] == [[1, 2], [3, 4]]
    assert frame.iloc[0]["authored_type"] is None
    assert frame.attrs["crs"] == "unverified"
    assert p.read_bytes() == before


@pytest.mark.parametrize(
    "text",
    [
        block() + block(),
        block().replace("BC Line Arc= 2", "BC Line Arc= 3"),
        block().replace("BC Line Storage Area=Area\n", ""),
        block(points=((1, float("nan")), (3, 4))),
        block().replace("BC Line Arc= 2", "BC Line Arc= 1"),
    ],
)
def test_malformed_or_ambiguous_features_rejected(tmp_path, text):
    p = tmp_path / "model.g01"
    p.write_text(text)
    with pytest.raises(ValueError):
        module.GeomBcLines.inspect_bc_line_blocks(p)


def test_empty_source_is_explicit_empty_inventory(tmp_path):
    p = tmp_path / "model.g01"
    p.write_text("Geom Title=No BC lines\n")
    frame = module.GeomBcLines.inspect_bc_line_blocks(p)
    assert frame.empty and list(frame.columns) == [
        "name",
        "area_2d",
        "coordinates",
        "authored_type",
        "area_association_status",
    ]


def test_legacy_unassigned_lines_preserved_without_inferred_association(tmp_path):
    path = tmp_path / "model.g01"
    path.write_text(block("WA1_Inflow", area="") + block("Inlet", area="Area"))
    frame = module.GeomBcLines.inspect_bc_line_blocks(path)
    assert frame["area_2d"].tolist() == ["", "Area"]
    assert frame["area_association_status"].tolist() == ["unassigned", "assigned"]


@pytest.fixture
def clone_fixture(tmp_path):
    import hashlib

    source_dir = tmp_path / "delivered"
    clone_dir = tmp_path / "run"
    source_dir.mkdir()
    clone_dir.mkdir()
    raw = (
        (
            "Geom Title=Area\n"
            + block("WA1_Inflow", area="")
            + block("Inlet", area="Area")
            + "Unchanged Tail=1\n"
        )
        .replace("\n", "\r\n")
        .encode()
    )
    source = source_dir / "Area.g01"
    clone = clone_dir / "Area.g01"
    source.write_bytes(raw)
    clone.write_bytes(raw)
    return source, clone, hashlib.sha256(raw).hexdigest()


def test_delete_only_exact_unused_orphan_preserves_other_bytes(clone_fixture):
    source, clone, digest = clone_fixture
    before = source.read_bytes()
    result = module.GeomBcLines.delete_unassigned_bc_lines(
        clone,
        ["WA1_Inflow"],
        source_geometry=source,
        expected_geometry_sha256=digest,
        active_boundary_names=["Inlet"],
    )
    expected = (
        ("Geom Title=Area\n" + block("Inlet", area="Area") + "Unchanged Tail=1\n")
        .replace("\n", "\r\n")
        .encode()
    )
    assert clone.read_bytes() == expected
    assert source.read_bytes() == before
    assert Path(result["backup_path"]).read_bytes() == before
    assert result["remaining_boundary_names"] == ["Inlet"]
    assert result["other_geometry_bytes_preserved"]


@pytest.mark.parametrize("fault", ["active", "assigned", "hash", "source", "unknown"])
def test_unsafe_orphan_deletion_is_rejected_before_mutation(clone_fixture, fault):
    source, clone, digest = clone_fixture
    before = clone.read_bytes()
    target = source if fault == "source" else clone
    names = (
        ["Inlet"]
        if fault == "assigned"
        else ["unknown"]
        if fault == "unknown"
        else ["WA1_Inflow"]
    )
    with pytest.raises(ValueError):
        module.GeomBcLines.delete_unassigned_bc_lines(
            target,
            names,
            source_geometry=source,
            expected_geometry_sha256="0" * 64 if fault == "hash" else digest,
            active_boundary_names=["WA1_Inflow"] if fault == "active" else ["Inlet"],
        )
    assert clone.read_bytes() == before and source.read_bytes() == before


@pytest.mark.parametrize(
    "fault",
    [
        "non_bc_before_closing",
        "missing_closing",
        "duplicate_closing",
        "unknown_bc_key",
        "extra_numeric",
        "nested_feature",
    ],
)
def test_malformed_block_never_consumes_unrelated_geometry(tmp_path, fault):
    import hashlib

    source_dir = tmp_path / "source"
    clone_dir = tmp_path / "clone"
    source_dir.mkdir()
    clone_dir.mkdir()
    text = block("unused", area="")
    if fault == "non_bc_before_closing":
        text = text.replace(
            "BC Line Text Position=", "Storage Area=Unrelated\nBC Line Text Position="
        )
    elif fault == "missing_closing":
        text = (
            text.replace("BC Line Text Position= 0,0\n", "")
            + "Connection=Keep this geometry\n"
        )
    elif fault == "duplicate_closing":
        text += "BC Line Text Position=0,0\n"
    elif fault == "unknown_bc_key":
        text = text.replace(
            "BC Line Text Position=",
            "BC Line Unknown Field=surprise\nBC Line Text Position=",
        )
    elif fault == "extra_numeric":
        text = text.replace(
            "BC Line Text Position=", f"{123:16g}\nBC Line Text Position="
        )
    else:
        text = text.replace("BC Line Text Position= 0,0\n", "") + block(
            "next", area="Area"
        )
    source = source_dir / "Area.g01"
    clone = clone_dir / "Area.g01"
    source.write_text(text)
    clone.write_text(text)
    before = clone.read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    with pytest.raises(ValueError):
        module.GeomBcLines.inspect_bc_line_blocks(clone)
    with pytest.raises(ValueError):
        module.GeomBcLines.delete_unassigned_bc_lines(
            clone,
            ["unused"],
            source_geometry=source,
            expected_geometry_sha256=digest,
            active_boundary_names=[],
        )
    assert clone.read_bytes() == before and source.read_bytes() == before
    assert list(clone_dir.iterdir()) == [clone]


def test_unrelated_feature_after_closed_block_is_preserved(tmp_path):
    import hashlib

    source_dir = tmp_path / "source"
    clone_dir = tmp_path / "clone"
    source_dir.mkdir()
    clone_dir.mkdir()
    unrelated = (
        "Storage Area=Keep this feature\nArea-Surface Area= 2\n     123     456\n"
    )
    text = block("unused", area="") + unrelated + block("assigned", area="Area")
    source = source_dir / "Area.g01"
    clone = clone_dir / "Area.g01"
    source.write_text(text)
    clone.write_text(text)
    digest = hashlib.sha256(clone.read_bytes()).hexdigest()
    module.GeomBcLines.delete_unassigned_bc_lines(
        clone,
        ["unused"],
        source_geometry=source,
        expected_geometry_sha256=digest,
        active_boundary_names=["assigned"],
    )
    assert clone.read_text() == unrelated + block("assigned", area="Area")
    assert source.read_text() == text


@pytest.mark.parametrize("link_type", ["hardlink", "symlink"])
def test_clone_alias_to_other_source_is_rejected_without_changes(
    clone_fixture, tmp_path, link_type
):
    import os

    source, clone, digest = clone_fixture
    original = source.read_bytes()
    other = tmp_path / "other-delivery.g01"
    other.write_bytes(original)
    clone.unlink()
    try:
        if link_type == "hardlink":
            os.link(other, clone)
        else:
            clone.symlink_to(other)
    except OSError:
        clone.write_bytes(original)
        pytest.skip("Requested link type unavailable on this account")
    with pytest.raises(ValueError, match=r"symlink|reparse|hardlink"):
        module.GeomBcLines.delete_unassigned_bc_lines(
            clone,
            ["WA1_Inflow"],
            source_geometry=source,
            expected_geometry_sha256=digest,
            active_boundary_names=["Inlet"],
        )
    assert source.read_bytes() == other.read_bytes() == clone.read_bytes() == original
    assert list(clone.parent.iterdir()) == [clone]


def test_symlinked_clone_ancestor_is_rejected_before_resolution(
    clone_fixture, tmp_path
):
    source, clone, digest = clone_fixture
    alias = tmp_path / "run-alias"
    try:
        alias.symlink_to(clone.parent, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks unavailable on this account")
    original = clone.read_bytes()
    with pytest.raises(ValueError, match=r"symlink|reparse"):
        module.GeomBcLines.delete_unassigned_bc_lines(
            alias / clone.name,
            ["WA1_Inflow"],
            source_geometry=source,
            expected_geometry_sha256=digest,
            active_boundary_names=["Inlet"],
        )
    assert source.read_bytes() == clone.read_bytes() == original
    assert list(clone.parent.iterdir()) == [clone]


@pytest.mark.parametrize("below_anchor", [False, True])
def test_geometry_guard_exempts_only_the_filesystem_anchor(
    clone_fixture, monkeypatch, below_anchor
):
    from types import SimpleNamespace

    source, clone, digest = clone_fixture
    marked = clone.parent if below_anchor else Path(clone.anchor)
    original_lstat = type(clone).lstat
    calls = []
    original = source.read_bytes()

    def bridged_lstat(path, *args, **kwargs):
        value = original_lstat(path, *args, **kwargs)
        if path == marked:
            calls.append(path)
            return SimpleNamespace(st_mode=value.st_mode, st_file_attributes=0x400)
        return value

    monkeypatch.setattr(type(clone), "lstat", bridged_lstat)
    original_resolve = type(clone).resolve

    def canonical(path, *args, **kwargs):
        if below_anchor and path == marked:
            return marked.parent / "another-source-directory"
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(type(clone), "resolve", canonical)

    def repair():
        return module.GeomBcLines.delete_unassigned_bc_lines(
            clone,
            ["WA1_Inflow"],
            source_geometry=source,
            expected_geometry_sha256=digest,
            active_boundary_names=["Inlet"],
        )

    if below_anchor:
        with pytest.raises(ValueError, match="filesystem anchor") as exc:
            repair()
        assert str(clone.parent) in str(exc.value)
        assert calls and clone.read_bytes() == original
        assert list(clone.parent.iterdir()) == [clone]
    else:
        assert repair()["source_unchanged"]
        assert calls == []
    assert source.read_bytes() == original


@pytest.mark.parametrize("file_reparse", [False, True])
def test_geometry_nonredirecting_directory_mount_does_not_allow_file_reparse(
    clone_fixture, monkeypatch, file_reparse
):
    from types import SimpleNamespace

    source, clone, digest = clone_fixture
    marked = clone if file_reparse else clone.parent
    original_lstat = type(clone).lstat
    original = source.read_bytes()

    def metadata(path, *args, **kwargs):
        info = original_lstat(path, *args, **kwargs)
        if path == marked:
            return SimpleNamespace(
                st_mode=info.st_mode, st_nlink=info.st_nlink, st_file_attributes=0x400
            )
        return info

    monkeypatch.setattr(type(clone), "lstat", metadata)
    assert marked.resolve(strict=True) == marked.absolute()

    def repair():
        return module.GeomBcLines.delete_unassigned_bc_lines(
            clone,
            ["WA1_Inflow"],
            source_geometry=source,
            expected_geometry_sha256=digest,
            active_boundary_names=["Inlet"],
        )

    if file_reparse:
        with pytest.raises(ValueError, match="reparse"):
            repair()
        assert clone.read_bytes() == original
    else:
        assert repair()["source_unchanged"]
    assert source.read_bytes() == original
