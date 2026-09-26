"""Version-aware gridded-precipitation capability policy for HEC-RAS."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal, Optional

from ..Decorators import log_call
from ..ExecutionArtifacts import normalize_program_version


TimingStatus = Literal["unsupported", "shifted", "corrected"]
PrecipitationSource = Literal["dss", "netcdf", "grib", "geotiff"]
QualificationRoute = Literal[
    "ras_commander",
    "native",
    "native_hdf",
    "translated_netcdf_with_native_hdf",
]
QualificationStatus = Literal[
    "unsupported",
    "documented",
    "qualified_windows",
    "qualified_windows_with_host_shim",
    "qualified_windows_and_wine",
    "historical_beta",
    "inconclusive",
]


@dataclass(frozen=True)
class GriddedPrecipitationCapabilities:
    """Evidence-backed precipitation capabilities for one HEC-RAS release."""

    version: str
    global_gridded_supported: bool
    native_sources: tuple[str, ...]
    ras_commander_inputs: tuple[str, ...]
    ratio_applied: bool
    period_average_timing: TimingStatus
    native_dss_qualification: QualificationStatus
    native_netcdf_qualification: QualificationStatus
    netcdf_hdf_qualification: QualificationStatus
    native_grib_qualification: QualificationStatus
    grib_translation_qualification: QualificationStatus
    geotiff_translation_qualification: QualificationStatus
    requires_wmic_compatibility: bool
    notes: tuple[str, ...] = ()

    def require_global_gridded(self) -> None:
        """Raise when this release predates global gridded meteorology."""
        if not self.global_gridded_supported:
            raise ValueError(
                f"HEC-RAS {self.version} does not support global gridded "
                "meteorology. HEC-RAS 5.x supports only the separate "
                "uniform-per-area precipitation boundary; use HEC-RAS 6.0+ "
                "for gridded rain-on-grid."
            )

    def qualification_for(
        self,
        source: str,
        *,
        route: QualificationRoute = "ras_commander",
    ) -> QualificationStatus:
        """Return qualification for one explicit source and processing route."""
        normalized = str(source).strip().lower().replace("-", "")
        route_normalized = str(route).strip().lower().replace("-", "_")
        source_aliases: dict[str, PrecipitationSource] = {
            "dss": "dss",
            "netcdf": "netcdf",
            "nc": "netcdf",
            "grib": "grib",
            "grib2": "grib",
            "geotiff": "geotiff",
            "tif": "geotiff",
            "tiff": "geotiff",
        }
        try:
            canonical_source = source_aliases[normalized]
        except KeyError as exc:
            raise ValueError(
                f"Unknown gridded-precipitation source {source!r}; expected "
                "DSS, NetCDF, GRIB/GRIB2, or GeoTIFF"
            ) from exc

        valid_routes = {
            "ras_commander",
            "native",
            "native_hdf",
            "translated_netcdf_with_native_hdf",
        }
        if route_normalized not in valid_routes:
            raise ValueError(
                f"Unknown gridded-precipitation route {route!r}; expected "
                "ras_commander, native, native_hdf, or translated_netcdf_with_native_hdf"
            )

        if canonical_source == "dss":
            if route_normalized in {"ras_commander", "native"}:
                return self.native_dss_qualification
        elif canonical_source == "netcdf":
            if route_normalized == "native":
                return self.native_netcdf_qualification
            if route_normalized in {"ras_commander", "native_hdf"}:
                return self.netcdf_hdf_qualification
        elif canonical_source == "grib":
            if route_normalized == "native":
                return self.native_grib_qualification
            if route_normalized in {
                "ras_commander",
                "translated_netcdf_with_native_hdf",
            }:
                return self.grib_translation_qualification
        elif route_normalized in {
            "ras_commander",
            "translated_netcdf_with_native_hdf",
        }:
            return self.geotiff_translation_qualification

        raise ValueError(
            f"Route {route!r} is not valid for gridded-precipitation source "
            f"{source!r}"
        )


class PrecipCapabilities:
    """Resolve and enforce HEC-RAS gridded-precipitation capabilities."""

    _QUALIFIED_WINDOWS = {"6.3", "6.3.1", "6.6", "7.0", "7.0.1"}
    _QUALIFIED_WITH_WMIC = {"6.1", "6.2", "6.3", "6.3.1"}

    @staticmethod
    def _version_label(version: object) -> str:
        """Keep only the executable parent when given a path, never ancestor digits."""
        label = str(version).strip()
        if "/" in label or "\\" in label:
            label = PurePosixPath(label.replace("\\", "/")).parent.name
        return label

    @staticmethod
    def _version_tuple(version: str) -> tuple[int, int, int]:
        parts = [int(part) for part in version.split(".")]
        return tuple((parts + [0, 0])[:3])

    @staticmethod
    @log_call
    def for_version(version: object) -> GriddedPrecipitationCapabilities:
        """Return the evidence-backed capability record for ``version``."""
        label = PrecipCapabilities._version_label(version)
        normalized = normalize_program_version(label)
        if normalized is None:
            raise ValueError(f"Could not parse HEC-RAS version from {version!r}")

        release = PrecipCapabilities._version_tuple(normalized)
        prerelease = "beta" in label.lower()
        if release[0] < 6:
            return GriddedPrecipitationCapabilities(
                version=normalized,
                global_gridded_supported=False,
                native_sources=(),
                ras_commander_inputs=(),
                ratio_applied=False,
                period_average_timing="unsupported",
                native_dss_qualification="unsupported",
                native_netcdf_qualification="unsupported",
                netcdf_hdf_qualification="unsupported",
                native_grib_qualification="unsupported",
                grib_translation_qualification="unsupported",
                geotiff_translation_qualification="unsupported",
                requires_wmic_compatibility=False,
                notes=(
                    "Only uniform-per-area precipitation is available in HEC-RAS 5.x.",
                ),
            )

        notes: list[str] = []
        ratio_applied = release >= (6, 2, 0)
        if not ratio_applied:
            notes.append(
                "HEC-RAS 6.0-6.1 do not apply the optional precipitation ratio."
            )

        timing: TimingStatus = "corrected" if release >= (6, 4, 0) else "shifted"
        if timing == "shifted":
            notes.append(
                "HEC-RAS 6.0-6.3.1 can shift native period-average precipitation "
                "by one interval; prefer cumulative materialization."
            )

        if prerelease:
            dss_qualification: QualificationStatus = "historical_beta"
            notes.append("Prerelease evidence is historical and is not a stable support target.")
        elif normalized in {"6.1", "6.2"}:
            dss_qualification = "qualified_windows_with_host_shim"
        elif normalized in PrecipCapabilities._QUALIFIED_WINDOWS:
            dss_qualification = "qualified_windows"
            if normalized == "6.6":
                dss_qualification = "qualified_windows_and_wine"
                notes.append(
                    "Wine DSS qualified with the required runtime available; disabling "
                    "mscoree/mshtml via WINEDLLOVERRIDES blocked preprocessing in a control run."
                )
        elif normalized == "6.5":
            dss_qualification = "inconclusive"
            notes.append(
                "The available 6.5 host exits before precipitation preprocessing; "
                "format support is documented but executable qualification is inconclusive."
            )
        else:
            dss_qualification = "documented"

        netcdf_qualification: QualificationStatus = "documented"
        if prerelease:
            netcdf_qualification = "historical_beta"
        elif normalized == "6.6":
            netcdf_qualification = "qualified_windows_and_wine"
        elif normalized == "7.0":
            netcdf_qualification = "qualified_windows"

        native_grib_qualification: QualificationStatus = (
            "historical_beta" if prerelease else "documented"
        )
        grib_translation_qualification: QualificationStatus = (
            "historical_beta" if prerelease else "documented"
        )
        geotiff_qualification: QualificationStatus = (
            "historical_beta" if prerelease else (
                "qualified_windows_and_wine" if normalized == "6.6" else "documented"
            )
        )

        notes.append(
            "WPC QPF GRIB2 compression is not accepted natively through 7.0.1; "
            "translate it to DSS with HEC-Vortex or HEC-MetVue."
        )
        return GriddedPrecipitationCapabilities(
            version=normalized,
            global_gridded_supported=True,
            native_sources=("dss", "netcdf", "grib"),
            ras_commander_inputs=("dss", "netcdf", "grib", "geotiff"),
            ratio_applied=ratio_applied,
            period_average_timing=timing,
            native_dss_qualification=dss_qualification,
            native_netcdf_qualification="historical_beta" if prerelease else "documented",
            netcdf_hdf_qualification=netcdf_qualification,
            native_grib_qualification=native_grib_qualification,
            grib_translation_qualification=grib_translation_qualification,
            geotiff_translation_qualification=geotiff_qualification,
            requires_wmic_compatibility=(
                normalized in PrecipCapabilities._QUALIFIED_WITH_WMIC
            ),
            notes=tuple(notes),
        )

    @staticmethod
    @log_call
    def resolve(
        *,
        version: Optional[object] = None,
        ras_object: Optional[object] = None,
    ) -> GriddedPrecipitationCapabilities:
        """Resolve a capability record from an explicit or initialized version."""
        candidates = [version] if version is not None else [
            getattr(ras_object, "ras_exe_path", None),
            getattr(ras_object, "ras_version", None),
        ]
        for candidate in candidates:
            if candidate is not None:
                label = PrecipCapabilities._version_label(candidate)
                normalized = normalize_program_version(label)
                if normalized is not None:
                    # Some beta installers use a stable-looking directory. Keep
                    # an explicit matching beta identity from the init argument.
                    for other in candidates:
                        other_label = PrecipCapabilities._version_label(other)
                        if (
                            "beta" in other_label.lower()
                            and normalize_program_version(other_label) == normalized
                        ):
                            label = other_label
                            break
                    return PrecipCapabilities.for_version(label)
        raise ValueError(
            "A resolvable HEC-RAS version is required to evaluate precipitation capabilities"
        )


__all__ = [
    "GriddedPrecipitationCapabilities",
    "PrecipCapabilities",
    "PrecipitationSource",
    "QualificationRoute",
    "QualificationStatus",
    "TimingStatus",
]
