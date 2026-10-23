#[path = "../src/fluvial_geometry.rs"]
mod fluvial_geometry;
use fluvial_geometry::*;

fn grid(nx: usize, ny: usize) -> (Vec<[f64; 2]>, Vec<Vec<usize>>) {
    let points = (0..=ny)
        .flat_map(|y| (0..=nx).map(move |x| [x as f64, y as f64]))
        .collect();
    let rings = (0..ny)
        .flat_map(|y| {
            (0..nx).map(move |x| {
                let a = y * (nx + 1) + x;
                vec![a, a + 1, a + nx + 2, a + nx + 1]
            })
        })
        .collect();
    (points, rings)
}
fn polygon_count(g: &Geometry) -> usize {
    g.regions.iter().map(|r| r.polygons.len()).sum()
}
fn total_area(g: &Geometry) -> f64 {
    g.regions
        .iter()
        .flat_map(|r| r.polygons.iter())
        .map(|p| p.area_m2)
        .sum()
}

#[test]
fn adjacent_cells_cancel_internal_edge_and_canonicalize() {
    let (points, rings) = grid(2, 1);
    let g = polygonize(&points, &rings, &[7, 7], &[1, 1], 1.0, 0.0).unwrap();
    assert_eq!(g.regions[0].mesh_id, 7);
    assert_eq!(g.regions[0].polygons[0].shell, vec![0, 1, 2, 5, 4, 3, 0]);
    assert_eq!(g.regions[0].polygons[0].area_m2, 2.0);
    assert_eq!(g.diagnostics.boundary_edges, 6);
}

#[test]
fn closed_clockwise_input_is_normalized_without_changing_output() {
    let (points, rings) = grid(2, 2);
    let reference = polygonize(&points, &rings, &[0; 4], &[1; 4], 1.0, 0.0).unwrap();
    let changed: Vec<Vec<usize>> = rings
        .into_iter()
        .rev()
        .map(|mut r| {
            r.reverse();
            r.rotate_left(2);
            r.push(r[0]);
            r
        })
        .collect();
    let actual = polygonize(&points, &changed, &[0; 4], &[1; 4], 1.0, 0.0).unwrap();
    assert_eq!(reference.regions, actual.regions);
}

#[test]
fn hole_has_clockwise_exact_id_ring() {
    let (points, rings) = grid(3, 3);
    let selected: Vec<Vec<usize>> = rings
        .into_iter()
        .enumerate()
        .filter(|(i, _)| *i != 4)
        .map(|(_, r)| r)
        .collect();
    let g = polygonize(&points, &selected, &[0; 8], &[1; 8], 1.0, 0.0).unwrap();
    assert_eq!(polygon_count(&g), 1);
    let p = &g.regions[0].polygons[0];
    assert_eq!(p.shell, vec![0, 1, 2, 3, 7, 11, 15, 14, 13, 12, 8, 4, 0]);
    assert_eq!(p.holes, vec![vec![5, 9, 10, 6, 5]]);
    assert_eq!(p.area_m2, 8.0);
}

#[test]
fn diagonal_corner_contact_yields_two_simple_polygons() {
    let (points, rings) = grid(2, 2);
    let selected = vec![rings[0].clone(), rings[3].clone()];
    let g = polygonize(&points, &selected, &[0; 2], &[1; 2], 1.0, 0.0).unwrap();
    assert_eq!(polygon_count(&g), 2);
    assert_eq!(g.regions[0].polygons[0].shell, vec![0, 1, 4, 3, 0]);
    assert_eq!(g.regions[0].polygons[1].shell, vec![4, 5, 8, 7, 4]);
}

#[test]
fn hole_touching_shell_at_corner_is_split_without_repeated_vertices() {
    // Four squares around the missing central square, joined by three corners
    // and an outer path. Missing square touches exterior only at vertex 0,0.
    let (points, rings) = grid(3, 3);
    let selected: Vec<_> = rings
        .into_iter()
        .enumerate()
        .filter(|(i, _)| *i != 0 && *i != 4)
        .map(|(_, r)| r)
        .collect();
    let g = polygonize(&points, &selected, &[0; 7], &[1; 7], 1.0, 0.0).unwrap();
    assert_eq!(polygon_count(&g), 1);
    assert_eq!(g.regions[0].polygons[0].holes.len(), 1);
    assert_eq!(total_area(&g), 7.0);
}

#[test]
fn nested_island_is_separate_shell_with_outer_hole() {
    let (points, rings) = grid(5, 5);
    let selected: Vec<_> = rings
        .into_iter()
        .enumerate()
        .filter(|(i, _)| {
            let (x, y) = (i % 5, i / 5);
            x == 0 || x == 4 || y == 0 || y == 4 || (x == 2 && y == 2)
        })
        .map(|(_, r)| r)
        .collect();
    let n = selected.len();
    let g = polygonize(&points, &selected, &vec![0; n], &vec![1; n], 1.0, 0.0).unwrap();
    assert_eq!(polygon_count(&g), 2);
    assert_eq!(g.regions[0].polygons[0].holes.len(), 1);
    assert_eq!(g.regions[0].polygons[0].area_m2, 16.0);
    assert_eq!(g.regions[0].polygons[1].area_m2, 1.0);
}

#[test]
fn labels_and_mesh_ids_keep_regions_distinct() {
    let (points, rings) = grid(2, 1);
    let g = polygonize(&points, &rings, &[0; 2], &[1, 2], 1.0, 0.0).unwrap();
    assert_eq!(g.regions.len(), 2);
    assert_eq!(g.diagnostics.boundary_edges, 8);
    let repeated = vec![rings[0].clone(), rings[0].clone()];
    let g = polygonize(&points, &repeated, &[3, 4], &[1; 2], 1.0, 0.0).unwrap();
    assert_eq!(g.regions.len(), 2);
    assert_eq!(total_area(&g), 2.0);
}

#[test]
fn square_metre_filter_uses_squared_feet_conversion_and_strict_threshold() {
    let (points, rings) = grid(1, 1);
    let factor = 0.3048_f64;
    let sqm = factor * factor;
    let keep = polygonize(&points, &rings, &[0], &[1], factor, sqm).unwrap();
    assert_eq!(polygon_count(&keep), 1);
    assert_eq!(total_area(&keep), sqm);
    let drop = polygonize(&points, &rings, &[0], &[1], factor, 0.1).unwrap();
    assert_eq!(polygon_count(&drop), 0);
    assert_eq!(drop.diagnostics.removed_polygons, 1);
    assert_eq!(drop.diagnostics.removed_area_m2, sqm);
    let metre = polygonize(&points, &rings, &[0], &[1], 1.0, 0.1).unwrap();
    assert_eq!(polygon_count(&metre), 1);
}

#[test]
fn area_filter_applies_to_net_area_after_holes() {
    let (points, rings) = grid(3, 3);
    let selected: Vec<_> = rings
        .into_iter()
        .enumerate()
        .filter(|(i, _)| *i != 4)
        .map(|(_, r)| r)
        .collect();
    let g = polygonize(&points, &selected, &[0; 8], &[1; 8], 1.0, 8.5).unwrap();
    assert_eq!(g.diagnostics.removed_polygons, 1);
    assert_eq!(g.diagnostics.removed_area_m2, 8.0);
}

#[test]
fn large_projected_offsets_preserve_small_area() {
    let (mut points, rings) = grid(2, 1);
    for p in &mut points {
        p[0] += 10_000_000.0;
        p[1] += 20_000_000.0;
    }
    let g = polygonize(&points, &rings, &[0; 2], &[1; 2], 1.0, 0.0).unwrap();
    assert_eq!(total_area(&g), 2.0);
}

#[test]
fn distinct_point_ids_at_same_coordinates_are_not_snapped() {
    let points = vec![
        [0., 0.],
        [1., 0.],
        [1., 1.],
        [0., 1.],
        [1., 0.],
        [2., 0.],
        [2., 1.],
        [1., 1.],
    ];
    let rings = vec![vec![0, 1, 2, 3], vec![4, 5, 6, 7]];
    let g = polygonize(&points, &rings, &[0; 2], &[1; 2], 1.0, 0.0).unwrap();
    assert_eq!(polygon_count(&g), 2);
    assert_eq!(total_area(&g), 2.0);
}

#[test]
fn malformed_rings_report_structured_errors() {
    let (points, rings) = grid(1, 1);
    for bad in [vec![0, 1], vec![0, 1, 3, 1], vec![0, 3, 1, 2]] {
        assert!(matches!(
            polygonize(&points, &[bad], &[0], &[1], 1.0, 0.0),
            Err(GeometryError::InvalidRing { .. })
        ));
    }
    assert_eq!(
        polygonize(&points, &[vec![0, 1, 99]], &[0], &[1], 1.0, 0.0).unwrap_err(),
        GeometryError::PointOutOfRange { cell: 0, point: 99 }
    );
    assert!(matches!(
        polygonize(&points, &rings, &[], &[1], 1.0, 0.0),
        Err(GeometryError::Length { .. })
    ));
    for factor in [0.0, -1.0, f64::NAN, f64::INFINITY, 1e-300, 1e300] {
        assert_eq!(
            polygonize(&points, &rings, &[0], &[1], factor, 0.0).unwrap_err(),
            GeometryError::InvalidLinearUnit
        );
    }
    assert_eq!(
        polygonize(&points, &rings, &[0], &[1], 1.0, -1.0).unwrap_err(),
        GeometryError::InvalidMinimumArea
    );
    let mut points = points;
    points[0][0] = f64::NAN;
    assert_eq!(
        polygonize(&points, &rings, &[0], &[1], 1.0, 0.0).unwrap_err(),
        GeometryError::NonFinitePoint(0)
    );
}

#[test]
fn same_side_and_nonmanifold_edges_are_rejected() {
    let (points, rings) = grid(1, 1);
    assert!(matches!(
        polygonize(
            &points,
            &[rings[0].clone(), rings[0].clone()],
            &[0; 2],
            &[1; 2],
            1.0,
            0.0
        ),
        Err(GeometryError::SameSideEdge { .. })
    ));
    assert!(matches!(
        polygonize(
            &points,
            &[rings[0].clone(), rings[0].clone(), rings[0].clone()],
            &[0; 3],
            &[1; 3],
            1.0,
            0.0
        ),
        Err(GeometryError::NonManifoldEdge { .. })
    ));
}

#[test]
fn empty_mesh_is_successful_empty_geometry() {
    let g = polygonize(&[], &[], &[], &[], 1.0, 0.0).unwrap();
    assert!(g.regions.is_empty());
    assert_eq!(g.diagnostics.cells, 0);
}

#[test]
fn multiple_fractional_holes_have_bitwise_stable_areas_under_permutation() {
    let (mut points, rings) = grid(7, 3);
    for p in &mut points {
        p[0] = p[0] * 0.7 + p[0] * p[0] * 0.013;
        p[1] *= 0.3;
    }
    let mut selected: Vec<_> = rings
        .into_iter()
        .enumerate()
        .filter(|(i, _)| ![8, 10, 12].contains(i))
        .map(|(_, r)| r)
        .collect();
    let n = selected.len();
    let expected = polygonize(&points, &selected, &vec![0; n], &vec![1; n], 0.3048, 0.0).unwrap();
    assert_eq!(expected.regions[0].polygons[0].holes.len(), 3);
    for _ in 0..n {
        selected.rotate_left(1);
        let actual = polygonize(&points, &selected, &vec![0; n], &vec![1; n], 0.3048, 0.0).unwrap();
        assert_eq!(expected.regions, actual.regions);
    }
}

#[test]
fn nonfinite_geometry_area_returns_structured_error() {
    let points = vec![[0., 0.], [1e200, 0.], [0., 1e200]];
    assert!(matches!(
        polygonize(&points, &[vec![0, 1, 2]], &[0], &[1], 1.0, 0.0),
        Err(GeometryError::InvalidRing { .. })
    ));
    let (points, rings) = grid(1, 1);
    assert_eq!(
        polygonize(&points, &rings, &[0], &[1], 1.0, f64::INFINITY).unwrap_err(),
        GeometryError::InvalidMinimumArea
    );
}

#[test]
fn cell_validator_reports_no_errors_for_valid_cells_in_either_winding() {
    let (points, mut rings) = grid(3, 3);
    rings[1].reverse();
    let first = rings[2][0];
    rings[2].push(first);
    assert!(validate_cells(&points, &rings).unwrap().is_empty());
    assert!(validate_cells(&[], &[]).unwrap().is_empty());
}

#[test]
fn cell_validator_reports_every_bad_ring_in_input_order() {
    let (points, rings) = grid(1, 1);
    let inputs = vec![
        rings[0].clone(),
        vec![0, 1],
        rings[0].clone(),
        vec![0, 3, 1, 2],
    ];
    assert_eq!(
        validate_cells(&points, &inputs).unwrap(),
        vec![
            (1, "fewer than three points".to_string()),
            (3, "self-intersection".to_string()),
        ]
    );
    assert_eq!(
        polygonize(&points, &inputs, &[0; 4], &[1; 4], 1.0, 0.0).unwrap_err(),
        GeometryError::InvalidRing {
            cell: 1,
            reason: "fewer than three points"
        }
    );
}

#[test]
fn cell_validator_keeps_global_and_structural_errors_fatal() {
    let (mut points, rings) = grid(1, 1);
    points.push([f64::NAN, 0.0]);
    assert_eq!(
        validate_cells(&points, &rings).unwrap_err(),
        GeometryError::NonFinitePoint(4)
    );
    points.pop();
    assert_eq!(
        validate_cells(&points, &[vec![0, 1, 99]]).unwrap_err(),
        GeometryError::PointOutOfRange { cell: 0, point: 99 }
    );
}

#[test]
fn source_507_curved_face_crossings_remain_rejected_by_shared_validator() {
    // Exact source FacePoint/perimeter coordinates for D601 cells 317422 and
    // 339176. Both source curved faces properly cross another cell boundary
    // segment; accepting them would silently change model geometry.
    let points = vec![
        [3119942.6683242363, 13831959.888107771],
        [3120015.9436983857, 13831869.3247041],
        [3119977.789256263, 13831808.352194661],
        [3119902.7878298927, 13831828.278811347],
        [3119904.24810791, 13831827.3101196],
        [3054599.6673751683, 13831219.464754138],
        [3054454.7385322736, 13831214.444909181],
        [3054452.080226666, 13831311.404645696],
        [3054554.4245963595, 13831314.100435475],
        [3054559.29730225, 13831217.8817139],
    ];
    let rings = vec![vec![0, 1, 2, 3, 4], vec![5, 6, 7, 8, 9]];
    assert_eq!(
        validate_cells(&points, &rings).unwrap(),
        vec![
            (0, "self-intersection".to_string()),
            (1, "self-intersection".to_string()),
        ]
    );
    for ring in rings {
        assert_eq!(
            polygonize(&points, &[ring], &[0], &[1], 1.0, 0.0).unwrap_err(),
            GeometryError::InvalidRing {
                cell: 0,
                reason: "self-intersection"
            }
        );
    }
}

#[test]
fn exhaustive_small_grid_label_masks_conserve_area_and_simple_rings() {
    let (points, rings) = grid(3, 3);
    for mask in 0..512_u16 {
        let labels: Vec<_> = (0..9).map(|i| ((mask >> i) & 1) as u8).collect();
        let g = polygonize(&points, &rings, &[0; 9], &labels, 1.0, 0.0)
            .unwrap_or_else(|e| panic!("mask {mask}: {e}"));
        assert_eq!(total_area(&g), 9.0);
        for r in g.regions {
            let expected = (0..9).filter(|&i| labels[i] == r.label).count() as f64;
            assert_eq!(r.polygons.iter().map(|p| p.area_m2).sum::<f64>(), expected);
            for p in r.polygons {
                for ring in std::iter::once(p.shell).chain(p.holes) {
                    assert_eq!(ring.first(), ring.last());
                    let mut interior = ring[..ring.len() - 1].to_vec();
                    interior.sort_unstable();
                    interior.dedup();
                    assert_eq!(interior.len(), ring.len() - 1);
                }
            }
        }
    }
}
