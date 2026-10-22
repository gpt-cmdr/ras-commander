"""Read-only input snapshots and native geometry-product completion checks.

Geometry text is authoritative when an incoming HDF still describes a parent.
Only native product datasets are invalidated; authored features are never restored
from a stale HDF. All HDF contexts close before native execution.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import h5py
import numpy as np

from ._breakline_controls import _protection_radius_flag

AREA = "Geometry/2D Flow Areas"
CALIBRATION = "Geometry/Land Cover (Manning's n)/Calibration Table"
CELL_PRODUCTS = (
    "Cells Center Manning's n",
    "Cells Minimum Elevation",
    "Cells Surface Area",
    "Cells Volume Elevation Info",
    "Cells Volume Elevation Values",
)
FACE_PRODUCTS = (
    "Faces Area Elevation Info",
    "Faces Area Elevation Values",
    "Faces Low Elevation Centroid",
    "Faces Minimum Elevation",
)
FEATURES = {
    "Geometry/2D Flow Area Break Lines": "BreakLine Name=",
    "Geometry/Boundary Condition Lines": "BC Line Name=",
    "Geometry/Reference Lines": "Reference Line Name=",
    "Geometry/Structures": "Connection=",
}
REFINEMENT = "Geometry/2D Flow Area Refinement Regions"
ASSOCIATIONS = (
    "Terrain Filename",
    "Terrain Layername",
    "Land Cover Filename",
    "Land Cover Layername",
    "Infiltration Filename",
    "Infiltration Layername",
    "Percent Impervious Filename",
    "Percent Impervious Layername",
    "SI Units",
)


INFILTRATION_PRODUCTS = {
    "infiltration_scs": (
        "Curve Number",
        "Abstraction Ratio",
        "Minimum Infiltration Rate",
    ),
    "infiltration_deficit_constant": (
        "Maximum Deficit",
        "Initial Deficit",
        "Potential Percolation Rate",
    ),
    "infiltration_green_ampt": (
        "Wetting Front Suction",
        "Saturated Hydraulic Conductivity",
        "Initial Soil Water Content",
        "Saturated Soil Water Content",
    ),
}


def _semantic(value):
    """Preserve values while ignoring fixed-string width and compound padding."""
    if isinstance(value, np.ndarray):
        if value.dtype.names:
            return (
                value.shape,
                tuple(value.dtype.names),
                tuple(_semantic(v) for v in value.flat),
            )
        return (value.shape, tuple(_semantic(v) for v in value.flat))
    if isinstance(value, np.void) and value.dtype.names:
        return tuple((n, _semantic(value[n])) for n in value.dtype.names)
    if isinstance(value, (bytes, np.bytes_)):
        return bytes(value).rstrip(b"\x00")
    if isinstance(value, np.generic):
        return _semantic(value.item())
    if isinstance(value, float) and np.isnan(value):
        return ("nan",)
    return value


def _digest(value) -> str:
    return hashlib.sha256(repr(_semantic(value)).encode("utf-8")).hexdigest()


def _projection_equal(before, after) -> bool:
    """Compare CRS definitions, including native equivalent WKT serialization."""
    from .GeomPreprocessor import GeomPreprocessor

    left = GeomPreprocessor._decode_hdf_attribute(before)
    right = GeomPreprocessor._decode_hdf_attribute(after)
    if left == right:
        return True
    try:
        from pyproj import CRS
        from pyproj.exceptions import CRSError
    except ImportError:
        return False

    try:
        return CRS.from_user_input(left).equals(
            CRS.from_user_input(right), ignore_axis_order=False
        )
    except (ValueError, TypeError, CRSError):
        return False


def _text_features(lines: list[str], prefix: str, arc: str) -> list[dict]:
    from .GeomParser import GeomParser

    features = []
    for index, line in enumerate(lines):
        if not line.startswith(prefix):
            continue
        name = line.split("=", 1)[1].strip()
        storage = ""
        controls = {}
        for end in range(index + 1, len(lines)):
            if "Storage Area=" in lines[end]:
                storage = lines[end].split("=", 1)[1].strip()
            for key, field in (
                ("BreakLine CellSize Min=", "Cell Spacing Near"),
                ("BreakLine CellSize Max=", "Cell Spacing Far"),
                ("BreakLine Near Repeats=", "Near Repeats"),
                ("BreakLine Protection Radius=", "Protection Radius"),
            ):
                if lines[end].startswith(key) and lines[end].split("=", 1)[1].strip():
                    controls[field] = float(lines[end].split("=", 1)[1])
            if lines[end].startswith(arc):
                count = int(lines[end].split("=", 1)[1].strip())
                values = []
                for raw in lines[end + 1 :]:
                    if len(values) >= count * 2:
                        break
                    values.extend(GeomParser.parse_fixed_width(raw, 16))
                if len(values) != count * 2:
                    raise ValueError(f"Malformed authored feature {name!r}")
                features.append(
                    {
                        "name": name,
                        "storage_area": storage,
                        "coordinates": np.asarray(values).reshape(count, 2),
                        "controls": controls,
                    }
                )
                break
            if lines[end].startswith(prefix):
                raise ValueError(f"Missing authored coordinates for {name!r}")
        else:
            raise ValueError(f"Missing authored coordinates for {name!r}")
    return features


def _control_matches(field: str, authored, stored, dtype) -> bool:
    """Compare representable controls without NumPy's unsafe integer casts."""
    try:
        if field == "Protection Radius":
            authored = _protection_radius_flag(authored)
        if not np.isfinite(authored):
            return False
        if dtype.kind in "iu":
            integer = int(authored)
            bounds = np.iinfo(dtype)
            if integer != authored or not bounds.min <= integer <= bounds.max:
                return False
            return int(stored) == integer
        if dtype.kind == "b" and authored not in (0, 1):
            return False
        with np.errstate(over="ignore", invalid="ignore"):
            converted = np.asarray(authored, dtype=dtype)
        return bool(np.isfinite(converted)) and float(stored) == float(converted)
    except (ValueError, TypeError, OverflowError):
        return False


def _feature_issues(
    hdf, path: str, features: list[dict], family="Polyline"
) -> list[str]:
    """Compare each serialized feature's identity and coordinates, in FID order."""
    issues = []
    if not features:
        if path in hdf and "Attributes" in hdf[path] and len(hdf[path]["Attributes"]):
            return [f"{path}: obsolete features remain"]
        return issues
    if path not in hdf:
        return [path]
    group = hdf[path]
    if any(
        name not in group
        for name in ("Attributes", f"{family} Info", f"{family} Points")
    ):
        return [f"{path}: missing authored feature geometry"]
    attrs, info, points = (
        group["Attributes"],
        group[f"{family} Info"],
        group[f"{family} Points"],
    )
    if (
        len(attrs) != len(features)
        or len(info) != len(features)
        or "Name" not in (attrs.dtype.names or ())
    ):
        return [f"{path}: authored feature identities differ"]
    if family == "Polygon" and (
        len(info.shape) != 2 or info.shape[1] != 4 or "Polygon Parts" not in group
    ):
        return [f"{path}: unsupported polygon part schema"]
    for index, feature in enumerate(features):
        # Native string fields are fixed width; names longer than the field are
        # not accepted as preserved identities by this contract.
        name = bytes(attrs["Name"][index]).rstrip(b"\x00").decode("utf-8").rstrip()
        start, count = (int(v) for v in info[index, :2])
        if family == "Polygon":
            part_start, part_count = (int(v) for v in info[index, 2:4])
            parts = group["Polygon Parts"]
            if (
                part_count != 1
                or part_start < 0
                or part_start >= len(parts)
                or parts.shape[1:] != (2,)
                or not np.array_equal(parts[part_start], [0, count])
            ):
                issues.append(f"{path}/{index}: unsupported polygon part ranges")
        coords = points[start : start + count]
        if (
            name != feature["name"]
            or start < 0
            or count < 2
            or coords.shape != feature["coordinates"].shape
            or not np.allclose(coords, feature["coordinates"], rtol=0, atol=1e-6)
        ):
            issues.append(f"{path}/{index}: authored identity or coordinates changed")
        if feature["storage_area"]:
            area_field = next(
                (key for key in ("SA-2D", "2D Area Name") if key in attrs.dtype.names),
                None,
            )
            if (
                area_field is None
                or bytes(attrs[area_field][index]).rstrip(b"\x00").decode().strip()
                != feature["storage_area"]
            ):
                issues.append(f"{path}/{index}: authored area association changed")
        if "bc_type" in feature and (
            "Type" not in (attrs.dtype.names or ())
            or _semantic(attrs["Type"][index]) != feature["bc_type"]
        ):
            issues.append(f"{path}/{index}: authored BC Type changed")
        for field, value in feature.get("controls", {}).items():
            if field not in attrs.dtype.names or not _control_matches(
                field, value, attrs[field][index], attrs.dtype[field]
            ):
                issues.append(f"{path}/{index}: authored {field} changed")
    return issues


def snapshot(
    geometry_path: Path, hdf_path: Path, *, require_complete_products: bool = True
) -> dict:
    """Bind authored text, HDF-only associations, calibration and current inputs."""
    from .GeomMesh import _mesh_hdf_consistency_issues, _read_mesh_metadata_from_text

    text = geometry_path.read_bytes()
    lines = text.decode("utf-8", errors="replace").splitlines()
    result = {
        "text_sha256": hashlib.sha256(text).hexdigest(),
        "areas": _read_mesh_metadata_from_text(geometry_path),
        "features": {
            path: sum(line.startswith(key) for line in lines)
            for path, key in FEATURES.items()
        },
        "inputs": {},
        "attributes": {},
        "feature_geometry": {
            "Geometry/2D Flow Area Break Lines": _text_features(
                lines, "BreakLine Name=", "BreakLine Polyline="
            ),
            "Geometry/Boundary Condition Lines": _text_features(
                lines, "BC Line Name=", "BC Line Arc="
            ),
            "Geometry/Reference Lines": _text_features(
                lines, "Reference Line Name=", "Reference Line Arc="
            ),
        },
        "manning_regions": [],
        "infiltration_methods": {},
        "projections": {},
        "contract_qualified": True,
    }
    result["features"]["Geometry/Structures"] += sum(
        line.startswith(
            ("SA/2D Area Conn=", "Bridge Culvert-", "IW Pilot Flow=", "Lat Struct=")
        )
        for line in lines
    )
    # A malformed structure block can lack its normal feature marker. Only
    # ordinary cross-section type 1 is understood in the structure-free scope.
    from .GeomParser import GeomParser

    unsupported_sections = any(
        GeomParser.extract_keyword_value(line, "Type RM Length L Ch R")
        .split(",", 1)[0]
        .strip()
        != "1"
        for line in lines
        if line.startswith("Type RM Length L Ch R =")
    )
    # Metadata helper includes storage areas; only authored Is2D=-1 blocks belong
    # in the required mesh contract, including an invalid empty seed block.
    from .GeomStorage import GeomStorage

    blocks = list(GeomStorage._iter_storage_area_blocks(lines))
    two_d = {
        GeomStorage._extract_storage_area_name(block[2][0])
        for block in blocks
        if GeomStorage._inspect_storage_area_block(block[2])["is_2d"]
    }
    result["areas"] = {
        name: value for name, value in result["areas"].items() if name in two_d
    }
    if result["areas"] and (
        result["features"]["Geometry/Structures"] or unsupported_sections
    ):
        if require_complete_products:
            raise NotImplementedError(
                "GEOMETRY_PRODUCTS_SCHEMA_UNSUPPORTED: authored 2D structures require a qualified native structure-product contract"
            )
        result["contract_qualified"] = False
        return result
    from .GeomParser import GeomParser

    result["seed_points"] = {}
    from .GeomMesh import _text_flow_area_perimeter

    result["perimeters"] = {
        name: _text_flow_area_perimeter(geometry_path, name) for name in two_d
    }
    for _, _, block in blocks:
        name = GeomStorage._extract_storage_area_name(block[0])
        if name not in two_d:
            continue
        info = GeomStorage._inspect_storage_area_block(block)
        count = result["areas"][name]["seed_count"]
        if info["points_idx"] is None or count is None:
            raise ValueError(
                f"GEOMETRY_INPUT_INVALID: no computation points for {name}"
            )
        values = []
        for raw in block[info["points_idx"] + 1 : info["points_end"]]:
            values.extend(GeomParser.parse_fixed_width(raw, 16))
        if len(values) != int(count) * 2:
            raise ValueError(
                f"GEOMETRY_INPUT_INVALID: malformed computation points for {name}"
            )
        result["seed_points"][name] = np.asarray(values).reshape(int(count), 2)
    from .GeomLandCover import GeomLandCover

    for block in GeomLandCover._find_region_blocks(lines):
        if block["polygon_idx"] is None:
            continue  # A calibration table name alone is not a polygon override.
        features = _text_features(
            lines[block["start_idx"] : block["end_idx"]],
            "LCMann Region Name=",
            "LCMann Region Polygon=",
        )
        result["manning_regions"].extend(features)
    result["manning_region_interactions"] = []
    if result["manning_regions"]:
        from shapely.geometry import Polygon

        areas = GeomStorage.get_storage_area_polygons(geometry_path, exclude_2d=False)
        if any(list(areas["Name"]).count(name) != 1 for name in result["areas"]):
            raise ValueError(
                "GEOMETRY_INPUT_INVALID: incomplete current 2D perimeter inventory"
            )
        for feature in result["manning_regions"]:
            polygon = Polygon(feature["coordinates"])
            if not polygon.is_valid or polygon.is_empty:
                raise NotImplementedError(
                    "GEOMETRY_PRODUCTS_SCHEMA_UNSUPPORTED: invalid or multipart Manning region requires a qualified interaction contract"
                )
            intersected = []
            for _, area in areas.iterrows():
                if area["Name"] not in result["areas"]:
                    continue
                if not area.geometry.is_valid or area.geometry.is_empty:
                    raise ValueError("GEOMETRY_INPUT_INVALID: invalid 2D perimeter")
                if not polygon.disjoint(area.geometry):
                    intersected.append(area["Name"])
            if len(intersected) > 1:
                raise NotImplementedError(
                    "GEOMETRY_PRODUCTS_SCHEMA_UNSUPPORTED: multi-area Manning region requires a qualified interaction contract"
                )
            result["manning_region_interactions"].append(
                {
                    "name": feature["name"],
                    "areas": intersected,
                    "reason": "intersects_current_mesh"
                    if intersected
                    else "outside_current_mesh",
                }
            )
    if not hdf_path.exists():
        return result
    current = not _mesh_hdf_consistency_issues(geometry_path, hdf_path)
    with h5py.File(hdf_path, "r") as hdf:
        bc_path = "Geometry/Boundary Condition Lines"
        bc_features = result["feature_geometry"][bc_path]
        # A current feature mirror can contain explicitly authored native types.
        # Do not bind unrelated parent BC attributes to newly authored child lines.
        if bc_features and not _feature_issues(hdf, bc_path, bc_features):
            attrs = hdf[bc_path]["Attributes"]
            if "Type" in (attrs.dtype.names or ()):
                for index, feature in enumerate(bc_features):
                    value = _semantic(attrs["Type"][index])
                    if value in (b"Internal", b"External", "Internal", "External"):
                        feature["bc_type"] = value
        for path in ("/", "Geometry", *(f"{AREA}/{name}" for name in result["areas"])):
            if path not in hdf:
                continue
            for name in (*ASSOCIATIONS, "Projection", "Units System"):
                if name in hdf[path].attrs:
                    if name == "Projection":
                        result["projections"][f"{path}@{name}"] = hdf[path].attrs[name]
                    result["attributes"][f"{path}@{name}"] = _digest(
                        hdf[path].attrs[name]
                    )
        for path in ("Projection", CALIBRATION):
            if path in hdf:
                result["inputs"][path] = _digest(hdf[path][()])
                if path == "Projection":
                    result["projections"][path] = hdf[path][()]
        # Refinement regions are HDF-only authored input, including when the
        # cached parent topology has not yet been refreshed from child text.
        if REFINEMENT in hdf:
            result["features"][REFINEMENT] = len(hdf[REFINEMENT].get("Attributes", []))
            for name, obj in hdf[REFINEMENT].items():
                if isinstance(obj, h5py.Dataset):
                    result["inputs"][f"{REFINEMENT}/{name}"] = _digest(obj[()])
        if "Geometry/Infiltration" in hdf:

            def capture_infiltration(name, obj):
                if isinstance(obj, h5py.Dataset) and name.split("/", 1)[0] not in (
                    "External Faces",
                    "Internal Faces",
                    "Internal Cells",
                ):
                    result["inputs"][f"Geometry/Infiltration/{name}"] = _digest(obj[()])

            hdf["Geometry/Infiltration"].visititems(capture_infiltration)
        # Text-backed inputs are compared with their selected text, never with
        # an incoming mirror. Even a same-count HDF can contain unrounded seed
        # coordinates or outdated breakline controls. Native import canonicalizes
        # that mirror; the complete authored text must remain byte-identical.
        result["incoming_mesh_current"] = current
        from ..hdf.HdfInfiltration import HdfInfiltration
        from .GeomMesh import _decode_hdf_text

        for name in result["areas"]:
            area = hdf.get(f"{AREA}/{name}")
            raw = area.attrs.get("Infiltration Filename") if area is not None else None
            if raw is None and "Geometry" in hdf:
                raw = hdf["Geometry"].attrs.get("Infiltration Filename")
            filename = _decode_hdf_text(raw) if raw is not None else ""
            if filename:
                asset = Path(filename.replace("\\", "/"))
                if not asset.is_absolute():
                    asset = hdf_path.parent / asset
                result["infiltration_methods"][name] = (
                    HdfInfiltration._native_infiltration_layer_type(asset)
                )
    return result


def invalidate_products(hdf_path: Path) -> list[str]:
    """Remove recognized derived tables so file freshness cannot hide old products."""
    removed = []
    if not hdf_path.exists():
        return removed
    with h5py.File(hdf_path, "r+") as hdf:
        from .GeomPreprocessor import GeomPreprocessor

        file_type = GeomPreprocessor._decode_hdf_attribute(hdf.attrs.get("File Type"))
        version = GeomPreprocessor._decode_hdf_attribute(hdf.attrs.get("File Version"))
        geometry_only_copy = file_type == "HEC-RAS Results" and not any(
            key in hdf for key in ("Results", "Event Conditions", "Plan Data")
        )
        if (
            (file_type != "HEC-RAS Geometry" and not geometry_only_copy)
            or not re.search(r"\.g\d{1,2}\.hdf$", hdf_path.name, re.IGNORECASE)
            or re.match(r"^HEC-RAS [56]\.\d+(?:\.\d+)?\b", version) is None
        ):
            raise ValueError(
                "GEOMETRY_CACHE_SCHEMA_UNSUPPORTED: product invalidation requires a HEC-RAS 5/6 geometry HDF or geometry-only results copy"
            )
        paths = [
            "Geometry/GeomPreprocess",
            "Geometry/Cross Sections/Property Tables",
            "Geometry/Cross Sections/Flow Distribution",
            "Geometry/Structures/Property Tables",
        ]
        for path in ("Geometry/Boundary Condition Lines", "Geometry/Reference Lines"):
            paths.extend(
                f"{path}/{name}"
                for name in (
                    "External Faces",
                    "Internal Cells",
                    "Internal Faces",
                    "Terrain Profiles Info",
                    "Terrain Profiles Values",
                )
            )
        paths.extend(
            f"Geometry/Land Cover (Manning's n)/{name}"
            for name in ("External Faces", "Internal Cells", "Internal Faces")
        )
        if AREA in hdf:
            for name, area in hdf[AREA].items():
                if not isinstance(area, h5py.Group):
                    continue
                paths.extend(
                    f"{AREA}/{name}/{product}"
                    for product in (
                        *CELL_PRODUCTS,
                        *FACE_PRODUCTS,
                        "Infiltration",
                        "Percent Impervious",
                    )
                )
                if "Property Tables Last Computed" in area.attrs:
                    del area.attrs["Property Tables Last Computed"]
        for path in paths:
            if path in hdf:
                del hdf[path]
                removed.append(path)
    return removed


def _topology_issues(area: h5py.Group) -> list[str]:
    """Check HEC-RAS 5/6 packed incidence, padding and reciprocal connectivity.

    Coordinates use the geometry CRS/units. Float32 native normals and lengths
    are compared at their storage precision; index/incidence checks are exact.
    This reads regenerated topology, never restores or binds stale parent arrays.
    """
    issues = []

    def read(name, rows=None, columns=None, integer=False):
        obj = area.get(name)
        if not isinstance(obj, h5py.Dataset):
            issues.append(f"{name}: missing topology")
            return None
        data = obj[()]
        if (
            (columns is None and data.ndim != 1)
            or (columns is not None and (data.ndim != 2 or data.shape[1] != columns))
            or (rows is not None and len(data) != rows)
            or (integer and data.dtype.kind not in "iu")
        ):
            issues.append(f"{name}: invalid topology schema")
            return None
        return data.astype(np.int64) if integer else data

    centers = read("Cells Center Coordinate", columns=2)
    points = read("FacePoints Coordinate", columns=2)
    faces = read("Faces FacePoint Indexes", columns=2, integer=True)
    if any(value is None for value in (centers, points, faces)):
        return issues
    nc, npnt, nf = len(centers), len(points), len(faces)
    if not nc or not npnt or not nf:
        return ["empty topology"]
    for name, data in (
        ("Cells Center Coordinate", centers),
        ("FacePoints Coordinate", points),
    ):
        if not np.all(np.isfinite(data)):
            issues.append(f"{name}: nonfinite coordinates")
    adjacency = read("Faces Cell Indexes", nf, 2, integer=True)
    if np.any(faces < 0) or np.any(faces >= npnt) or np.any(faces[:, 0] == faces[:, 1]):
        issues.append("Faces FacePoint Indexes: invalid endpoint indexes")
    if adjacency is not None and (
        np.any(adjacency < 0)
        or np.any(adjacency >= nc)
        or np.any(adjacency[:, 0] == adjacency[:, 1])
    ):
        issues.append("Faces Cell Indexes: invalid adjacency")
    if issues:
        return issues  # Do not dereference malformed indexes.

    def packed(prefix, rows, value_name, columns=None):
        info = read(prefix + " Info", rows, 2, integer=True)
        values = read(value_name, columns=columns, integer=True)
        if info is None or values is None:
            return None, None
        # The packed native table is a partition, including zero-length rows.
        counts = info[:, 1]
        if np.any(info < 0) or np.any(counts > len(values)):
            issues.append(f"{prefix}: invalid packed ranges")
            return None, None
        ends = np.cumsum(counts)
        if ends[-1] != len(values) or not np.array_equal(info[:, 0], ends - counts):
            issues.append(f"{prefix}: invalid packed ranges")
            return None, None
        return np.repeat(np.arange(rows), counts), values

    cell_owner, cell_faces = packed(
        "Cells Face and Orientation", nc, "Cells Face and Orientation Values", 2
    )
    point_owner, point_faces = packed(
        "FacePoints Face and Orientation",
        npnt,
        "FacePoints Face and Orientation Values",
        2,
    )
    pc_owner, point_cells = packed(
        "FacePoints Cell", npnt, "FacePoints Cell Index Values"
    )

    def oriented(owner, values, targets, positive_column, name):
        if owner is None:
            return
        if (
            np.any(values[:, 0] < 0)
            or np.any(values[:, 0] >= nf)
            or not np.all(np.isin(values[:, 1], [-1, 1]))
        ):
            issues.append(f"{name}: invalid face indexes or orientations")
            return
        column = np.where(values[:, 1] == 1, positive_column, 1 - positive_column)
        ids = values[:, 0]
        if not np.array_equal(targets[ids, column], owner):
            issues.append(f"{name}: adjacency/orientation mismatch")
        # Each face has exactly one incidence on each side/endpoint.
        if not np.array_equal(np.sort(ids * 2 + column), np.arange(nf * 2)):
            issues.append(f"{name}: missing or duplicate face incidences")

    if adjacency is not None:
        oriented(cell_owner, cell_faces, adjacency, 0, "Cells Face and Orientation")
    oriented(point_owner, point_faces, faces, 1, "FacePoints Face and Orientation")

    obj = area.get("Cells FacePoint Indexes")
    cell_points = obj[()] if isinstance(obj, h5py.Dataset) else None
    if (
        cell_points is None
        or cell_points.ndim != 2
        or len(cell_points) != nc
        or cell_points.dtype.kind not in "iu"
        or cell_points.shape[1] == 0
    ):
        issues.append("Cells FacePoint Indexes: invalid topology schema")
    elif np.any(cell_points < -1) or np.any(cell_points >= npnt):
        issues.append("Cells FacePoint Indexes: invalid point indexes")
    else:
        cell_points = cell_points.astype(np.int64)
        valid = cell_points >= 0
        if np.any(np.diff(valid.astype(int), axis=1) > 0) or np.any(
            valid.sum(axis=1) < 2
        ):
            issues.append(
                "Cells FacePoint Indexes: invalid trailing padding or empty cell"
            )
        cids, slots = np.nonzero(valid)
        cp = cids * npnt + cell_points[cids, slots]
        if len(np.unique(cp)) != len(cp):
            issues.append("Cells FacePoint Indexes: duplicate cell points")
        if pc_owner is not None:
            if np.any(point_cells < 0) or np.any(point_cells >= nc):
                issues.append("FacePoints Cell: invalid cell indexes")
            elif not np.array_equal(
                np.sort(cp), np.sort(point_cells * npnt + pc_owner)
            ):
                issues.append("FacePoints Cell: reciprocal cell/point mismatch")
        if cell_owner is not None and cell_faces is not None and not issues:
            endpoints = faces[cell_faces[:, 0]]
            referenced = (cell_owner[:, None] * npnt + endpoints).ravel()
            if not np.all(np.isin(referenced, cp)):
                issues.append(
                    "Cells FacePoint Indexes: cell faces reference other points"
                )

    normals = read("Faces NormalUnitVector and Length", nf, 3)
    delta = points[faces[:, 1]] - points[faces[:, 0]]
    lengths = np.linalg.norm(delta, axis=1)
    if np.any(lengths <= 0) or not np.all(np.isfinite(lengths)):
        issues.append("FacePoints Coordinate: degenerate face coordinates")
    elif normals is not None:
        expected_normals = np.column_stack(
            (delta[:, 1] / lengths, -delta[:, 0] / lengths, lengths)
        )
        if not np.all(np.isfinite(normals)) or not np.allclose(
            normals, expected_normals, rtol=2e-6, atol=2e-6
        ):
            issues.append("Faces NormalUnitVector and Length: face-coordinate mismatch")

    info = read("Faces Perimeter Info", nf, 2, integer=True)
    values = read("Faces Perimeter Values", columns=2)
    if info is not None and values is not None:
        counts = info[:, 1]
        if (
            np.any(info < 0)
            or np.any(counts > len(values))
            or np.sum(counts) != len(values)
            or not np.array_equal(info[:, 0], np.cumsum(counts) - counts)
        ):
            issues.append("Faces Perimeter: invalid packed ranges")
        if not np.all(np.isfinite(values)):
            issues.append("Faces Perimeter Values: nonfinite coordinates")
    flags = read("FacePoints Is Perimeter", npnt, integer=True)
    if flags is not None and not np.all(np.isin(flags, [-1, 0])):
        issues.append("FacePoints Is Perimeter: invalid flags")
    return issues


def _mesh_binding_issues(
    area: h5py.Group, seeds: np.ndarray, ring: np.ndarray
) -> list[str]:
    """Bind native float64 coordinates to current text in its CRS and units.

    Interior rows match current native computation points exactly. The caller
    validates that regenerated seed mirror against current text at one float64
    ULP for native decimal parsing; no incoming parent mirror is used.
    Remaining rows are native
    two-vertex ghost cells; their centers are not authored seeds. All native
    face polylines, including ghost-adjacent faces and packed intermediate
    vertices, must be covered by the current perimeter. Boundary arithmetic
    allows eight float64 ULPs at the original perimeter magnitude in source
    CRS units. Spatial predicates use a uniformly translated local frame to
    avoid cancellation in tiny buffers at large projected offsets; authored
    and native arrays remain unchanged. Spatial imports are local
    so nonspatial preprocessing does not require Shapely.
    """
    issues = []
    centers = area["Cells Center Coordinate"][()]
    points = area["FacePoints Coordinate"][()]
    if any(v.dtype.kind != "f" or v.dtype.itemsize != 8 for v in (centers, points)):
        return ["mesh coordinates: unsupported native coordinate precision"]
    if not np.array_equal(centers[: len(seeds)], seeds):
        issues.append(
            "Cells Center Coordinate: interior centers differ from authored computation points"
        )
    cell_points = area.get("Cells FacePoint Indexes")
    if (
        cell_points is not None
        and cell_points.ndim == 2
        and len(cell_points) == len(centers)
        and np.any((cell_points[len(seeds) :] >= 0).sum(axis=1) != 2)
    ):
        issues.append("Cells FacePoint Indexes: ghost cells must have two vertices")
    if (
        ring is None
        or ring.ndim != 2
        or ring.shape[1] != 2
        or len(ring) < 3
        or not np.all(np.isfinite(ring))
    ):
        return issues + ["FacePoints Coordinate: invalid authored perimeter"]
    tolerance = 8 * np.spacing(max(1.0, float(np.max(np.abs(ring)))))
    origin = ring[0].copy()
    ring = ring - origin
    points = points - origin
    import shapely

    # Native rings can encode holes with doubled connecting edges. Noding and
    # build_area recover polygonal interiors without admitting those connector
    # lines as domain. This also honors reversed rings and nested holes.
    domain = shapely.build_area(
        shapely.node(shapely.LineString(np.vstack([ring, ring[0]])))
    )
    if domain.is_empty or not domain.is_valid:
        return issues + ["FacePoints Coordinate: invalid authored perimeter"]
    domain = domain.buffer(tolerance)
    shapely.prepare(domain)
    if not np.all(shapely.covers(domain, shapely.points(points))):
        issues.append("FacePoints Coordinate: points outside authored perimeter")
    faces = area["Faces FacePoint Indexes"][()]
    info = area["Faces Perimeter Info"][()]
    values = area["Faces Perimeter Values"][()]
    if values.dtype.kind != "f" or values.dtype.itemsize != 8:
        return issues + [
            "Faces Perimeter Values: unsupported native coordinate precision"
        ]
    values = values - origin
    if not np.all(shapely.covers(domain, shapely.points(values))):
        issues.append("Faces Perimeter Values: points outside authored perimeter")
    # Topology/ranges were checked before this function. Resolve the same
    # endpoint + indexed intermediates + endpoint sequence as HdfMesh. Never
    # use an endpoint chord for a bent boundary face. Batches bound GEOS memory;
    # prepared, vectorized coverage checks every interior/boundary segment.
    for first in range(0, len(faces), 32768):
        last = min(first + 32768, len(faces))
        packed = info[first:last].astype(np.int64)
        counts = packed[:, 1] + 2
        starts = np.cumsum(counts) - counts
        coordinates = np.empty((int(counts.sum()), 2), dtype=np.float64)
        coordinates[starts] = points[faces[first:last, 0]]
        coordinates[starts + counts - 1] = points[faces[first:last, 1]]
        owners = np.repeat(np.arange(last - first), packed[:, 1])
        offset = int(packed[0, 0])
        stop = int(packed[-1, 0] + packed[-1, 1])
        slots = np.arange(offset, stop) - packed[owners, 0] + 1
        coordinates[starts[owners] + slots] = values[offset:stop]
        lines = shapely.linestrings(
            coordinates, indices=np.repeat(np.arange(last - first), counts)
        )
        if not np.all(shapely.covers(domain, lines)):
            issues.append("Faces Perimeter: face segments outside authored perimeter")
            break
    return issues


def validate(
    geometry_path: Path, hdf_path: Path, expected: dict, started: float
) -> tuple[list[str], list[str], dict]:
    """Verify unchanged authored inputs and complete products for the current mesh."""
    from .GeomMesh import _mesh_hdf_consistency_issues

    changed = []
    missing = []
    evidence = {
        "schema": "ras-geometry-completion/v1",
        "areas": {},
        "text_sha256": expected["text_sha256"],
    }
    if (
        hashlib.sha256(geometry_path.read_bytes()).hexdigest()
        != expected["text_sha256"]
    ):
        changed.append("geometry text")
    if not expected.get("contract_qualified", True):
        evidence.update(
            status="not_qualified_for_structures",
            reason_code="GEOMETRY_COMPLETION_NOT_QUALIFIED_FOR_STRUCTURES",
            message="completion contract not qualified for structures",
            inputs_preserved=None,
            products_complete=False,
        )
        return changed, [], evidence
    if not hdf_path.exists():
        return changed, ["geometry HDF"], evidence
    if hdf_path.stat().st_mtime < started - 2:
        missing.append("geometry HDF not freshly written")
    with h5py.File(hdf_path, "r") as hdf:
        for path, digest in expected["inputs"].items():
            same = path in hdf and (
                _projection_equal(expected["projections"][path], hdf[path][()])
                if path in expected.get("projections", {})
                else _digest(hdf[path][()]) == digest
            )
            if not same:
                changed.append(path)
        for key, digest in expected["attributes"].items():
            path, name = key.rsplit("@", 1)
            if (
                path not in hdf
                or name not in hdf[path].attrs
                or not (
                    _projection_equal(
                        expected["projections"][key], hdf[path].attrs[name]
                    )
                    if key in expected.get("projections", {})
                    else _digest(hdf[path].attrs[name]) == digest
                )
            ):
                changed.append(key)
        for path, features in expected["feature_geometry"].items():
            changed.extend(_feature_issues(hdf, path, features))
        if "Geometry/GeomPreprocess" not in hdf or not len(
            hdf["Geometry/GeomPreprocess"]
        ):
            missing.append("Geometry/GeomPreprocess")

        def require(path, rows=None, columns=None):
            if path not in hdf or not isinstance(hdf[path], h5py.Dataset):
                missing.append(path)
                return None
            obj = hdf[path]
            if (rows is not None and (not obj.shape or obj.shape[0] != rows)) or (
                columns is not None and (len(obj.shape) != 2 or obj.shape[1] != columns)
            ):
                missing.append(f"{path}: invalid shape {obj.shape}")
                return None
            return obj

        def pair(path, family, rows, columns, active_rows=None):
            info = require(f"{path}/{family} Info", rows, 2)
            values = require(f"{path}/{family} Values", columns=columns)
            if info is None or values is None:
                return
            spans = info[()]
            active = spans if active_rows is None else spans[:active_rows]
            if (
                np.any(spans < 0)
                or np.any(spans[:, 0] + spans[:, 1] > len(values))
                or np.any(active[:, 1] == 0)
            ):
                missing.append(f"{path}/{family}: invalid packed ranges")

        def attachments(
            path,
            table,
            count,
            identity,
            index_field,
            required_ids=None,
            allowed_areas=None,
        ):
            required_ids = (
                set(range(count)) if required_ids is None else set(required_ids)
            )
            if not required_ids and f"{path}/{table}" not in hdf:
                return
            obj = require(f"{path}/{table}")
            if obj is None:
                return
            fields = obj.dtype.names or ()
            if identity not in fields or index_field not in fields:
                missing.append(f"{path}/{table}: invalid attachment schema")
                return
            data = obj[()]
            identifiers = data[identity]
            if (
                np.any(identifiers < 0)
                or np.any(identifiers >= count)
                or not required_ids.issubset(set(identifiers))
            ):
                missing.append(
                    f"{path}/{table}: invalid or missing feature attachments"
                )
            attrs = hdf.get(f"{path}/Attributes")
            area_field = next(
                (
                    field
                    for field in ("SA-2D", "2D Area Name")
                    if attrs is not None and field in (attrs.dtype.names or ())
                ),
                None,
            )
            if area_field is None:
                missing.append(f"{path}/{table}: missing area associations")
                return
            for fid in {int(v) for v in identifiers if 0 <= v < count}:
                area_name = (
                    bytes(attrs[area_field][fid]).rstrip(b"\x00").decode().strip()
                )
                if allowed_areas is not None and area_name not in allowed_areas[fid]:
                    missing.append(
                        f"{path}/{table}: attachment outside authored region interaction"
                    )
                area = evidence["areas"].get(area_name)
                limit = (
                    None
                    if area is None
                    else area[
                        "faces" if index_field == "Face Index" else "interior_cells"
                    ]
                )
                indices = data[index_field][identifiers == fid]
                if limit is None or np.any(indices < 0) or np.any(indices >= limit):
                    missing.append(f"{path}/{table}: indexes outside current mesh")

        for name, source in expected["areas"].items():
            if not source.get("seed_count"):
                missing.append(
                    f"{AREA}/{name}: authored 2D area has no computation points"
                )
                continue
            path = f"{AREA}/{name}"
            current_seeds = expected["seed_points"][name]
            collection = hdf.get(AREA)
            if collection is None or any(
                key not in collection
                for key in ("Attributes", "Cell Info", "Cell Points")
            ):
                changed.append(f"{AREA}: missing authored computation points")
            else:
                attrs = collection["Attributes"]
                names = [
                    bytes(value).rstrip(b"\x00").decode().strip()
                    for value in attrs["Name"]
                ]
                if names.count(name) != 1:
                    changed.append(f"{path}: authored area identity changed")
                else:
                    index = names.index(name)
                    start, count = (int(v) for v in collection["Cell Info"][index, :2])
                    actual = collection["Cell Points"][start : start + count]
                    authored = expected["seed_points"][name]
                    # Native decimal parsing can differ from Python by one ULP.
                    # Bind only the regenerated mirror proven to represent the
                    # current text; never retain an incoming parent seed array.
                    if (
                        actual.shape != authored.shape
                        or actual.dtype.kind != "f"
                        or actual.dtype.itemsize != 8
                        or not np.all(np.isfinite(actual))
                        or not np.all(np.isfinite(authored))
                        or not np.all(
                            np.abs(actual - authored) <= np.abs(np.spacing(authored))
                        )
                    ):
                        changed.append(f"{path}: authored computation points changed")
                    else:
                        current_seeds = actual
            centers = require(f"{path}/Cells Center Coordinate", columns=2)
            faces = require(f"{path}/Faces FacePoint Indexes", columns=2)
            points = require(f"{path}/FacePoints Coordinate", columns=2)
            if centers is None or faces is None or points is None:
                continue
            cells, face_count = len(centers), len(faces)
            if cells < int(source["seed_count"]):
                missing.append(
                    f"{path}: fewer total cells than authored interior cells"
                )
            if cells == 0 or face_count == 0:
                missing.append(f"{path}: empty topology")
                continue
            if np.any(faces[()] < 0) or np.any(faces[()] >= len(points)):
                missing.append(f"{path}: invalid face point indexes")
            cell_indexes = require(f"{path}/Faces Cell Indexes", face_count, 2)
            if cell_indexes is not None and (
                np.any(cell_indexes[()] < 0) or np.any(cell_indexes[()] >= cells)
            ):
                missing.append(f"{path}: invalid face cell indexes")
            for product in CELL_PRODUCTS[:3]:
                # Complete topology is required even when all hydraulic property
                # arrays happen to be present and correctly sized.
                require(f"{path}/{product}", cells)
            for topology, rows, columns in (
                ("Cells Face and Orientation Info", cells, 2),
                ("Cells Face and Orientation Values", None, 2),
                ("Cells FacePoint Indexes", cells, None),
                ("Faces NormalUnitVector and Length", face_count, 3),
                ("Faces Perimeter Info", face_count, 2),
                ("Faces Perimeter Values", None, 2),
                ("FacePoints Cell Info", len(points), 2),
                ("FacePoints Cell Index Values", None, None),
                ("FacePoints Face and Orientation Info", len(points), 2),
                ("FacePoints Face and Orientation Values", None, 2),
                ("FacePoints Is Perimeter", len(points), None),
            ):
                require(f"{path}/{topology}", rows, columns)
            topology_issues = _topology_issues(hdf[path])
            missing.extend(f"{path}/{issue}" for issue in topology_issues)
            if not topology_issues:
                missing.extend(
                    f"{path}/{issue}"
                    for issue in _mesh_binding_issues(
                        hdf[path],
                        current_seeds,
                        expected["perimeters"][name],
                    )
                )
            for product in FACE_PRODUCTS[2:]:
                require(f"{path}/{product}", face_count)
            pair(path, "Cells Volume Elevation", cells, 2, int(source["seed_count"]))
            pair(path, "Faces Area Elevation", face_count, 4)
            area = hdf[path]
            # Infiltration has one value per interior cell, excluding ghost cells.
            interior = int(source["seed_count"])
            for family, association in (
                ("Infiltration", "Infiltration Filename"),
                ("Percent Impervious", "Percent Impervious Filename"),
            ):
                associated = bool(
                    _semantic(
                        area.attrs.get(
                            association, hdf["Geometry"].attrs.get(association, b"")
                        )
                    )
                )
                if not associated:
                    continue
                group = area.get(family)
                if group is None or not len(group):
                    missing.append(f"{path}/{family}")
                    continue
                require(f"{path}/{family}/Cell Center Classifications", interior)
                require(f"{path}/{family}/Face Center Classifications", face_count)
                if family == "Infiltration":
                    require(f"{path}/{family}/Properties")
                    method = expected["infiltration_methods"].get(name)
                    if method not in INFILTRATION_PRODUCTS:
                        missing.append(f"{path}/{family}: unverified associated method")
                    else:
                        for product in INFILTRATION_PRODUCTS[method]:
                            require(f"{path}/{family}/{product}", interior)
                else:
                    require(f"{path}/{family}/Percent Impervious", interior)
                for product, obj in group.items():
                    if isinstance(obj, h5py.Dataset) and product not in (
                        "Properties",
                        "Face Center Classifications",
                    ):
                        require(f"{path}/{family}/{product}", interior)
            evidence["areas"][name] = {
                "interior_cells": interior,
                "total_cells": cells,
                "faces": face_count,
            }

        for path, count in expected["features"].items():
            if not count:
                continue
            require(f"{path}/Attributes", count)
            if path.endswith("Boundary Condition Lines"):
                # Types choose the required family; an empty external table is not completion.
                attrs = hdf.get(f"{path}/Attributes")
                if attrs is not None and "Type" in (attrs.dtype.names or ()):
                    types = [bytes(v).rstrip(b"\x00").decode() for v in attrs["Type"]]
                    for kind, table in (
                        ("External", "External Faces"),
                        ("Internal", "Internal Cells"),
                        ("Internal", "Internal Faces"),
                    ):
                        ids = [i for i, value in enumerate(types) if value == kind]
                        if ids:
                            obj = require(f"{path}/{table}")
                            if obj is not None and (
                                "BC Line ID" not in (obj.dtype.names or ())
                                or not set(ids).issubset(set(obj["BC Line ID"]))
                            ):
                                missing.append(
                                    f"{path}/{table}: missing line attachments"
                                )
                            if obj is not None:
                                # Only the corresponding type must have rows;
                                # other IDs remain valid and bounded by mesh.
                                all_ids = (
                                    {int(v) for v in obj["BC Line ID"]}
                                    if "BC Line ID" in (obj.dtype.names or ())
                                    else set()
                                )
                                if not all_ids.issubset(set(range(count))):
                                    missing.append(
                                        f"{path}/{table}: invalid line indexes"
                                    )
                                field = (
                                    "Face Index" if "Faces" in table else "Cell Index"
                                )
                                if field not in (obj.dtype.names or ()):
                                    missing.append(f"{path}/{table}: missing {field}")
                                else:
                                    for fid in all_ids & set(range(count)):
                                        area_name = (
                                            bytes(attrs["SA-2D"][fid])
                                            .rstrip(b"\x00")
                                            .decode()
                                            .strip()
                                        )
                                        area = evidence["areas"].get(area_name)
                                        limit = (
                                            None
                                            if area is None
                                            else area[
                                                "faces"
                                                if field == "Face Index"
                                                else "interior_cells"
                                            ]
                                        )
                                        data = obj[()]
                                        indices = data[field][data["BC Line ID"] == fid]
                                        if (
                                            limit is None
                                            or np.any(indices < 0)
                                            or np.any(indices >= limit)
                                        ):
                                            missing.append(
                                                f"{path}/{table}: indexes outside current mesh"
                                            )
                    if any(t not in ("Internal", "External") for t in types):
                        missing.append(f"{path}/Attributes: invalid BC Type")
                else:
                    missing.append(f"{path}/Attributes: missing BC Type")
            elif path.endswith("Reference Lines"):
                attachments(
                    path, "Internal Cells", count, "Reference Line ID", "Cell Index"
                )
                attachments(
                    path, "Internal Faces", count, "Reference Line ID", "Face Index"
                )
                pair(path, "Terrain Profiles", count, 2)
            elif path.endswith("Structures"):
                if f"{path}/Property Tables" not in hdf or not len(
                    hdf[f"{path}/Property Tables"]
                ):
                    missing.append(f"{path}/Property Tables")
        if expected["manning_regions"]:
            path = "Geometry/Land Cover (Manning's n)"
            changed.extend(
                _feature_issues(hdf, path, expected["manning_regions"], "Polygon")
            )
            count = len(expected["manning_regions"])
            require(f"{path}/Attributes", count)
            interactions = expected["manning_region_interactions"]
            evidence["manning_region_interactions"] = interactions
            active = [i for i, region in enumerate(interactions) if region["areas"]]
            for table, field in (
                ("External Faces", "Face Index"),
                ("Internal Faces", "Face Index"),
                ("Internal Cells", "Cell Index"),
            ):
                attachments(
                    path,
                    table,
                    count,
                    "Region ID",
                    field,
                    active,
                    {i: region["areas"] for i, region in enumerate(interactions)},
                )
    if expected["areas"]:
        changed.extend(_mesh_hdf_consistency_issues(geometry_path, hdf_path))
    evidence.update(inputs_preserved=not changed, products_complete=not missing)
    return sorted(set(changed)), sorted(set(missing)), evidence
