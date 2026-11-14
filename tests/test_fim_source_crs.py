"""Source-coordinate identity never transforms or substitutes a datum."""

import json

import pytest
from pyproj import CRS
from pyproj.crs import BoundCRS, CompoundCRS
from pyproj.crs.coordinate_operation import ToWGS84Transformation

from ras_commander.fim._source_crs import source_crs, describe_crs


def bound(source, shift):
    return BoundCRS(source_crs=source, target_crs=CRS.from_epsg(4326),
        transformation=ToWGS84Transformation(source.geodetic_crs,
            x_axis_translation=shift, y_axis_translation=2 * shift, z_axis_translation=3 * shift))


@pytest.mark.parametrize("shift", [0, 1.25, -17.5])
def test_bound_source_identity_retains_original_datum_projection_and_units(shift):
    projected = CRS.from_epsg(6588)
    original = bound(projected, shift)
    assert original.is_bound and original != projected
    result = source_crs(original)
    assert result == projected and result.to_epsg() == 6588
    assert result.is_projected and result.axis_info[0].unit_name == "US survey foot"
    record = describe_crs(original)
    assert record["is_bound"] is True
    assert CRS.from_wkt(record["original_wkt"]) == original
    assert CRS.from_wkt(record["source_wkt"]) == projected
    assert record["binding_operation"] == original.coordinate_operation.to_json_dict()
    json.dumps(record, allow_nan=False)


def test_ordinary_projected_crs_does_not_unwrap_to_geographic_base():
    projected = CRS.from_epsg(6588)
    assert projected.source_crs.is_geographic
    assert source_crs(projected) == projected
    assert source_crs(projected).is_projected
    record = describe_crs(projected)
    assert record["is_bound"] is False and record["binding_operation"] is None


@pytest.mark.parametrize("other", [2278, 6587, 4326])
def test_different_datum_units_or_coordinate_system_remain_different(other):
    assert source_crs(bound(CRS.from_epsg(6588), 1)) != source_crs(CRS.from_epsg(other))


def test_coordinate_conversion_operation_is_not_discarded():
    original = CRS.from_epsg(6588)
    definition = original.to_json_dict()
    definition["conversion"]["parameters"][0]["value"] += .1
    changed = CRS.from_json_dict(definition)
    assert source_crs(bound(original, 0)) != source_crs(changed)


def test_compound_crs_is_never_stripped_to_its_horizontal_component():
    horizontal = CRS.from_epsg(6588)
    compound = CompoundCRS("horizontal and vertical", [horizontal, CRS.from_epsg(5703)])
    assert source_crs(compound) == compound
    assert source_crs(compound) != horizontal


def test_geographic_input_is_not_promoted_to_projected():
    assert source_crs(4326) == CRS.from_epsg(4326)
    assert source_crs(4326).is_geographic


def test_invalid_definition_refuses():
    from pyproj.exceptions import CRSError
    with pytest.raises(CRSError):
        source_crs("not a CRS")
