// Path inclusion permits a dependency-free `rustc --test` build before the
// coordinator registers `pub mod fluvial;` in lib.rs. Also a test-only stdin
// harness for Python conformance; this is not a production CLI or binding.
#[path = "../src/fluvial.rs"]
mod fluvial;
use fluvial::*;

fn graph(n: usize, edges: &[(usize, usize)]) -> VerifiedGraph {
    let mut rows = vec![vec![]; n];
    for &(a, b) in edges {
        rows[a].push(b);
        rows[b].push(a);
    }
    let mut offsets = vec![0];
    let mut neighbors = vec![];
    for row in rows {
        neighbors.extend(row);
        offsets.push(neighbors.len());
    }
    VerifiedGraph::new(
        (0..n)
            .map(|i| CellKey {
                mesh_id: 0,
                cell_id: i as u64,
            })
            .collect(),
        offsets,
        neighbors,
    )
    .unwrap()
}

fn run(g: &VerifiedGraph, ms: &[i64], delta: u64, tolerance: u64) -> Classification {
    let yes = vec![true; ms.len()];
    classify(
        g,
        PeakTimes {
            milliseconds: ms,
            valid: &yes,
            wet: &yes,
            time_valid: &yes,
        },
        Thresholds {
            delta_t_ms: delta,
            tolerance_ms: tolerance,
        },
    )
    .unwrap()
}

#[test]
fn empty_and_no_seeds() {
    assert_eq!(
        run(&graph(0, &[]), &[], 1, 1).diagnostics.label_counts,
        [0; 7]
    );
    let g = graph(3, &[(0, 1)]);
    assert_eq!(
        run(&g, &[5, 5, 0], 1, 99).labels,
        vec![Label::Unclassified; 3]
    );
}

#[test]
fn inclusive_seed_equality_and_one_millisecond_below() {
    let g = graph(2, &[(0, 1)]);
    assert_eq!(
        run(&g, &[1000, 0], 1000, 0).labels,
        [Label::Fluvial, Label::Pluvial]
    );
    assert_eq!(run(&g, &[999, 0], 1000, 0).labels, [Label::Unclassified; 2]);
}

#[test]
fn zero_threshold_equal_times_are_conflicting_seeds() {
    let result = run(&graph(2, &[(0, 1)]), &[4, 4], 0, 0);
    assert_eq!(result.labels, [Label::Ambiguous; 2]);
    assert_eq!(result.diagnostics.conflicting_seeds, 2);
    assert_eq!(result.diagnostics.waves, 0);
}

#[test]
fn seed_conflicts_are_order_independent_barriers() {
    let a = graph(4, &[(0, 1), (1, 2), (1, 3)]);
    let b = graph(4, &[(1, 3), (1, 2), (0, 1)]);
    let result = run(&a, &[0, 10, 20, 10], 10, 0);
    assert_eq!(
        result.labels,
        [
            Label::Pluvial,
            Label::Ambiguous,
            Label::Fluvial,
            Label::Unclassified
        ]
    );
    assert_eq!(result, run(&b, &[0, 10, 20, 10], 10, 0));
    assert_eq!(result.diagnostics.seeded_cells, 3);
    assert_eq!(result.diagnostics.conflicting_seeds, 1);
}

#[test]
fn synchronous_fronts_and_ambiguous_barrier() {
    let g = graph(4, &[(0, 1), (0, 2), (1, 2), (2, 3)]);
    let result = run(&g, &[0, 10, 5, 5], 10, 5);
    assert_eq!(
        result.labels,
        [
            Label::Pluvial,
            Label::Fluvial,
            Label::Ambiguous,
            Label::Unclassified
        ]
    );
    assert_eq!(result.diagnostics.growth_conflicts, 1);
}

#[test]
fn growth_equality_and_one_millisecond_outside() {
    let g = graph(4, &[(0, 1), (1, 2), (2, 3)]);
    assert_eq!(
        run(&g, &[0, 100, 105, 111], 100, 5).labels,
        [
            Label::Pluvial,
            Label::Fluvial,
            Label::Fluvial,
            Label::Unclassified
        ]
    );
}

#[test]
fn sequential_waves_do_not_claim_earlier_than_distance() {
    let g = graph(6, &[(0, 1), (1, 2), (2, 3), (0, 4), (4, 5), (5, 3)]);
    let result = run(&g, &[0, 100, 60, 50, 40, 50], 100, 50);
    // 3 is first reached through 1 -> 2 -> 3, while the pluvial route is longer.
    assert_eq!(
        result.labels,
        [
            Label::Pluvial,
            Label::Fluvial,
            Label::Fluvial,
            Label::Fluvial,
            Label::Pluvial,
            Label::Pluvial
        ]
    );
}

#[test]
fn exclusions_are_distinct_and_block_seeding_and_growth() {
    let g = graph(6, &[(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)]);
    let ms = [0, 100, 100, 100, 100, 100];
    let result = classify(
        &g,
        PeakTimes {
            milliseconds: &ms,
            valid: &[true, true, false, true, true, true],
            wet: &[true, true, false, false, true, true],
            time_valid: &[true, true, false, false, false, true],
        },
        Thresholds {
            delta_t_ms: 100,
            tolerance_ms: 100,
        },
    )
    .unwrap();
    assert_eq!(
        result.labels,
        [
            Label::Pluvial,
            Label::Fluvial,
            Label::Invalid,
            Label::Dry,
            Label::MissingTime,
            Label::Unclassified
        ]
    );
    assert_eq!(result.diagnostics.qualifying_edges, 1);
    assert_eq!(result.diagnostics.label_counts, [1, 1, 1, 0, 1, 1, 1]);
}

#[test]
fn mesh_local_ids_remain_independent() {
    let g = VerifiedGraph::new(
        vec![
            CellKey {
                mesh_id: 1,
                cell_id: 0,
            },
            CellKey {
                mesh_id: 1,
                cell_id: 1,
            },
            CellKey {
                mesh_id: 2,
                cell_id: 0,
            },
            CellKey {
                mesh_id: 2,
                cell_id: 1,
            },
        ],
        vec![0, 1, 2, 3, 4],
        vec![1, 0, 3, 2],
    )
    .unwrap();
    assert_eq!(
        run(&g, &[100, 0, 0, 100], 100, 0).labels,
        [
            Label::Fluvial,
            Label::Pluvial,
            Label::Pluvial,
            Label::Fluvial
        ]
    );
    assert_eq!(g.keys()[2].cell_id, 0);
    assert_eq!(g.neighbors(4), None);
}

#[test]
fn datetime_extrema_and_year_3000_do_not_overflow() {
    let g = graph(2, &[(0, 1)]);
    assert_eq!(
        run(&g, &[i64::MIN, i64::MAX], u64::MAX, 0).labels,
        [Label::Pluvial, Label::Fluvial]
    );
    assert_eq!(
        run(&g, &[32503680000000, 32503680000001], 1, 0).labels,
        [Label::Pluvial, Label::Fluvial]
    );
}

#[test]
fn reject_malformed_csr() {
    let keys = || {
        vec![
            CellKey {
                mesh_id: 0,
                cell_id: 0,
            },
            CellKey {
                mesh_id: 0,
                cell_id: 1,
            },
        ]
    };
    for offsets in [
        vec![],
        vec![0, 1],
        vec![1, 1, 1],
        vec![0, 2, 1],
        vec![0, 3, 3],
    ] {
        assert!(matches!(
            VerifiedGraph::new(keys(), offsets, vec![1]),
            Err(GraphError::Offsets)
        ));
    }
    assert!(matches!(
        VerifiedGraph::new(keys(), vec![0, 1, 1], vec![2]),
        Err(GraphError::NeighborOutOfRange(2))
    ));
    assert!(matches!(
        VerifiedGraph::new(keys(), vec![0, 1, 1], vec![0]),
        Err(GraphError::SelfEdge(0))
    ));
    assert!(matches!(
        VerifiedGraph::new(keys(), vec![0, 2, 2], vec![1, 1]),
        Err(GraphError::DuplicateEdge(0, 1))
    ));
    assert!(matches!(
        VerifiedGraph::new(keys(), vec![0, 1, 1], vec![1]),
        Err(GraphError::AsymmetricEdge(0, 1))
    ));
    assert!(matches!(
        VerifiedGraph::new(vec![keys()[0]; 2], vec![0, 0, 0], vec![]),
        Err(GraphError::DuplicateKey(_))
    ));
    let mut cross = keys();
    cross[1].mesh_id = 1;
    assert!(matches!(
        VerifiedGraph::new(cross, vec![0, 1, 2], vec![1, 0]),
        Err(GraphError::CrossMeshEdge(0, 1))
    ));
}

#[test]
fn every_input_length_is_checked() {
    let g = graph(1, &[]);
    for index in 0..4 {
        let yes = [true];
        let input = PeakTimes {
            milliseconds: if index == 0 { &[] } else { &[0] },
            valid: if index == 1 { &[] } else { &yes },
            wet: if index == 2 { &[] } else { &yes },
            time_valid: if index == 3 { &[] } else { &yes },
        };
        assert!(matches!(
            classify(
                &g,
                input,
                Thresholds {
                    delta_t_ms: 1,
                    tolerance_ms: 1
                }
            ),
            Err(GraphError::Length { .. })
        ));
    }
}

#[test]
fn shared_graph_concurrent_calls_are_deterministic() {
    let g = graph(4, &[(0, 1), (0, 2), (1, 2), (2, 3)]);
    let expected = run(&g, &[0, 10, 5, 5], 10, 5);
    for count in [1, 2, 4, 8] {
        std::thread::scope(|scope| {
            let handles: Vec<_> = (0..count)
                .map(|_| scope.spawn(|| run(&g, &[0, 10, 5, 5], 10, 5)))
                .collect();
            for handle in handles {
                assert_eq!(handle.join().unwrap(), expected);
            }
        });
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    use std::io::{self, Read};
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).unwrap();
    let mut tokens = input.split_whitespace();
    macro_rules! take {
        ($t:ty) => {
            tokens
                .next()
                .expect("missing field")
                .parse::<$t>()
                .expect("invalid field")
        };
    }
    let n = take!(usize);
    let e = take!(usize);
    let delta_t_ms = take!(u64);
    let tolerance_ms = take!(u64);
    let mut keys = Vec::new();
    let mut ms = Vec::new();
    let mut valid = Vec::new();
    let mut wet = Vec::new();
    let mut time_valid = Vec::new();
    for _ in 0..n {
        keys.push(CellKey {
            mesh_id: take!(u32),
            cell_id: take!(u64),
        });
        ms.push(take!(i64));
        valid.push(take!(u8) != 0);
        wet.push(take!(u8) != 0);
        time_valid.push(take!(u8) != 0);
    }
    let offsets: Vec<usize> = (0..=n).map(|_| take!(usize)).collect();
    let neighbors: Vec<usize> = (0..e).map(|_| take!(usize)).collect();
    assert!(tokens.next().is_none(), "extra fields");
    let start = std::time::Instant::now();
    let graph = VerifiedGraph::new(keys, offsets, neighbors)?;
    let setup = start.elapsed();
    let result = classify(
        &graph,
        PeakTimes {
            milliseconds: &ms,
            valid: &valid,
            wet: &wet,
            time_valid: &time_valid,
        },
        Thresholds {
            delta_t_ms,
            tolerance_ms,
        },
    )?;
    let elapsed = start.elapsed() - setup;
    for label in result.labels {
        print!("{} ", label as u8);
    }
    println!();
    eprintln!(
        "setup_ns={} classify_ns={} diagnostics={:?}",
        setup.as_nanos(),
        elapsed.as_nanos(),
        result.diagnostics
    );
    Ok(())
}

fn run_overrides(
    g: &VerifiedGraph,
    ms: &[i64],
    delta: u64,
    tolerance: u64,
    overrides: &[(usize, Label)],
) -> Result<Classification, GraphError> {
    let yes = vec![true; ms.len()];
    classify_with_seed_overrides(
        g,
        PeakTimes {
            milliseconds: ms,
            valid: &yes,
            wet: &yes,
            time_valid: &yes,
        },
        Thresholds {
            delta_t_ms: delta,
            tolerance_ms: tolerance,
        },
        overrides,
    )
}

#[test]
fn seed_override_resolves_only_conflicts_then_grows() {
    // Path 0-1-2-3: vertex 1 is later than 0 (fluvial vote) and earlier than
    // 2 (pluvial vote), so it conflicts. Vertex 3 grows from 2 at tolerance.
    let g = graph(4, &[(0, 1), (1, 2), (2, 3)]);
    let ms = [0, 100, 200, 201];
    let plain = run(&g, &ms, 100, 5);
    assert_eq!(plain.labels[1], Label::Ambiguous);
    assert_eq!(plain.diagnostics.conflicting_seeds, 1);
    let empty = run_overrides(&g, &ms, 100, 5, &[]).unwrap();
    assert_eq!(empty, plain);
    for (label, expected) in [
        (Label::Fluvial, Label::Fluvial),
        (Label::Pluvial, Label::Pluvial),
    ] {
        let resolved = run_overrides(&g, &ms, 100, 5, &[(1, label)]).unwrap();
        assert_eq!(resolved.labels[1], expected);
        assert_eq!(
            resolved.labels,
            vec![Label::Pluvial, expected, Label::Fluvial, Label::Fluvial]
        );
        assert_eq!(resolved.diagnostics.conflicting_seeds, 1);
        assert_eq!(
            resolved.diagnostics.seeded_cells,
            plain.diagnostics.seeded_cells
        );
    }
}

#[test]
fn overridden_seed_propagates_through_growth() {
    // Vertex 4 hangs off conflicting vertex 1 within tolerance; it remains
    // unclassified when 1 is ambiguous and follows 1 once 1 is resolved.
    let g = graph(5, &[(0, 1), (1, 2), (1, 4)]);
    let ms = [0, 100, 200, 0, 101];
    assert_eq!(run(&g, &ms, 100, 5).labels[4], Label::Unclassified);
    let resolved = run_overrides(&g, &ms, 100, 5, &[(1, Label::Pluvial)]).unwrap();
    assert_eq!(resolved.labels[4], Label::Pluvial);
}

#[test]
fn invalid_seed_overrides_are_rejected() {
    let g = graph(4, &[(0, 1), (1, 2), (2, 3)]);
    let ms = [0, 100, 200, 201];
    for bad in [
        vec![(0, Label::Fluvial)],                      // not a conflict
        vec![(3, Label::Pluvial)],                      // unseeded vertex
        vec![(9, Label::Fluvial)],                      // out of range
        vec![(1, Label::Ambiguous)],                    // not fluvial/pluvial
        vec![(1, Label::Fluvial), (1, Label::Pluvial)], // duplicate
    ] {
        let index = bad.last().unwrap().0;
        assert_eq!(
            run_overrides(&g, &ms, 100, 5, &bad),
            Err(GraphError::InvalidSeedOverride(index))
        );
    }
}
