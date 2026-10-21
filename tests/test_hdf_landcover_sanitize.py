"""Focused tests for native HEC-RAS 6.6 land-cover label sanitization."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from ras_commander._landcover_native import (
    _companion_tiff_transaction,
    _qualified_sanitize_version,
    _sidecar_transaction,
    _validate_sanitized_classifications,
    sanitize_landcover_classification_names,
)
from ras_commander.hdf.HdfLandCover import HdfLandCover


class _NativeLandCoverNames:
    @staticmethod
    def IsValidClassificationName(name: str) -> bool:
        return bool(name) and "/" not in name and "\\" not in name and name != "NoData"


def _class_row(name: str, mannings_n: float | None) -> dict[str, object]:
    return {"name": name, "parameters": {"ManningsN": mannings_n}}


def test_sanitize_requires_exact_qualified_version_before_native_load() -> None:
    assert _qualified_sanitize_version("6.6") == "6.6"
    assert _qualified_sanitize_version("6.6.0") == "6.6"
    for version in ("5.0.7", "6.5", "6.6.1", "7.0", "not-a-version"):
        with pytest.raises(NotImplementedError, match="only for HEC-RAS 6.6"):
            _qualified_sanitize_version(version)

    # Version qualification occurs before the function resolves files or loads
    # pythonnet/RASMapperLib.
    with pytest.raises(NotImplementedError, match="only for HEC-RAS 6.6"):
        sanitize_landcover_classification_names(
            Path("missing.hdf"),
            raster_path=Path("missing.tif"),
            hecras_version="7.0",
        )


def test_sanitized_class_validation_keeps_ids_and_parameters() -> None:
    before = {
        0: _class_row("NoData", None),
        19: _class_row("Hay/Pasture", 0.15),
        27: _class_row("Shrub/Scrub", 0.1),
    }
    after = {
        0: _class_row("NoData", None),
        19: _class_row("Hay-Pasture", 0.15),
        27: _class_row("Shrub-Scrub", 0.1),
    }

    renames = _validate_sanitized_classifications(
        before,
        after,
        _NativeLandCoverNames,
    )

    assert renames == [
        {"class_id": 19, "old_name": "Hay/Pasture", "new_name": "Hay-Pasture"},
        {"class_id": 27, "old_name": "Shrub/Scrub", "new_name": "Shrub-Scrub"},
    ]


def test_sidecar_and_tiff_transactions_restore_both_files(tmp_path: Path) -> None:
    hdf_path = tmp_path / "Mannings_n.hdf"
    tiff_path = tmp_path / "Mannings_n.tif"
    hdf_path.write_bytes(b"original sidecar")
    tiff_path.write_bytes(b"original tiff")

    with pytest.raises(RuntimeError, match="intentional failure"):
        with _sidecar_transaction(hdf_path):
            with _companion_tiff_transaction(tiff_path):
                hdf_path.write_bytes(b"changed sidecar")
                tiff_path.write_bytes(b"changed tiff")
                raise RuntimeError("intentional failure")

    assert hdf_path.read_bytes() == b"original sidecar"
    assert tiff_path.read_bytes() == b"original tiff"
    assert list(tmp_path.glob("Mannings_n.native_parameters.*.backup.hdf"))


@pytest.mark.skipif(
    not os.environ.get("RAS_COMMANDER_LANDCOVER_SANITIZE_SOURCE"),
    reason="set RAS_COMMANDER_LANDCOVER_SANITIZE_SOURCE to a disposable-copy source HDF",
)
def test_native_66_sanitizes_disposable_legacy_sidecar(
    tmp_path: Path,
) -> None:
    """Qualify the native V1-to-V2 path without modifying the supplied source."""
    source_hdf = Path(os.environ["RAS_COMMANDER_LANDCOVER_SANITIZE_SOURCE"])
    source_tiff = source_hdf.with_suffix(".tif")
    assert source_hdf.exists()
    assert source_tiff.exists()
    target_hdf = tmp_path / source_hdf.name
    target_tiff = tmp_path / source_tiff.name
    shutil.copy2(source_hdf, target_hdf)
    shutil.copy2(source_tiff, target_tiff)

    result = HdfLandCover.sanitize_classification_names(
        target_hdf,
        raster_path=target_tiff,
        hecras_version="6.6",
    )

    assert result.schema_version_before == "1.0"
    assert result.schema_version_after == "2.0"
    assert result.class_ids == tuple(range(31))
    assert result.tiff_sha256_before == result.tiff_sha256_after
    assert result.classes_before[0]["name"] == "NoData"
    assert result.classes_after[0]["name"] == "NoData"
    assert result.renames == (
        {"class_id": 19, "old_name": "Hay/Pasture", "new_name": "Hay-Pasture"},
        {
            "class_id": 20,
            "old_name": "Hay/Pasture - Stream",
            "new_name": "Hay-Pasture - Stream",
        },
        {"class_id": 27, "old_name": "Shrub/Scrub", "new_name": "Shrub-Scrub"},
        {
            "class_id": 28,
            "old_name": "Shrub/Scrub - Stream",
            "new_name": "Shrub-Scrub - Stream",
        },
    )
