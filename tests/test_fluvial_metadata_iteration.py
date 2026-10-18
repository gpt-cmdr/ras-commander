"""Regression for quadratic GeoDataFrame metadata copying during adjacency."""
import geopandas as gpd
from shapely.geometry import box
from ras_commander import HdfFluvialPluvial

class CopyCounter:
    copies = 0
    def __deepcopy__(self, memo):
        type(self).copies += 1
        return self

def test_adjacency_preserves_metadata_without_per_cell_deepcopy():
    # A chain has independently known edges. Diagnostics model the real mesh
    # reader's per-cell attrs; the guard tests copy complexity, not wall time.
    count = 64
    cells = gpd.GeoDataFrame({'cell_id': list(range(count))},
        geometry=[box(i, 0, i + 1, 1) for i in range(count)], crs='EPSG:3857')
    diagnostics = {'records': tuple(range(count)), 'probe': CopyCounter()}
    cells.attrs['cell_polygon_diagnostics'] = diagnostics
    CopyCounter.copies = 0
    adjacency, edges = HdfFluvialPluvial._process_cell_adjacencies(cells)
    assert dict(adjacency) == {i: [j for j in (i - 1, i + 1) if 0 <= j < count]
                               for i in range(count)}
    assert edges[0][1].equals(box(0, 0, 1, 1).boundary.intersection(box(1, 0, 2, 1).boundary))
    assert cells.attrs['cell_polygon_diagnostics'] is diagnostics
    assert CopyCounter.copies <= 3
