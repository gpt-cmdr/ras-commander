import pytest
from types import SimpleNamespace

from ras_commander import RasUnsteady
from ras_commander.precip import PrecipCapabilities


@pytest.mark.parametrize("version", ["5.0", "5.0.1", "5.0.7", "5.07"])
def test_hec_ras_5x_rejects_global_gridded_precipitation(version):
    capabilities = PrecipCapabilities.for_version(version)

    assert capabilities.global_gridded_supported is False
    assert capabilities.native_sources == ()
    with pytest.raises(ValueError, match="uniform-per-area"):
        capabilities.require_global_gridded()


@pytest.mark.parametrize("version", ["6.0", "6.1"])
def test_ratio_defect_is_exposed(version):
    capabilities = PrecipCapabilities.for_version(version)

    assert capabilities.ratio_applied is False
    assert capabilities.period_average_timing == "shifted"


@pytest.mark.parametrize("version", ["6.2", "6.3", "6.31"])
def test_pre_64_timing_defect_is_exposed(version):
    capabilities = PrecipCapabilities.for_version(version)

    assert capabilities.global_gridded_supported is True
    assert capabilities.ratio_applied is True
    assert capabilities.period_average_timing == "shifted"


@pytest.mark.parametrize("version", ["6.4", "6.6", "7.0", "7.0.1"])
def test_64_and_later_report_corrected_timing(version):
    capabilities = PrecipCapabilities.for_version(version)

    assert capabilities.period_average_timing == "corrected"
    assert capabilities.ras_commander_inputs == (
        "dss",
        "netcdf",
        "grib",
        "geotiff",
    )


def test_wmic_requirement_matches_executable_evidence():
    assert PrecipCapabilities.for_version("6.1").requires_wmic_compatibility
    assert PrecipCapabilities.for_version("6.2").requires_wmic_compatibility
    assert PrecipCapabilities.for_version("6.3.1").requires_wmic_compatibility
    assert not PrecipCapabilities.for_version("6.4.1").requires_wmic_compatibility


def test_67_beta_is_historical_not_stable_qualification():
    capabilities = PrecipCapabilities.for_version("6.7 Beta 5")

    assert capabilities.native_dss_qualification == "historical_beta"
    assert capabilities.qualification_for("grib2") == "historical_beta"


def test_unparseable_version_fails_closed():
    with pytest.raises(ValueError, match="Could not parse"):
        PrecipCapabilities.for_version("current")


def test_dss_configuration_rejects_hec_ras_5x_before_mutation(tmp_path):
    unsteady = tmp_path / "Legacy.u01"
    original = "Flow Title=Legacy\nProgram Version=5.07\n"
    unsteady.write_text(original, encoding="ascii")

    with pytest.raises(ValueError, match="uniform-per-area"):
        RasUnsteady.configure_gridded_dss_precipitation(
            unsteady,
            "rain.dss",
            "/A/B/C//1HOUR/F/",
        )

    assert unsteady.read_text(encoding="ascii") == original
    assert not (tmp_path / "Legacy.u01.hdf").exists()


def test_netcdf_configuration_rejects_hec_ras_5x_before_source_or_model_mutation(
    tmp_path,
):
    unsteady = tmp_path / "Legacy.u01"
    original = "Flow Title=Legacy\nProgram Version=5.07\n"
    unsteady.write_text(original, encoding="ascii")
    project = SimpleNamespace(
        project_folder=tmp_path,
        project_name="Legacy",
        ras_version="5.0.7",
        check_initialized=lambda: None,
    )

    with pytest.raises(ValueError, match="uniform-per-area"):
        RasUnsteady.set_gridded_precipitation(
            unsteady,
            tmp_path / "missing.nc",
            ras_object=project,
        )

    assert unsteady.read_text(encoding="ascii") == original
    assert not (tmp_path / "Legacy.u01.hdf").exists()


def test_public_capability_api_uses_explicit_version():
    capabilities = RasUnsteady.get_gridded_precipitation_capabilities("6.1")

    assert capabilities.native_dss_qualification == "qualified_windows_with_host_shim"
    assert capabilities.ratio_applied is False


def test_route_qualification_does_not_overstate_format_evidence():
    capabilities = PrecipCapabilities.for_version("6.6")

    assert capabilities.qualification_for("dss") == "qualified_windows_and_wine"
    assert any("WINEDLLOVERRIDES" in note for note in capabilities.notes)
    assert capabilities.qualification_for("netcdf") == "qualified_windows_and_wine"
    assert capabilities.qualification_for("netcdf", route="native_hdf") == "qualified_windows_and_wine"
    assert capabilities.qualification_for("netcdf", route="native") == "documented"
    assert capabilities.qualification_for("geotiff") == "qualified_windows_and_wine"
    assert capabilities.qualification_for("grib") == "documented"
    assert capabilities.qualification_for("grib", route="native") == "documented"


def test_hec_ras_70_geotiff_translation_has_exact_windows_qualification():
    capabilities = PrecipCapabilities.for_version("7.0")

    assert capabilities.qualification_for("geotiff") == "qualified_windows"
    assert PrecipCapabilities.for_version("7.0.1").qualification_for(
        "geotiff"
    ) == "documented"


@pytest.mark.parametrize("version", ["6.6 Beta 1", "7.0 Beta 1"])
def test_prereleases_never_inherit_stable_runtime_qualification(version):
    capabilities = PrecipCapabilities.for_version(version)
    for source in ("dss", "netcdf", "geotiff", "grib"):
        assert capabilities.qualification_for(source) == "historical_beta"


def test_qualification_evidence_is_exact_to_tested_release():
    capabilities_632 = PrecipCapabilities.for_version("6.3.2")
    assert capabilities_632.native_dss_qualification == "documented"
    assert not capabilities_632.requires_wmic_compatibility
    assert (
        PrecipCapabilities.for_version("7.0.1").native_netcdf_qualification
        == "documented"
    )


@pytest.mark.parametrize("path", [
    "C:/profiles/.wine-5.0.7/drive_c/HEC/6.6/Ras.exe",
    r"C:\profiles\v2.1\HEC\6.6\Ras.exe",
])
def test_executable_version_ignores_ancestor_numbers(path):
    assert PrecipCapabilities.for_version(path).version == "6.6"
    assert PrecipCapabilities.resolve(ras_object=SimpleNamespace(ras_version=path)).version == "6.6"


def test_resolved_runtime_parent_precedes_raw_version_and_keeps_beta():
    project = SimpleNamespace(ras_exe_path="C:/HEC/6.6 Beta 1/Ras.exe", ras_version="5.0.7")
    cap = PrecipCapabilities.resolve(ras_object=project)
    assert cap.qualification_for("netcdf") == "historical_beta"


def test_stable_looking_directory_preserves_matching_explicit_beta_identity():
    project = SimpleNamespace(ras_exe_path="C:/HEC/6.6/Ras.exe", ras_version="6.6 Beta 1")
    assert PrecipCapabilities.resolve(ras_object=project).qualification_for("netcdf") == "historical_beta"


def test_unparseable_executable_parent_falls_back_to_unsteady_header(tmp_path):
    unsteady = tmp_path / "Model.u01"
    unsteady.write_text("Program Version=6.60\n")
    project = SimpleNamespace(ras_version="C:/v5.0.7/custom/Ras.exe")
    cap = RasUnsteady._gridded_precipitation_capabilities(unsteady, project)
    assert cap.version == "6.6"


@pytest.mark.parametrize("version", ["6.3", "6.3.1"])
def test_63_host_shim_and_qualification_are_consistent(version):
    capabilities = PrecipCapabilities.for_version(version)

    assert capabilities.requires_wmic_compatibility
    assert capabilities.native_dss_qualification == "qualified_windows"


def test_unknown_route_qualification_fails_closed():
    with pytest.raises(ValueError, match="Unknown gridded-precipitation source"):
        PrecipCapabilities.for_version("6.6").qualification_for("generic-gdal")

    with pytest.raises(ValueError, match="Unknown gridded-precipitation route"):
        PrecipCapabilities.for_version("6.6").qualification_for(
            "geotiff", route="banana"
        )

    with pytest.raises(ValueError, match="not valid"):
        PrecipCapabilities.for_version("6.6").qualification_for(
            "geotiff", route="native"
        )

    with pytest.raises(ValueError, match="not valid"):
        PrecipCapabilities.for_version("6.6").qualification_for(
            "dss", route="translated_netcdf_with_native_hdf"
        )
