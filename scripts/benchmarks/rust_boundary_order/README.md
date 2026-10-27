# Boundary merge order counterexample

Run `cargo run --release --locked --manifest-path scripts/benchmarks/rust_boundary_order/Cargo.toml`.
This isolated diagnostic uses unmodified `clipper2-rust` 1.2.0. It constructs
two exterior squares and one reversed interior ring. Only their order changes.

With separate first-Subject/rest-Clip sets and NonZero filling, one order fills
the 3,600-unit hole (total area 20,000), while the other preserves it (16,400).
The all-subject control preserves the hole in both cases. Exact signed area
uses i128 accumulation to avoid cancellation at large projected coordinates.

Optionally append `retained-rings.json candidate_index`. Input is an array of
rings, each an array of `[x, y]` signed integer coordinates on a 0.001 projected
unit lattice. The diagnostic compares first ring zero and the supplied index.
Reported input-replay area is in squared projected units. No model data is
distributed, no HEC-RAS is executed, and no production mapping option is added.

The Davis Max investigation used candidate index 332 to demonstrate a particular
7,423.019980-square-foot hole filling. That index was selected as a diagnostic
counterexample; it does not establish which ring occurred first in a native
export and must never become a fixture-specific production rule. Native worker
partitions and contour-stream order remain uncaptured for those exports.

See the boundary ordering investigation in `docs/development/fim-mapping-performance.md`.
