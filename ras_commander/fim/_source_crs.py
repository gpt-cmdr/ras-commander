"""Coordinate identity of a stored CRS and its optional datum-bound wrapper.

Unwrapping a BoundCRS selects its existing source coordinate system. It does not
apply the binding operation, transform coordinates, strip a compound CRS, or
substitute a datum. Ordinary projected CRSs retain their projection.
"""


def source_crs(value):
    """Return the original CRS, unwrapping only an explicit BoundCRS wrapper."""
    from pyproj import CRS
    from pyproj.exceptions import CRSError

    original = CRS.from_user_input(value)
    if not original.is_bound:
        return original
    source = original.source_crs
    if source is None or source.is_bound:
        raise CRSError("BoundCRS has no supported direct source coordinate system")
    return source


def describe_crs(value):
    """Retain full original/source WKT and the unapplied datum-binding operation."""
    from pyproj import CRS

    original = CRS.from_user_input(value)
    operation = original.coordinate_operation if original.is_bound else None
    return {"original_wkt": original.to_wkt(), "source_wkt": source_crs(original).to_wkt(),
            "is_bound": original.is_bound,
            "binding_operation": operation.to_json_dict() if operation is not None else None}
