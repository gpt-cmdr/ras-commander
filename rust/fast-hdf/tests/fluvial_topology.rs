#[path = "../src/fluvial.rs"]
mod fluvial;
#[path = "../src/fluvial_topology.rs"]
mod fluvial_topology;
use fluvial::*;
use fluvial_topology::*;

fn faces<'a>(id: u32, ids: &'a [u64], physical: &'a [bool], rows: &'a [[i64; 2]]) -> MeshFaces<'a> {
    MeshFaces {
        mesh_id: id,
        cell_ids: ids,
        physical,
        faces: rows,
        boundary_sentinels: &[-1],
    }
}

#[test]
fn explicit_mapping_boundary_ghost_and_dedup() {
    let built = build_face_graph(&[faces(
        4,
        &[100, 99, 27, 53],
        &[true, false, true, true],
        &[[0, 2], [2, 0], [0, -1], [1, 2], [2, 3], [-1, -1]],
    )])
    .unwrap();
    assert_eq!(
        built.graph.keys(),
        &[
            CellKey {
                mesh_id: 4,
                cell_id: 100
            },
            CellKey {
                mesh_id: 4,
                cell_id: 27
            },
            CellKey {
                mesh_id: 4,
                cell_id: 53
            }
        ]
    );
    assert_eq!(built.graph.neighbors(0), Some(&[1][..]));
    assert_eq!(built.graph.neighbors(1), Some(&[0, 2][..]));
    assert_eq!(
        built.source_rows,
        vec![
            SourceRow {
                mesh_index: 0,
                cell_row: 0
            },
            SourceRow {
                mesh_index: 0,
                cell_row: 2
            },
            SourceRow {
                mesh_index: 0,
                cell_row: 3
            }
        ]
    );
    assert_eq!(
        built.diagnostics,
        TopologyDiagnostics {
            physical_cells: 3,
            ghost_cells: 1,
            source_faces: 6,
            boundary_faces: 2,
            ghost_faces: 1,
            interior_faces: 3,
            duplicate_edges: 1,
            unique_edges: 2
        }
    );
}

#[test]
fn mesh_local_ids_cannot_create_cross_mesh_edges() {
    let built = build_face_graph(&[
        faces(10, &[1, 2], &[true, true], &[[0, 1]]),
        faces(11, &[1, 2], &[true, true], &[[0, 1]]),
    ])
    .unwrap();
    assert_eq!(built.graph.neighbors(0), Some(&[1][..]));
    assert_eq!(built.graph.neighbors(2), Some(&[3][..]));
    assert_eq!(
        built.source_rows[2],
        SourceRow {
            mesh_index: 1,
            cell_row: 0
        }
    );
}

#[test]
fn no_negative_sentinel_guessing_or_boundary_error_suppression() {
    assert!(matches!(
        build_face_graph(&[faces(1, &[0], &[true], &[[-2, 0]])]),
        Err(TopologyError::UnknownNegativeEndpoint { value: -2, .. })
    ));
    assert!(matches!(
        build_face_graph(&[faces(1, &[0], &[true], &[[-1, 9]])]),
        Err(TopologyError::EndpointOutOfRange { value: 9, .. })
    ));
    assert!(matches!(
        build_face_graph(&[faces(1, &[0], &[false], &[[0, -9]])]),
        Err(TopologyError::UnknownNegativeEndpoint { value: -9, .. })
    ));
    let mut input = faces(1, &[0], &[true], &[[-2, 0]]);
    input.boundary_sentinels = &[-2];
    assert_eq!(
        build_face_graph(&[input])
            .unwrap()
            .diagnostics
            .boundary_faces,
        1
    );
    let mut input = faces(1, &[0], &[true], &[]);
    input.boundary_sentinels = &[0];
    assert!(matches!(
        build_face_graph(&[input]),
        Err(TopologyError::NonnegativeSentinel { .. })
    ));
}

#[test]
fn bad_schema_rejected_deterministically() {
    assert!(matches!(
        build_face_graph(&[faces(1, &[0, 0], &[true, true], &[])]),
        Err(TopologyError::DuplicateCell { .. })
    ));
    assert!(matches!(
        build_face_graph(&[faces(1, &[0], &[], &[])]),
        Err(TopologyError::Length { .. })
    ));
    assert!(matches!(
        build_face_graph(&[faces(1, &[0], &[true], &[[0, 0]])]),
        Err(TopologyError::SelfFace { .. })
    ));
    assert!(matches!(
        build_face_graph(&[faces(1, &[0], &[true], &[]), faces(1, &[1], &[true], &[])]),
        Err(TopologyError::DuplicateMesh(1))
    ));
    let empty = build_face_graph(&[]).unwrap();
    assert!(empty.graph.keys().is_empty());
}

#[test]
fn faces_order_does_not_change_csr() {
    let a = build_face_graph(&[faces(
        1,
        &[20, 30, 40],
        &[true; 3],
        &[[0, 2], [1, 2], [0, 1], [1, 0]],
    )])
    .unwrap();
    let b = build_face_graph(&[faces(
        1,
        &[20, 30, 40],
        &[true; 3],
        &[[0, 1], [1, 0], [2, 1], [2, 0]],
    )])
    .unwrap();
    for vertex in 0..3 {
        assert_eq!(a.graph.neighbors(vertex), b.graph.neighbors(vertex));
    }
    assert_eq!(a.diagnostics, b.diagnostics);
}

#[test]
fn rings_match_faces_and_respect_mesh_and_ghosts() {
    let rings = vec![vec![0, 1, 4, 3, 0], vec![1, 2, 5, 4], vec![]];
    let input = MeshRings {
        mesh_id: 7,
        cell_ids: &[13, 17, 19],
        physical: &[true, true, false],
        rings: &rings,
    };
    let ring_graph = build_ring_graph(&[input]).unwrap();
    let face_graph = build_face_graph(&[faces(
        7,
        &[13, 17, 19],
        &[true, true, false],
        &[[0, 1], [0, -1], [1, -1]],
    )])
    .unwrap();
    for vertex in 0..2 {
        assert_eq!(
            ring_graph.graph.neighbors(vertex),
            face_graph.graph.neighbors(vertex)
        );
    }
    assert_eq!(ring_graph.diagnostics.unique_edges, 1);
    assert_eq!(ring_graph.diagnostics.boundary_faces, 6);
    let a = MeshRings {
        mesh_id: 1,
        cell_ids: &[1],
        physical: &[true],
        rings: &rings[..1],
    };
    let b = MeshRings {
        mesh_id: 2,
        cell_ids: &[1],
        physical: &[true],
        rings: &rings[..1],
    };
    let separate = build_ring_graph(&[a, b]).unwrap();
    assert!(separate.graph.neighbors(0).unwrap().is_empty());
}

#[test]
fn rings_reject_nonmanifold_and_invalid_cells() {
    let rings = vec![vec![0, 1, 2], vec![1, 0, 3], vec![0, 1, 4]];
    assert!(matches!(
        build_ring_graph(&[MeshRings {
            mesh_id: 3,
            cell_ids: &[0, 1, 2],
            physical: &[true; 3],
            rings: &rings
        }]),
        Err(TopologyError::NonManifoldEdge { .. })
    ));
    for ring in [vec![0, 1], vec![0, 1, 1, 2], vec![0, 1, 2, 1]] {
        assert!(matches!(
            build_ring_graph(&[MeshRings {
                mesh_id: 3,
                cell_ids: &[0],
                physical: &[true],
                rings: &[ring]
            }]),
            Err(TopologyError::InvalidRing { .. })
        ));
    }
    assert!(matches!(
        build_ring_graph(&[MeshRings {
            mesh_id: 3,
            cell_ids: &[0],
            physical: &[true],
            rings: &[]
        }]),
        Err(TopologyError::Length { .. })
    ));
}

#[test]
fn state_is_owned_reusable_and_thread_safe() {
    let graph = build_face_graph(&[faces(1, &[0, 1, 2], &[true; 3], &[[0, 1], [1, 2]])])
        .unwrap()
        .graph;
    let state = AnalysisState::new(
        graph,
        vec![0, 10, 11],
        vec![true; 3],
        vec![true; 3],
        vec![true; 3],
    )
    .unwrap();
    let high = Thresholds {
        delta_t_ms: 10,
        tolerance_ms: 1,
    };
    let low = Thresholds {
        delta_t_ms: 20,
        tolerance_ms: 1,
    };
    assert_eq!(
        state.classify(high).unwrap().labels,
        vec![Label::Pluvial, Label::Fluvial, Label::Fluvial]
    );
    assert_eq!(
        state.classify(low).unwrap().labels,
        vec![Label::Unclassified; 3]
    );
    assert_eq!(state.graph().keys().len(), 3);
    assert_eq!(state.peak_times().milliseconds, &[0, 10, 11]);
    std::thread::scope(|scope| {
        let handles: Vec<_> = (0..8)
            .map(|_| scope.spawn(|| state.classify(high).unwrap()))
            .collect();
        let expected = state.classify(high).unwrap();
        for handle in handles {
            assert_eq!(handle.join().unwrap(), expected);
        }
    });
    let masks = AnalysisState::new(
        state.graph().clone(),
        vec![i64::MIN, 0, i64::MAX],
        vec![false, true, true],
        vec![true, false, true],
        vec![true, true, false],
    )
    .unwrap();
    assert_eq!(
        masks.classify(high).unwrap().labels,
        vec![Label::Invalid, Label::Dry, Label::MissingTime]
    );
    assert!(matches!(
        AnalysisState::new(state.graph().clone(), vec![], vec![], vec![], vec![]),
        Err(GraphError::Length {
            field: "milliseconds",
            ..
        })
    ));
}

#[test]
fn assemble_curved_faces_deterministically_and_skip_ghosts() {
    let polylines = vec![vec![0, 8, 1], vec![1, 2], vec![2, 3], vec![3, 0]];
    let rings = assemble_cell_rings(
        &[[0, 4], [-999, -999]],
        &[[2, 0], [0, 1], [3, 1], [1, 0]],
        &polylines,
        &[true, false],
    )
    .unwrap();
    assert_eq!(rings, vec![vec![0, 3, 2, 1, 8], vec![]]);
    let reversed: Vec<Vec<usize>> = polylines
        .iter()
        .map(|ring| ring.iter().copied().rev().collect())
        .collect();
    assert_eq!(
        assemble_cell_rings(
            &[[0, 4]],
            &[[0, 0], [1, 1], [2, 1], [3, 0]],
            &reversed,
            &[true]
        )
        .unwrap()[0],
        rings[0]
    );
}

#[test]
fn assemble_rejects_invalid_layout_branches_repeats_and_multiple_cycles() {
    let triangle = vec![vec![0, 1], vec![1, 2], vec![2, 0]];
    assert!(matches!(
        assemble_cell_rings(&[[-1, 3]], &[], &triangle, &[true]),
        Err(TopologyError::CellFaceLayout { .. })
    ));
    assert!(matches!(
        assemble_cell_rings(&[[0, 3]], &[[0, 0], [1, 0], [8, 0]], &triangle, &[true]),
        Err(TopologyError::CellFaceLayout { .. })
    ));
    assert_eq!(
        assemble_cell_rings(
            &[[0, 3]],
            &[[0, -1], [1, i64::MIN], [2, i64::MAX]],
            &triangle,
            &[true]
        )
        .unwrap(),
        vec![vec![0, 1, 2]]
    );
    assert!(matches!(
        assemble_cell_rings(&[[0, 3]], &[[0, 0], [1, 0], [1, 0]], &triangle, &[true]),
        Err(TopologyError::CellBoundary { .. })
    ));
    let mut disconnected = triangle.clone();
    disconnected.extend([vec![3, 4], vec![4, 5], vec![5, 3]]);
    assert!(matches!(
        assemble_cell_rings(
            &[[0, 6]],
            &[[0, 0], [1, 0], [2, 0], [3, 0], [4, 0], [5, 0]],
            &disconnected,
            &[true]
        ),
        Err(TopologyError::CellBoundary { .. })
    ));
    assert!(matches!(
        assemble_cell_rings(&[[0, 2]], &[[0, 0], [1, 0]], &triangle, &[true]),
        Err(TopologyError::CellBoundary { .. })
    ));
    assert!(matches!(
        assemble_cell_rings(&[[0, 1]], &[[0, 0]], &[vec![1, 1]], &[true]),
        Err(TopologyError::FacePolyline { .. })
    ));
    assert!(matches!(
        assemble_cell_rings(&[], &[], &[], &[true]),
        Err(TopologyError::Length { .. })
    ));
}

#[cfg(not(test))]
fn main() {}
