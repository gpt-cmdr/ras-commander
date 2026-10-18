//! Bounded temporal reductions over HEC-RAS `(time, element)` result series.
//!
//! The reduction mirrors `HdfResultsMesh._get_mesh_temporal_maximum`:
//!
//! - Rows are timesteps and columns are elements (cells or faces), matching
//!   the HDF `Rows=Times` orientation. Values are reduced in `f32`; `f64`
//!   storage is rounded to `f32` first, exactly like NumPy `astype(float32)`.
//! - With a per-element offset (`Cells Minimum Elevation`), each sample is
//!   `value - offset` in `f32`, then clipped below at zero. The offset is not
//!   a dry sentinel; no value is ever treated as "dry" by magnitude.
//! - NaN and +/- infinity (before or after the offset) are missing samples.
//!   Valid negative stored values are kept; only derived values are clipped.
//! - The maximum ignores missing samples; an element without a finite sample
//!   has a NaN maximum, a peak index of -1 and a zero finite count.
//! - Ties keep the first (lowest) row index.
//! - An optional finite threshold counts samples with `value >= threshold`
//!   (inclusive) and records the first such row, or -1.
//!
//! Indices are row positions, not times; the Python adapter maps them to
//! timestamps without nanosecond coercion.

pub mod bindings;

use rayon::prelude::*;

/// Element slab processed by one task; keeps per-task work cache-friendly.
const SLAB: usize = 4096;

#[derive(Debug, Clone, PartialEq)]
pub struct Reduction {
    pub maximum: Vec<f32>,
    pub peak_index: Vec<i64>,
    pub finite_count: Vec<u64>,
    pub exceed_count: Option<Vec<u64>>,
    pub first_exceed_index: Option<Vec<i64>>,
    pub rows: u64,
}

/// Mutable views of one slab: maximum, peak, finite count and exceedance.
type Slab<'a> = (
    &'a mut [f32],
    &'a mut [i64],
    &'a mut [u64],
    Option<(&'a mut [u64], &'a mut [i64])>,
);

/// Streaming accumulator; blocks of complete rows may arrive in any size.
pub struct Accumulator {
    elements: usize,
    offset: Option<Vec<f32>>,
    threshold: Option<f32>,
    rows: u64,
    maximum: Vec<f32>,
    peak_index: Vec<i64>,
    finite_count: Vec<u64>,
    exceed_count: Vec<u64>,
    first_exceed_index: Vec<i64>,
}

impl Accumulator {
    pub fn new(
        elements: usize,
        offset: Option<Vec<f32>>,
        threshold: Option<f32>,
    ) -> Result<Self, String> {
        if let Some(offset) = &offset {
            if offset.len() != elements {
                return Err(format!(
                    "offset length {} does not match element count {elements}",
                    offset.len()
                ));
            }
        }
        if threshold.is_some_and(|t| !t.is_finite()) {
            return Err("threshold must be finite".into());
        }
        let with_threshold = threshold.is_some();
        Ok(Self {
            elements,
            offset,
            threshold,
            rows: 0,
            maximum: vec![f32::NAN; elements],
            peak_index: vec![-1; elements],
            finite_count: vec![0; elements],
            exceed_count: if with_threshold {
                vec![0; elements]
            } else {
                Vec::new()
            },
            first_exceed_index: if with_threshold {
                vec![-1; elements]
            } else {
                Vec::new()
            },
        })
    }

    /// Fold a row-major block of `values.len() / elements` complete rows.
    pub fn update(&mut self, values: &[f32], parallel: bool) -> Result<(), String> {
        let n = self.elements;
        if n == 0 {
            if !values.is_empty() {
                return Err("values supplied for zero elements".into());
            }
            return Ok(());
        }
        if values.len() % n != 0 {
            return Err(format!(
                "block of {} values is not a whole number of {n}-element rows",
                values.len()
            ));
        }
        let rows = values.len() / n;
        let row0 = i64::try_from(self.rows).map_err(|_| "row index overflow")?;
        if i64::try_from(rows)
            .ok()
            .and_then(|r| row0.checked_add(r))
            .is_none()
        {
            return Err("row index overflow".into());
        }
        let threshold = self.threshold;
        let offset = self.offset.as_deref();
        let fold = |start: usize,
                    maximum: &mut [f32],
                    peak: &mut [i64],
                    count: &mut [u64],
                    mut exceed: Option<(&mut [u64], &mut [i64])>| {
            let width = maximum.len();
            let off = offset.map(|o| &o[start..start + width]);
            for r in 0..rows {
                let row = &values[r * n + start..r * n + start + width];
                let index = row0 + r as i64;
                for j in 0..width {
                    let mut v = row[j];
                    if let Some(off) = off {
                        v -= off[j];
                    }
                    if !v.is_finite() {
                        continue;
                    }
                    if off.is_some() && v < 0.0 {
                        v = 0.0;
                    }
                    count[j] += 1;
                    let current = maximum[j];
                    if current.is_nan() || v > current {
                        maximum[j] = v;
                        peak[j] = index;
                    }
                    if let (Some(t), Some((counts, first))) = (threshold, exceed.as_mut()) {
                        if v >= t {
                            counts[j] += 1;
                            if first[j] < 0 {
                                first[j] = index;
                            }
                        }
                    }
                }
            }
        };
        let slabs = self
            .maximum
            .chunks_mut(SLAB)
            .zip(self.peak_index.chunks_mut(SLAB))
            .zip(self.finite_count.chunks_mut(SLAB));
        let mut work: Vec<Slab<'_>> = if threshold.is_some() {
            slabs
                .zip(
                    self.exceed_count
                        .chunks_mut(SLAB)
                        .zip(self.first_exceed_index.chunks_mut(SLAB)),
                )
                .map(|(((m, p), c), e)| (m, p, c, Some(e)))
                .collect()
        } else {
            slabs.map(|((m, p), c)| (m, p, c, None)).collect()
        };
        let task = |(slab, (m, p, c, e)): (usize, &mut Slab<'_>)| {
            let e = e.as_mut().map(|(a, b)| (&mut **a, &mut **b));
            fold(slab * SLAB, m, p, c, e);
        };
        if parallel && work.len() > 1 {
            work.par_iter_mut().enumerate().for_each(task);
        } else {
            work.iter_mut().enumerate().for_each(task);
        }
        self.rows += rows as u64;
        Ok(())
    }

    pub fn finish(self) -> Reduction {
        let with_threshold = self.threshold.is_some();
        Reduction {
            maximum: self.maximum,
            peak_index: self.peak_index,
            finite_count: self.finite_count,
            exceed_count: with_threshold.then_some(self.exceed_count),
            first_exceed_index: with_threshold.then_some(self.first_exceed_index),
            rows: self.rows,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn reduce(
        rows: &[&[f32]],
        offset: Option<Vec<f32>>,
        threshold: Option<f32>,
        parallel: bool,
    ) -> Reduction {
        let n = rows.first().map_or(0, |r| r.len());
        let mut acc = Accumulator::new(n, offset, threshold).unwrap();
        for row in rows {
            acc.update(row, parallel).unwrap();
        }
        acc.finish()
    }

    #[test]
    fn missing_ties_and_all_missing() {
        let nan = f32::NAN;
        let inf = f32::INFINITY;
        let r = reduce(
            &[
                &[1.0, nan, -5.0, inf],
                &[3.0, nan, -2.0, 2.0],
                &[3.0, nan, -7.0, nan],
            ],
            None,
            None,
            false,
        );
        assert_eq!(r.maximum[0], 3.0);
        assert_eq!(r.peak_index, vec![1, -1, 1, 1]);
        assert!(r.maximum[1].is_nan());
        // Valid negative stored values are kept; infinity is missing.
        assert_eq!(r.maximum[2], -2.0);
        assert_eq!(r.maximum[3], 2.0);
        assert_eq!(r.finite_count, vec![3, 0, 3, 1]);
        assert_eq!(r.rows, 3);
        assert!(r.exceed_count.is_none());
    }

    #[test]
    fn offset_clips_and_threshold_is_inclusive() {
        let r = reduce(
            &[&[10.0, 5.0, 1.0], &[12.0, 4.0, 2.0], &[11.0, 6.0, 3.0]],
            Some(vec![10.0, 7.0, f32::NAN]),
            Some(1.0),
            false,
        );
        assert_eq!(r.maximum[..2], [2.0, 0.0]);
        assert!(r.maximum[2].is_nan());
        assert_eq!(r.peak_index, vec![1, 0, -1]);
        assert_eq!(r.exceed_count.unwrap(), vec![2, 0, 0]);
        assert_eq!(r.first_exceed_index.unwrap(), vec![1, -1, -1]);
    }

    #[test]
    fn blocks_and_parallel_slabs_match_serial() {
        let n = SLAB * 2 + 17;
        let rows: Vec<Vec<f32>> = (0..7)
            .map(|t| {
                (0..n)
                    .map(|j| match (t * 31 + j) % 11 {
                        0 => f32::NAN,
                        k => (k as f32 - 5.0) * (j % 3) as f32,
                    })
                    .collect()
            })
            .collect();
        let refs: Vec<&[f32]> = rows.iter().map(Vec::as_slice).collect();
        let serial = reduce(&refs, None, Some(0.0), false);
        let mut acc = Accumulator::new(n, None, Some(0.0)).unwrap();
        acc.update(&rows[..3].concat(), true).unwrap();
        acc.update(&rows[3..].concat(), true).unwrap();
        let blocked = acc.finish();
        assert_eq!(serial.peak_index, blocked.peak_index);
        assert_eq!(serial.finite_count, blocked.finite_count);
        assert_eq!(serial.exceed_count, blocked.exceed_count);
        assert_eq!(serial.first_exceed_index, blocked.first_exceed_index);
        let bits = |v: &[f32]| v.iter().map(|x| x.to_bits()).collect::<Vec<_>>();
        assert_eq!(bits(&serial.maximum), bits(&blocked.maximum));
    }

    #[test]
    fn rejects_bad_shapes_and_threshold() {
        assert!(Accumulator::new(3, Some(vec![0.0; 2]), None).is_err());
        assert!(Accumulator::new(3, None, Some(f32::NAN)).is_err());
        let mut acc = Accumulator::new(3, None, None).unwrap();
        assert!(acc.update(&[1.0; 4], false).is_err());
        let empty = Accumulator::new(0, None, None).unwrap().finish();
        assert!(empty.maximum.is_empty() && empty.rows == 0);
    }
}
