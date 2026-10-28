"""Internal: native fluvial/pluvial adapter behind ``HdfFluvialPluvial(engine=...)``.

**Not public API.** Use ``HdfFluvialPluvial.calculate_fluvial_pluvial_boundary``
and ``generate_fluvial_pluvial_polygons`` with ``engine="native"``/``"auto"``.
``Analysis``, ``LABELS``, ``integer_milliseconds`` and the ``NATIVE_CALLS``
counter (used by the qualification tests to prove that Rust ran) may change or
disappear in any release; nothing here is exported (``__all__`` is empty).

Isolated, reviewable adapter; all graph/ring/region kernels execute in Rust.
HDF interpretation and CRS metadata use ras-commander. NativeAnalysis owns an
immutable snapshot: construct a new one after source changes. Explicit wetness
policy is required. No global file cache or Python per-cell polygonization.
The extension is obtained through ``fast_hdf``'s availability and API-version
check, so an incompatible ``ras_commander_fast_hdf`` raises ImportError here.
"""
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
import math
import time

import numpy as np
from ras_commander import HdfBase, HdfMesh, HdfResultsMesh, get_logger, log_call
from ras_commander import fast_hdf as _fast_hdf

rust_fluvial, _failure, _import_exc = _fast_hdf._load_native()
if rust_fluvial is None:
    raise ImportError(_failure) from _import_exc

__all__ = []

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
    """Checked epoch milliseconds without a nanosecond conversion (year3000).

    Lightweight scalar conversion used in per-cell loops; intentionally no
    ``log_call`` here. The public bulk analysis boundary logs once instead.
    Accepts the #548 time contract as is (``datetime64[ns]``, or ``[us]``
    beyond 2262): the integer is an internal kernel key only and never
    appears in any returned frame, so no datetime unit leaks into outputs.
    """
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


def _int_table(value, columns):
    """``value`` as an int64 table with at least ``columns`` columns, or None."""
    array=np.asarray(value)
    if array.ndim!=2 or array.shape[1]<columns or array.dtype.kind not in "iu":
        return None
    if array.dtype.kind=="u" and array.size and array.max()>np.iinfo(np.int64).max:
        return None
    return array.astype(np.int64,copy=False)


def _fast_face_rings(topology, lines, physical, points, point_base, n_points, mesh_id, n, edge_faces):
    """The per-face loop of ``Analysis.from_hdf`` for one mesh, vectorized.

    Returns ``(face_rings, removed)`` and appends to ``points`` (and, when
    given, ``edge_faces``) exactly what the loop appends, in the same order;
    faces with intermediate vertices still go through ``_append_face_ring``.
    Returns None, having changed nothing, for any input on which the loop
    could fail or behave differently (non-integer or out-of-range tables,
    face IDs that are not ``0..n_faces-1`` in order, non-LineString or short
    geometry, endpoint mismatch); the caller then runs the loop itself.
    """
    import shapely
    n_faces=int(topology["n_faces"])
    cell_info=_int_table(topology["cell_face_info"],2)
    cell_values=_int_table(topology["cell_face_values"],1)
    face_points=_int_table(topology["face_facepoints"],2)
    face_cells=_int_table(topology["face_cells"],2) if edge_faces is not None else None
    if (cell_info is None or cell_values is None or face_points is None
            or (edge_faces is not None and face_cells is None)
            or len(face_points)<n_faces or (face_cells is not None and len(face_cells)<n_faces)
            or len(physical)>len(cell_info)
            or not np.array_equal(lines.index.to_numpy(),np.arange(n_faces))):
        return None
    rows=np.flatnonzero(physical)
    starts,lengths=cell_info[rows,0],cell_info[rows,1]
    if (starts<0).any() or (lengths<0).any() or (starts+lengths>len(cell_values)).any():
        return None
    total=int(lengths.sum())
    within=np.arange(total)-np.repeat(np.cumsum(lengths)-lengths,lengths)
    referenced=cell_values[np.repeat(starts,lengths)+within,0]
    needed=np.zeros(n_faces,dtype=bool)
    needed[referenced[(referenced>=0)&(referenced<n_faces)]]=True
    faces=np.flatnonzero(needed)
    a,b=face_points[faces,0],face_points[faces,1]
    if ((a<0)|(a>=n_points)|(b<0)|(b>=n_points)).any():
        return None
    geometry=np.asarray(lines.array,dtype=object)[faces]
    if not (shapely.get_type_id(geometry)==shapely.GeometryType.LINESTRING).all():
        return None
    coordinates,owner=shapely.get_coordinates(geometry,return_index=True)
    sizes=np.bincount(owner,minlength=len(faces))
    if (sizes<2).any():
        return None
    offsets=np.zeros(len(faces)+1,dtype=np.int64)
    np.cumsum(sizes,out=offsets[1:])
    source=np.asarray(points[point_base:point_base+n_points],dtype=float).reshape(-1,2)
    straight=sizes==2
    if not (np.array_equal(coordinates[offsets[:-1]][straight],source[a[straight]])
            and np.array_equal(coordinates[offsets[1:]-1][straight],source[b[straight]])):
        return None
    face_rings=[[] for _ in range(n_faces)]
    pairs=np.stack([a+point_base,b+point_base],axis=1).tolist()
    removed=0
    curved=set(np.flatnonzero(~straight).tolist())
    for k,i in enumerate(faces.tolist()):
        if k in curved:
            coords=[tuple(c) for c in coordinates[offsets[k]:offsets[k+1]].tolist()]
            ring,dropped=_append_face_ring(points,pairs[k][0],pairs[k][1],coords)
            removed+=dropped
            face_rings[i]=ring
        else:
            face_rings[i]=pairs[k]
    if edge_faces is not None:
        left,right=face_cells[faces,0],face_cells[faces,1]
        inside=(left>=0)&(left<n)&(right>=0)&(right<n)
        mask=np.asarray(physical,dtype=bool)
        inside[inside]&=mask[left[inside]]&mask[right[inside]]
        k=np.flatnonzero(inside)
        edge_faces.add_mesh(mesh_id,np.minimum(left[k],right[k]),np.maximum(left[k],right[k]),
                            faces[k],coordinates,offsets[k],offsets[k+1])
    return face_rings,removed


class _EdgeFaces(Mapping):
    """``{(mesh_id, low_cell, high_cell): [(face_id, coords), ...]}``, built on lookup.

    The same mapping the per-face loop builds with ``setdefault`` (lists in
    face order, keys in first-face order, ``coords`` a tuple of ``(x, y)``
    float tuples), but a vectorized mesh is kept as packed arrays and a key's
    list is made only when it is looked up. Meshes the loop handles are
    written through ``setdefault`` into an ordinary dict.
    """

    def __init__(self):
        self._plain={}
        self._meshes={}

    def setdefault(self,key,default=None):
        return self._plain.setdefault(key,default)

    def add_mesh(self,mesh_id,low,high,face_ids,coordinates,starts,stops):
        low=np.asarray(low,dtype=np.int64); high=np.asarray(high,dtype=np.int64)
        combined=(low<<32)|high
        order=np.argsort(combined,kind="stable")
        self._meshes[mesh_id]=(combined[order],np.asarray(face_ids,dtype=np.int64)[order],
                               coordinates,np.asarray(starts)[order],np.asarray(stops)[order],
                               combined)

    def _span(self,key):
        if not (isinstance(key,tuple) and len(key)==3):
            return None
        mesh_id,low,high=key
        block=self._meshes.get(mesh_id)
        if block is None or type(low) is not int or type(high) is not int or not 0<=low<=high<2**31:
            return None
        combined=block[0]
        target=(low<<32)|high
        first=int(np.searchsorted(combined,target,side="left"))
        last=int(np.searchsorted(combined,target,side="right"))
        return (block,first,last) if last>first else None

    def __getitem__(self,key):
        if key in self._plain:
            return self._plain[key]
        span=self._span(key)
        if span is None:
            raise KeyError(key)
        (_, face_ids, coordinates, starts, stops, _), first, last = span
        return [(int(face_ids[k]),tuple(tuple(c) for c in coordinates[starts[k]:stops[k]].tolist()))
                for k in range(first,last)]

    def __contains__(self,key):
        return key in self._plain or self._span(key) is not None

    def _keys(self):
        meshes=sorted(set(self._meshes)|{key[0] for key in self._plain})
        for mesh_id in meshes:
            if mesh_id in self._meshes:
                combined=self._meshes[mesh_id][5]
                _,first=np.unique(combined,return_index=True)
                for value in combined[np.sort(first)].tolist():
                    yield (mesh_id,value>>32,value&0xFFFFFFFF)
            else:
                yield from (key for key in self._plain if key[0]==mesh_id)

    def __iter__(self):
        return self._keys()

    def __len__(self):
        return len(self._plain)+sum(len(np.unique(block[5])) for block in self._meshes.values())


def _fast_peak_times(sources, meshes, peaks):
    """``integer_milliseconds`` of every source cell's peak, vectorized.

    Returns ``(times, present)`` as the per-cell loop builds them, raising the
    loop's error for a sub-millisecond peak, or None (use the loop) when the
    peak times are not a timezone-naive NumPy datetime column or the keys are
    not plain names and nonnegative integer cell IDs.
    """
    count=len(sources)
    if peaks is None:
        return [0]*count,[False]*count
    column=peaks["maximum_water_surface_time"]
    stamps=column.to_numpy()
    if column.dtype.kind!="M" or stamps.dtype.kind!="M":
        return None
    names=peaks["mesh_name"].to_numpy(dtype=object)
    cells=peaks["cell_id"].to_numpy()
    if cells.dtype.kind not in "iu" or (len(cells) and cells.min()<0):
        return None
    if not all(type(name) is str for name in set(names.tolist())):
        return None
    pairs=np.asarray(sources,dtype=np.int64).reshape(-1,2) if count else np.empty((0,2),np.int64)
    if (pairs[:,1]<0).any():
        return None
    found=np.full(count,-1,dtype=np.int64)
    for mesh_index,mesh in enumerate(meshes):
        selected=np.flatnonzero(pairs[:,0]==mesh_index)
        if not len(selected):
            continue
        rows=np.flatnonzero(names==str(mesh))
        ids=cells[rows].astype(np.int64)
        wanted=pairs[selected,1]
        size=int(max(ids.max() if len(ids) else -1,wanted.max())+1)
        position=np.full(size,-1,dtype=np.int64)
        position[ids]=rows
        found[selected]=position[wanted]
    if not len(stamps):
        return [0]*count,[False]*count
    value=stamps[np.where(found>=0,found,0)]
    present=(found>=0)&~np.isnat(value)
    converted=value.astype("datetime64[ms]")
    if (converted[present].astype(value.dtype)!=value[present]).any():
        raise ValueError("peak time has sub-millisecond precision")
    times=np.where(present,converted.astype(np.int64),0)
    return times.tolist(),present.tolist()


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
            peaks = HdfResultsMesh.get_mesh_max_ws(
                path, round_to=peak_round_to, include_geometry=False
            )
            if peaks.empty:
                raise ValueError("computed HDF returned an empty peak table")
            if peaks.duplicated(["mesh_name", "cell_id"]).any():
                raise ValueError("duplicate composite peak identity")
        points=[]; meshes=[]; all_rings=[]; masks=[]; cell_ids=[]; face_cells=[]
        ring_seconds=0.0; normalized_perimeter_vertices=0; edge_faces=_EdgeFaces()
        for mesh_id,(name,count) in enumerate(counts):
            topology = HdfMesh.get_mesh_sloped_topology(path,name)
            if not topology:
                raise ValueError(f"topology API failed for {name}")
            n = topology["n_cells"]; count=int(count)
            if not 0<count<=n:
                raise ValueError("invalid physical cell count")
            if selection is None:
                physical=[True]*count+[False]*(n-count)
            else:
                physical=[i<count and (name,i) in selection for i in range(n)]
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
            fast=_fast_face_rings(topology,lines,physical,points,point_base,len(source_points),
                                  mesh_id,n,edge_faces if retain_faces else None)
            if fast is not None:
                face_rings,removed=fast
                normalized_perimeter_vertices+=removed
            needed=set()
            for row in np.flatnonzero(physical) if fast is None else ():
                offset,length=map(int,topology["cell_face_info"][row,:2])
                needed.update(map(int,topology["cell_face_values"][offset:offset+length,0]))
            if fast is None:
                face_rings=[]
            for i in range(topology["n_faces"]) if fast is None else ():
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
        fast=_fast_peak_times(sources,meshes,peaks) if wet_policy=="all" else None
        if fast is None:
            peak_map = {} if peaks is None else {(str(m),int(c)): t for m,c,t in
                        peaks[["mesh_name","cell_id","maximum_water_surface_time"]].itertuples(index=False,name=None)}
        if fast is not None:
            times,present=fast
            identities=[(meshes[mesh_index],row) for mesh_index,row in sources]
            wet=[True]*len(identities)
            rings=[all_rings[mesh_index][row] for mesh_index,row in sources]
        for mesh_index,row in sources if fast is None else ():
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

    @log_call
    def qualifying_edges(self, delta_t_ms):
        """Native (i, j) vertex pairs, i < j, meeting the seed predicate."""
        if type(delta_t_ms) is not int or not 0<=delta_t_ms<=2**64-1:
            raise ValueError("delta_t_ms must be a nonnegative u64 integer")
        NATIVE_CALLS["NativeAnalysis.qualifying_edges"]+=1
        return self.native.qualifying_edges(delta_t_ms)
