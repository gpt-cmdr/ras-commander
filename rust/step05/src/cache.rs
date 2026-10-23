//! Shared, immutable, byte-bounded decoded-tile cache with single-flight loading.
//!
//! - Values are `Arc<[f32]>`; readers never mutate them.
//! - A key is decoded at most once while resident: concurrent requests wait for the loader.
//! - Eviction is least-recently-used among *unpinned* entries (no outside `Arc` holder), so the
//!   resident byte total, including in-use and loading tiles, never exceeds the budget. If the
//!   budget cannot be met because everything is pinned, the request fails with a budget error
//!   rather than exceeding it. The session validates `threads * max_tiles_per_item * tile_bytes
//!   <= budget`, which makes that failure unreachable for planned work.
//! - The budget covers decoded *resident* slots only. Decoder transients of a concurrent miss
//!   (terrio window buffer, tiff chunk buffer, compressed bytes, chunk offset tables and the
//!   `Arc<[f32]>` copy) are outside it; `peak_concurrent_loads` lets callers estimate them.
//! - Unwind safety: a loader that returns an error *or panics* releases its `Loading` slot and
//!   its bytes, counts a load error and wakes every waiter (drop guard). A panic is caught and
//!   returned as a typed `MapError::Terrain`; waiters then retry the load themselves.
use crate::MapError;
use serde::Serialize;
use std::collections::{HashMap, HashSet};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::{Arc, Condvar, Mutex};

pub type Key = (u32, u32);

enum Slot {
    Loading,
    Ready {
        data: Arc<[f32]>,
        bytes: u64,
        last: u64,
    },
}

#[derive(Default, Clone, Serialize, Debug, PartialEq)]
pub struct CacheStats {
    pub budget_bytes: u64,
    /// Successful decodes (cache misses that loaded a tile).
    pub tile_reads: u64,
    pub hits: u64,
    /// Requests that waited for a concurrent loader of the same tile (duplicate decode avoided).
    pub single_flight_waits: u64,
    pub evictions: u64,
    pub peak_bytes: u64,
    pub resident_bytes: u64,
    pub decoded_bytes_total: u64,
    pub distinct_tiles_loaded: u64,
    /// tile_reads - distinct_tiles_loaded: re-decodes caused by eviction.
    pub reloads_after_eviction: u64,
    /// Failed loads, including caught loader panics.
    pub load_errors: u64,
    /// Loader panics caught and converted to errors (subset of `load_errors`).
    pub loader_panics: u64,
    /// Maximum number of loaders running at once (each holds decoder transients).
    pub peak_concurrent_loads: u64,
}

struct State {
    map: HashMap<Key, Slot>,
    bytes: u64,
    tick: u64,
    seen: HashSet<Key>,
    loading: u64,
    stats: CacheStats,
}

/// Releases a `Loading` slot unless disarmed; runs on error return and on unwind.
struct LoadGuard<'a> {
    cache: &'a TileCache,
    key: Key,
    bytes: u64,
    armed: bool,
}

impl Drop for LoadGuard<'_> {
    fn drop(&mut self) {
        if !self.armed {
            return;
        }
        let mut st = self.cache.lock();
        if matches!(st.map.get(&self.key), Some(Slot::Loading)) {
            st.map.remove(&self.key);
            st.bytes -= self.bytes;
        }
        st.loading -= 1;
        st.stats.load_errors += 1;
        drop(st);
        self.cache.cv.notify_all();
    }
}

fn panic_message(p: &(dyn std::any::Any + Send)) -> String {
    p.downcast_ref::<&str>()
        .map(|s| s.to_string())
        .or_else(|| p.downcast_ref::<String>().cloned())
        .unwrap_or_else(|| "non-string panic payload".into())
}

pub struct TileCache {
    state: Mutex<State>,
    cv: Condvar,
    budget: u64,
}

impl TileCache {
    pub fn new(budget: u64) -> Self {
        Self {
            state: Mutex::new(State {
                map: HashMap::new(),
                bytes: 0,
                tick: 0,
                seen: HashSet::new(),
                loading: 0,
                stats: CacheStats {
                    budget_bytes: budget,
                    ..Default::default()
                },
            }),
            cv: Condvar::new(),
            budget,
        }
    }

    pub fn budget(&self) -> u64 {
        self.budget
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, State> {
        // Loaders never run under the lock, and every critical section completes its accounting
        // before it can panic, so a poisoned lock still holds consistent state. Recover it so
        // other workers report errors instead of panicking.
        self.state.lock().unwrap_or_else(|p| p.into_inner())
    }

    /// Returns the tile, loading it with `load` on a miss. `bytes` must equal 4 * loaded length.
    pub fn get_or_load(
        &self,
        key: Key,
        bytes: u64,
        load: impl FnOnce() -> Result<Vec<f32>, MapError>,
    ) -> Result<Arc<[f32]>, MapError> {
        if bytes > self.budget {
            return Err(MapError::Budget(format!(
                "one tile of {bytes} bytes exceeds the cache budget {}",
                self.budget
            )));
        }
        let mut st = self.lock();
        let mut waited = false;
        loop {
            st.tick += 1;
            let tick = st.tick;
            match st.map.get_mut(&key) {
                Some(Slot::Ready { data, last, .. }) => {
                    *last = tick;
                    let data = data.clone();
                    st.stats.hits += 1;
                    return Ok(data);
                }
                Some(Slot::Loading) => {
                    if !waited {
                        st.stats.single_flight_waits += 1;
                        waited = true;
                    }
                    st = self.cv.wait(st).unwrap_or_else(|p| p.into_inner());
                }
                None => break,
            }
        }
        self.make_room(&mut st, bytes)?;
        st.map.insert(key, Slot::Loading);
        st.bytes += bytes;
        st.stats.peak_bytes = st.stats.peak_bytes.max(st.bytes);
        st.loading += 1;
        st.stats.peak_concurrent_loads = st.stats.peak_concurrent_loads.max(st.loading);
        drop(st);
        // From here until the slot is Ready, every exit (error or unwind) goes through the guard.
        let mut guard = LoadGuard {
            cache: self,
            key,
            bytes,
            armed: true,
        };

        let result = match catch_unwind(AssertUnwindSafe(load)) {
            Ok(r) => r,
            Err(p) => {
                self.lock().stats.loader_panics += 1;
                Err(MapError::Terrain(format!(
                    "tile {key:?} loader panicked: {}",
                    panic_message(p.as_ref())
                )))
            }
        };
        let data = result.and_then(|v| {
            if (v.len() as u64).checked_mul(4) != Some(bytes) {
                Err(MapError::Terrain(format!(
                    "decoded tile has {} values, expected {} bytes",
                    v.len(),
                    bytes
                )))
            } else {
                Ok(Arc::<[f32]>::from(v))
            }
        })?;
        let mut st = self.lock();
        guard.armed = false;
        st.loading -= 1;
        st.tick += 1;
        let last = st.tick;
        st.map.insert(
            key,
            Slot::Ready {
                data: data.clone(),
                bytes,
                last,
            },
        );
        st.stats.tile_reads += 1;
        st.stats.decoded_bytes_total += bytes;
        if st.seen.insert(key) {
            st.stats.distinct_tiles_loaded += 1;
        }
        drop(st);
        self.cv.notify_all();
        Ok(data)
    }

    fn make_room(&self, st: &mut State, need: u64) -> Result<(), MapError> {
        while st.bytes + need > self.budget {
            let victim = st
                .map
                .iter()
                .filter_map(|(k, s)| match s {
                    Slot::Ready { data, last, .. } if Arc::strong_count(data) == 1 => {
                        Some((*last, *k))
                    }
                    _ => None,
                })
                .min();
            let Some((_, k)) = victim else {
                return Err(MapError::Budget(format!(
                    "terrain cache budget {} exhausted by pinned/loading tiles ({} resident, {} needed)",
                    self.budget, st.bytes, need
                )));
            };
            if let Some(Slot::Ready { bytes, .. }) = st.map.remove(&k) {
                st.bytes -= bytes;
                st.stats.evictions += 1;
            }
        }
        Ok(())
    }

    pub fn stats(&self) -> CacheStats {
        let st = self.lock();
        let mut s = st.stats.clone();
        s.resident_bytes = st.bytes;
        s.reloads_after_eviction = s.tile_reads - s.distinct_tiles_loaded;
        s
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    #[test]
    fn hits_evictions_and_budget() {
        let c = TileCache::new(32);
        let a = c.get_or_load((0, 0), 16, || Ok(vec![1.0; 4])).unwrap();
        drop(a);
        let _ = c.get_or_load((0, 0), 16, || panic!("must hit")).unwrap();
        c.get_or_load((0, 1), 16, || Ok(vec![2.0; 4])).unwrap();
        c.get_or_load((0, 2), 16, || Ok(vec![3.0; 4])).unwrap();
        let s = c.stats();
        assert_eq!((s.tile_reads, s.hits, s.evictions), (3, 1, 1));
        assert!(s.peak_bytes <= 32);
        // Evicted LRU key (0,0) reloads.
        c.get_or_load((0, 0), 16, || Ok(vec![1.0; 4])).unwrap();
        assert_eq!(c.stats().reloads_after_eviction, 1);
    }

    #[test]
    fn pinned_tiles_are_not_evicted() {
        let c = TileCache::new(32);
        let _a = c.get_or_load((0, 0), 16, || Ok(vec![1.0; 4])).unwrap();
        let _b = c.get_or_load((0, 1), 16, || Ok(vec![1.0; 4])).unwrap();
        let e = c.get_or_load((0, 2), 16, || Ok(vec![1.0; 4])).unwrap_err();
        assert_eq!(e.kind(), "budget");
        assert!(c.stats().peak_bytes <= 32);
    }

    #[test]
    fn single_flight_and_errors() {
        let c = Arc::new(TileCache::new(1 << 20));
        let loads = Arc::new(AtomicUsize::new(0));
        std::thread::scope(|s| {
            for _ in 0..8 {
                let (c, loads) = (c.clone(), loads.clone());
                s.spawn(move || {
                    c.get_or_load((5, 5), 4, || {
                        loads.fetch_add(1, Ordering::SeqCst);
                        std::thread::sleep(std::time::Duration::from_millis(20));
                        Ok(vec![7.0])
                    })
                    .unwrap();
                });
            }
        });
        assert_eq!(loads.load(Ordering::SeqCst), 1);
        assert!(c.get_or_load((1, 1), 8, || Ok(vec![1.0])).is_err());
        assert_eq!(c.stats().resident_bytes, 4);
    }

    /// QA repro R1 as a regression test: a panicking loader must not strand its waiters or its
    /// bytes. Every wait is bounded by `recv_timeout`, so a regression fails instead of hanging.
    #[test]
    fn loader_panic_releases_slot_and_wakes_waiters() {
        use std::sync::mpsc;
        use std::time::Duration;
        let c = Arc::new(TileCache::new(1 << 20));
        let (started_tx, started_rx) = mpsc::channel();
        let (loader_tx, loader_rx) = mpsc::channel();
        let c1 = c.clone();
        std::thread::spawn(move || {
            let r = c1.get_or_load((3, 4), 1024, || {
                started_tx.send(()).unwrap();
                std::thread::sleep(Duration::from_millis(100));
                panic!("simulated decoder panic");
            });
            let _ = loader_tx.send(r);
        });
        started_rx.recv_timeout(Duration::from_secs(5)).unwrap();
        // Concurrent waiter on the same key, started while the loader runs.
        let (waiter_tx, waiter_rx) = mpsc::channel();
        let c2 = c.clone();
        std::thread::spawn(move || {
            let _ = waiter_tx.send(c2.get_or_load((3, 4), 1024, || Ok(vec![1.0f32; 256])));
        });
        let loader = loader_rx
            .recv_timeout(Duration::from_secs(5))
            .expect("loader returned");
        let e = loader.expect_err("panic must become an error");
        assert_eq!(e.kind(), "terrain");
        assert!(e.to_string().contains("simulated decoder panic"), "{e}");
        let waiter = waiter_rx
            .recv_timeout(Duration::from_secs(5))
            .expect("waiter must not hang");
        assert_eq!(waiter.unwrap().len(), 256);
        // A later request is a hit on the waiter's successful reload.
        let later = c.get_or_load((3, 4), 1024, || panic!("must hit")).unwrap();
        assert_eq!(later[0], 1.0);
        let s = c.stats();
        assert_eq!((s.load_errors, s.loader_panics, s.tile_reads), (1, 1, 1));
        assert_eq!(s.resident_bytes, 1024);
        assert!(s.peak_bytes <= 2048);
    }

    #[test]
    fn loader_panic_without_waiters_leaves_no_bytes() {
        let c = TileCache::new(64);
        let e = c
            .get_or_load((0, 0), 64, || panic!("boom"))
            .expect_err("typed error");
        assert_eq!(e.kind(), "terrain");
        let s = c.stats();
        assert_eq!(
            (s.resident_bytes, s.load_errors, s.loader_panics),
            (0, 1, 1)
        );
        // The full budget is available again.
        c.get_or_load((0, 1), 64, || Ok(vec![0.0; 16])).unwrap();
        assert_eq!(c.stats().peak_concurrent_loads, 1);
    }
}
