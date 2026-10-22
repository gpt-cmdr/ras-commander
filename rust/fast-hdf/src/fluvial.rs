//! Python-independent peak-timing heuristic. No geometry or hydraulic attribution.
//!
//! CSR vertices use unique (mesh_id, cell_id) identities. Only symmetric, simple,
//! within-mesh edges are accepted. Construction canonicalizes neighbor order and
//! can be reused across threshold sweeps. All time differences use overflow-safe
//! integer milliseconds; no datetime range or missing-value sentinel is imposed.
//!
//! Seed edges qualify at difference >= delta_t_ms. Later endpoints vote fluvial,
//! earlier endpoints vote pluvial. Equal-time qualifying edges vote BOTH at both
//! ends. Any conflicting seed is permanently ambiguous, independent of edge order.
//! Growth uses difference <= tolerance_ms, synchronous waves, and BOTH arrivals
//! in one wave become permanently ambiguous. Ambiguous cells never propagate.
//! Exclusion priority is invalid > dry > missing time. Excluded cells are barriers.
//! `classify_with_seed_overrides` lets a caller resolve named conflicting seeds
//! (for example, to replay a legacy order-dependent tie-break) before growth.

use std::collections::HashSet;
use std::fmt;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct CellKey {
    pub mesh_id: u32,
    pub cell_id: u64,
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Label {
    Unclassified = 0,
    Fluvial = 1,
    Pluvial = 2,
    Ambiguous = 3,
    Invalid = 4,
    Dry = 5,
    MissingTime = 6,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum GraphError {
    Offsets,
    DuplicateKey(CellKey),
    NeighborOutOfRange(usize),
    SelfEdge(usize),
    DuplicateEdge(usize, usize),
    CrossMeshEdge(usize, usize),
    AsymmetricEdge(usize, usize),
    /// A seed override named a vertex that is not a conflicting seed, named
    /// it twice, or requested a label other than fluvial/pluvial.
    InvalidSeedOverride(usize),
    Length {
        field: &'static str,
        expected: usize,
        actual: usize,
    },
}

impl fmt::Display for GraphError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "invalid fluvial graph input: {self:?}")
    }
}
impl std::error::Error for GraphError {}

#[derive(Clone, Debug)]
pub struct VerifiedGraph {
    keys: Vec<CellKey>,
    offsets: Vec<usize>,
    neighbors: Vec<usize>,
}

impl VerifiedGraph {
    /// Validate once. Unsorted rows are accepted; duplicates are rejected.
    pub fn new(
        keys: Vec<CellKey>,
        offsets: Vec<usize>,
        mut neighbors: Vec<usize>,
    ) -> Result<Self, GraphError> {
        let n = keys.len();
        if offsets.len() != n + 1
            || offsets.first() != Some(&0)
            || offsets.last() != Some(&neighbors.len())
            || offsets.windows(2).any(|w| w[0] > w[1])
        {
            return Err(GraphError::Offsets);
        }
        let mut seen = HashSet::with_capacity(n);
        for &key in &keys {
            if !seen.insert(key) {
                return Err(GraphError::DuplicateKey(key));
            }
        }
        for i in 0..n {
            let row = &mut neighbors[offsets[i]..offsets[i + 1]];
            row.sort_unstable();
            for (pos, &j) in row.iter().enumerate() {
                if j >= n {
                    return Err(GraphError::NeighborOutOfRange(j));
                }
                if i == j {
                    return Err(GraphError::SelfEdge(i));
                }
                if pos > 0 && row[pos - 1] == j {
                    return Err(GraphError::DuplicateEdge(i, j));
                }
                if keys[i].mesh_id != keys[j].mesh_id {
                    return Err(GraphError::CrossMeshEdge(i, j));
                }
            }
        }
        for i in 0..n {
            for &j in &neighbors[offsets[i]..offsets[i + 1]] {
                if neighbors[offsets[j]..offsets[j + 1]]
                    .binary_search(&i)
                    .is_err()
                {
                    return Err(GraphError::AsymmetricEdge(i, j));
                }
            }
        }
        Ok(Self {
            keys,
            offsets,
            neighbors,
        })
    }

    pub fn keys(&self) -> &[CellKey] {
        &self.keys
    }
    pub fn neighbors(&self, vertex: usize) -> Option<&[usize]> {
        (vertex < self.keys.len())
            .then(|| &self.neighbors[self.offsets[vertex]..self.offsets[vertex + 1]])
    }
}

/// Caller provides independently checked geometry/ghost, wet, and time masks.
/// Integer values at masked vertices are ignored. No depth rule is inferred.
#[derive(Clone, Copy, Debug)]
pub struct PeakTimes<'a> {
    pub milliseconds: &'a [i64],
    pub valid: &'a [bool],
    pub wet: &'a [bool],
    pub time_valid: &'a [bool],
}

#[derive(Clone, Copy, Debug)]
pub struct Thresholds {
    pub delta_t_ms: u64,
    pub tolerance_ms: u64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Diagnostics {
    pub qualifying_edges: usize,
    pub seeded_cells: usize,
    pub conflicting_seeds: usize,
    pub growth_conflicts: usize,
    /// Number of nonempty expansion frontiers processed, including a final
    /// frontier that makes no claims. Zero if no fluvial/pluvial seeds exist.
    pub waves: usize,
    /// Counts indexed by Label's stable discriminant, including exclusions.
    pub label_counts: [usize; 7],
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Classification {
    /// Same order as VerifiedGraph::keys().
    pub labels: Vec<Label>,
    pub diagnostics: Diagnostics,
}

/// Serial deterministic kernel; safe to call concurrently against one graph.
/// O(V + E) classification work and O(V) auxiliary memory. Parallel scheduling
/// is deliberately left to the integration layer, with wave barriers preserved.
pub fn classify(
    graph: &VerifiedGraph,
    times: PeakTimes<'_>,
    thresholds: Thresholds,
) -> Result<Classification, GraphError> {
    classify_with_seed_overrides(graph, times, thresholds, &[])
}

/// As `classify`, but each listed conflicting seed takes the caller's
/// fluvial/pluvial label instead of becoming ambiguous, then grows normally.
/// This lets a caller reproduce an external, order-dependent tie-break (such
/// as legacy last-write seeding) without changing any other cell. Overrides
/// of non-conflicting vertices are rejected, never silently applied.
/// `conflicting_seeds` still counts every conflict, including overridden ones.
pub fn classify_with_seed_overrides(
    graph: &VerifiedGraph,
    times: PeakTimes<'_>,
    thresholds: Thresholds,
    overrides: &[(usize, Label)],
) -> Result<Classification, GraphError> {
    let n = graph.keys.len();
    for (field, actual) in [
        ("milliseconds", times.milliseconds.len()),
        ("valid", times.valid.len()),
        ("wet", times.wet.len()),
        ("time_valid", times.time_valid.len()),
    ] {
        if actual != n {
            return Err(GraphError::Length {
                field,
                expected: n,
                actual,
            });
        }
    }
    let mut labels: Vec<_> = (0..n)
        .map(|i| {
            if !times.valid[i] {
                Label::Invalid
            } else if !times.wet[i] {
                Label::Dry
            } else if !times.time_valid[i] {
                Label::MissingTime
            } else {
                Label::Unclassified
            }
        })
        .collect();
    let mut votes = vec![0u8; n];
    let mut diagnostics = Diagnostics::default();
    for i in 0..n {
        if labels[i] != Label::Unclassified {
            continue;
        }
        for &j in &graph.neighbors[graph.offsets[i]..graph.offsets[i + 1]] {
            if j <= i || labels[j] != Label::Unclassified {
                continue;
            }
            let a = times.milliseconds[i];
            let b = times.milliseconds[j];
            if a.abs_diff(b) >= thresholds.delta_t_ms {
                diagnostics.qualifying_edges += 1;
                match a.cmp(&b) {
                    std::cmp::Ordering::Greater => {
                        votes[i] |= 1;
                        votes[j] |= 2;
                    }
                    std::cmp::Ordering::Less => {
                        votes[i] |= 2;
                        votes[j] |= 1;
                    }
                    std::cmp::Ordering::Equal => {
                        votes[i] |= 3;
                        votes[j] |= 3;
                    }
                }
            }
        }
    }
    for &(i, label) in overrides {
        if i >= n || votes[i] != 3 || !matches!(label, Label::Fluvial | Label::Pluvial) {
            return Err(GraphError::InvalidSeedOverride(i));
        }
        // Mark as resolved (bit 4) so a duplicate override is detected above.
        votes[i] = 4 | if label == Label::Fluvial { 1 } else { 2 };
    }
    let mut frontier = Vec::new();
    for i in 0..n {
        match votes[i] {
            5 | 6 => {
                labels[i] = if votes[i] == 5 {
                    Label::Fluvial
                } else {
                    Label::Pluvial
                };
                diagnostics.conflicting_seeds += 1;
                frontier.push(i);
            }
            1 => {
                labels[i] = Label::Fluvial;
                frontier.push(i);
            }
            2 => {
                labels[i] = Label::Pluvial;
                frontier.push(i);
            }
            3 => {
                labels[i] = Label::Ambiguous;
                diagnostics.conflicting_seeds += 1;
            }
            _ => continue,
        }
        diagnostics.seeded_cells += 1;
    }
    // Reset only touched votes each wave: avoid O(V * number_of_waves).
    votes.fill(0);
    let mut touched = Vec::new();
    let mut next = Vec::new();
    while !frontier.is_empty() {
        diagnostics.waves += 1;
        for &i in &frontier {
            let vote = if labels[i] == Label::Fluvial { 1 } else { 2 };
            for &j in &graph.neighbors[graph.offsets[i]..graph.offsets[i + 1]] {
                if labels[j] == Label::Unclassified
                    && times.milliseconds[i].abs_diff(times.milliseconds[j])
                        <= thresholds.tolerance_ms
                {
                    if votes[j] == 0 {
                        touched.push(j);
                    }
                    votes[j] |= vote;
                }
            }
        }
        for &j in &touched {
            labels[j] = match votes[j] {
                1 => {
                    next.push(j);
                    Label::Fluvial
                }
                2 => {
                    next.push(j);
                    Label::Pluvial
                }
                _ => {
                    diagnostics.growth_conflicts += 1;
                    Label::Ambiguous
                }
            };
            votes[j] = 0;
        }
        touched.clear();
        frontier.clear();
        std::mem::swap(&mut frontier, &mut next);
    }
    for &label in &labels {
        diagnostics.label_counts[label as usize] += 1;
    }
    Ok(Classification {
        labels,
        diagnostics,
    })
}
