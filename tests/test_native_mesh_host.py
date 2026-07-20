"""Unit tests for the out-of-process RasMapperLib mesh host wrapper."""

from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from ras_commander.native import mesh_host


def _write_mesh_candidate(
    path: Path,
    *,
    mesh_name: str = "MainArea",
    cell_count: int = 2,
    face_count: int = 5,
    logical_centers=None,
    empty_face_perimeter: bool = False,
) -> None:
    capacity = cell_count + 1
    facepoint_count = face_count + 1
    face_cells = np.column_stack(
        (
            np.arange(face_count, dtype="i4") % capacity,
            (np.arange(face_count, dtype="i4") + 1) % capacity,
        )
    )
    face_facepoints = np.column_stack(
        (
            np.arange(face_count, dtype="i4") % facepoint_count,
            (np.arange(face_count, dtype="i4") + 1) % facepoint_count,
        )
    )
    with h5py.File(path, "w") as hdf:
        root = hdf.create_group("Geometry/2D Flow Areas")
        attributes_dtype = np.dtype([("Name", "S16"), ("Cell Count", "i4")])
        root.create_dataset(
            "Attributes",
            data=np.array([(mesh_name.encode(), cell_count)], dtype=attributes_dtype),
        )
        root.create_dataset("Cell Info", data=np.array([[0, cell_count]], dtype="i4"))
        root.create_dataset("Cell Points", data=np.ones((cell_count, 2)))
        area = root.create_group(mesh_name)
        if logical_centers is None:
            logical_centers = (
                np.arange(1, cell_count * 2 + 1, dtype=np.float64)
                .reshape(cell_count, 2)
                * 10.0
            )
        allocated_centers = np.ones((capacity, 2), dtype=np.float64)
        allocated_centers[:cell_count] = np.asarray(logical_centers, dtype=np.float64)
        area.create_dataset("Cells Center Coordinate", data=allocated_centers)
        cell_records = [[] for _ in range(capacity)]
        for face_id, (first_cell, second_cell) in enumerate(face_cells):
            cell_records[int(first_cell)].append((face_id, 1))
            cell_records[int(second_cell)].append((face_id, -1))
        cell_face_info = np.zeros((capacity, 2), dtype="i4")
        cell_values = []
        for index, records in enumerate(cell_records):
            cell_face_info[index] = (len(cell_values), len(records))
            cell_values.extend(records)
        area.create_dataset("Cells Face and Orientation Info", data=cell_face_info)
        cell_face_values = np.asarray(cell_values, dtype="i4")
        area.create_dataset(
            "Cells Face and Orientation Values", data=cell_face_values
        )
        cell_facepoints = np.full((capacity, 8), -1, dtype="i4")
        cell_facepoints[:cell_count, :2] = np.array([0, 1], dtype="i4")
        area.create_dataset("Cells FacePoint Indexes", data=cell_facepoints)
        area.create_dataset(
            "FacePoints Cell Index Values",
            data=np.arange(facepoint_count, dtype="i4") % capacity,
        )
        point_cell_info = np.column_stack(
            (np.arange(facepoint_count, dtype="i4"), np.ones(facepoint_count, dtype="i4"))
        )
        area.create_dataset("FacePoints Cell Info", data=point_cell_info)
        area.create_dataset(
            "FacePoints Coordinate", data=np.ones((facepoint_count, 2))
        )
        point_records = [[] for _ in range(facepoint_count)]
        for face_id, (first_point, second_point) in enumerate(face_facepoints):
            point_records[int(first_point)].append((face_id, -1))
            point_records[int(second_point)].append((face_id, 1))
        point_face_info = np.zeros((facepoint_count, 2), dtype="i4")
        point_values = []
        for index, records in enumerate(point_records):
            point_face_info[index] = (len(point_values), len(records))
            point_values.extend(records)
        area.create_dataset(
            "FacePoints Face and Orientation Info", data=point_face_info
        )
        point_face_values = np.asarray(point_values, dtype="i4")
        area.create_dataset(
            "FacePoints Face and Orientation Values", data=point_face_values
        )
        area.create_dataset(
            "FacePoints Is Perimeter", data=np.ones(facepoint_count, dtype="i4")
        )
        area.create_dataset("Faces Cell Indexes", data=face_cells)
        area.create_dataset("Faces FacePoint Indexes", data=face_facepoints)
        normals = np.zeros((face_count, 3), dtype="f4")
        normals[:, 0] = 1.0
        normals[:, 2] = 1.0
        area.create_dataset("Faces NormalUnitVector and Length", data=normals)
        perimeter_info = np.zeros((face_count, 2), dtype="i4")
        if not empty_face_perimeter:
            perimeter_info[0] = (0, 1)
            perimeter_info[1:, 0] = 1
        area.create_dataset("Faces Perimeter Info", data=perimeter_info)
        area.create_dataset(
            "Faces Perimeter Values",
            data=(
                np.empty((0, 0))
                if empty_face_perimeter
                else np.ones((1, 2))
            ),
        )
        area.create_dataset(
            "Perimeter",
            data=np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]),
        )


def test_is_wine_runtime_uses_explicit_wine_environment(monkeypatch):
    monkeypatch.delenv("WINEPREFIX", raising=False)
    monkeypatch.delenv("WINELOADERNOEXEC", raising=False)
    monkeypatch.delenv("WINEARCH", raising=False)
    assert mesh_host.is_wine_runtime() is False

    monkeypatch.setenv("WINEPREFIX", "/tmp/rasq-prefix")
    assert mesh_host.is_wine_runtime() is True


def test_ensure_managed_mesh_host_compiles_once_per_source_hash(
    monkeypatch, tmp_path
):
    python_dir = tmp_path / "Python311"
    python_dir.mkdir()
    python_executable = python_dir / "python.exe"
    python_executable.touch()
    compiler = tmp_path / "csc.exe"
    compiler.touch()
    calls = []

    monkeypatch.setattr(mesh_host.platform, "system", lambda: "Windows")
    monkeypatch.setattr(mesh_host.sys, "executable", str(python_executable))
    local_appdata = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setattr(
        mesh_host,
        "configure_rasmapper_gdal_bridge",
        lambda _hecras_dir, **_kwargs: None,
    )
    monkeypatch.setattr(mesh_host, "_compiler_path", lambda: compiler)

    def fake_run(command, **_kwargs):
        calls.append(command)
        output = Path(next(value[5:] for value in command if value.startswith("/out:")))
        output.touch()
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mesh_host.subprocess, "run", fake_run)

    first = mesh_host.ensure_managed_mesh_host(tmp_path / "HEC-RAS")
    second = mesh_host.ensure_managed_mesh_host(tmp_path / "HEC-RAS")

    assert first == (
        local_appdata
        / "ras_commander"
        / "managed_host"
        / "RasMapperMeshHelper.exe"
    )
    assert second == first
    assert len(calls) == 1


def test_managed_helper_reflects_nonpublic_h5writer_constructor():
    source = Path(mesh_host.__file__).with_name(
        "RasMapperMeshHelper.cs"
    ).read_text(encoding="utf-8")
    constructor_block = source.split(
        "ConstructorInfo writerConstructor", 1
    )[1].split("if (writerConstructor == null)", 1)[0]

    assert "BindingFlags.Instance" in constructor_block
    assert "BindingFlags.NonPublic" in constructor_block
    assert "new[] { typeof(string), typeof(bool) }" in constructor_block


def test_managed_helper_binds_cell_count_through_vendor_write_only_serializer():
    source = Path(mesh_host.__file__).with_name(
        "RasMapperMeshHelper.cs"
    ).read_text(encoding="utf-8")
    serializer_block = source.split(
        "private static object CellCountAwareDatatableManager", 1
    )[1].split("private static void WriteMeshDirectly", 1)[0]

    assert 'new object[] { "Cell Count", cellCount }' in serializer_block
    assert ".MakeGenericMethod(typeof(int))" in serializer_block
    assert "targetCellCount != expectedCellCount" in serializer_block
    assert "CompleteMeshCellCount(d2FlowArea, rowFid)" in serializer_block
    assert 'GetField(\n            "_h5MemoryMap"' in serializer_block
    assert '"_writeColumnNames"' in serializer_block
    assert "cellCountIndexes.Count != 1 || cellCountIndexes[0] != 0" in (
        serializer_block
    )

    override_position = serializer_block.index(
        "merge.Invoke(\n            cellCountManager"
    )
    product_manager_position = serializer_block.index(
        "new object[] { d2Manager }", override_position
    )
    perimeter_position = serializer_block.index(
        "new object[] { perimeterManager }", product_manager_position
    )
    assert override_position < product_manager_position < perimeter_position


def test_managed_helper_records_regenerate_mesh_points_signature():
    source = Path(mesh_host.__file__).with_name(
        "RasMapperMeshHelper.cs"
    ).read_text(encoding="utf-8")

    assert "RegenerateParameterSignature" in source
    assert "regenerate.GetParameters().Select" in source
    assert 'parameter.Name + ":"' in source
    assert "regenerate_parameter_signature" in source


def test_managed_helper_regenerates_only_the_selected_flow_area():
    source = Path(mesh_host.__file__).with_name(
        "RasMapperMeshHelper.cs"
    ).read_text(encoding="utf-8")
    regeneration = source.split(
        "List<int> activeRegions = FeatureIds(meshRegions);", 1
    )[1].split('Stage("seeds-regenerated")', 1)[0]

    assert regeneration.count("new List<int> { fid }") == 2
    assert regeneration.index("activePerimeters,") < regeneration.index(
        "regeneratePerimeters,"
    )


def test_managed_helper_repairs_max_faces_with_rasmapper_midpoint_seeds():
    source = Path(mesh_host.__file__).with_name(
        "RasMapperMeshHelper.cs"
    ).read_text(encoding="utf-8")
    repair = source.split(
        "private static object AddMaxFaceMidpointSeeds", 1
    )[1].split("private static double Coordinate", 1)[0]
    generation = source.split("object mesh = null;", 1)[1].split(
        'Stage("mesh-complete")', 1
    )[0]

    assert 'GetMethod(\n            "CellFacesCount"' in repair
    assert 'GetMethod(\n            "CellFaces"' in repair
    assert 'GetMethod(\n            "PointsOnFace"' in repair
    assert 'GetMethod(\n            "FaceSegment"' in repair
    assert "faceCount <= 8" in repair
    assert "addedForCell >= 2" in repair
    assert 'meshState != "MaxFacesPerCellExceeded"' in generation
    assert "meshAttempt < 6" in generation
    assert "AddMaxFaceMidpointSeeds(" in generation
    assert 'Stage("mesh-points-max-faces-repair-retained")' in generation
    assert '\\"mesh_iterations\\"' in source
    assert '\\"fixes_applied\\"' in source


def test_managed_helper_validates_exact_feature_row_before_attribute_write():
    source = Path(mesh_host.__file__).with_name(
        "RasMapperMeshHelper.cs"
    ).read_text(encoding="utf-8")
    write_block = source.split("private static void WriteMeshDirectly", 1)[1].split(
        "private static void WriteReceipt", 1
    )[0]

    assert 'table.Columns.Contains("FID")' in write_block
    assert 'table.Columns.Contains("Name")' in write_block
    assert '.Where(row => Convert.ToInt32(' in write_block
    assert "targetRows.Count != 1" in write_block
    assert "rowFid != meshFid || rowName != meshName" in write_block
    assert "LayerMeshReferenceMatchesGenerated" in write_block
    assert "VendorManagedCellCountBeforeOverride" in write_block
    assert "FeatureTableTargetValidated = true" in write_block
    assert "CellCountAwareDatatableManager(" in write_block
    assert write_block.index("FeatureTableTargetValidated = true") < write_block.index(
        '"Geometry/2D Flow Areas/Attributes"'
    )


def test_managed_helper_sets_feature_before_mesh_state_flags():
    source = Path(mesh_host.__file__).with_name(
        "RasMapperMeshHelper.cs"
    ).read_text(encoding="utf-8")
    save_block = source.split("if (hdfSaveRequested)", 1)[1].split(
        'Stage("hdf-save-skipped")', 1
    )[0]

    set_feature = save_block.index("setFeature.Invoke")
    row_reference = save_block.index("SetFeatureRowReferenceMatchesGenerated = true")
    set_recomputed = save_block.index('"SetMeshHasBeenRecomputed"')
    set_up_to_date = save_block.index('"SetMeshUpToDate"')
    assert set_feature < row_reference < set_recomputed < set_up_to_date


def test_managed_helper_suppresses_reload_through_direct_write_and_flush():
    source = Path(mesh_host.__file__).with_name(
        "RasMapperMeshHelper.cs"
    ).read_text(encoding="utf-8")
    suppressor_block = source.split(
        "private static ReloadSuppressorHandle CreateReloadSuppressor", 1
    )[1].split("private static object CellCountAwareDatatableManager", 1)[0]
    save_block = source.split("if (hdfSaveRequested)", 1)[1].split(
        'Stage("hdf-save-skipped")', 1
    )[0]
    direct_write_block = source.split(
        "private static void WriteMeshDirectly", 1
    )[1].split("private static void WriteReceipt", 1)[0]

    assert '"RasMapperLib.FeatureTableReloadSuppressor"' in suppressor_block
    assert "BindingFlags.Public | BindingFlags.Instance" in suppressor_block
    assert "suppressor as IDisposable" in suppressor_block

    created = save_block.index("CreateReloadSuppressor(")
    set_feature = save_block.index("setFeature.Invoke")
    returned_row = save_block.index("setFeatureResult as System.Data.DataRow")
    reference_check = save_block.index(
        "updatedRow[persistence.SetFeatureColumnName]"
    )
    direct_write = save_block.index("WriteMeshDirectly(")
    assert created < set_feature < returned_row < reference_check < direct_write

    attribute_write = direct_write_block.index(
        '"Geometry/2D Flow Areas/Attributes"'
    )
    save_mesh = direct_write_block.index("saveMesh.Invoke")
    flush = direct_write_block.index('"Flush"')
    dispose = direct_write_block.index("reloadSuppressor.Dispose()")
    reopen = direct_write_block.index('Stage("validation-reopen-started")')
    assert attribute_write < save_mesh < flush < dispose < reopen
    assert "ReloadSuppressorDisposedBeforeReopen = true" in direct_write_block


def test_managed_helper_emits_reload_suppression_receipt_diagnostics():
    source = Path(mesh_host.__file__).with_name(
        "RasMapperMeshHelper.cs"
    ).read_text(encoding="utf-8")

    for field in (
        "reload_suppressor_created",
        "reload_suppressor_disposed",
        "reload_suppressor_disposed_before_reopen",
        "reload_suppressor_type",
        "set_feature_returned_data_row",
        "set_feature_row_reference_matches_generated",
        "set_feature_column_name",
    ):
        assert field in source


def test_run_managed_mesh_host_returns_content_receipt(monkeypatch, tmp_path):
    executable = tmp_path / "RasMapperMeshHelper.exe"
    executable.touch()
    hdf_path = tmp_path / "model.g01.hdf"
    hdf_path.touch()
    monkeypatch.setattr(
        mesh_host,
        "ensure_managed_mesh_host",
        lambda _hecras_dir: executable,
    )
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["environment"] = kwargs["env"]
        receipt_path = Path(command[-2])
        receipt_path.write_text(
            '{"status":"complete","mesh_state":"Complete",'
            '"seed_count":2,"cell_count":2,"face_count":5,'
            '"refinement_regions":[{"fid":0,"name":"Qualification",'
            '"spacing_dx":50.0,"spacing_dy":50.0,"point_count":5}],'
            '"cell_centers_extracted":true,'
            '"cell_centers":[[10.0,20.0],[30.0,40.0]],'
            '"hdf_save_requested":true,"mesh_saved":true}',
            encoding="utf-8",
        )
        receipt_path.with_name(receipt_path.name + ".progress").write_text(
            "0.1 mesh-complete\n0.2 cell-centers-extracted\n",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="saved", stderr="")

    monkeypatch.setattr(mesh_host.subprocess, "run", fake_run)
    monkeypatch.setattr(mesh_host, "is_wine_runtime", lambda: False)

    receipt = mesh_host.run_managed_mesh_host(
        hdf_path,
        "MainArea",
        tmp_path / "HEC-RAS",
        cell_size=75.0,
        seed_generation_mode="point_generator",
    )

    assert receipt["status"] == "complete"
    assert receipt["cell_count"] == 2
    assert receipt["face_count"] == 5
    assert receipt["mesh_saved"] is True
    assert receipt["refinement_regions"][0]["name"] == "Qualification"
    assert receipt["return_code"] == 0
    assert receipt["attempt_count"] == 1
    assert receipt["stage_trace"][-1].endswith("cell-centers-extracted")
    assert observed["command"][-3] == "75"
    assert observed["command"][-1] == "legacy_save"
    assert observed["environment"]["RAS_MESH_SEED_GENERATION_MODE"] == (
        "point_generator"
    )


def test_run_managed_mesh_host_retries_crashed_clr_process(monkeypatch, tmp_path):
    executable = tmp_path / "RasMapperMeshHelper.exe"
    executable.touch()
    hdf_path = tmp_path / "model.g01.hdf"
    hdf_path.touch()
    monkeypatch.setattr(
        mesh_host,
        "ensure_managed_mesh_host",
        lambda _hecras_dir: executable,
    )
    monkeypatch.setattr(mesh_host, "is_wine_runtime", lambda: True)
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        receipt_path = Path(command[-2])
        progress_path = receipt_path.with_name(receipt_path.name + ".progress")
        progress_path.write_text("0.1 seeds-regenerated\n", encoding="utf-8")
        if len(calls) == 1:
            return SimpleNamespace(returncode=0xC0000005, stdout="", stderr="")
        receipt_path.write_text(
            '{"status":"complete","mesh_state":"Complete",'
            '"seed_count":2,"cell_count":2,"face_count":5,'
            '"cell_centers_extracted":true,'
            '"cell_centers":[[10.0,20.0],[30.0,40.0]],'
            '"hdf_save_requested":false,"mesh_saved":false}',
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mesh_host.subprocess, "run", fake_run)

    receipt = mesh_host.run_managed_mesh_host(
        hdf_path,
        "MainArea",
        tmp_path / "HEC-RAS",
    )

    assert receipt["attempt_count"] == 2
    assert receipt["failed_attempts"][0]["return_code"] == 0xC0000005
    assert receipt["cell_count"] == 2
    assert len(calls) == 2


@pytest.mark.parametrize(
    "exception_name",
    (
        "EntryPointNotFoundException",
        "ArrayTypeMismatchException",
        "NullReferenceException",
        "ArgumentOutOfRangeException",
        "IndexOutOfRangeException",
        "CorruptedWineReceipt",
    ),
)
def test_run_managed_mesh_host_retries_transient_managed_receipt(
    monkeypatch, tmp_path, exception_name
):
    executable = tmp_path / "RasMapperMeshHelper.exe"
    executable.touch()
    hdf_path = tmp_path / "model.g01.hdf"
    hdf_path.touch()
    monkeypatch.setattr(
        mesh_host,
        "ensure_managed_mesh_host",
        lambda _hecras_dir: executable,
    )
    monkeypatch.setattr(mesh_host, "is_wine_runtime", lambda: True)
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        receipt_path = Path(command[-2])
        if len(calls) == 1:
            receipt_path.write_text(
                '{"status":"error","mesh_state":"",'
                '"seed_count":2,"cell_count":0,"face_count":0,'
                f'"error":"System.{exception_name}: transient"}}',
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=99, stdout="", stderr="loader")
        receipt_path.write_text(
            '{"status":"complete","mesh_state":"Complete",'
            '"seed_count":2,"cell_count":2,"face_count":5,'
            '"cell_centers_extracted":true,'
            '"cell_centers":[[10.0,20.0],[30.0,40.0]],'
            '"hdf_save_requested":false,"mesh_saved":false}',
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mesh_host.subprocess, "run", fake_run)

    receipt = mesh_host.run_managed_mesh_host(
        hdf_path,
        "MainArea",
        tmp_path / "HEC-RAS",
    )

    assert receipt["attempt_count"] == 2
    assert exception_name in receipt["failed_attempts"][0][
        "managed_error"
    ]


def test_transactional_hdf_path_preserves_geometry_suffix(tmp_path):
    original = tmp_path / "Project.With.Dots.g09.hdf"

    candidate = mesh_host._transactional_hdf_path(original)

    assert candidate.parent == original.parent
    assert candidate.name.startswith("Project.With.Dots.rascommander-mesh-")
    assert candidate.name.endswith(".g09.hdf")


def test_candidate_inspection_rejects_corrupt_allocated_capacity_row(tmp_path):
    candidate = tmp_path / "model.g01.hdf"
    _write_mesh_candidate(candidate, cell_count=2, face_count=5)
    with h5py.File(candidate, "r+") as hdf:
        hdf["Geometry/2D Flow Areas/MainArea/Cells Center Coordinate"][-1] = (
            np.nan,
            np.nan,
        )

    inspection = mesh_host._inspect_transactional_candidate(
        candidate,
        "MainArea",
        expected_cell_count=2,
        expected_face_count=5,
    )

    assert inspection["center_storage_rows"] == 3
    assert inspection["checks"]["hdf_all_allocated_centers_finite"] is False


def test_candidate_inspection_requires_exact_csr_coverage(tmp_path):
    candidate = tmp_path / "model.g01.hdf"
    _write_mesh_candidate(candidate)
    area_path = "Geometry/2D Flow Areas/MainArea"
    with h5py.File(candidate, "r+") as hdf:
        hdf[f"{area_path}/Cells Face and Orientation Info"][1, 0] += 1
        hdf[f"{area_path}/FacePoints Face and Orientation Info"][1, 0] += 1
        hdf[f"{area_path}/FacePoints Cell Info"][1, 0] += 1
        hdf[f"{area_path}/Faces Perimeter Info"][-1, 0] = 0

    checks = mesh_host._inspect_transactional_candidate(
        candidate, "MainArea", 2, 5
    )["checks"]

    assert checks["hdf_cell_face_csr_contiguous_exact"] is False
    assert checks["hdf_facepoint_face_csr_contiguous_exact"] is False
    assert checks["hdf_facepoint_cell_csr_contiguous_exact"] is False
    assert checks["hdf_face_perimeter_csr_contiguous_exact"] is False


def test_candidate_inspection_requires_exact_face_incidence_cross_references(
    tmp_path,
):
    candidate = tmp_path / "model.g01.hdf"
    _write_mesh_candidate(candidate)
    area_path = "Geometry/2D Flow Areas/MainArea"
    with h5py.File(candidate, "r+") as hdf:
        cell_values = hdf[f"{area_path}/Cells Face and Orientation Values"]
        cell_values[0, 0] = (int(cell_values[0, 0]) + 1) % 5
        point_values = hdf[f"{area_path}/FacePoints Face and Orientation Values"]
        point_values[0, 0] = (int(point_values[0, 0]) + 1) % 5
        face_cells = hdf[f"{area_path}/Faces Cell Indexes"]
        face_cells[0, 1] = face_cells[0, 0]
        face_points = hdf[f"{area_path}/Faces FacePoint Indexes"]
        face_points[0, 1] = face_points[0, 0]

    checks = mesh_host._inspect_transactional_candidate(
        candidate, "MainArea", 2, 5
    )["checks"]

    assert checks["hdf_cell_face_values_twice_per_face"] is False
    assert checks["hdf_cell_face_cross_references_faces"] is False
    assert checks["hdf_facepoint_face_values_twice_per_face"] is False
    assert checks["hdf_facepoint_face_cross_references_faces"] is False
    assert checks["hdf_face_cell_indexes_distinct"] is False
    assert checks["hdf_face_facepoint_indexes_distinct"] is False


def test_candidate_inspection_requires_orientation_specific_face_mapping(
    tmp_path,
):
    candidate = tmp_path / "model.g01.hdf"
    _write_mesh_candidate(candidate)
    area_path = "Geometry/2D Flow Areas/MainArea"
    with h5py.File(candidate, "r+") as hdf:
        for dataset_name in (
            "Cells Face and Orientation Values",
            "FacePoints Face and Orientation Values",
        ):
            values = hdf[f"{area_path}/{dataset_name}"]
            array = values[()]
            array[array[:, 0] == 0, 1] *= -1
            values[...] = array

    checks = mesh_host._inspect_transactional_candidate(
        candidate, "MainArea", 2, 5
    )["checks"]

    assert checks["hdf_cell_face_orientations_opposite"] is True
    assert checks["hdf_facepoint_face_orientations_opposite"] is True
    assert checks["hdf_cell_face_cross_references_faces"] is False
    assert checks["hdf_facepoint_face_cross_references_faces"] is False


def test_candidate_inspection_requires_finite_global_points_closed_perimeter_and_unit_normals(
    tmp_path,
):
    candidate = tmp_path / "model.g01.hdf"
    _write_mesh_candidate(candidate)
    area_path = "Geometry/2D Flow Areas/MainArea"
    with h5py.File(candidate, "r+") as hdf:
        hdf["Geometry/2D Flow Areas/Cell Points"][0, 0] = np.nan
        hdf[f"{area_path}/Perimeter"][-1] = (2.0, 2.0)
        hdf[f"{area_path}/Faces NormalUnitVector and Length"][0, :2] = (
            2.0,
            0.0,
        )

    checks = mesh_host._inspect_transactional_candidate(
        candidate, "MainArea", 2, 5
    )["checks"]

    assert checks["hdf_global_cell_points_finite"] is False
    assert checks["hdf_perimeter_closed"] is False
    assert checks["hdf_face_normal_xy_unit_length"] is False


def test_candidate_inspection_allows_zero_seed_range_for_other_area(tmp_path):
    candidate = tmp_path / "model.g01.hdf"
    _write_mesh_candidate(candidate)
    with h5py.File(candidate, "r+") as hdf:
        root = hdf["Geometry/2D Flow Areas"]
        del root["Attributes"]
        attributes_dtype = np.dtype([("Name", "S16"), ("Cell Count", "i4")])
        root.create_dataset(
            "Attributes",
            data=np.array(
                [(b"MainArea", 2), (b"UnmeshedArea", 0)],
                dtype=attributes_dtype,
            ),
        )
        del root["Cell Info"]
        root.create_dataset(
            "Cell Info",
            data=np.array([[0, 2], [2, 0]], dtype="i4"),
        )

    checks = mesh_host._inspect_transactional_candidate(
        candidate, "MainArea", 2, 5
    )["checks"]

    assert checks["hdf_global_cell_info_contiguous_exact"] is True


def test_candidate_inspection_records_intermediate_area_name_width(tmp_path):
    candidate = tmp_path / "model.g01.hdf"
    _write_mesh_candidate(candidate)
    with h5py.File(candidate, "r+") as hdf:
        root = hdf["Geometry/2D Flow Areas"]
        rows = root["Attributes"][()]
        del root["Attributes"]
        short_dtype = np.dtype([("Name", "S11"), ("Cell Count", "i4")])
        root.create_dataset(
            "Attributes",
            data=np.array(
                [(row["Name"], row["Cell Count"]) for row in rows],
                dtype=short_dtype,
            ),
        )

    inspection = mesh_host._inspect_transactional_candidate(
        candidate, "MainArea", 2, 5
    )

    assert inspection["attributes_name_width"] == 11
    assert inspection["checks"]["hdf_attributes_name_width_supported"] is True


def test_candidate_inspection_accepts_vendor_empty_face_perimeter_encoding(
    tmp_path,
):
    candidate = tmp_path / "model.g01.hdf"
    _write_mesh_candidate(candidate, empty_face_perimeter=True)

    checks = mesh_host._inspect_transactional_candidate(
        candidate, "MainArea", 2, 5
    )["checks"]

    assert checks["hdf_face_perimeter_values_shape"] is True
    assert checks["hdf_face_perimeter_empty_encoding_consistent"] is True
    assert checks["hdf_face_perimeter_csr_contiguous_exact"] is True
    assert all(checks.values())


def test_candidate_inspection_rejects_inconsistent_empty_face_perimeter_encoding(
    tmp_path,
):
    candidate = tmp_path / "model.g01.hdf"
    _write_mesh_candidate(candidate, empty_face_perimeter=True)
    with h5py.File(candidate, "r+") as hdf:
        info = hdf[
            "Geometry/2D Flow Areas/MainArea/Faces Perimeter Info"
        ]
        info[0] = (0, 1)

    checks = mesh_host._inspect_transactional_candidate(
        candidate, "MainArea", 2, 5
    )["checks"]

    assert checks["hdf_face_perimeter_empty_encoding_consistent"] is False
    assert checks["hdf_face_perimeter_csr_contiguous_exact"] is False


def test_transactional_direct_replaces_only_exact_reopened_topology(
    monkeypatch, tmp_path
):
    executable = tmp_path / "RasMapperMeshHelper.exe"
    executable.touch()
    hdf_path = tmp_path / "model.g01.hdf"
    hdf_path.write_bytes(b"original")
    monkeypatch.setattr(
        mesh_host,
        "ensure_managed_mesh_host",
        lambda _hecras_dir: executable,
    )
    monkeypatch.setattr(mesh_host, "is_wine_runtime", lambda: False)
    observed = {}

    def fake_run(command, **_kwargs):
        candidate = Path(command[2])
        observed["candidate"] = candidate
        observed["mode"] = command[-1]
        _write_mesh_candidate(candidate)
        expected_bytes = candidate.read_bytes()
        observed["expected_bytes"] = expected_bytes
        receipt_path = Path(command[-2])
        receipt_path.write_text(
            '{"status":"complete","mesh_state":"Complete",'
            '"seed_count":2,"cell_count":2,"face_count":5,'
            '"cell_centers_extracted":true,'
            '"cell_centers":[[10.0,20.0],[30.0,40.0]],'
            '"hdf_persistence_mode":"transactional_direct",'
            '"hdf_save_requested":true,"mesh_saved":true,'
            '"feature_table_written":true,'
            '"mesh_points_set_feature_row_reference_matches_generated":true,'
            '"mesh_points_feature_table_written":true,'
            '"feature_table_restored_after_mesh_points":true,'
            '"save_mesh_parameter_count":5,'
            '"reopened_topology_validated":true,'
            '"reopened_centers_validated":true,'
            '"reopened_center_max_abs_error":0.0,'
            '"reopened_cell_count":2,"reopened_face_count":5}',
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mesh_host.subprocess, "run", fake_run)

    receipt = mesh_host.run_managed_mesh_host(
        hdf_path,
        "MainArea",
        tmp_path / "HEC-RAS",
        persistence_mode="transactional_direct",
        expected_cell_count=2,
        expected_face_count=5,
    )

    assert observed["candidate"].parent == hdf_path.parent
    assert observed["candidate"].name.endswith(".g01.hdf")
    assert observed["mode"] == "transactional_direct"
    assert hdf_path.read_bytes() == observed["expected_bytes"]
    assert receipt["transactional_replace_completed"] is True
    assert all(receipt["transactional_topology_checks"].values())
    inspection = receipt["transactional_hdf_inspection"]
    assert inspection["center_max_abs_error"] == 0.0
    assert inspection["generated_center_fingerprint"] == (
        inspection["candidate_center_fingerprint"]
    )
    assert receipt["transaction_lock"]["released"] is True
    assert not mesh_host._transaction_lock_path(hdf_path).exists()
    assert not observed["candidate"].exists()


def test_transactional_direct_recovers_exact_checkpoint_after_clr_reopen_crash(
    monkeypatch, tmp_path
):
    executable = tmp_path / "RasMapperMeshHelper.exe"
    executable.touch()
    hdf_path = tmp_path / "model.g01.hdf"
    hdf_path.write_bytes(b"original")
    monkeypatch.setattr(
        mesh_host,
        "ensure_managed_mesh_host",
        lambda _hecras_dir: executable,
    )
    monkeypatch.setattr(mesh_host, "is_wine_runtime", lambda: False)

    def fake_run(command, **_kwargs):
        candidate = Path(command[2])
        _write_mesh_candidate(candidate)
        receipt_path = Path(command[-2])
        receipt_path.write_text(
            # A fatal callback on another CLR thread can overwrite the durable
            # persisted-awaiting-validation receipt after its checkpoint was
            # emitted. The parent must key recovery to the durable stage trace
            # and independently validated candidate, not the final status word.
            '{"status":"error",'
            '"mesh_state":"Complete","seed_count":2,'
            '"cell_count":2,"face_count":5,'
            '"cell_centers_extracted":true,'
            '"cell_centers":[[10.0,20.0],[30.0,40.0]],'
            '"hdf_persistence_mode":"transactional_direct",'
            '"hdf_save_requested":true,"mesh_saved":true,'
            '"feature_table_written":true,'
            '"mesh_points_set_feature_row_reference_matches_generated":true,'
            '"mesh_points_feature_table_written":true,'
            '"feature_table_restored_after_mesh_points":true}',
            encoding="utf-8",
        )
        receipt_path.with_name(receipt_path.name + ".progress").write_text(
            "1.0 mesh-save-completed\n"
            "1.1 writer-closed\n"
            "1.2 feature-table-reload-suppressor-disposed\n"
            "1.3 validation-checkpoint-written\n"
            "1.4 validation-reopen-started\n",
            encoding="utf-8",
        )
        return SimpleNamespace(
            returncode=5,
            stdout="",
            stderr="CLR crashed while reopening persisted mesh",
        )

    monkeypatch.setattr(mesh_host.subprocess, "run", fake_run)

    receipt = mesh_host.run_managed_mesh_host(
        hdf_path,
        "MainArea",
        tmp_path / "HEC-RAS",
        persistence_mode="transactional_direct",
        expected_cell_count=2,
        expected_face_count=5,
    )

    assert receipt["status"] == "complete"
    assert receipt["checkpoint_recovery_attempted"] is True
    assert receipt["checkpoint_recovery_completed"] is True
    assert receipt["transactional_replace_completed"] is True
    assert receipt["reopened_cell_count"] == 2
    assert receipt["reopened_face_count"] == 5
    assert all(receipt["transactional_topology_checks"].values())


def test_transactional_direct_recovers_exact_candidate_after_save_crash(
    monkeypatch, tmp_path
):
    executable = tmp_path / "RasMapperMeshHelper.exe"
    executable.touch()
    hdf_path = tmp_path / "model.g01.hdf"
    hdf_path.write_bytes(b"original")
    monkeypatch.setattr(
        mesh_host,
        "ensure_managed_mesh_host",
        lambda _hecras_dir: executable,
    )
    monkeypatch.setattr(mesh_host, "is_wine_runtime", lambda: False)

    def fake_run(command, **_kwargs):
        candidate = Path(command[2])
        _write_mesh_candidate(candidate)
        receipt_path = Path(command[-2])
        receipt_path.write_text(
            '{"status":"generated-awaiting-persistence",'
            '"mesh_state":"Complete","seed_count":2,'
            '"cell_count":2,"face_count":5,'
            '"cell_centers_extracted":true,'
            '"cell_centers":[[10.0,20.0],[30.0,40.0]],'
            '"hdf_persistence_mode":"transactional_direct",'
            '"hdf_save_requested":true,"mesh_saved":false,'
            '"feature_table_written":true,'
            '"mesh_points_set_feature_row_reference_matches_generated":true,'
            '"mesh_points_feature_table_written":true,'
            '"feature_table_restored_after_mesh_points":true}',
            encoding="utf-8",
        )
        receipt_path.with_name(receipt_path.name + ".progress").write_text(
            "1.0 feature-table-written\n"
            "1.1 persistence-attempt-checkpoint-written\n"
            "1.2 mesh-save-overload-5\n",
            encoding="utf-8",
        )
        return SimpleNamespace(
            returncode=5,
            stdout="",
            stderr="CLR crashed in SaveMesh after writing the candidate",
        )

    monkeypatch.setattr(mesh_host.subprocess, "run", fake_run)

    receipt = mesh_host.run_managed_mesh_host(
        hdf_path,
        "MainArea",
        tmp_path / "HEC-RAS",
        persistence_mode="transactional_direct",
        expected_cell_count=2,
        expected_face_count=5,
    )

    assert receipt["status"] == "complete"
    assert receipt["save_interruption_recovery_attempted"] is True
    assert receipt["save_interruption_recovery_completed"] is True
    assert receipt["mesh_saved"] is True
    assert receipt["transactional_replace_completed"] is True
    assert receipt["reopened_cell_count"] == 2
    assert receipt["reopened_face_count"] == 5
    assert all(receipt["transactional_topology_checks"].values())


def test_transactional_direct_discards_topology_mismatch(monkeypatch, tmp_path):
    executable = tmp_path / "RasMapperMeshHelper.exe"
    executable.touch()
    hdf_path = tmp_path / "model.g01.hdf"
    hdf_path.write_bytes(b"original")
    monkeypatch.setattr(
        mesh_host,
        "ensure_managed_mesh_host",
        lambda _hecras_dir: executable,
    )
    monkeypatch.setattr(mesh_host, "is_wine_runtime", lambda: False)
    candidates = []

    def fake_run(command, **_kwargs):
        candidate = Path(command[2])
        candidates.append(candidate)
        _write_mesh_candidate(candidate, face_count=4)
        Path(command[-2]).write_text(
            '{"status":"complete","mesh_state":"Complete",'
            '"seed_count":2,"cell_count":2,"face_count":5,'
            '"cell_centers_extracted":true,'
            '"cell_centers":[[10.0,20.0],[30.0,40.0]],'
            '"hdf_persistence_mode":"transactional_direct",'
            '"hdf_save_requested":true,"mesh_saved":true,'
            '"feature_table_written":true,'
            '"mesh_points_set_feature_row_reference_matches_generated":true,'
            '"mesh_points_feature_table_written":true,'
            '"feature_table_restored_after_mesh_points":true,'
            '"reopened_topology_validated":true,'
            '"reopened_centers_validated":true,'
            '"reopened_center_max_abs_error":0.0,'
            '"reopened_cell_count":2,"reopened_face_count":4}',
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mesh_host.subprocess, "run", fake_run)

    receipt = mesh_host.run_managed_mesh_host(
        hdf_path,
        "MainArea",
        tmp_path / "HEC-RAS",
        persistence_mode="transactional_direct",
        expected_cell_count=2,
        expected_face_count=5,
    )

    assert receipt["status"] == "error"
    assert receipt["transactional_replace_completed"] is False
    assert hdf_path.read_bytes() == b"original"
    assert candidates and not candidates[0].exists()


def test_transactional_direct_discards_stale_matching_count_centers(
    monkeypatch, tmp_path
):
    executable = tmp_path / "RasMapperMeshHelper.exe"
    executable.touch()
    hdf_path = tmp_path / "model.g01.hdf"
    hdf_path.write_bytes(b"original")
    monkeypatch.setattr(
        mesh_host,
        "ensure_managed_mesh_host",
        lambda _hecras_dir: executable,
    )
    monkeypatch.setattr(mesh_host, "is_wine_runtime", lambda: False)

    def fake_run(command, **_kwargs):
        _write_mesh_candidate(
            Path(command[2]),
            logical_centers=[[10.01, 20.0], [30.0, 40.0]],
        )
        Path(command[-2]).write_text(
            '{"status":"complete","mesh_state":"Complete",'
            '"seed_count":2,"cell_count":2,"face_count":5,'
            '"cell_centers_extracted":true,'
            '"cell_centers":[[10.0,20.0],[30.0,40.0]],'
            '"hdf_persistence_mode":"transactional_direct",'
            '"hdf_save_requested":true,"mesh_saved":true,'
            '"feature_table_written":true,'
            '"mesh_points_set_feature_row_reference_matches_generated":true,'
            '"mesh_points_feature_table_written":true,'
            '"feature_table_restored_after_mesh_points":true,'
            '"reopened_topology_validated":true,'
            '"reopened_centers_validated":true,'
            '"reopened_center_max_abs_error":0.0,'
            '"reopened_cell_count":2,"reopened_face_count":5}',
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mesh_host.subprocess, "run", fake_run)

    receipt = mesh_host.run_managed_mesh_host(
        hdf_path,
        "MainArea",
        tmp_path / "HEC-RAS",
        persistence_mode="transactional_direct",
        expected_cell_count=2,
        expected_face_count=5,
    )

    inspection = receipt["transactional_hdf_inspection"]
    assert receipt["status"] == "error"
    assert receipt["transactional_replace_completed"] is False
    assert inspection["center_max_abs_error"] == pytest.approx(0.01)
    assert inspection["generated_center_fingerprint"] != (
        inspection["candidate_center_fingerprint"]
    )
    assert inspection["checks"][
        "hdf_generated_centers_match_candidate_ordered"
    ] is False
    assert hdf_path.read_bytes() == b"original"


def test_transactional_direct_timeout_leaves_original_unchanged(
    monkeypatch, tmp_path
):
    executable = tmp_path / "RasMapperMeshHelper.exe"
    executable.touch()
    hdf_path = tmp_path / "model.g01.hdf"
    hdf_path.write_bytes(b"original")
    monkeypatch.setattr(
        mesh_host,
        "ensure_managed_mesh_host",
        lambda _hecras_dir: executable,
    )
    monkeypatch.setattr(mesh_host, "is_wine_runtime", lambda: False)
    monkeypatch.setattr(
        mesh_host,
        "_bounded_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            mesh_host.subprocess.TimeoutExpired(args[0], kwargs["timeout"])
        ),
    )

    with pytest.raises(RuntimeError, match="exhausted 1 isolated attempts"):
        mesh_host.run_managed_mesh_host(
            hdf_path,
            "MainArea",
            tmp_path / "HEC-RAS",
            persistence_mode="transactional_direct",
            expected_cell_count=2,
            expected_face_count=5,
            max_attempts=1,
        )

    assert hdf_path.read_bytes() == b"original"
    assert not list(tmp_path.glob("*.rascommander-mesh-*.g01.hdf"))
    assert not mesh_host._transaction_lock_path(hdf_path).exists()


def test_transactional_direct_refuses_concurrent_original_change(
    monkeypatch, tmp_path
):
    executable = tmp_path / "RasMapperMeshHelper.exe"
    executable.touch()
    hdf_path = tmp_path / "model.g01.hdf"
    hdf_path.write_bytes(b"original")
    monkeypatch.setattr(
        mesh_host,
        "ensure_managed_mesh_host",
        lambda _hecras_dir: executable,
    )
    monkeypatch.setattr(mesh_host, "is_wine_runtime", lambda: False)

    def fake_run(command, **_kwargs):
        _write_mesh_candidate(Path(command[2]))
        hdf_path.write_bytes(b"concurrent owner")
        Path(command[-2]).write_text(
            '{"status":"complete","mesh_state":"Complete",'
            '"seed_count":2,"cell_count":2,"face_count":5,'
            '"cell_centers_extracted":true,'
            '"cell_centers":[[10.0,20.0],[30.0,40.0]],'
            '"hdf_persistence_mode":"transactional_direct",'
            '"hdf_save_requested":true,"mesh_saved":true,'
            '"feature_table_written":true,'
            '"mesh_points_set_feature_row_reference_matches_generated":true,'
            '"mesh_points_feature_table_written":true,'
            '"feature_table_restored_after_mesh_points":true,'
            '"reopened_topology_validated":true,'
            '"reopened_centers_validated":true,'
            '"reopened_center_max_abs_error":0.0,'
            '"reopened_cell_count":2,"reopened_face_count":5}',
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mesh_host.subprocess, "run", fake_run)

    receipt = mesh_host.run_managed_mesh_host(
        hdf_path,
        "MainArea",
        tmp_path / "HEC-RAS",
        persistence_mode="transactional_direct",
        expected_cell_count=2,
        expected_face_count=5,
    )

    assert receipt["status"] == "error"
    assert "changed during transactional" in receipt["error"]
    assert receipt["transactional_replace_completed"] is False
    assert hdf_path.read_bytes() == b"concurrent owner"
    assert not list(tmp_path.glob("*.rascommander-mesh-*.g01.hdf"))


def test_transactional_direct_fails_closed_when_cooperative_lock_exists(
    monkeypatch, tmp_path
):
    hdf_path = tmp_path / "model.g01.hdf"
    hdf_path.write_bytes(b"original")
    lock_path = mesh_host._transaction_lock_path(hdf_path)
    lock_path.write_text(
        '{"process_id":42,"mesh_name":"OtherArea",'
        '"started_utc":"2026-07-19T00:00:00+00:00"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        mesh_host,
        "ensure_managed_mesh_host",
        lambda _hecras_dir: pytest.fail("locked transaction must not start"),
    )

    with pytest.raises(RuntimeError, match="lock is already held"):
        mesh_host.run_managed_mesh_host(
            hdf_path,
            "MainArea",
            tmp_path / "HEC-RAS",
            persistence_mode="transactional_direct",
            expected_cell_count=2,
            expected_face_count=5,
        )

    assert hdf_path.read_bytes() == b"original"
    assert lock_path.exists()


def test_transactional_direct_refuses_replace_after_lock_ownership_changes(
    monkeypatch, tmp_path
):
    executable = tmp_path / "RasMapperMeshHelper.exe"
    executable.touch()
    hdf_path = tmp_path / "model.g01.hdf"
    hdf_path.write_bytes(b"original")
    lock_path = mesh_host._transaction_lock_path(hdf_path)
    monkeypatch.setattr(
        mesh_host,
        "ensure_managed_mesh_host",
        lambda _hecras_dir: executable,
    )
    monkeypatch.setattr(mesh_host, "is_wine_runtime", lambda: False)

    def fake_run(command, **_kwargs):
        _write_mesh_candidate(Path(command[2]))
        Path(command[-2]).write_text(
            '{"status":"complete","mesh_state":"Complete",'
            '"seed_count":2,"cell_count":2,"face_count":5,'
            '"cell_centers_extracted":true,'
            '"cell_centers":[[10.0,20.0],[30.0,40.0]],'
            '"hdf_persistence_mode":"transactional_direct",'
            '"hdf_save_requested":true,"mesh_saved":true,'
            '"feature_table_written":true,'
            '"mesh_points_set_feature_row_reference_matches_generated":true,'
            '"mesh_points_feature_table_written":true,'
            '"feature_table_restored_after_mesh_points":true,'
            '"reopened_topology_validated":true,'
            '"reopened_centers_validated":true,'
            '"reopened_center_max_abs_error":0.0,'
            '"reopened_cell_count":2,"reopened_face_count":5}',
            encoding="utf-8",
        )
        lock_path.write_text(
            '{"token":"replacement-owner","process_id":99}',
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mesh_host.subprocess, "run", fake_run)

    receipt = mesh_host.run_managed_mesh_host(
        hdf_path,
        "MainArea",
        tmp_path / "HEC-RAS",
        persistence_mode="transactional_direct",
        expected_cell_count=2,
        expected_face_count=5,
    )

    assert receipt["status"] == "error"
    assert "lock ownership changed" in receipt["error"]
    assert receipt["transactional_replace_completed"] is False
    assert receipt["transaction_lock"]["released"] is False
    assert hdf_path.read_bytes() == b"original"
    assert lock_path.exists()
    assert "replacement-owner" in lock_path.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.rascommander-mesh-*.g01.hdf"))
