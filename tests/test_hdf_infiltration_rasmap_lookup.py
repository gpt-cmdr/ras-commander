"""Tests for status-aware implicit infiltration HDF path resolution."""

from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander._rasmap_schema import create_rasmap_dataframe
from ras_commander.hdf import HdfInfiltration


def _write_infiltration_hdf(path: Path) -> Path:
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset(
            "Raster Map",
            data=np.array(
                [(1, b"100"), (2, b"200")],
                dtype=[("raster_value", "i4"), ("mukey", "S16")],
            ),
        )
        hdf.create_dataset(
            "Infiltration Parameters",
            data=np.array(
                [(b"100", 0.25, 0.10, 12.0)],
                dtype=[
                    ("mukey", "S16"),
                    ("initial_loss", "f8"),
                    ("constant_loss_rate", "f8"),
                    ("impervious_area", "f8"),
                ],
            ),
        )
    return path


def _call(method_name: str, ras_object, hdf_path: Path | None = None):
    method = getattr(HdfInfiltration, method_name)
    kwargs = {"hdf_path": hdf_path, "ras_object": ras_object}
    if method_name == "get_infiltration_parameters":
        kwargs["mukey"] = "100"
    return method(**kwargs)


@pytest.mark.parametrize(
    "method_name",
    ["get_infiltration_map", "get_infiltration_parameters"],
)
@pytest.mark.parametrize(
    ("rasmap_df", "message"),
    [
        (
            pd.DataFrame(),
            "rasmap_df has no summary row",
        ),
        (
            create_rasmap_dataframe(
                rasmap_path="Missing.rasmap",
                rasmap_status="absent",
            ),
            "rasmap_status='absent'",
        ),
        (
            create_rasmap_dataframe(
                rasmap_path="Broken.rasmap",
                rasmap_status="failed",
                rasmap_error="ParseError: invalid XML",
            ),
            "rasmap_status='failed'",
        ),
        (
            create_rasmap_dataframe(
                rasmap_path="Partial.rasmap",
                rasmap_status="parsed_with_errors",
                rasmap_field_errors={
                    "infiltration_hdf_path": "ValueError: missing Filename"
                },
            ),
            "field failed to parse",
        ),
        (
            create_rasmap_dataframe(
                rasmap_path="NoLayer.rasmap",
                rasmap_status="parsed",
            ),
            "No infiltration layer is configured",
        ),
    ],
)
def test_implicit_lookup_has_clear_status_aware_errors(
    method_name: str,
    rasmap_df: pd.DataFrame,
    message: str,
):
    ras_object = SimpleNamespace(rasmap_df=rasmap_df)

    with pytest.raises(ValueError, match=message):
        _call(method_name, ras_object)


@pytest.mark.parametrize(
    "method_name",
    ["get_infiltration_map", "get_infiltration_parameters"],
)
def test_implicit_lookup_reads_configured_path(
    method_name: str,
    tmp_path: Path,
):
    hdf_path = _write_infiltration_hdf(tmp_path / "Infiltration.hdf")
    rasmap_df = create_rasmap_dataframe(
        rasmap_path=tmp_path / "Project.rasmap",
        rasmap_status="parsed",
    )
    rasmap_df.at[0, "infiltration_hdf_path"] = [str(hdf_path)]
    ras_object = SimpleNamespace(rasmap_df=rasmap_df)

    result = _call(method_name, ras_object)

    if method_name == "get_infiltration_map":
        assert result == {1: "100", 2: "200"}
    else:
        assert result == {
            "Initial Loss (in)": 0.25,
            "Constant Loss Rate (in/hr)": 0.10,
            "Impervious Area (%)": 12.0,
        }


@pytest.mark.parametrize(
    "method_name",
    ["get_infiltration_map", "get_infiltration_parameters"],
)
def test_legacy_rasmap_df_without_status_remains_usable(
    method_name: str,
    tmp_path: Path,
):
    hdf_path = _write_infiltration_hdf(tmp_path / "LegacyInfiltration.hdf")
    ras_object = SimpleNamespace(
        rasmap_df=pd.DataFrame({"infiltration_hdf_path": [[str(hdf_path)]]})
    )

    result = _call(method_name, ras_object)

    assert result is not None


@pytest.mark.parametrize(
    "method_name",
    ["get_infiltration_map", "get_infiltration_parameters"],
)
def test_explicit_path_bypasses_failed_rasmap_status(
    method_name: str,
    tmp_path: Path,
):
    hdf_path = _write_infiltration_hdf(tmp_path / "ExplicitInfiltration.hdf")
    ras_object = SimpleNamespace(
        rasmap_df=create_rasmap_dataframe(
            rasmap_path="Broken.rasmap",
            rasmap_status="failed",
            rasmap_error="ParseError: invalid XML",
        )
    )

    result = _call(method_name, ras_object, hdf_path=hdf_path)

    assert result is not None


@pytest.mark.parametrize(
    "method_name",
    ["get_infiltration_map", "get_infiltration_parameters"],
)
def test_unrelated_partial_field_error_does_not_block_lookup(
    method_name: str,
    tmp_path: Path,
):
    hdf_path = _write_infiltration_hdf(tmp_path / "PartialInfiltration.hdf")
    rasmap_df = create_rasmap_dataframe(
        rasmap_path=tmp_path / "Project.rasmap",
        rasmap_status="parsed_with_errors",
        rasmap_field_errors={"terrain_hdf_path": "ValueError: malformed terrain"},
    )
    rasmap_df.at[0, "infiltration_hdf_path"] = [str(hdf_path)]
    ras_object = SimpleNamespace(rasmap_df=rasmap_df)

    result = _call(method_name, ras_object)

    assert result is not None


@pytest.mark.parametrize(
    "method_name",
    ["get_infiltration_map", "get_infiltration_parameters"],
)
def test_field_error_does_not_hide_valid_sibling_candidate(
    method_name: str,
    tmp_path: Path,
):
    hdf_path = _write_infiltration_hdf(tmp_path / "ValidSibling.hdf")
    rasmap_df = create_rasmap_dataframe(
        rasmap_path=tmp_path / "Project.rasmap",
        rasmap_status="parsed_with_errors",
        rasmap_field_errors={
            "infiltration_hdf_path": "ValueError: another layer is malformed"
        },
    )
    rasmap_df.at[0, "infiltration_hdf_path"] = [str(hdf_path)]
    ras_object = SimpleNamespace(rasmap_df=rasmap_df)

    result = _call(method_name, ras_object)

    assert result is not None


@pytest.mark.parametrize(
    "method_name",
    ["get_infiltration_map", "get_infiltration_parameters"],
)
def test_explicit_missing_path_uses_decorator_file_error(
    method_name: str,
    tmp_path: Path,
):
    ras_object = SimpleNamespace(rasmap_df=pd.DataFrame())

    with pytest.raises(FileNotFoundError, match="HDF file not found"):
        _call(method_name, ras_object, hdf_path=tmp_path / "Missing.hdf")


@pytest.mark.parametrize(
    ("method_name", "path_kwargs"),
    [
        ("get_soils_raster_stats", {}),
        ("get_soil_raster_stats", {}),
        ("get_infiltration_stats", {}),
        ("get_landcover_raster_stats", {}),
    ],
)
def test_statistics_lookups_keep_empty_frame_contract_on_unusable_rasmap(
    method_name: str,
    path_kwargs: dict,
    tmp_path: Path,
):
    geom_hdf_path = tmp_path / "Geometry.hdf"
    geom_hdf_path.touch()
    ras_object = SimpleNamespace(
        rasmap_df=create_rasmap_dataframe(
            rasmap_path="Broken.rasmap",
            rasmap_status="failed",
            rasmap_error="ParseError: invalid XML",
        )
    )

    result = getattr(HdfInfiltration, method_name)(
        geom_hdf_path=geom_hdf_path,
        ras_object=ras_object,
        **path_kwargs,
    )

    assert result.empty


@pytest.mark.parametrize(
    "column",
    ["soil_layer_path", "landcover_hdf_path", "infiltration_hdf_path"],
)
def test_shared_resolver_prefers_a_valid_sibling_before_field_error(
    column: str,
    tmp_path: Path,
):
    configured = tmp_path / f"{column}.hdf"
    rasmap_df = create_rasmap_dataframe(
        rasmap_status="parsed_with_errors",
        rasmap_field_errors={column: "ValueError: another declaration is malformed"},
    )
    rasmap_df.at[0, column] = [str(configured)]

    resolved = HdfInfiltration._resolve_rasmap_hdf_path(
        None,
        column,
        SimpleNamespace(rasmap_df=rasmap_df),
    )

    assert resolved == configured
