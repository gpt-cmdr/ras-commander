"""Isolated, reviewable adapter; all graph/ring/region kernels execute in Rust.

HDF interpretation and CRS metadata use ras-commander. NativeAnalysis owns an
immutable snapshot: construct a new one after source changes. Explicit wetness
policy is required. No global file cache or Python per-cell polygonization.
"""
from collections import Counter
from pathlib import Path
import math
import time

import numpy as np
from ras_commander import HdfBase, HdfMesh, HdfResultsMesh, get_logger, log_call
import ras_commander_fast_hdf as rust_fluvial

logger = get_logger(__name__)
LABELS = ("unclassified", "fluvial", "pluvial", "ambiguous", "invalid", "dry", "missing_time")
# Per-process count of native kernel invocations; tests use it to prove that
# public calls really execute Rust rather than a Python fallback.
NATIVE_CALLS = Counter()


def _native(name, *args, **kwargs):
    NATIVE_CALLS[name] += 1
    return getattr(rust_fluvial, name)(*args, **kwargs)


def _append_face_ring(points, endpoint_a, endpoint_b, coordinates):
    """Preserve endpoint IDs, removing only exact repeated perimeter vertices.

    Intermediate duplicate XY adds a zero-length segment but no geometry. This
    never merges distinct source FacePoints or applies a distance tolerance.
    """
    start=tuple(points[endpoint_a]); end=tuple(points[endpoint_b])
    if tuple(coordinates[0])!=start or tuple(coordinates[-1])!=end:
        raise ValueError("face geometry endpoint identity mismatch")
    intermediate=[]; previous=start
    for value in coordinates[1:-1]:
        coord=tuple(map(float,value))
        if not all(map(math.isfinite,coord)):
            raise ValueError("nonfinite face perimeter coordinate")
        if coord!=previous:
            intermediate.append(coord); previous=coord
    if intermediate and intermediate[-1]==end:
        intermediate.pop()
    ring=[endpoint_a]
    for coord in intermediate:
        ring.append(len(points)); points.append(list(coord))
    ring.append(endpoint_b)
    return ring,len(coordinates)-2-len(intermediate)


def integer_milliseconds(value):
    """Checked epoch milliseconds without a nanosecond conversion (year3000)."""
    import pandas as pd
    if pd.isna(value):
        return 0, False
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        raise ValueError("HEC-RAS local peak times must be timezone-naive")
    raw = stamp.asm8
    converted = raw.astype("datetime64[ms]")
    if converted.astype(raw.dtype) != raw:
        raise ValueError("peak time has sub-millisecond precision")
    result = int(converted.astype(np.int64))
    if result == -(2**63):
        raise ValueError("datetime conversion produced NaT sentinel")
    return result, True


class Analysis:
    def __setattr__(self, name, value):
        if getattr(self,"_sealed",False):
            raise AttributeError("Analysis is an immutable source snapshot")
        object.__setattr__(self,name,value)

    @classmethod
    @log_call
    def from_hdf(cls, path, *, wet_policy, wet_masks=None, selection=None, require_peaks=True,
                 invalid_geometry="strict", peak_round_to="1ms", retain_faces=False):
        """Cache one immutable mesh/peak snapshot. `selection` gives induced subgraphs.

        wet_policy='all' is an explicit timing-only analysis, not an assertion
        that every cell floods. 'provided' requires {(mesh_name,cell_id): bool}.
        Geometry-only HDFs must opt in with require_peaks=False; no peak times
        are fabricated and labels then correctly remain missing_time.
        invalid_geometry='quarantine' explicitly audits malformed cell rings,
        labels them invalid/barriers, and omits their geometry. It never repairs
        source coordinates. The default 'strict' retains lazy rejection.
        peak_round_to is passed to HdfResultsMesh.get_mesh_max_ws; legacy
        HdfFluvialPluvial uses that API's "100ms" default. retain_faces keeps
        each graph edge's source face polylines for boundary-line output.
        """
        if invalid_geometry not in ("strict","quarantine"):
            raise ValueError("invalid_geometry must be strict or quarantine")
        if wet_policy not in ("all", "provided"):
            raise ValueError("wet_policy must be all or provided")
        if wet_policy == "provided" and wet_masks is None:
            raise ValueError("provide wet_masks for wet_policy=provided")
        path = Path(path).resolve()
        source_stat=path.stat()
        fingerprint=(source_stat.st_size,source_stat.st_mtime_ns)
        start = time.perf_counter()
        counts = HdfBase.get_2d_flow_area_names_and_counts(path)
        if not counts:
            raise ValueError("HDF has no physical mesh cells")
        if selection is not None:
            selection=set(selection)
            count_map=dict(counts)
            if not selection or any(name not in count_map or type(cell) is not int or not 0<=cell<int(count_map[name])
                                    for name,cell in selection):
                raise ValueError("selection must contain known physical cell identities")
        face_frame = HdfMesh.get_mesh_cell_faces(path)
        if face_frame.empty:
            raise ValueError("HDF face API returned no geometry")
        projection = HdfBase.get_projection(path)
        from pyproj import CRS
        crs = CRS.from_user_input(projection)
        if not crs.is_projected or len(crs.axis_info)<2:
            raise ValueError("area operations require a projected CRS")
        factors = [axis.unit_conversion_factor for axis in crs.axis_info[:2]]
        if not all(math.isfinite(f) and f>0 for f in factors) or factors[0] != factors[1]:
            raise ValueError("inconsistent projected axis units")
        peaks = None
        if require_peaks:
            peaks = HdfResultsMesh.get_mesh_max_ws(path, round_to=peak_round_to)
            if peaks.empty:
                raise ValueError("computed HDF returned an empty peak table")
            if peaks.duplicated(["mesh_name", "cell_id"]).any():
                raise ValueError("duplicate composite peak identity")
        peak_map = {} if peaks is None else {(str(m),int(c)): t for m,c,t in
                    peaks[["mesh_name","cell_id","maximum_water_surface_time"]].itertuples(index=False,name=None)}
        points=[]; meshes=[]; all_rings=[]; masks=[]; cell_ids=[]; face_cells=[]
        ring_seconds=0.0; normalized_perimeter_vertices=0; edge_faces={}
        for mesh_id,(name,count) in enumerate(counts):
            topology = HdfMesh.get_mesh_sloped_topology(path,name)
            if not topology:
                raise ValueError(f"topology API failed for {name}")
            n = topology["n_cells"]; count=int(count)
            if not 0<count<=n:
                raise ValueError("invalid physical cell count")
            physical=[i<count and (selection is None or (name,i) in selection) for i in range(n)]
            # Preserve source FacePoint identity, including distinct co-located
            # vertices. Curved perimeter vertices belong to their physical face
            # and are shared by its two incident cells, never welded by XY.
            point_base=len(points)
            source_points=np.asarray(topology["facepoint_coords"][:,:2],dtype=float)
            if not np.isfinite(source_points).all():
                raise ValueError("nonfinite face coordinate")
            points.extend(source_points.tolist())
            lines=face_frame[face_frame.mesh_name==name].set_index("face_id").geometry
            if len(lines)!=topology["n_faces"] or not lines.index.is_unique:
                raise ValueError("face geometry identity mismatch")
            needed=set()
            for row in np.flatnonzero(physical):
                offset,length=map(int,topology["cell_face_info"][row,:2])
                needed.update(map(int,topology["cell_face_values"][offset:offset+length,0]))
            face_rings=[]
            for i in range(topology["n_faces"]):
                if i not in needed:
                    face_rings.append([]); continue
                a,b=map(int,topology["face_facepoints"][i])
                if not 0<=a<len(source_points) or not 0<=b<len(source_points):
                    raise ValueError("face endpoint outside source points")
                coords=[tuple(map(float,c[:2])) for c in lines.loc[i].coords]
                ring,removed=_append_face_ring(points,point_base+a,point_base+b,coords)
                normalized_perimeter_vertices+=removed
                face_rings.append(ring)
                if retain_faces:
                    left,right=map(int,topology["face_cells"][i,:2])
                    if 0<=left<n and 0<=right<n and physical[left] and physical[right]:
                        key=(mesh_id,min(left,right),max(left,right))
                        edge_faces.setdefault(key,[]).append((i,tuple(coords)))
            begin=time.perf_counter()
            rings=_native("assemble_rings",topology["cell_face_info"][:,:2].tolist(),
                    topology["cell_face_values"][:,:2].tolist(),face_rings,physical)
            ring_seconds += time.perf_counter()-begin
            meshes.append(name); all_rings.append(rings); masks.append(physical)
            cell_ids.append(list(range(n))); face_cells.append(topology["face_cells"].tolist())
        graph_start=time.perf_counter()
        keys,offsets,neighbors,sources,diagnostics=_native("face_graph",list(range(len(meshes))),cell_ids,masks,face_cells)
        graph_seconds=time.perf_counter()-graph_start
        times=[]; present=[]; wet=[]; rings=[]; identities=[]
        for mesh_index,row in sources:
            identity=(meshes[mesh_index],row); identities.append(identity)
            value,valid=integer_milliseconds(peak_map.get(identity))
            times.append(value); present.append(valid)
            if wet_policy=="provided" and (identity not in wet_masks or not isinstance(wet_masks[identity],(bool,np.bool_))):
                raise ValueError(f"wet mask must supply a bool for {identity}")
            wet.append(True if wet_policy=="all" else bool(wet_masks[identity]))
            rings.append(all_rings[mesh_index][row])
        valid=[True]*len(keys)
        quarantined=[]
        if invalid_geometry=="quarantine":
            for index,reason in _native("validate_geometry",points,rings):
                valid[index]=False
                quarantined.append((*identities[index],reason))
            if quarantined:
                logger.warning("Quarantining %s malformed source cells without repair: %s",len(quarantined),quarantined)
        obj=cls.__new__(cls)
        obj.native=_native("NativeAnalysis",keys,offsets,neighbors,times,valid,wet,present,points,rings)
        obj.identities=tuple(identities); obj.keys=tuple(keys)
        obj.offsets=tuple(offsets); obj.neighbors=tuple(neighbors)
        obj.points=tuple(map(tuple,points)); obj.rings=tuple(map(tuple,rings))
        obj.times=tuple(times); obj.present=tuple(present); obj.wet=tuple(wet)
        obj.meshes=tuple(meshes); obj.crs=crs; obj.linear_unit_to_m=factors[0]; obj.path=path
        obj.valid=tuple(valid); obj.invalid_geometry=invalid_geometry
        obj.quarantined_cells=tuple(quarantined)
        obj.sources=tuple(map(tuple,sources)); obj.edge_faces=edge_faces if retain_faces else None
        obj.peak_round_to=peak_round_to
        obj.metadata=HdfBase.get_attrs(path,"/")
        obj.setup={"total_seconds":time.perf_counter()-start,"ring_assembly_seconds":ring_seconds,
                   "bound_face_graph_seconds":graph_seconds,
                   "topology_diagnostics":diagnostics,"physical_selected":len(keys),"wet_policy":wet_policy,
                   "geometry_only":not require_peaks}
        obj.setup["invalid_geometry_policy"]=invalid_geometry
        obj.setup["quarantined_cells"]=len(quarantined)
        obj.setup["normalized_redundant_perimeter_vertices"]=normalized_perimeter_vertices
        end_stat=path.stat()
        if fingerprint!=(end_stat.st_size,end_stat.st_mtime_ns):
            raise ValueError("HDF changed while constructing the snapshot")
        obj.source_fingerprint=fingerprint
        obj._sealed=True
        return obj

    @log_call
    def classify(self, delta_t_ms, tolerance_ms, seed_overrides=()):
        """Classify cached peaks; reject lossy/coerced thresholds before binding.

        seed_overrides lists (vertex, 1|2) labels for conflicting seeds only;
        native rejects any vertex that is not a conflicting seed.
        """
        for value in (delta_t_ms,tolerance_ms):
            if type(value) is not int or not 0<=value<=2**64-1:
                raise ValueError("thresholds must be nonnegative u64 integer milliseconds")
        overrides=[(int(i),int(label)) for i,label in seed_overrides]
        NATIVE_CALLS["NativeAnalysis.classify"]+=1
        labels,diagnostics,seconds=self.native.classify(delta_t_ms,tolerance_ms,overrides)
        return list(labels),diagnostics,seconds

    @log_call
    def polygons(self, labels, *, min_area_acres=0.0, area_filter_policy="none"):
        """Lazy geometry; removal requires area_filter_policy='remove' explicitly.

        Filtering removes polygons, unlike legacy Python's class-swapping option.
        The default 'none' preserves all geometry and rejects a nonzero minimum.
        The existing HdfFluvialPluvial public API and its defaults are unchanged.
        """
        if area_filter_policy not in ("none","remove"):
            raise ValueError("area_filter_policy must be none or remove; legacy class-swapping remains in HdfFluvialPluvial")
        if not math.isfinite(min_area_acres) or min_area_acres<0:
            raise ValueError("min_area_acres must be finite and nonnegative")
        if area_filter_policy=="none" and min_area_acres!=0:
            raise ValueError("nonzero min_area_acres requires explicit area_filter_policy='remove'")
        labels=list(labels)
        if any(isinstance(label,(bool,np.bool_)) or not isinstance(label,(int,np.integer)) or not 0<=int(label)<=6
               for label in labels):
            raise ValueError("labels must be integer classification codes 0 through 6")
        labels=list(map(int,labels))
        NATIVE_CALLS["NativeAnalysis.polygons"]+=1
        regions,diagnostics=self.native.polygons(labels,self.linear_unit_to_m,min_area_acres*4046.8564224,
                        exclude_invalid=self.invalid_geometry=="quarantine")
        diagnostics["area_filter_policy"]=area_filter_policy
        from shapely.geometry import Polygon
        import geopandas as gpd
        records=[]
        for mesh,label,polygons in regions:
            for shell,holes,area_m2 in polygons:
                records.append({"mesh_name":self.meshes[mesh],"classification":LABELS[label],
                                "area_acres":area_m2/4046.8564224,
                                "geometry":Polygon([self.points[i] for i in shell],
                                         [[self.points[i] for i in hole] for hole in holes])})
        frame=gpd.GeoDataFrame(records,columns=["mesh_name","classification","area_acres","geometry"],geometry="geometry",crs=self.crs)
        return frame,diagnostics

    def qualifying_edges(self, delta_t_ms):
        """Native (i, j) vertex pairs, i < j, meeting the seed predicate."""
        if type(delta_t_ms) is not int or not 0<=delta_t_ms<=2**64-1:
            raise ValueError("delta_t_ms must be a nonnegative u64 integer")
        NATIVE_CALLS["NativeAnalysis.qualifying_edges"]+=1
        return self.native.qualifying_edges(delta_t_ms)
