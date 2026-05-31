"""Unit tests for GeomMesh headless mesh generation and BC repair."""

from importlib import import_module
import os
import platform
import shutil
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

h5py = pytest.importorskip("h5py")
np = pytest.importorskip("numpy")

geom_mesh_module = import_module("ras_commander.geom.GeomMesh")
GeomMesh = geom_mesh_module.GeomMesh
_patch_text_seeds = geom_mesh_module._patch_text_seeds
_reseed_after_perimeter_fix = geom_mesh_module._reseed_after_perimeter_fix
_remove_short_perimeter_segments = geom_mesh_module._remove_short_perimeter_segments
_ensure_hdf = geom_mesh_module._ensure_hdf
_dedupe_seed_points = geom_mesh_module._dedupe_seed_points
_bad_seed_indexes = geom_mesh_module._bad_seed_indexes
_remove_seed_indexes = geom_mesh_module._remove_seed_indexes
_safe_non_virtual_cell_count = geom_mesh_module._safe_non_virtual_cell_count

HECRAS_INTEGRATION_ENV = "RAS_COMMANDER_RUN_HECRAS_INTEGRATION"


class MockPointM:
    """Mock .NET PointM with X, Y properties."""

    def __init__(self, x, y):
        self.X = x
        self.Y = y


class MockPolygon:
    """Mock .NET Polygon with Count and PointM(i)."""

    def __init__(self, coords_or_pointms):
        if isinstance(coords_or_pointms, MockPointMs):
            self._coords = [(p.X, p.Y) for p in coords_or_pointms._items]
        else:
            self._coords = coords_or_pointms

    @property
    def Count(self):
        return len(self._coords)

    def PointM(self, i):
        x, y = self._coords[i]
        return MockPointM(x, y)


class MockPointMs:
    """Mock .NET PointMs collection."""

    def __init__(self):
        self._items = []

    @property
    def Count(self):
        return len(self._items)

    def Add(self, pm):
        self._items.append(pm)

    def __getitem__(self, index):
        return self._items[index]


class FakePointCollection:
    """Small stand-in for seed collections returned from helper functions."""

    def __init__(self, count=2):
        self.Count = count

    def __getitem__(self, index):
        return MockPointM(float(index), float(index))


class FakeMeshState(int):
    """Enum-like int that preserves a readable string representation."""

    def __new__(cls, value, name):
        obj = int.__new__(cls, value)
        obj._name = name
        return obj

    def __str__(self):
        return self._name


class FakeCell:
    """Mesh cell with a point center."""

    def __init__(self, x, y):
        self.Point = MockPointM(x, y)


class FakeMesh:
    """Mesh object with the subset of properties GeomMesh.generate() uses."""

    def __init__(self):
        self.MeshCompletionState = FakeMeshState(1, "Complete")
        self.NonVirtualCellCount = 2
        self.FaceCount = 5
        self._cells = [FakeCell(10.0, 10.0), FakeCell(20.0, 20.0)]

    def Cell(self, index):
        return self._cells[index]


class FakeMeshWithUnavailableCellCount:
    @property
    def NonVirtualCellCount(self):
        raise RuntimeError("mesh cell collection is unavailable")


class FakeBadIndexes:
    def __init__(self, values):
        self._values = values

    @property
    def Count(self):
        return len(self._values)

    def __getitem__(self, index):
        return self._values[index]


class FakeMeshWithBadIndexes:
    def __init__(self, values):
        self.BadIndexes = FakeBadIndexes(values)


@pytest.fixture
def square_perimeter():
    """Simple 100x100 square polygon."""
    return MockPolygon([(0, 0), (100, 0), (100, 100), (0, 100)])


@pytest.fixture
def dense_perimeter():
    """Square with many closely-spaced points along each edge."""
    coords = []
    for i in range(0, 100, 5):
        coords.append((i, 0))
    for i in range(0, 100, 5):
        coords.append((100, i))
    for i in range(100, 0, -5):
        coords.append((i, 100))
    for i in range(100, 0, -5):
        coords.append((0, i))
    return MockPolygon(coords)


@pytest.fixture
def bc_conflict_hdf(tmp_path):
    """Create a synthetic .g01.hdf with per-area 7.0 BC lines."""
    hdf_path = tmp_path / "test.g01.hdf"
    with h5py.File(str(hdf_path), "w") as hf:
        fa_group = hf.create_group("Geometry/2D Flow Areas")
        area_grp = fa_group.create_group("MainArea")

        bc_grp = area_grp.create_group("BC Lines")
        nd1 = bc_grp.create_group("NormDepth1")
        nd1.create_dataset(
            "Coordinates",
            data=np.array(
                [
                    [0.0, 0.0],
                    [50.0, 0.0],
                    [100.0, 0.0],
                ],
                dtype=np.float64,
            ),
        )
        nd1.attrs["Type"] = "Normal Depth"

        us1 = bc_grp.create_group("USInflow1")
        us1.create_dataset(
            "Coordinates",
            data=np.array(
                [
                    [80.0, 0.0],
                    [150.0, 0.0],
                    [200.0, 0.0],
                ],
                dtype=np.float64,
            ),
        )
        us1.attrs["Type"] = "Flow Hydrograph"

        area_grp.create_dataset(
            "FacePoints Coordinate",
            data=np.array(
                [
                    [90.0, 0.0],
                    [95.0, 0.0],
                    [20.0, 0.0],
                    [25.0, 0.0],
                ],
                dtype=np.float64,
            ),
        )
        area_grp.create_dataset(
            "Faces FacePoint Indexes",
            data=np.array([[0, 1], [2, 3]], dtype=np.int32),
        )
        area_grp.create_dataset(
            "Faces Perimeter Info",
            data=np.array([[1, 1], [1, 1]], dtype=np.int32),
        )

    return hdf_path


@pytest.fixture
def multi_area_bc_conflict_hdf(tmp_path):
    """Create a synthetic HDF where only the second flow area has a BC conflict."""
    hdf_path = tmp_path / "multi_area.g01.hdf"
    with h5py.File(str(hdf_path), "w") as hf:
        fa_group = hf.create_group("Geometry/2D Flow Areas")

        area1 = fa_group.create_group("Area1")
        area1_bc = area1.create_group("BC Lines")
        flow1 = area1_bc.create_group("UpstreamOnly")
        flow1.create_dataset(
            "Coordinates",
            data=np.array([[0.0, 0.0], [25.0, 0.0], [50.0, 0.0]], dtype=np.float64),
        )
        flow1.attrs["Type"] = "Flow Hydrograph"
        area1.create_dataset(
            "FacePoints Coordinate",
            data=np.array([[0.0, 0.0], [5.0, 0.0]], dtype=np.float64),
        )
        area1.create_dataset(
            "Faces FacePoint Indexes",
            data=np.array([[0, 1]], dtype=np.int32),
        )
        area1.create_dataset(
            "Faces Perimeter Info",
            data=np.array([[1, 1]], dtype=np.int32),
        )

        area2 = fa_group.create_group("Area2")
        area2_bc = area2.create_group("BC Lines")
        nd2 = area2_bc.create_group("NormDepth2")
        nd2.create_dataset(
            "Coordinates",
            data=np.array(
                [[90.0, 0.0], [95.0, 0.0], [100.0, 0.0], [105.0, 0.0], [110.0, 0.0]],
                dtype=np.float64,
            ),
        )
        nd2.attrs["Type"] = "Normal Depth"
        us2 = area2_bc.create_group("USInflow2")
        us2.create_dataset(
            "Coordinates",
            data=np.array([[92.0, 0.0], [96.0, 0.0], [99.0, 0.0]], dtype=np.float64),
        )
        us2.attrs["Type"] = "Flow Hydrograph"
        area2.create_dataset(
            "FacePoints Coordinate",
            data=np.array(
                [[90.0, 0.0], [95.0, 0.0], [104.0, 0.0], [108.0, 0.0]],
                dtype=np.float64,
            ),
        )
        area2.create_dataset(
            "Faces FacePoint Indexes",
            data=np.array([[0, 1], [2, 3]], dtype=np.int32),
        )
        area2.create_dataset(
            "Faces Perimeter Info",
            data=np.array([[1, 1], [1, 1]], dtype=np.int32),
        )

    return hdf_path


@pytest.fixture
def breakline_geom_text(tmp_path):
    """Create a minimal .g01 text file with breakline spacing lines."""
    geom_text = tmp_path / "test.g01"
    geom_text.write_text(
        "Geom Title=Test\n"
        "Storage Area=MainArea\n"
        "Storage Area Point Generation Data=,,50.000000,50.000000\n"
        "BreakLine CellSize Min=50.000000\n"
        "BreakLine CellSize Max=200.000000\n"
        "Storage Area 2D Points= 0 \n"
        "LCMann Time=0\n",
        encoding="utf-8",
    )
    return geom_text


@pytest.fixture
def storage_area_geom_text(tmp_path):
    """Geometry text containing old seed rows with spacing and negative values."""
    geom_text = tmp_path / "storage_points.g01"
    geom_text.write_text(
        "Geom Title=Test\n"
        "Storage Area=MainArea\n"
        "Storage Area 2D Points= 3 \n"
        "      -25.0000000000    10.0000000000    15.0000000000   -40.0000000000\n"
        "        5.0000000000     8.0000000000\n"
        "BreakLine CellSize Min=25.000000\n",
        encoding="utf-8",
    )
    return geom_text


def _mock_generate_success(monkeypatch, geom_text_path: Path, *, has_breaklines: bool):
    """Patch the heavy .NET entrypoints so generate() can be unit tested.

    Follows the RASDecomp-style architecture: load geometry from .NET,
    generate seeds via .NET, compute mesh, save via .NET + patch text.
    """
    captured = {}
    hdf_path = geom_text_path.with_suffix(geom_text_path.suffix + ".hdf")
    hdf_path.write_text("compiled", encoding="utf-8")
    hdf_mtime = geom_text_path.stat().st_mtime + 1.0
    os.utime(hdf_path, (hdf_mtime, hdf_mtime))

    monkeypatch.setattr(geom_mesh_module, "_load_dlls", lambda hecras_dir=None: None)

    # Build mock .NET geometry chain
    mock_geom_obj = MagicMock()
    mock_geom_obj.D2FlowArea.GetFeatureByName.return_value = 0
    mock_geom_obj.D2FlowArea.GetFeatureName.return_value = "MainArea"
    mock_geom_obj.D2FlowArea.FeatureCount.return_value = 1
    mock_geom_obj.D2FlowArea.Geometry.MeshPerimeters.Polygon.return_value = (
        MockPolygon([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)])
    )
    mock_geom_obj.BreakLines = MagicMock()
    mock_geom_obj.BreakLines.FeatureCount.return_value = 1 if has_breaklines else 0

    monkeypatch.setattr(
        geom_mesh_module,
        "_imports",
        lambda: {
            "MeshStatus": type(
                "MeshStatus",
                (),
                {
                    "Complete": 1,
                    "MaxFacesPerCellExceeded": 2,
                    "FacePerimeterConnectionError": 3,
                    "PerimeterPolygonError": 4,
                },
            ),
            "RASGeometry": lambda path: mock_geom_obj,
            "PointGenerator": MagicMock(),
            "Polyline": MagicMock(),
            "PolylineFeatureLayer": MagicMock(),
            "Polygon": MockPolygon,
            "PointMs": MockPointMs,
            "Point2D": MagicMock(),
            "List": MagicMock(),
            "System": MagicMock(),
            "MeshFV2D": MagicMock(),
        },
    )

    monkeypatch.setattr(
        geom_mesh_module,
        "_build_breaklines",
        lambda d2fa, ns: "mock_breaklines" if has_breaklines else None,
    )
    monkeypatch.setattr(
        geom_mesh_module,
        "_generate_seeds_via_net",
        lambda hdf_path, ns, fid=0: (_ for _ in ()).throw(
            RuntimeError("mock: .NET unavailable")
        ),
    )

    def fake_generate_seeds_safe(perim, cell_size, ns):
        captured["cell_size"] = cell_size
        return FakePointCollection()

    monkeypatch.setattr(
        geom_mesh_module,
        "_generate_seeds_safe",
        fake_generate_seeds_safe,
    )
    monkeypatch.setattr(
        geom_mesh_module,
        "_compute_mesh",
        lambda perim, seeds_pm, breaklines, ratio, ns: FakeMesh(),
    )
    monkeypatch.setattr(
        geom_mesh_module,
        "_save_mesh",
        lambda geom, d2fa, fid, mesh, ns: None,
    )
    monkeypatch.setattr(
        geom_mesh_module,
        "_sync_cell_size_to_hdf",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        geom_mesh_module,
        "_sync_breakline_spacing_text_to_hdf",
        lambda *args, **kwargs: None,
    )
    captured["geom"] = mock_geom_obj
    return captured


def _install_fake_rasmapper_scripting(monkeypatch):
    """Install a stub RasMapperLib.Scripting module for helper tests."""

    fake_scripting = types.ModuleType("RasMapperLib.Scripting")

    class FakeSetGeometryAssociationCommand:
        def __init__(self):
            self.GeometryFilename = None
            self.TerrainFilename = None
            self.NValueFilename = None
            self.InfiltrationFilename = None
            self.SedimentSoilsFilename = None

        def Execute(self, progress):
            field_map = {
                "TerrainFilename": ("Terrain Filename", "Terrain Layername"),
                "NValueFilename": ("Land Cover Filename", "Land Cover Layername"),
                "InfiltrationFilename": (
                    "Infiltration Filename",
                    "Infiltration Layername",
                ),
                "SedimentSoilsFilename": (
                    "Sediment Bed Material Filename",
                    "Sediment Bed Material Layername",
                ),
            }
            geom_hdf_path = Path(self.GeometryFilename)
            with h5py.File(str(geom_hdf_path), "r+") as hf:
                geom_group = hf.require_group("Geometry")
                for prop_name, (filename_attr, layer_attr) in field_map.items():
                    value = getattr(self, prop_name)
                    if not value:
                        continue
                    value_path = Path(value)
                    relative = os.path.relpath(value_path, geom_hdf_path.parent)
                    geom_group.attrs[filename_attr] = relative.encode("utf-8")
                    geom_group.attrs[layer_attr] = value_path.stem.encode("utf-8")
                geom_group.attrs["SI Units"] = b"False"

    fake_scripting.SetGeometryAssociationCommand = FakeSetGeometryAssociationCommand

    fake_rasmapper = types.ModuleType("RasMapperLib")
    fake_rasmapper.Scripting = fake_scripting

    monkeypatch.setitem(sys.modules, "RasMapperLib", fake_rasmapper)
    monkeypatch.setitem(sys.modules, "RasMapperLib.Scripting", fake_scripting)


class TestRemoveShortPerimeterSegments:
    """Test greedy forward pass perimeter simplification."""

    def _call(self, perim, min_length, ns=None):
        mock_rml = MagicMock()
        mock_rml.PointMs = MockPointMs
        mock_rml.Polygon = MockPolygon
        mock_rml.PointM = MockPointM
        with patch.dict("sys.modules", {"RasMapperLib": mock_rml}):
            return _remove_short_perimeter_segments(perim, min_length, ns or {})

    def test_no_removal_well_spaced(self, square_perimeter):
        result = self._call(square_perimeter, 10.0)
        assert result.Count == 4

    def test_removes_close_points(self, dense_perimeter):
        result = self._call(dense_perimeter, 30.0)
        assert result.Count < dense_perimeter.Count

    def test_degenerate_polygon_unchanged(self):
        tri = MockPolygon([(0, 0), (1, 0), (0, 1)])
        result = self._call(tri, 100.0)
        assert result.Count == 3

    def test_very_small_min_length_no_change(self, square_perimeter):
        result = self._call(square_perimeter, 0.001)
        assert result.Count == 4


class TestSetBreaklineSpacing:
    """Test text file editing for breakline spacing."""

    def test_updates_values(self, breakline_geom_text):
        backup = GeomMesh.set_breakline_spacing(
            breakline_geom_text, near=33.0, far=100.0, all_breaklines=True
        )
        assert backup.exists()
        text = breakline_geom_text.read_text(encoding="utf-8")
        assert "BreakLine CellSize Min=33.000000" in text
        assert "BreakLine CellSize Max=100.000000" in text

    def test_creates_backup(self, breakline_geom_text):
        backup = GeomMesh.set_breakline_spacing(
            breakline_geom_text, near=10.0, far=50.0, all_breaklines=True
        )
        assert backup.exists()
        assert backup.suffix == ".bak"

    def test_keeps_existing_values_with_none(self, breakline_geom_text):
        GeomMesh.set_breakline_spacing(
            breakline_geom_text, near=None, far=None, all_breaklines=True
        )
        text = breakline_geom_text.read_text(encoding="utf-8")
        assert "BreakLine CellSize Min=50.000000" in text
        assert "BreakLine CellSize Max=200.000000" in text

    @pytest.mark.parametrize(
        ("near", "far"),
        [
            (0.0, 50.0),
            (25.0, -1.0),
        ],
    )
    def test_rejects_nonpositive_values(self, breakline_geom_text, near, far):
        with pytest.raises(ValueError, match="must be greater than 0.0"):
            GeomMesh.set_breakline_spacing(
                breakline_geom_text,
                near=near,
                far=far,
                all_breaklines=True,
            )


class TestPatchTextSeeds:
    """Test robust replacement of packed Storage Area 2D seed rows."""

    def test_replaces_right_justified_and_negative_coordinate_rows(self, storage_area_geom_text):
        cell_centers = np.array(
            [
                [1.0, 2.0],
                [3.0, 4.0],
                [5.0, 6.0],
            ],
            dtype=np.float64,
        )

        _patch_text_seeds(storage_area_geom_text, cell_centers)

        text = storage_area_geom_text.read_text(encoding="utf-8")
        assert "Storage Area 2D Points= 3 " in text
        assert "-25.0000000000" not in text
        assert "-40.0000000000" not in text
        assert "BreakLine CellSize Min=25.000000" in text


class TestReseedAfterPerimeterFix:
    """Test perimeter mutation refuses unavailable text-to-HDF regeneration."""

    def test_requires_external_geometry_hdf_regeneration(self, monkeypatch, tmp_path):
        geom_text_path = tmp_path / "test.g01"
        geom_text_path.write_text("Geom Title=Test\n", encoding="utf-8")
        monkeypatch.setattr(
            geom_mesh_module,
            "_patch_text_perimeter",
            lambda *args, **kwargs: pytest.fail("perimeter text was patched"),
        )

        with pytest.raises(RuntimeError, match="cannot generate .g##.hdf"):
            _reseed_after_perimeter_fix(
                geom_text_path,
                geom_text_path.with_suffix(".g01.hdf"),
                MockPolygon(
                    [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
                ),
                100.0,
                1,
                "SecondaryArea",
                {"RASGeometry": lambda path: MagicMock()},
            )


class TestGeometryHdfAvailability:
    """Test the explicit boundary around unavailable text-to-HDF generation."""

    def test_compile_geometry_is_disabled(self, breakline_geom_text):
        with pytest.raises(RuntimeError, match="not a text-geometry compiler"):
            GeomMesh.compile_geometry(breakline_geom_text)

    def test_ensure_hdf_rejects_missing_compiled_geometry(self, breakline_geom_text):
        with pytest.raises(RuntimeError, match="Compiled geometry HDF is missing"):
            _ensure_hdf(breakline_geom_text)

    def test_ensure_hdf_rejects_stale_compiled_geometry(self, breakline_geom_text):
        hdf_path = breakline_geom_text.with_suffix(breakline_geom_text.suffix + ".hdf")
        hdf_path.write_text("compiled", encoding="utf-8")
        text_mtime = breakline_geom_text.stat().st_mtime + 10.0
        os.utime(hdf_path, (text_mtime - 5.0, text_mtime - 5.0))
        os.utime(breakline_geom_text, (text_mtime, text_mtime))

        with pytest.raises(RuntimeError, match="is newer than"):
            _ensure_hdf(breakline_geom_text)


class TestGeometryAssociation:
    """Test geometry HDF association API."""

    def _make_geometry_hdf(self, tmp_path):
        hdf_path = tmp_path / "test.g01.hdf"
        with h5py.File(str(hdf_path), "w") as hf:
            hf.create_group("Geometry")
        return hdf_path

    def _make_artifact(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("artifact", encoding="utf-8")
        return path

    def test_sets_and_reads_all_association_paths(self, monkeypatch, tmp_path):
        geom_hdf_path = self._make_geometry_hdf(tmp_path)
        terrain = self._make_artifact(tmp_path / "Terrain" / "Terrain50.hdf")
        landcover = self._make_artifact(
            tmp_path / "Land Classification" / "LandCover.hdf"
        )
        infiltration = self._make_artifact(tmp_path / "Soils" / "Infiltration.hdf")
        sediment_soils = self._make_artifact(
            tmp_path / "Soils" / "Hydrologic Soil Groups.hdf"
        )

        _install_fake_rasmapper_scripting(monkeypatch)
        monkeypatch.setattr(geom_mesh_module, "_load_dlls", lambda hecras_dir=None: None)

        result = GeomMesh.set_geometry_association(
            geom_hdf_path,
            terrain_hdf_path=terrain,
            landcover_hdf_path=landcover,
            infiltration_hdf_path=infiltration,
            sediment_soils_hdf_path=sediment_soils,
        )

        assert result == geom_hdf_path
        association = GeomMesh.get_geometry_association(geom_hdf_path)
        assert Path(association["terrain_hdf_path"]).resolve() == terrain.resolve()
        assert Path(association["landcover_hdf_path"]).resolve() == landcover.resolve()
        assert Path(association["infiltration_hdf_path"]).resolve() == infiltration.resolve()
        assert (
            Path(association["sediment_soils_hdf_path"]).resolve()
            == sediment_soils.resolve()
        )
        assert association["terrain_layer_name"] == "Terrain50"
        assert association["landcover_layer_name"] == "LandCover"
        assert association["infiltration_layer_name"] == "Infiltration"
        assert association["sediment_soils_layer_name"] == "Hydrologic Soil Groups"
        assert association["si_units"] == "False"

    def test_requires_at_least_one_association_path(self, tmp_path):
        geom_hdf_path = self._make_geometry_hdf(tmp_path)

        with pytest.raises(ValueError, match="at least one"):
            GeomMesh.set_geometry_association(geom_hdf_path)

    def test_rejects_missing_association_artifact(self, monkeypatch, tmp_path):
        geom_hdf_path = self._make_geometry_hdf(tmp_path)
        missing_terrain = tmp_path / "Terrain" / "Missing.hdf"
        monkeypatch.setattr(geom_mesh_module, "_load_dlls", lambda hecras_dir=None: None)

        with pytest.raises(FileNotFoundError, match="terrain_hdf_path"):
            GeomMesh.set_geometry_association(
                geom_hdf_path,
                terrain_hdf_path=missing_terrain,
            )


class TestDetectBcConflicts:
    """Test BC conflict detection using synthetic HDF."""

    def test_detects_shared_face(self, bc_conflict_hdf):
        conflicts = GeomMesh.detect_bc_conflicts(str(bc_conflict_hdf), cell_size=50.0)
        assert len(conflicts) >= 1
        assert "NormDepth1" in conflicts[0].bc_names
        assert "USInflow1" in conflicts[0].bc_names

    def test_identifies_normal_depth_bc(self, bc_conflict_hdf):
        conflicts = GeomMesh.detect_bc_conflicts(str(bc_conflict_hdf), cell_size=50.0)
        assert conflicts[0].normal_depth_bc == "NormDepth1"

    def test_detects_conflicts_in_later_flow_area(self, multi_area_bc_conflict_hdf):
        conflicts = GeomMesh.detect_bc_conflicts(
            str(multi_area_bc_conflict_hdf), cell_size=50.0
        )
        assert len(conflicts) == 1
        assert conflicts[0].flow_area_name == "Area2"
        assert conflicts[0].normal_depth_bc == "NormDepth2"
        assert "USInflow2" in conflicts[0].bc_names


class TestFixBcConflicts:
    """Test BC conflict repair using synthetic HDF."""

    def test_trims_normal_depth_bc_and_updates_per_area_group(self, bc_conflict_hdf):
        result = GeomMesh.fix_bc_conflicts(str(bc_conflict_hdf), cell_size=50.0)
        assert result.conflicts_found == 1
        assert result.conflicts_fixed == 1
        assert result.modified_hdf is True

        with h5py.File(str(bc_conflict_hdf), "r") as hf:
            coords = hf["Geometry/2D Flow Areas/MainArea/BC Lines/NormDepth1/Coordinates"][:]
            assert len(coords) < 3

        conflicts = GeomMesh.detect_bc_conflicts(str(bc_conflict_hdf), cell_size=50.0)
        assert conflicts == []

    def test_dry_run_no_modification(self, bc_conflict_hdf):
        result = GeomMesh.fix_bc_conflicts(
            str(bc_conflict_hdf), cell_size=50.0, dry_run=True
        )
        assert result.modified_hdf is False
        assert result.conflicts_found == 1

    def test_repairs_only_conflicted_later_flow_area(self, multi_area_bc_conflict_hdf):
        with h5py.File(str(multi_area_bc_conflict_hdf), "r") as hf:
            before_area1 = hf["Geometry/2D Flow Areas/Area1/BC Lines/UpstreamOnly/Coordinates"][:]
            before_area2 = hf["Geometry/2D Flow Areas/Area2/BC Lines/NormDepth2/Coordinates"][:]

        result = GeomMesh.fix_bc_conflicts(
            str(multi_area_bc_conflict_hdf), cell_size=50.0
        )

        assert result.conflicts_found == 1
        assert result.conflicts_fixed == 1
        assert result.modified_hdf is True
        assert result.trims[0][0].startswith("Area2/")

        with h5py.File(str(multi_area_bc_conflict_hdf), "r") as hf:
            after_area1 = hf["Geometry/2D Flow Areas/Area1/BC Lines/UpstreamOnly/Coordinates"][:]
            after_area2 = hf["Geometry/2D Flow Areas/Area2/BC Lines/NormDepth2/Coordinates"][:]

        assert np.array_equal(before_area1, after_area1)
        assert len(after_area2) < len(before_area2)
        assert GeomMesh.detect_bc_conflicts(str(multi_area_bc_conflict_hdf), cell_size=50.0) == []


class TestGenerate:
    """Test generate() normalization and persistence semantics."""

    def test_safe_cell_count_handles_rasmapper_null_mesh(self):
        assert _safe_non_virtual_cell_count(FakeMeshWithUnavailableCellCount()) is None

    def test_dedupe_seed_points_removes_duplicate_coordinates(self):
        seeds = MockPointMs()
        seeds.Add(MockPointM(1.0, 2.0))
        seeds.Add(MockPointM(1.0, 2.0))
        seeds.Add(MockPointM(3.0, 4.0))

        deduped, removed = _dedupe_seed_points(
            seeds,
            {"PointMs": MockPointMs},
            tolerance=1e-6,
        )

        assert removed == 1
        assert deduped.Count == 2
        assert [(deduped[i].X, deduped[i].Y) for i in range(deduped.Count)] == [
            (1.0, 2.0),
            (3.0, 4.0),
        ]

    def test_bad_seed_indexes_filter_to_seed_range(self):
        indexes = _bad_seed_indexes(FakeMeshWithBadIndexes([-1, 0, 2, 10]), 3)
        assert indexes == {0, 2}

    def test_remove_seed_indexes_preserves_order(self):
        seeds = MockPointMs()
        seeds.Add(MockPointM(1.0, 1.0))
        seeds.Add(MockPointM(2.0, 2.0))
        seeds.Add(MockPointM(3.0, 3.0))

        filtered, removed = _remove_seed_indexes(seeds, {1}, {"PointMs": MockPointMs})

        assert removed == 1
        assert [(filtered[i].X, filtered[i].Y) for i in range(filtered.Count)] == [
            (1.0, 1.0),
            (3.0, 3.0),
        ]

    def test_defaults_persist_geometry_with_existing_hdf(self, monkeypatch, breakline_geom_text):
        captured = _mock_generate_success(
            monkeypatch,
            breakline_geom_text,
            has_breaklines=True,
        )

        result = GeomMesh.generate(breakline_geom_text)

        assert result.ok
        assert result.geom_hdf_path
        assert Path(result.geom_hdf_path).exists()
        assert captured["cell_size"] == pytest.approx(100.0)

        text = breakline_geom_text.read_text(encoding="utf-8")
        assert "Storage Area Point Generation Data=,,100.000000,100.000000" in text
        assert "BreakLine CellSize Min=50.000000" in text
        assert "BreakLine CellSize Max=200.000000" in text
        assert "Storage Area 2D Points= 2 " in text

    def test_accepts_breakline_spacing_override(self, monkeypatch, breakline_geom_text):
        captured = _mock_generate_success(
            monkeypatch,
            breakline_geom_text,
            has_breaklines=True,
        )

        result = GeomMesh.generate(
            breakline_geom_text,
            bl_spacing_near=75.0,
            bl_spacing_far=125.0,
        )

        assert result.ok

        text = breakline_geom_text.read_text(encoding="utf-8")
        assert "BreakLine CellSize Min=75.000000" in text
        assert "BreakLine CellSize Max=125.000000" in text

    def test_perimeter_fix_reports_external_hdf_requirement(
        self, monkeypatch, breakline_geom_text
    ):
        captured = _mock_generate_success(
            monkeypatch,
            breakline_geom_text,
            has_breaklines=True,
        )

        feature_names = ["MainArea", "SecondaryArea"]
        polygons = {
            0: MockPolygon([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]),
            1: MockPolygon([(200.0, 0.0), (300.0, 0.0), (300.0, 100.0), (200.0, 100.0)]),
        }
        geom = captured["geom"]
        geom.D2FlowArea.FeatureCount.return_value = 2
        geom.D2FlowArea.GetFeatureName.side_effect = lambda fid: feature_names[fid]
        geom.D2FlowArea.GetFeatureByName.side_effect = (
            lambda name: feature_names.index(name) if name in feature_names else -1
        )
        geom.D2FlowArea.Geometry.MeshPerimeters.Polygon.side_effect = (
            lambda fid: polygons[fid]
        )

        seed_calls = []

        def fake_generate_seeds_via_net(hdf_path, ns, fid=0):
            seed_calls.append(fid)
            return FakePointCollection()

        monkeypatch.setattr(
            geom_mesh_module,
            "_generate_seeds_via_net",
            fake_generate_seeds_via_net,
        )
        monkeypatch.setattr(
            geom_mesh_module,
            "_remove_short_perimeter_segments",
            lambda perim, min_length, ns: MockPolygon(
                [(200.0, 0.0), (300.0, 0.0), (300.0, 100.0)]
            ),
        )
        monkeypatch.setattr(
            geom_mesh_module,
            "_set_point_generation_data",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            geom_mesh_module,
            "_patch_text_seeds",
            lambda *args, **kwargs: None,
        )

        result = GeomMesh.generate(breakline_geom_text, mesh_index=1)

        assert result.ok is False
        assert result.status == "exception"
        assert "cannot generate .g##.hdf" in result.error_message
        assert seed_calls == [1]

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"bl_spacing_near": 0.0},
            {"bl_spacing_far": -25.0},
        ],
    )
    def test_rejects_nonpositive_breakline_spacing(self, monkeypatch, breakline_geom_text, kwargs):
        monkeypatch.setattr(geom_mesh_module, "_load_dlls", lambda hecras_dir=None: None)
        monkeypatch.setattr(geom_mesh_module, "_imports", lambda: {})

        with pytest.raises(ValueError, match="must be greater than 0.0"):
            GeomMesh.generate(breakline_geom_text, **kwargs)

    def test_does_not_report_complete_when_geometry_hdf_missing(
        self, monkeypatch, breakline_geom_text
    ):
        monkeypatch.setattr(geom_mesh_module, "_load_dlls", lambda hecras_dir=None: None)
        monkeypatch.setattr(geom_mesh_module, "_imports", lambda: {})

        result = GeomMesh.generate(breakline_geom_text)

        assert result.ok is False
        assert result.status == "exception"
        assert "Compiled geometry HDF is missing" in result.error_message


@pytest.mark.skipif(
    platform.system() != "Windows" or os.environ.get(HECRAS_INTEGRATION_ENV) != "1",
    reason="Requires Windows, HEC-RAS, and explicit opt-in integration execution",
)
def test_generate_smoke_persists_real_geometry(tmp_path):
    source_project = repo_root / "example_projects" / "BaldEagleCrkMulti2D"
    project_copy = tmp_path / "BaldEagleCrkMulti2D"
    shutil.copytree(source_project, project_copy)

    geom_text_path = project_copy / "BaldEagleDamBrk.g01"
    start_text_mtime = geom_text_path.stat().st_mtime
    start_hdf_path = geom_text_path.with_suffix(geom_text_path.suffix + ".hdf")
    start_hdf_mtime = start_hdf_path.stat().st_mtime if start_hdf_path.exists() else None

    result = GeomMesh.generate(geom_text_path, mesh_index=0)

    assert result.ok
    assert result.geom_hdf_path
    compiled_hdf_path = Path(result.geom_hdf_path)
    assert compiled_hdf_path.exists()
    assert geom_text_path.stat().st_mtime >= start_text_mtime
    if start_hdf_mtime is not None:
        assert compiled_hdf_path.stat().st_mtime >= start_hdf_mtime


# ── Fixtures for name management / refinement region tests ──────────


@pytest.fixture
def named_breakline_geom(tmp_path):
    """Geometry with 3 named breaklines (including a duplicate pair)."""
    geom_text = tmp_path / "named.g01"
    geom_text.write_text(
        "Geom Title=NameTest\n"
        "Storage Area=MainArea\n"
        "Storage Area Point Generation Data=,,100.000000,100.000000\n"
        "BreakLine Name=River\n"
        "BreakLine CellSize Min=10.000000\n"
        "BreakLine CellSize Max=50.000000\n"
        "BreakLine Near Repeats=1\n"
        "BreakLine Protection Radius=0\n"
        "BreakLine Polyline= 2 \n"
        "     0.0  0.0\n"
        "     100.0  100.0\n"
        "BreakLine Name=River\n"
        "BreakLine CellSize Min=20.000000\n"
        "BreakLine CellSize Max=80.000000\n"
        "BreakLine Near Repeats=2\n"
        "BreakLine Protection Radius=1\n"
        "BreakLine Polyline= 2 \n"
        "     0.0  50.0\n"
        "     100.0  150.0\n"
        "BreakLine Name=\n"
        "BreakLine CellSize Min=15.000000\n"
        "BreakLine CellSize Max=60.000000\n"
        "BreakLine Near Repeats=1\n"
        "BreakLine Protection Radius=0\n"
        "BreakLine Polyline= 2 \n"
        "     0.0  100.0\n"
        "     100.0  200.0\n"
        "Storage Area 2D Points= 0 \n"
        "LCMann Time=0\n",
        encoding="utf-8",
    )
    return geom_text


@pytest.fixture
def refinement_region_hdf(tmp_path):
    """Synthetic HDF with 3 refinement regions (full polygon geometry)."""
    geom_text = tmp_path / "rr_test.g01"
    geom_text.write_text("Geom Title=RRTest\n", encoding="utf-8")
    hdf_path = tmp_path / "rr_test.g01.hdf"
    rr = "Geometry/2D Flow Area Refinement Regions"
    dt = np.dtype([
        ("Name", "S32"),
        ("Spacing dx", "<f4"),
        ("Spacing dy", "<f4"),
    ])
    data = np.array([
        (b"North", 50.0, 50.0),
        (b"North", 75.0, 75.0),
        (b"", 100.0, 100.0),
    ], dtype=dt)
    # Three simple square polygons (5 pts each, closed rings)
    pts0 = np.array([[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]], dtype=np.float64)
    pts1 = np.array([[200, 0], [300, 0], [300, 100], [200, 100], [200, 0]], dtype=np.float64)
    pts2 = np.array([[400, 0], [500, 0], [500, 100], [400, 100], [400, 0]], dtype=np.float64)
    all_pts = np.vstack([pts0, pts1, pts2])
    info = np.array([[0, 5, 0, 1], [5, 5, 1, 1], [10, 5, 2, 1]], dtype=np.int32)
    parts = np.array([[0, 5], [0, 5], [0, 5]], dtype=np.int32)
    gzip_kw = dict(compression="gzip", compression_opts=1)
    with h5py.File(str(hdf_path), "w") as hf:
        hf.create_dataset(f"{rr}/Attributes", data=data, **gzip_kw)
        hf.create_dataset(f"{rr}/Polygon Info", data=info, **gzip_kw)
        hf.create_dataset(f"{rr}/Polygon Parts", data=parts, **gzip_kw)
        hf.create_dataset(f"{rr}/Polygon Points", data=all_pts, **gzip_kw)
    return geom_text, hdf_path


# ── Breakline name management tests ─────────────────────────────────


class TestBreaklineNameManagement:

    def test_get_breakline_names(self, named_breakline_geom):
        names = GeomMesh.get_breakline_names(named_breakline_geom)
        assert len(names) == 3
        assert names[0] == (0, "River")
        assert names[1] == (1, "River")
        assert names[2] == (2, "")

    def test_get_breakline_spacing_returns_all_fields(self, named_breakline_geom):
        spacings = GeomMesh.get_breakline_spacing(named_breakline_geom)
        assert len(spacings) == 3
        fid, name, near, far, nr, pr = spacings[0]
        assert fid == 0
        assert name == "River"
        assert abs(near - 10.0) < 0.01
        assert abs(far - 50.0) < 0.01
        assert nr == 1
        assert pr == 0

    def test_unnamed_breakline_spacing(self, named_breakline_geom):
        spacings = GeomMesh.get_breakline_spacing(named_breakline_geom)
        fid, name, near, far, nr, pr = spacings[2]
        assert fid == 2
        assert name == ""
        assert abs(near - 15.0) < 0.01

    def test_set_name_by_fid(self, named_breakline_geom):
        GeomMesh.set_breakline_name(
            named_breakline_geom, new_name="Channel", breakline_fid=2,
        )
        names = GeomMesh.get_breakline_names(named_breakline_geom)
        assert names[2] == (2, "Channel")

    def test_set_name_rejects_duplicate_old_name(self, named_breakline_geom):
        with pytest.raises(ValueError, match="Multiple breaklines"):
            GeomMesh.set_breakline_name(
                named_breakline_geom, new_name="X", old_name="River",
            )

    def test_set_name_by_unique_old_name(self, named_breakline_geom):
        GeomMesh.set_breakline_name(
            named_breakline_geom, new_name="Renamed", breakline_fid=0,
        )
        GeomMesh.set_breakline_name(
            named_breakline_geom, new_name="UniqueRiver", old_name="River",
        )
        names = GeomMesh.get_breakline_names(named_breakline_geom)
        assert names[1] == (1, "UniqueRiver")

    def test_set_name_fid_out_of_range(self, named_breakline_geom):
        with pytest.raises(ValueError, match="not found"):
            GeomMesh.set_breakline_name(
                named_breakline_geom, new_name="X", breakline_fid=99,
            )

    def test_set_spacing_rejects_duplicate_name(self, named_breakline_geom):
        with pytest.raises(ValueError, match="Multiple breaklines"):
            GeomMesh.set_breakline_spacing(
                named_breakline_geom, near=50.0, breakline_name="River",
            )

    def test_set_spacing_by_fid_isolates_target(self, named_breakline_geom):
        GeomMesh.set_breakline_spacing(
            named_breakline_geom, near=99.0, far=199.0, breakline_fid=1,
        )
        spacings = GeomMesh.get_breakline_spacing(named_breakline_geom)
        assert abs(spacings[1][2] - 99.0) < 0.01
        assert abs(spacings[0][2] - 10.0) < 0.01

    def test_set_spacing_fid_out_of_range(self, named_breakline_geom):
        with pytest.raises(ValueError, match="not found"):
            GeomMesh.set_breakline_spacing(
                named_breakline_geom, near=50.0, breakline_fid=99,
            )

    def test_set_spacing_negative_fid(self, named_breakline_geom):
        with pytest.raises(ValueError, match="not found"):
            GeomMesh.set_breakline_spacing(
                named_breakline_geom, near=50.0, breakline_fid=-1,
            )

    def test_conflicting_all_breaklines_and_name(self, named_breakline_geom):
        with pytest.raises(ValueError, match="cannot be combined"):
            GeomMesh.set_breakline_spacing(
                named_breakline_geom, near=50.0,
                all_breaklines=True, breakline_name="River",
            )

    def test_conflicting_all_breaklines_and_fid(self, named_breakline_geom):
        with pytest.raises(ValueError, match="cannot be combined"):
            GeomMesh.set_breakline_spacing(
                named_breakline_geom, near=50.0,
                all_breaklines=True, breakline_fid=0,
            )

    def test_conflicting_name_and_fid(self, named_breakline_geom):
        with pytest.raises(ValueError, match="not both"):
            GeomMesh.set_breakline_spacing(
                named_breakline_geom, near=50.0,
                breakline_name="River", breakline_fid=0,
            )

    def test_no_target_raises(self, named_breakline_geom):
        with pytest.raises(ValueError):
            GeomMesh.set_breakline_spacing(
                named_breakline_geom, near=50.0,
            )


# ── Refinement region tests ─────────────────────────────────────────


class TestRefinementRegions:

    def test_get_names(self, refinement_region_hdf):
        geom_text, _ = refinement_region_hdf
        names = GeomMesh.get_refinement_region_names(geom_text)
        assert len(names) == 3
        assert names[0] == (0, "North")
        assert names[1] == (1, "North")
        assert names[2] == (2, "")

    def test_get_regions_returns_spacing(self, refinement_region_hdf):
        geom_text, _ = refinement_region_hdf
        regions = GeomMesh.get_refinement_regions(geom_text)
        assert len(regions) == 3
        assert regions[0]["fid"] == 0
        assert abs(regions[0]["spacing_dx"] - 50.0) < 0.01
        assert abs(regions[1]["spacing_dx"] - 75.0) < 0.01

    def test_set_name_by_fid(self, refinement_region_hdf):
        geom_text, _ = refinement_region_hdf
        GeomMesh.set_refinement_region_name(geom_text, "South", region_fid=2)
        names = GeomMesh.get_refinement_region_names(geom_text)
        assert names[2] == (2, "South")

    def test_set_name_rejects_duplicate_old_name(self, refinement_region_hdf):
        geom_text, _ = refinement_region_hdf
        with pytest.raises(ValueError, match="Multiple"):
            GeomMesh.set_refinement_region_name(
                geom_text, "X", old_name="North",
            )

    def test_set_name_fid_out_of_range(self, refinement_region_hdf):
        geom_text, _ = refinement_region_hdf
        with pytest.raises(ValueError, match="not found"):
            GeomMesh.set_refinement_region_name(
                geom_text, "X", region_fid=99,
            )

    def test_set_spacing_by_fid(self, refinement_region_hdf):
        geom_text, _ = refinement_region_hdf
        GeomMesh.set_refinement_region_spacing(
            geom_text, spacing_dx=25.0, region_fid=0,
        )
        regions = GeomMesh.get_refinement_regions(geom_text)
        assert abs(regions[0]["spacing_dx"] - 25.0) < 0.01
        assert abs(regions[1]["spacing_dx"] - 75.0) < 0.01

    def test_set_spacing_all_regions(self, refinement_region_hdf):
        geom_text, _ = refinement_region_hdf
        GeomMesh.set_refinement_region_spacing(
            geom_text, spacing_dx=33.0, all_regions=True,
        )
        regions = GeomMesh.get_refinement_regions(geom_text)
        for r in regions:
            assert abs(r["spacing_dx"] - 33.0) < 0.01

    def test_set_spacing_rejects_duplicate_name(self, refinement_region_hdf):
        geom_text, _ = refinement_region_hdf
        with pytest.raises(ValueError, match="Multiple refinement regions"):
            GeomMesh.set_refinement_region_spacing(
                geom_text, spacing_dx=25.0, region_name="North",
            )

    def test_set_spacing_fid_out_of_range(self, refinement_region_hdf):
        geom_text, _ = refinement_region_hdf
        with pytest.raises(ValueError, match="not found"):
            GeomMesh.set_refinement_region_spacing(
                geom_text, spacing_dx=25.0, region_fid=99,
            )

    def test_conflicting_all_regions_and_name(self, refinement_region_hdf):
        geom_text, _ = refinement_region_hdf
        with pytest.raises(ValueError, match="cannot be combined"):
            GeomMesh.set_refinement_region_spacing(
                geom_text, spacing_dx=25.0,
                all_regions=True, region_name="North",
            )

    def test_conflicting_all_regions_and_fid(self, refinement_region_hdf):
        geom_text, _ = refinement_region_hdf
        with pytest.raises(ValueError, match="cannot be combined"):
            GeomMesh.set_refinement_region_spacing(
                geom_text, spacing_dx=25.0,
                all_regions=True, region_fid=0,
            )

    def test_conflicting_name_and_fid(self, refinement_region_hdf):
        geom_text, _ = refinement_region_hdf
        with pytest.raises(ValueError, match="not both"):
            GeomMesh.set_refinement_region_spacing(
                geom_text, spacing_dx=25.0,
                region_name="North", region_fid=0,
            )

    def test_utf8_truncation_preserves_valid_bytes(self, refinement_region_hdf):
        geom_text, hdf_path = refinement_region_hdf
        long_name = "\u00e9" * 20
        GeomMesh.set_refinement_region_name(geom_text, long_name, region_fid=0)
        names = GeomMesh.get_refinement_region_names(geom_text)
        stored = names[0][1]
        stored.encode("utf-8")
        assert "\ufffd" not in stored


# ── Add refinement region tests ───────────────────────────────────


@pytest.fixture
def empty_geom_hdf(tmp_path):
    """Geometry file + compiled HDF with no refinement regions."""
    geom_text = tmp_path / "empty.g01"
    geom_text.write_text("Geom Title=EmptyTest\n", encoding="utf-8")
    hdf_path = tmp_path / "empty.g01.hdf"
    with h5py.File(str(hdf_path), "w") as hf:
        hf.create_dataset(
            "Geometry/2D Flow Areas/Attributes",
            data=np.array(
                [(b"MainArea", 0, 0.04, 0, 0, 0.01, 0.01, 0.01, 0.01, 1.0, 0.1, 0.05, 60.96, 60.96, 0.0, 0.0, 0)],
                dtype=np.dtype([
                    ("Name", "S16"), ("Locked", "u1"), ("Mann", "<f4"),
                    ("Multiple Face Mann n", "u1"), ("Composite LC", "u1"),
                    ("Cell Vol Tol", "<f4"), ("Cell Min Area Fraction", "<f4"),
                    ("Face Profile Tol", "<f4"), ("Face Area Tol", "<f4"),
                    ("Face Conv Ratio", "<f4"), ("Laminar Depth", "<f4"),
                    ("Min Face Length Ratio", "<f4"), ("Spacing dx", "<f4"),
                    ("Spacing dy", "<f4"), ("Shift dx", "<f4"),
                    ("Shift dy", "<f4"), ("Cell Count", "<i4"),
                ]),
            ),
            compression="gzip",
            compression_opts=1,
        )
    return geom_text, hdf_path


SAMPLE_POLYGON = [
    (100.0, 100.0),
    (200.0, 100.0),
    (200.0, 200.0),
    (100.0, 200.0),
    (100.0, 100.0),
]


class TestAddRefinementRegion:

    def test_add_first_region_creates_group(self, empty_geom_hdf):
        geom_text, hdf_path = empty_geom_hdf
        fid = GeomMesh.add_refinement_region(
            geom_text, SAMPLE_POLYGON, spacing_dx=25.0, name="HighRes",
        )
        assert fid == 0
        with h5py.File(str(hdf_path), "r") as hf:
            rr = "Geometry/2D Flow Area Refinement Regions"
            assert f"{rr}/Attributes" in hf
            assert f"{rr}/Polygon Info" in hf
            assert f"{rr}/Polygon Parts" in hf
            assert f"{rr}/Polygon Points" in hf

            attrs = hf[f"{rr}/Attributes"][:]
            assert len(attrs) == 1
            assert attrs["Name"][0] == b"HighRes"
            assert abs(float(attrs["Spacing dx"][0]) - 25.0) < 0.01
            assert abs(float(attrs["Spacing dy"][0]) - 25.0) < 0.01

    def test_add_region_correct_dtypes(self, empty_geom_hdf):
        geom_text, hdf_path = empty_geom_hdf
        GeomMesh.add_refinement_region(
            geom_text, SAMPLE_POLYGON, spacing_dx=30.0,
        )
        with h5py.File(str(hdf_path), "r") as hf:
            rr = "Geometry/2D Flow Area Refinement Regions"
            assert hf[f"{rr}/Attributes"].dtype["Spacing dx"] == np.dtype("<f4")
            assert hf[f"{rr}/Attributes"].dtype["Spacing dy"] == np.dtype("<f4")
            assert hf[f"{rr}/Attributes"].dtype["Name"] == np.dtype("S32")
            assert hf[f"{rr}/Polygon Info"].dtype == np.dtype("int32")
            assert hf[f"{rr}/Polygon Parts"].dtype == np.dtype("int32")
            assert hf[f"{rr}/Polygon Points"].dtype == np.dtype("float64")

    def test_add_region_gzip_compression(self, empty_geom_hdf):
        geom_text, hdf_path = empty_geom_hdf
        GeomMesh.add_refinement_region(
            geom_text, SAMPLE_POLYGON, spacing_dx=30.0,
        )
        with h5py.File(str(hdf_path), "r") as hf:
            rr = "Geometry/2D Flow Area Refinement Regions"
            for ds_name in ("Attributes", "Polygon Info", "Polygon Parts", "Polygon Points"):
                ds = hf[f"{rr}/{ds_name}"]
                assert ds.compression == "gzip", f"{ds_name} missing gzip"

    def test_add_region_polygon_geometry(self, empty_geom_hdf):
        geom_text, hdf_path = empty_geom_hdf
        GeomMesh.add_refinement_region(
            geom_text, SAMPLE_POLYGON, spacing_dx=30.0,
        )
        with h5py.File(str(hdf_path), "r") as hf:
            rr = "Geometry/2D Flow Area Refinement Regions"
            info = hf[f"{rr}/Polygon Info"][:]
            points = hf[f"{rr}/Polygon Points"][:]
            parts = hf[f"{rr}/Polygon Parts"][:]
            assert info.shape == (1, 4)
            assert info[0, 0] == 0  # pnt_start
            assert info[0, 1] == 5  # pnt_count (closed ring)
            assert info[0, 2] == 0  # part_start
            assert info[0, 3] == 1  # part_count
            assert points.shape == (5, 2)
            assert parts.shape == (1, 2)
            assert parts[0, 0] == 0
            assert parts[0, 1] == 5

    def test_add_multiple_regions_appends(self, empty_geom_hdf):
        geom_text, hdf_path = empty_geom_hdf
        fid0 = GeomMesh.add_refinement_region(
            geom_text, SAMPLE_POLYGON, spacing_dx=25.0, name="First",
        )
        second_poly = [(300.0, 300.0), (400.0, 300.0), (400.0, 400.0), (300.0, 400.0)]
        fid1 = GeomMesh.add_refinement_region(
            geom_text, second_poly, spacing_dx=10.0, name="Second",
        )
        assert fid0 == 0
        assert fid1 == 1
        with h5py.File(str(hdf_path), "r") as hf:
            rr = "Geometry/2D Flow Area Refinement Regions"
            attrs = hf[f"{rr}/Attributes"][:]
            assert len(attrs) == 2
            assert attrs["Name"][0] == b"First"
            assert attrs["Name"][1] == b"Second"
            info = hf[f"{rr}/Polygon Info"][:]
            assert info.shape == (2, 4)
            # Second region points start after first region's 5 points
            assert info[1, 0] == 5
            # Second polygon was 4 pts, auto-closed to 5
            assert info[1, 1] == 5
            points = hf[f"{rr}/Polygon Points"][:]
            assert points.shape == (10, 2)

    def test_add_region_to_existing_fixture(self, refinement_region_hdf):
        geom_text, hdf_path = refinement_region_hdf
        fid = GeomMesh.add_refinement_region(
            geom_text, SAMPLE_POLYGON, spacing_dx=15.0, name="NewRegion",
        )
        assert fid == 3  # fixture has 3 existing regions
        regions = GeomMesh.get_refinement_regions(geom_text)
        assert len(regions) == 4
        assert regions[3]["name"] == "NewRegion"
        assert abs(regions[3]["spacing_dx"] - 15.0) < 0.01

    def test_add_region_auto_closes_ring(self, empty_geom_hdf):
        geom_text, hdf_path = empty_geom_hdf
        open_poly = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        GeomMesh.add_refinement_region(
            geom_text, open_poly, spacing_dx=5.0,
        )
        with h5py.File(str(hdf_path), "r") as hf:
            pts = hf["Geometry/2D Flow Area Refinement Regions/Polygon Points"][:]
            assert len(pts) == 5
            assert np.allclose(pts[0], pts[-1])

    def test_add_region_spacing_dy_defaults_to_dx(self, empty_geom_hdf):
        geom_text, hdf_path = empty_geom_hdf
        GeomMesh.add_refinement_region(
            geom_text, SAMPLE_POLYGON, spacing_dx=42.0,
        )
        with h5py.File(str(hdf_path), "r") as hf:
            attrs = hf["Geometry/2D Flow Area Refinement Regions/Attributes"][:]
            assert abs(float(attrs["Spacing dx"][0]) - 42.0) < 0.01
            assert abs(float(attrs["Spacing dy"][0]) - 42.0) < 0.01

    def test_add_region_separate_dx_dy(self, empty_geom_hdf):
        geom_text, hdf_path = empty_geom_hdf
        GeomMesh.add_refinement_region(
            geom_text, SAMPLE_POLYGON, spacing_dx=30.0, spacing_dy=15.0,
        )
        with h5py.File(str(hdf_path), "r") as hf:
            attrs = hf["Geometry/2D Flow Area Refinement Regions/Attributes"][:]
            assert abs(float(attrs["Spacing dx"][0]) - 30.0) < 0.01
            assert abs(float(attrs["Spacing dy"][0]) - 15.0) < 0.01

    def test_add_region_rejects_too_few_vertices(self, empty_geom_hdf):
        geom_text, _ = empty_geom_hdf
        with pytest.raises(ValueError, match="at least 3 vertices"):
            GeomMesh.add_refinement_region(
                geom_text, [(0.0, 0.0), (1.0, 1.0)], spacing_dx=10.0,
            )

    def test_add_region_rejects_non_positive_spacing(self, empty_geom_hdf):
        geom_text, _ = empty_geom_hdf
        with pytest.raises(ValueError, match="positive"):
            GeomMesh.add_refinement_region(
                geom_text, SAMPLE_POLYGON, spacing_dx=0.0,
            )
        with pytest.raises(ValueError, match="positive"):
            GeomMesh.add_refinement_region(
                geom_text, SAMPLE_POLYGON, spacing_dx=-5.0,
            )

    def test_add_region_name_truncation(self, empty_geom_hdf):
        geom_text, hdf_path = empty_geom_hdf
        long_name = "A" * 50
        GeomMesh.add_refinement_region(
            geom_text, SAMPLE_POLYGON, spacing_dx=20.0, name=long_name,
        )
        with h5py.File(str(hdf_path), "r") as hf:
            stored = hf["Geometry/2D Flow Area Refinement Regions/Attributes"]["Name"][0]
            assert len(stored) <= 32

    def test_add_region_readable_by_hdfbndry_pattern(self, empty_geom_hdf):
        """Verify datasets match the schema HdfBndry.get_refinement_regions() reads."""
        geom_text, hdf_path = empty_geom_hdf
        GeomMesh.add_refinement_region(
            geom_text, SAMPLE_POLYGON, spacing_dx=25.0, name="Test",
        )
        with h5py.File(str(hdf_path), "r") as hf:
            rr = hf["Geometry/2D Flow Area Refinement Regions"]
            # Read exactly the way HdfBndry does (lines 253-269)
            attrs = rr["Attributes"][()]
            assert "Name" in attrs.dtype.names
            for pnt_start, pnt_cnt, part_start, part_cnt in rr["Polygon Info"][()]:
                points = rr["Polygon Points"][()][pnt_start:pnt_start + pnt_cnt]
                assert points.shape == (pnt_cnt, 2)
                assert part_cnt >= 1
                if part_cnt > 1:
                    parts = rr["Polygon Parts"][()][part_start:part_start + part_cnt]
                    assert parts.shape[1] == 2

    def test_add_region_shapely_polygon(self, empty_geom_hdf):
        """Accept a Shapely Polygon if available."""
        pytest.importorskip("shapely")
        from shapely.geometry import Polygon as ShapelyPolygon
        geom_text, hdf_path = empty_geom_hdf
        poly = ShapelyPolygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        fid = GeomMesh.add_refinement_region(
            geom_text, poly, spacing_dx=20.0, name="ShapelyRgn",
        )
        assert fid == 0
        regions = GeomMesh.get_refinement_regions(geom_text)
        assert regions[0]["name"] == "ShapelyRgn"


class TestFlowlineRefinementRegions:

    def test_linestring_defaults_spacing_to_buffer_width(self, empty_geom_hdf):
        pytest.importorskip("shapely")
        from shapely.geometry import LineString

        geom_text, hdf_path = empty_geom_hdf
        mappings = GeomMesh.add_flowline_refinement_regions(
            geom_text,
            LineString([(0.0, 0.0), (100.0, 0.0)]),
            buffer_width=20.0,
            name_prefix="Channel",
        )

        assert mappings == [{
            "fid": 0,
            "name": "Channel_001",
            "source_index": 0,
            "part_index": 0,
            "spacing_dx": 20.0,
            "spacing_dy": 20.0,
            "buffer_width": 20.0,
            "area": pytest.approx(4000.0),
        }]
        regions = GeomMesh.get_refinement_regions(geom_text)
        assert regions[0]["name"] == "Channel_001"
        assert abs(regions[0]["spacing_dx"] - 20.0) < 0.01
        with h5py.File(str(hdf_path), "r") as hf:
            points = hf["Geometry/2D Flow Area Refinement Regions/Polygon Points"][:]
            assert np.isclose(points[:, 0].min(), 0.0)
            assert np.isclose(points[:, 0].max(), 100.0)
            assert np.isclose(points[:, 1].min(), -20.0)
            assert np.isclose(points[:, 1].max(), 20.0)

    def test_geodataframe_name_column(self, empty_geom_hdf):
        pytest.importorskip("shapely")
        gpd = pytest.importorskip("geopandas")
        from shapely.geometry import LineString

        geom_text, _ = empty_geom_hdf
        flowlines = gpd.GeoDataFrame(
            {"rr_name": ["Main", "Trib"]},
            geometry=[
                LineString([(0.0, 0.0), (100.0, 0.0)]),
                LineString([(0.0, 50.0), (100.0, 50.0)]),
            ],
        )

        mappings = GeomMesh.add_flowline_refinement_regions(
            geom_text,
            flowlines,
            buffer_width=10.0,
            name_column="rr_name",
        )

        assert [m["fid"] for m in mappings] == [0, 1]
        assert [m["name"] for m in mappings] == ["Main", "Trib"]
        assert [m["source_index"] for m in mappings] == [0, 1]
        regions = GeomMesh.get_refinement_regions(geom_text)
        assert [r["name"] for r in regions] == ["Main", "Trib"]

    def test_simplifies_flowline_before_buffering(self, empty_geom_hdf):
        pytest.importorskip("shapely")
        from shapely.geometry import LineString

        geom_text, hdf_path = empty_geom_hdf
        sinuous = LineString([
            (0.0, 0.0),
            (10.0, 1.0),
            (20.0, -1.0),
            (30.0, 1.0),
            (40.0, 0.0),
        ])
        GeomMesh.add_flowline_refinement_regions(
            geom_text,
            sinuous,
            buffer_width=5.0,
            name_prefix="Raw",
        )
        GeomMesh.add_flowline_refinement_regions(
            geom_text,
            sinuous,
            buffer_width=5.0,
            name_prefix="Simple",
            simplify_tolerance=5.0,
        )

        with h5py.File(str(hdf_path), "r") as hf:
            info = hf["Geometry/2D Flow Area Refinement Regions/Polygon Info"][:]
            raw_point_count = info[0, 1]
            simplified_point_count = info[1, 1]
        assert simplified_point_count < raw_point_count

    def test_trim_geometries_split_bridge_overlap(self, empty_geom_hdf):
        pytest.importorskip("shapely")
        from shapely.geometry import LineString

        geom_text, _ = empty_geom_hdf
        mappings = GeomMesh.add_flowline_refinement_regions(
            geom_text,
            LineString([(0.0, 0.0), (100.0, 0.0)]),
            buffer_width=10.0,
            name_prefix="BridgeTrim",
            trim_geometries=LineString([(50.0, -30.0), (50.0, 30.0)]),
            trim_distance=2.0,
        )

        assert len(mappings) == 2
        assert [m["fid"] for m in mappings] == [0, 1]
        assert [m["name"] for m in mappings] == [
            "BridgeTrim_001_1",
            "BridgeTrim_001_2",
        ]
        assert all(m["area"] < 1000.0 for m in mappings)

    def test_trim_hook_can_return_custom_polygon(self, empty_geom_hdf):
        pytest.importorskip("shapely")
        from shapely.geometry import LineString, box

        geom_text, hdf_path = empty_geom_hdf

        def left_half(polygon, line, source):
            assert source["index"] == 0
            assert line.length == pytest.approx(100.0)
            return polygon.intersection(box(-1000.0, -1000.0, 50.0, 1000.0))

        mappings = GeomMesh.add_flowline_refinement_regions(
            geom_text,
            LineString([(0.0, 0.0), (100.0, 0.0)]),
            buffer_width=10.0,
            name_prefix="Hooked",
            trim_hook=left_half,
        )

        assert len(mappings) == 1
        assert mappings[0]["name"] == "Hooked_001"
        with h5py.File(str(hdf_path), "r") as hf:
            points = hf["Geometry/2D Flow Area Refinement Regions/Polygon Points"][:]
            assert points[:, 0].max() <= 50.0

    def test_trim_overlaps_skips_duplicate_flowline_region(self, empty_geom_hdf):
        pytest.importorskip("shapely")
        from shapely.geometry import LineString

        geom_text, _ = empty_geom_hdf
        line = LineString([(0.0, 0.0), (100.0, 0.0)])
        mappings = GeomMesh.add_flowline_refinement_regions(
            geom_text,
            [line, line],
            buffer_width=10.0,
            name_prefix="NoOverlap",
            trim_overlaps=True,
        )

        assert len(mappings) == 1
        assert mappings[0]["name"] == "NoOverlap_001"

    def test_rejects_non_line_geometry(self, empty_geom_hdf):
        pytest.importorskip("shapely")
        from shapely.geometry import Polygon

        geom_text, _ = empty_geom_hdf
        with pytest.raises(ValueError, match="LineString or MultiLineString"):
            GeomMesh.add_flowline_refinement_regions(
                geom_text,
                Polygon([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]),
                buffer_width=5.0,
            )
