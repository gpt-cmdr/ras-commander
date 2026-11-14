"""Pin how CRS evidence that differs only by datum realization resolves.

EPSG:6479 (NAD83(2011) / Louisiana South ftUS) and EPSG:3452 (NAD83 /
Louisiana South ftUS) share the ellipsoid, projection method, parameters and
units but name different datums. The resolver treats them as a conflict, and
returns no CRS. See docs/development/crs-datum-realization-design.md for the
proposed explicit opt-in. A change to this behavior must be deliberate.
"""

from __future__ import annotations

import pytest

pyproj = pytest.importorskip("pyproj")

from ras_commander.hdf.HdfUtils import (  # noqa: E402
    CRS_CONFLICT,
    CRS_EVIDENCE_FOUND,
    CrsEvidence,
    HdfUtils,
)


def _evidence(source: str, epsg: int, wkt_version: str = "WKT2_2019") -> CrsEvidence:
    wkt = pyproj.CRS.from_epsg(epsg).to_wkt(wkt_version)
    return CrsEvidence(source, None, CRS_EVIDENCE_FOUND, wkt)


def test_datum_realization_only_difference_is_reported_as_conflict():
    nad83_2011 = pyproj.CRS.from_epsg(6479)
    nad83 = pyproj.CRS.from_epsg(3452)
    # Same projection definition; only the datum realization differs.
    assert (
        nad83_2011.coordinate_operation.to_json_dict()["parameters"]
        == nad83.coordinate_operation.to_json_dict()["parameters"]
    )
    assert nad83_2011.ellipsoid == nad83.ellipsoid
    assert nad83_2011.datum.name != nad83.datum.name

    resolution = HdfUtils.resolve_crs_evidence([
        _evidence("hdf_attribute", 6479),
        _evidence("rasmap_projection", 6479, "WKT1_ESRI"),
        _evidence("terrain_hdf", 3452, "WKT1_ESRI"),
    ])

    assert resolution.status == CRS_CONFLICT
    assert resolution.crs is None
    assert resolution.to_crs_string() is None
    assert len(resolution.candidates) == 2
