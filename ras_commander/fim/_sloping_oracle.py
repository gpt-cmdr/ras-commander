"""Development-only native component oracle for plain sloping reconstruction.

The production Rust mapper must not depend on these installed HEC-RAS calls.
This private reader records versioned native intermediate values for tests.
"""

from pathlib import Path
import hashlib
import json

from .. import get_logger, log_call
from ..RasGeometryCompute import RasGeometryCompute, _LOCK

logger = get_logger(__name__)


def _sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@log_call
def capture_components(
    hdf_path, output_path, *, mesh_index=0, version="7.0.1", sample_cells=128
):
    """Read native Max-profile face/corner intermediates without saving geometry."""
    from .RasFim import RasFim

    hdf = Path(hdf_path).resolve(strict=True)
    output = Path(output_path).resolve()
    if output.exists():
        raise FileExistsError(output)
    RasFim.validate_2d_model(hdf)
    before = _sha256(hdf)
    with _LOCK:
        RasGeometryCompute._ensure_clr(version)
        import clr
        from System import Array, Int32, Single
        from RasMapperLib import RASResults, SharedData, MeshFV2D
        from RasMapperLib.Render import WaterSurfaceRenderer, SlopingFactors

        results = RASResults.TryIdentifyResultsFile(str(hdf))
        if results is None:
            raise ValueError("Native runtime could not identify the result HDF")
        geometry = None
        try:
            SharedData.SetSlopingRenderingMode()
            geometry = results.Geometry
            d2 = geometry.D2FlowArea
            mesh = d2.Mesh(mesh_index)
            renderer = WaterSurfaceRenderer(results)
            profile_values = renderer.PreReadHDFValues(Int32.MaxValue)
            cell_ws = profile_values.MeshCellWaterSurfaces[mesh_index]
            face_values = SlopingFactors.ComputeSlopingWSFaceFactors(mesh, cell_ws)
            location = d2.GetFaceLocationFunc(mesh_index)
            vertex_values = Array[Array[Single]](
                [
                    mesh.ComputeFacePointWSs(i, face_values, location)
                    for i in range(mesh.FacePointCount)
                ]
            )
            record = {
                "schema": "ras-commander-native-sloping-components/1",
                "runtime_version": version,
                "runtime_assembly": str(clr.GetClrType(RASResults).Assembly.FullName),
                "hdf_sha256": before,
                "mesh_index": mesh_index,
                "mesh_name": str(d2.GetFeatureName(mesh_index)),
                "use_face_centroid_adjustment": bool(
                    RASResults.UseFaceCentroidAdjustment
                ),
                "use_face_midside_caching": bool(MeshFV2D.USE_FACE_MIDSIDE_CACHING),
                "physical_cell_count": mesh.NonVirtualCellCount,
                "options": {
                    name: str(getattr(SharedData, name))
                    for name in (
                        "CellRenderMode",
                        "CellStencilMode",
                        "FacepointAdjustmentMode",
                        "ShallowBehaviorMode",
                        "UseDepthWeightedFaces",
                        "FaceWSMode",
                    )
                },
                "min_ws_plot_tolerance": float(RASResults.MinWSPlotTolerance),
                "cells": [],
                "faces": [],
                "vertices": [],
            }
            for i in range(mesh.CellCount):
                cell = mesh.Cell(i)
                record["cells"].append(
                    {
                        "point": [cell.Point.X, cell.Point.Y],
                        "minimum_elevation": float(cell.MinimumElevation),
                        "wse": float(cell_ws[i]),
                        "virtual": bool(mesh.CellIsVirtual(i)),
                        "faces": [int(x) for x in cell.Faces],
                        "corner_values": [
                            float(x) for x in mesh.GetFPLocalValues(i, vertex_values)
                        ],
                    }
                )
            for i in range(mesh.FaceCount):
                face = mesh.Faces[i]
                value = face_values[i]
                point = location(i)
                record["faces"].append(
                    {
                        "cells": [face.cellA, face.cellB],
                        "vertices": [face.fpA, face.fpB],
                        "minimum_elevation": float(face.MinimumElevation),
                        "perimeter": bool(mesh.FaceIsPerimeter(i)),
                        "application": [point.X, point.Y],
                        "values": [float(value.ValueA), float(value.ValueB)],
                        "connection": str(value.HydraulicConnection),
                        "connected": bool(value.IsHydraulicallyConnected),
                        "prev_a": face.GetFPPrev(face.cellA),
                        "next_a": face.GetFPNext(face.cellA),
                    }
                )
            for i in range(mesh.FacePointCount):
                vertex = mesh.FacePoints[i]
                record["vertices"].append(
                    {
                        "point": [vertex.Point.X, vertex.Point.Y],
                        "faces": [int(x) for x in vertex.Faces],
                        "ccw": [
                            vertex.CCWFaceByLocalIndex(j)
                            for j in range(vertex.Faces.Count)
                        ],
                        "cw": [
                            vertex.CWFaceByLocalIndex(j)
                            for j in range(vertex.Faces.Count)
                        ],
                        "values": [float(x) for x in vertex_values[i]],
                    }
                )
            record["pixel_samples"] = _pixel_samples(
                geometry,
                mesh,
                vertex_values,
                sample_cells,
            )
        finally:
            RasGeometryCompute._release_geometry(geometry)
        after = _sha256(hdf)
        if before != after:
            raise RuntimeError("Native component capture changed the result HDF")
        record["input_unchanged"] = True
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(record, indent=2, allow_nan=False), encoding="utf-8"
        )
    return output


def _pixel_samples(geometry, mesh, vertex_values, sample_count):
    """Reflect native private geometry weights and scalar paint, for tests only."""
    import clr
    from System import Activator, Array, Int32, Object, Single
    from System.Reflection import BindingFlags
    from System.Collections.Generic import List
    from RasMapperLib import RASGeometryMapPoints
    from RasMapperLib.Mapping import SlopingCellMap, SlopingCellPoint
    from RasMapperLib.Render import Renderer

    if sample_count <= 0:
        return []
    mapper = RASGeometryMapPoints(geometry)
    private = BindingFlags.NonPublic | BindingFlags.Instance
    weights_method = clr.GetClrType(RASGeometryMapPoints).GetMethod(
        "BensWeights", private
    )
    parameters = weights_method.GetParameters()
    paint = next(
        m
        for m in clr.GetClrType(Renderer).GetMethods(
            BindingFlags.NonPublic | BindingFlags.Static
        )
        if m.Name == "FacepointWeightedPaint"
        and m.GetParameters()[1].ParameterType == clr.GetClrType(Array[Single])
    )
    samples = []
    stride = max(1, mesh.NonVirtualCellCount // sample_count)
    for cell_id in list(range(0, mesh.NonVirtualCellCount, stride))[:sample_count]:
        cell = mesh.Cell(cell_id)
        face = mesh.Faces[cell.Faces[0]]
        first = mesh.FacePoints[face.GetFPPrev(cell_id)].Point
        second = mesh.FacePoints[face.GetFPNext(cell_id)].Point
        points = [
            (cell.Point.X, cell.Point.Y),
            (first.X, first.Y),
            ((first.X + second.X) * 0.5, (first.Y + second.Y) * 0.5),
        ]
        for x, y in points:
            point = Activator.CreateInstance(parameters[0].ParameterType)
            point.X, point.Y = x, y
            buffer = Activator.CreateInstance(
                parameters[4].ParameterType,
                Array[Object]([Int32(cell.Faces.Count)]),
            )
            args = Array[Object](
                [point, mesh, Int32(cell_id), Single(0), buffer, None, None]
            )
            weights_method.Invoke(mapper, args)
            weights = args[5]
            map_points = List[SlopingCellPoint]()
            map_points.Add(SlopingCellPoint(0, weights))
            mapped_cell = SlopingCellMap(cell_id, map_points)
            values = mesh.GetFPLocalValues(cell_id, vertex_values)
            output = Array[Single]([Single(-9999)])
            paint.Invoke(None, Array[Object]([mapped_cell, values, output, None]))
            samples.append(
                {
                    "cell": cell_id,
                    "point": [x, y],
                    "weights": [float(v) for v in weights],
                    "wse": float(output[0]),
                }
            )
    return samples
