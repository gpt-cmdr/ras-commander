"""A property-table recompute must prove that RASMapper rewrote every 2D area.

``ComputePropertyTablesCommand`` exits 0 when it refuses an area (for example,
a land-cover layer whose raster is missing). It reports the reason and keeps
the area's previous tables, which still pass the structural non-empty check.
The geometry HDF's ``File Version`` is no signal: the command does not restamp
it, even after a successful recompute. The per-area completion line is.
"""

import shutil
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

import ras_commander._landcover_native as native

# Output recorded from HEC-RAS 7.0.1 (BaldEagleCrkMulti2D g09).
_COMPLETED = """\
HDF.PInvoke identity verified: C:\\HEC-RAS\\7.0.1\\bin64\\hdf5.dll (module 0x1)
Computing 2D Flow Area '{name}' tables: Mesh property tables are current.
LAYER=Processing 2D Face Profiles (1/4) ({name})
PROGRESS=0.5
LAYER=2D Face Profiles Time (1/4): 8.82 sec ({name})
LAYER=2D Cell Tables time (4/4): 8.68 sec ({name})
2D Flow Area '{name}' tables complete 20.84 sec
"""
# Refusal written to stdout (raster of the associated land cover removed).
_REFUSED_STDOUT = """\
HDF.PInvoke identity verified: C:\\HEC-RAS\\7.0.1\\bin64\\hdf5.dll (module 0x1)
WARNING: NOTE! {name}: Cannot recompute 2D property tables because: Land Cover file(s) are missing.
Infiltration file(s) are missing.
Percent Impervious file(s) are missing.
Existing tables appear to match this geometry, so we'll use those.
"""
# Refusal written to stderr (observed on a HEC-RAS 6.5 geometry HDF).
_REFUSED_STDERR = """\
{name}: Cannot recompute 2D property tables because: Land Cover file(s) are missing.
Percent Impervious file(s) are missing.
Existing tables DO NOT match this geometry because: Associated terrain has been updated.
"""


def _geometry_with_stale_tables(path: Path, areas=("Upper", "Lower")) -> Path:
    """Complete geometry whose areas already hold non-empty tables."""
    with h5py.File(path, "w") as hdf:
        hdf.attrs["File Version"] = np.bytes_(b"HEC-RAS 6.5 February 2024")
        geometry = hdf.create_group("Geometry")
        geometry.attrs["Complete Geometry"] = np.bytes_(b"True")
        flow_areas = geometry.create_group("2D Flow Areas")
        flow_areas.create_dataset("Attributes", data=np.zeros(len(areas)))
        for name in areas:
            area = flow_areas.create_group(name)
            for table in (
                "Cells Volume Elevation Info",
                "Cells Volume Elevation Values",
                "Faces Area Elevation Info",
                "Faces Area Elevation Values",
            ):
                area.create_dataset(table, data=np.ones((2, 2)))
    return path


@pytest.mark.synthetic_hdf_layout
def test_every_area_reported_complete_passes(tmp_path):
    geometry = _geometry_with_stale_tables(tmp_path / "model.g01.hdf")
    stdout = _COMPLETED.format(name="Upper") + _COMPLETED.format(name="Lower")
    native._require_native_recompute_of_every_2d_area(geometry, stdout, "")


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_refused_area_fails_with_native_reason(tmp_path, stream):
    geometry = _geometry_with_stale_tables(tmp_path / "model.g01.hdf")
    refused = (_REFUSED_STDOUT if stream == "stdout" else _REFUSED_STDERR).format(
        name="Lower"
    )
    stdout = _COMPLETED.format(name="Upper")
    stderr = ""
    if stream == "stdout":
        stdout += refused
    else:
        stderr = refused
    with pytest.raises(RuntimeError) as error:
        native._require_native_recompute_of_every_2d_area(geometry, stdout, stderr)
    message = str(error.value)
    assert "returned without recomputing 2D flow area(s) 'Lower'" in message
    assert "'Upper'" not in message
    assert "Land Cover file(s) are missing." in message
    assert "Percent Impervious file(s) are missing." in message
    # The structural check alone accepts these stale tables.
    native._validate_property_tables_postcondition(geometry)


@pytest.mark.synthetic_hdf_layout
def test_silent_return_without_completion_fails(tmp_path):
    geometry = _geometry_with_stale_tables(tmp_path / "model.g01.hdf", ("Only",))
    with pytest.raises(RuntimeError, match="no completion and no reason"):
        native._require_native_recompute_of_every_2d_area(
            geometry, "HDF.PInvoke identity verified: x\n", ""
        )


@pytest.mark.synthetic_hdf_layout
def test_area_name_with_apostrophe_and_crlf(tmp_path):
    geometry = _geometry_with_stale_tables(tmp_path / "model.g01.hdf", ("Bob's Bay",))
    stdout = _COMPLETED.format(name="Bob's Bay").replace("\n", "\r\n")
    native._require_native_recompute_of_every_2d_area(geometry, stdout, "")


@pytest.mark.synthetic_hdf_layout
def test_geometry_without_2d_areas_needs_no_report(tmp_path):
    geometry = tmp_path / "model.g01.hdf"
    with h5py.File(geometry, "w") as hdf:
        hdf.create_group("Geometry").create_group("Cross Sections")
    native._require_native_recompute_of_every_2d_area(geometry, "", "")


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("refused", [False, True])
def test_recompute_property_tables_rejects_stale_success(
    tmp_path, monkeypatch, refused
):
    mapper = tmp_path / "model.rasmap"
    mapper.touch()
    geometry = _geometry_with_stale_tables(tmp_path / "model.g01.hdf")
    stdout = _COMPLETED.format(name="Upper") + (
        _REFUSED_STDOUT.format(name="Lower")
        if refused
        else _COMPLETED.format(name="Lower")
    )
    monkeypatch.setattr(native, "find_hecras_install", lambda version: tmp_path)
    monkeypatch.setattr(
        native,
        "_run_property_tables_worker",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
    )
    def call():
        return native.recompute_property_tables(
            rasmap_path=mapper, geometry_hdf_path=geometry, hecras_version="7.0.1"
        )

    if refused:
        with pytest.raises(RuntimeError, match="'Lower'"):
            call()
    else:
        assert call() == native.RasUtils.safe_resolve(geometry)


def _hecras_701():
    from ras_commander.dotnet.clr_bootstrap import find_hecras_install

    try:
        install = find_hecras_install("7.0.1")
    except FileNotFoundError:
        pytest.skip("HEC-RAS 7.0.1 is not installed")
    if not (install / "RasMapperLib.dll").exists():
        pytest.skip("HEC-RAS 7.0.1 RasMapperLib is not installed")
    return install


@pytest.mark.integration
@pytest.mark.real_ras
@pytest.mark.destructive_copy
def test_real_recompute_refusal_on_pre_701_geometry_raises(tmp_path):
    """BaldEagleCrkMulti2D g09 (a HEC-RAS 6.2 geometry HDF) with its land-cover
    raster removed: HEC-RAS 7.0.1 refuses the area, exits 0 and keeps the old
    tables. Before the fix this call returned success."""
    if native.os.name != "nt":
        pytest.skip("Native RASMapper property tables require Windows")
    pytest.importorskip("clr")
    _hecras_701()
    from ras_commander import RasExamples, RasMap

    try:
        project = RasExamples.extract_project(
            "BaldEagleCrkMulti2D", output_path=tmp_path / "src"
        )
    except Exception as exc:  # download or archive unavailable
        pytest.skip(f"BaldEagleCrkMulti2D example unavailable: {exc}")
    geometry_hdf = project / "BaldEagleDamBrk.g09.hdf"
    with h5py.File(geometry_hdf, "r") as hdf:
        file_version = hdf.attrs["File Version"]
        assert not bytes(file_version).startswith(b"HEC-RAS 7.0.1")
        tables = "Geometry/2D Flow Areas/BaldEagleCr/Cells Volume Elevation Values"
        assert hdf[tables].size > 0  # stale tables that pass the structural check
    raster = project / "Land Classification" / "LandCover.tif"
    hidden = raster.with_name(raster.name + ".hidden")
    raster.rename(hidden)

    with pytest.raises(RuntimeError) as error:
        RasMap.recompute_property_tables(
            project, project / "BaldEagleDamBrk.g09", hecras_version="7.0.1"
        )
    message = str(error.value)
    assert "returned without recomputing 2D flow area(s) 'BaldEagleCr'" in message
    assert "Land Cover file(s) are missing." in message

    # With its raster back, the same disposable copy recomputes and passes.
    hidden.rename(raster)
    RasMap.recompute_property_tables(
        project, project / "BaldEagleDamBrk.g09", hecras_version="7.0.1"
    )
    with h5py.File(geometry_hdf, "r") as hdf:
        # The command does not restamp the file version; it is not the signal.
        assert hdf.attrs["File Version"] == file_version
    shutil.rmtree(tmp_path / "src", ignore_errors=True)
