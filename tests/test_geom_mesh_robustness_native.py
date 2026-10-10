"""Native opt-in qualification on a disposable public Bald Eagle model."""
import json
import os
import platform
from datetime import datetime, timedelta
from importlib import import_module
from pathlib import Path

import pytest


@pytest.mark.integration
@pytest.mark.destructive_copy
@pytest.mark.slow
@pytest.mark.skipif(
    platform.system() != 'Windows'
    or os.environ.get('RAS_COMMANDER_RUN_HECRAS_INTEGRATION') != '1',
    reason='Requires Windows, HEC-RAS 6.6 and explicit integration opt-in',
)
def test_screening_regions_structures_and_native_repair(tmp_path):
    import h5py
    import numpy as np
    from shapely.geometry import box
    from ras_commander import (
        RasExamples, RasPlan, RasCmdr, RasPreprocess, RasUnsteady, RasUtils,
        init_ras_project,
    )
    from ras_commander.geom import GeomMesh, GeomStorage
    from ras_commander.hdf import HdfMesh, HdfStruc

    hd = Path(os.environ.get('RAS_COMMANDER_HECRAS_DIR',
                            r'C:\Program Files (x86)\HEC\HEC-RAS\6.6'))
    if not (hd / 'Ras.exe').is_file():
        pytest.skip('Configured HEC-RAS installation is unavailable')
    project = RasExamples.extract_project('BaldEagleCrkMulti2D', output_path=tmp_path,
                                          suffix='robustness')
    g = project / 'BaldEagleDamBrk.g02'
    area = 'BaldEagleCr'
    polygons = GeomStorage.get_storage_area_polygons(g, exclude_2d=False)
    center = polygons.loc[polygons.Name == area].iloc[0].geometry.buffer(-500).representative_point()
    region = box(center.x - 250, center.y - 250, center.x + 250, center.y + 250)
    GeomMesh.replace_refinement_regions(g, [dict(
        name='QA refinement 25ft', polygon=region, spacing_dx=25, spacing_dy=25,
        perimeter_spacing=25, near_repeats=1, far_spacing=100,
    )], expected_existing_names=[])
    ras = init_ras_project(project, hd / 'Ras.exe', hide_intro=True, accept_tcu=True,
                           load_results_summary=False)
    RasPlan.set_geom('03', '02', ras_object=ras)
    result = GeomMesh.generate(
        '02', mesh_name=area, cell_size=125, bl_spacing_near=12.5,
        bl_spacing_far=125, near_repeats=2, min_face_length_ratio=.0025,
        robustness_screening=True, hecras_dir=hd, ras_object=ras,
    )
    assert result.ok, result.error_message
    assert result.robustness_screening['converged']
    assert len(result.robustness_screening['rounds'][-1]['checks']) == 9

    gm = import_module('ras_commander.geom.GeomMesh')
    ns = gm._imports()
    native_geometry = ns['RASGeometry'](str(g) + '.hdf')
    d2fa = native_geometry.D2FlowArea
    perim = d2fa.Geometry.MeshPerimeters.Polygon(d2fa.GetFeatureByName(area))
    assert sum(1 for _ in d2fa.Geometry.Structures.Polylines()) == 2
    with h5py.File(str(g) + '.hdf') as hf:
        points = hf[f'Geometry/2D Flow Areas/{area}/Cells Center Coordinate'][:result.cell_count]
    # Controlled nine-face cell away from the region and structures in this fixture.
    fault_center = np.array([2080044.27456347, 369570.082554372])
    angles = np.arange(9) * 2 * np.pi / 9 + .123
    ring = fault_center + 100 * np.column_stack([np.cos(angles), np.sin(angles)])
    points = np.vstack([points[np.linalg.norm(points - fault_center, axis=1) > 250],
                        fault_center.reshape(1, 2), ring])
    seeds = ns['PointMs']()
    for x, y in points:
        seeds.Add(ns['PointM'](float(x), float(y)))
    report = {}
    mesh = gm._screen_mesh_robustness(perim, seeds, d2fa, .0025, .0025, ns,
                                     8, False, .5, report)
    assert report['rounds'][0]['checks'][0]['bad_cells'] > 0
    assert report['converged'] and report['final_seed_count'] > len(points)
    (tmp_path / 'screening.json').write_text(json.dumps(report, indent=2))
    repaired = np.array([[mesh.Cell(i).Point.X, mesh.Cell(i).Point.Y]
                         for i in range(mesh.NonVirtualCellCount)])
    gm._patch_text_seeds(g, repaired, mesh_name=area)
    GeomStorage.set_2d_flow_area_settings(g, area, min_face_length_ratio=.05)

    # Plan 03's gate names its original g09 structure. Retarget the copy to g02.
    def retarget_gate(lines):
        selected = [b for b in RasUnsteady._find_boundary_blocks(lines)
                    if len(b['parts']) > 4 and b['parts'][4] == 'Sayers Dam']
        assert len(selected) == 1
        i = selected[0]['start_idx']
        assert lines[i].count('Sayers Dam') == 1
        lines[i] = lines[i].replace('Sayers Dam      ', 'Dam             ')
        return lines
    RasUtils.update_file(project / 'BaldEagleDamBrk.u13', retarget_gate)
    receipt = RasPreprocess.preprocess_plan('03', ras_object=ras, max_wait=180,
                                            clear_existing=True)
    assert receipt, str(receipt)
    start = datetime(1999, 1, 1, 12)
    RasPlan.update_simulation_date('03', start, start + timedelta(minutes=1), ras_object=ras)
    RasPlan.set_2d_flow_options('03', mesh_name=area, initial_conditions_time_hours=0,
                                ras_object=ras)
    receipt = RasCmdr.compute_plan('03', ras_object=ras, num_cores=2,
                                  max_runtime=240, force_rerun=True, verify=True)
    assert receipt, str(receipt)
    hdf = Path(ras.plan_df.loc[ras.plan_df.plan_number == '03', 'HDF_Results_Path'].iloc[0])
    attachments = HdfStruc.get_connection_attachments(hdf)
    assert len(attachments) == 2 and attachments.attachment_verified.all()
    topology = HdfMesh.get_mesh_sloped_topology(hdf, mesh_name=area)
    assert topology['cell_face_info'][:, 1].max() <= 8
    from shapely.geometry import Point
    with h5py.File(hdf) as hf:
        centers = hf[f'Geometry/2D Flow Areas/{area}/Cells Center Coordinate'][:]
    assert sum(region.contains(Point(*xy)) for xy in centers) == 400
