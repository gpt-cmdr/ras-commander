# eBFE tranche 2 — standing brief for every worker subagent

**Written 2026-09-09 by the coordinator.** One subagent per container. Read, in order:
`agent_tasks/2026-09-09_ebfe_tranche2_fleet_handoff.md` (§3 rules, §6 design), `F:\eBFE\AGENTS.md`,
your host's prep report under `.claude/outputs/proxmox/`, and this file. The plan
(`agent_tasks/plans/look-under-h-clb-repos-and-greedy-parnas.md`) §A2b/A3/A4b is authoritative on
gates and decisions if anything here is unclear.

## Non-negotiable rules (each earned by an incident)

1. **Never hash corpus data** (D2). Size vs sidecar, ETag label, zip CRC only. Hashing a git diff or a
   script is fine; hashing anything under `raw/` is not.
2. **Never write under any `raw` tree.** The ro export/bind refuses it; do not work around that.
3. **A durable record is never removed before its replacement is fully written.** The worker writes
   `<dir>.v2tmp` and atomically publishes. Never `rm -rf` anything under `/nas/ebfe/audit/<key>` yourself.
   `_v1/` is never touched.
4. **A changed deploy is verified before it is trusted:** script size > 100,000 bytes, `def main`,
   `def assert_reference_invariants`, `def publish_record`, `py_compile`, then **one real study
   end-to-end with its record verified on disk** before a second study is touched.
   **And diff the deployed script against the retired copy** (`_worker/retired/`): a `read_text`/`write_text`
   round-trip once rewrote 3,563 CRLF line endings and every size/symbol/compile check passed it. The
   current script of record is **revision 20260909c** (b + case-folded plan→HDF lookup in G7 so RasCheck runs on deliveries that lowercase `Output/`) (174,783 B, `WORKER_REVISION` in provenance); the
   snapshot of record is `_worker/build-20260909c/` (`cd8815a7b`).
5. **Every reported gap is reviewed by a different code path** (`deficiency_review.py`) before the unit
   is called audited. Only `review.verdict == real` counts.
6. Framing is "audit log / data gap analysis" in anything user-facing; internal script names are what they are.
7. No HEC-RAS execution, no Wine, in Track 1. Do not touch CT213 (CLB07), VM159 (CLB09, Ajith's
   desktop: if it re-inflates, stop CT191, never VM159), VM100/VM101/the GPU VM (CLB03), VM159/VM160 (CLB04).
8. One agent per container. You own exactly one. Do not SSH into another host's container.
9. Proxmox host-level admin (config, storage, exports) is done from `H:\backups\proxmox` conventions:
   back up any file before editing, record the rollback.
10. You do not audit anything by hand: the worker script does the auditing; you drive it, verify it,
    and report. Write your report to `.claude/outputs/ebfe/2026-09-09-tranche2-<host>.md` and
    return the path plus a five-line summary.

## Path contract inside every container (CT214 is the reference; symlinks are fine)

| Path | Meaning |
|---|---|
| `/nas/ebfe/raw` | ro, 329 study dirs |
| `/nas/ebfe/audit` | rw, the only NAS write path |
| `/work` | container-local scratch, `/work/<key>[__<area>]` per unit |
| `/mnt/ras2cng-work/ebfe/src/rc-tree` | library snapshot (editable install) — **the worker's `git_provenance()` hardcodes this path** |
| `/mnt/ras2cng-work/ebfe/venv/bin/python` | venv with ras-commander editable + `zipfile-deflate64` |
| `/mnt/ras2cng-work/ebfe/scripts/` | `ebfe_worker.py`, `deficiency_review.py`, `reclassify_model_type.py`, drivers |
| `/mnt/ras2cng-work/ebfe/logs/` | one log per unit |

**Library snapshot of record:** `/nas/ebfe/audit/_worker/build-20260909c/rc-tree.tgz` (~227.9 MB) with
`rc-tree.provenance.json` (`git_commit cd8815a7b…`). Builds `20260909` and `20260909b` are superseded. Unpack it to `/mnt/ras2cng-work/ebfe/src/` (it contains `rc-tree/`), then
`uv pip install -e /mnt/ras2cng-work/ebfe/src/rc-tree zipfile-deflate64` into the venv. Verify:
`python -c "import ras_commander.sources.federal.ebfe_extract as m; print(m.__file__, m.StreamingZipReader.supported_methods())"` (`supported_methods` is a classmethod on `StreamingZipReader`)
→ path under `rc-tree`, `(0, 8, 9)`; and `cat rc-tree/.provenance.json` shows the same commit and
`snapshot_content_sha256` as the NAS copy. Every `_audit.json` you produce must carry that provenance.
Do not re-sync from `H:\` — the tarball is the single source so all four hosts are byte-identical.

**Build deps:** `zipfile-deflate64` has no cp312 wheel — `apt-get install build-essential` before the venv install
(Debian 12 containers). **`EBFE_HOST=<host>` must be exported** before running the drivers (e.g. `clb04b` on CT216);
otherwise `run_unit.sh` derives the host from the container name and can write another worker's hostlog.

**Java:** the worker's DSS verification uses the Java bridge (`RasDss._ensure_monolith()`); CT214 has
OpenJDK 17. Install `openjdk-17-jre-headless` if absent and export
`JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64` in every driver invocation. If the bridge cannot come
up the worker records the reason and continues — but say so in the report.

**Scripts of record:** copy `ebfe_worker.py` (169,723 B), `deficiency_review.py`,
`reclassify_model_type.py` from `/nas/ebfe/audit/_worker/` into `scripts/`. Run the deploy gate (rule 4).

**DSS bridge parity (added after Phase 1):** CT214 verifies DSS boundaries through `pyjnius` plus the
native HEC monolith at `/root/.ras-commander/dss/lib/libjavaHeclib.so`; the other hosts had neither, so
every boundary came out `inferred`. Install from the NAS, not the internet:
`uv pip install -r /nas/ebfe/audit/_worker/build-20260909/dss-python-deps.txt` into the venv, and
`tar -xzf /nas/ebfe/audit/_worker/build-20260909/dss-runtime-root.tgz -C /root` (creates
`/root/.ras-commander/dss/`). Verify with the venv, with `JAVA_HOME` exported (`import jnius` needs it at import time; a JRE is enough):
`python -c "import jnius; from ras_commander.dss import RasDss; RasDss._ensure_monolith(); print('DSS bridge ok', jnius.__version__)"`.
Verify by the import, never by `pip`'s exit code (an empty requirements file installs nothing and exits 0 --
the first copy of `dss-python-deps.txt` was 0 bytes; it now reads `pyjnius==1.7.0`, wheel, no compiler).
`libjavaHeclib.so` needs `libgfortran5` (`apt-get install libgfortran5`; check `ldd /root/.ras-commander/dss/lib/libjavaHeclib.so`
shows nothing missing). **`bridge=True` is not the proof** -- CT220 had it while resolving 0 of 35 boundaries; the proof is the
worker log line `DSS verification: bridge=True boundaries N resolved` with N > 0 on a study that has DSS-backed boundaries.

**Thin-provisioned scratch (CT220, CT215, CT191):** a discarded extraction does not return blocks to the
thin pool. Run `sync && fstrim /work` after every unit (the shared driver does this -- without the `sync`, ext4 had not released the blocks yet and 17-24 GiB stayed allocated); CT220's pool rose
67.7 → 70.6 % on one 25 GB study until trimmed.

**Memory accounting:** `memory.peak` saturates at the container cap with page cache and says nothing
about headroom. Record `anon` from `memory.stat` (peak of it during the run) as the working-set number.

**Shared drivers (published by CT214):** `/nas/ebfe/audit/_worker/tranche2/run_unit.sh <key> [area] <work-unit> <jobs>`
runs the whole chain, verification and hostlog; `pick_next.py --max-gb X [...]` chooses the largest
eligible study. **`_worker/tranche2/` is a distribution point, never an execution path.** Copy the drivers into the
container-local `scripts/` at a unit boundary and run them from there. Bash reads a script incrementally, so an
`mv -f` onto a driver another host is executing from the NAS kills that run with `Stale file handle` (it
happened to CT214 mid-Rio-Chama: the worker had published, the review chain never ran). Publishing a driver
revision: write to a temp name and rename, note it in the file header, and retire the old copy. A loop must
also confirm an `rc=2` against the record's actual `stage` — a died script and a deferral look alike.

## The per-unit chain (what "one study" means)

```
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
PY=/mnt/ras2cng-work/ebfe/venv/bin/python; S=/mnt/ras2cng-work/ebfe/scripts; L=/mnt/ras2cng-work/ebfe/logs
cd /work && $PY -u $S/ebfe_worker.py <key> [--area <substr>] --jobs <N> --work-unit <model|group> --discard > $L/t2_<key>[_<area>].log 2>&1
$PY $S/deficiency_review.py <key>[/<area>]                 # ALWAYS pass the unit: with no argument it silently re-reviews every tranche-01 unit. Review (writes deficiency_review.jsonl, gaps review verdicts, _audit.json["deficiency_review"], re-renders the .md)
$PY $S/deficiency_review.py --disambiguate <key>[/<area>]  # proximity + same-path duplicate rule
verify: _audit.json exists, ≥ 1000 B, stage == "audited" (or "deferred" with result DISK_INSUFFICIENT), audit_schema_version == 2,
        "deficiency_review" block present, "provenance" matches the snapshot, "critical_missing" key present (list, may be empty),
        "terrain" has "modifications", exactly one *_audit.md > 2000 B, no <dir>.v2tmp / <dir>.prev left, _claims entry released.
```

`--work-unit`: `model` for 2D studies, `group` for 1D (D13). Decide from the probe / geometry text
the way tranche 01 did; the worker records `model_type_basis`. When unsure, `model`.
`--jobs`: CT214 7 · CT215 6 · CT191 6 · CT220 3. Phase 1 showed the 8 GiB hosts are inflate-CPU-bound, not memory-bound (anon ≤ 630 MiB; the rest of `memory.peak` is page cache).

**Multi-archive studies (43 in the queue):** run whole-study first. If G2's space gate defers
(`DISK_INSUFFICIENT`), split by model area using `--area <substring of archive name>`, one area at a
time, the way `12070104` ran as `LB_MA01/LB_MA02/LB_MA03`; each area lands under
`/nas/ebfe/audit/<key>/<area>/`. Never split a single archive.

**Memory:** after every unit, record the container's peak
(`cat /sys/fs/cgroup/memory.peak` inside the container, or `/sys/fs/cgroup/lxc/<ctid>/memory.peak` on
the host) plus wall seconds, archive GB, uncompressed GB and MB/s into
`/nas/ebfe/audit/_worker/hostlog/<host>.jsonl` (one JSON line per unit). CT191 and CT220 use this to
earn larger studies.

## The queue and routing

`F:\eBFE\audit\_index\tranche2_queue.csv` (`/nas/ebfe/audit/_index/tranche2_queue.csv`): 319 studies,
largest-first, columns `rank,key,key_kind,name,gb,archive_count,band,archives`. Bands: `>300` 5 ·
`100-300` 41 · `25-100` 105 · `5-25` 59 · `<5` 109.

A study is **done** when `/nas/ebfe/audit/<key>/_audit.json` (or every area's) has `stage: audited`.
A study is **in flight** when `/nas/ebfe/audit/_claims/<key>*.json` exists with a heartbeat younger
than its `lease_seconds`. `stage: deferred` is **not done** — a host with more scratch takes it.
The worker's `O_CREAT|O_EXCL` claim is the arbiter; if the claim fails, take the next study.

| Host | Container | Scratch | RAM | Takes (archive GB on disk) |
|---|---|---|---|---|
| CLB04 `.104` | CT214 | ~579 GB free | 28 GiB | `>300` (split by area when the probe says so) and `100-300` first |
| CLB09 `.109` | CT191 | 700 GiB budget | 8 GiB, swap 0 | `25-100` until `memory.peak` shows headroom, then anything that fits |
| CLB03 `.103` | CT215 | 227 GiB free | 48 GiB | ≤ ~140 GB archives (scratch/1.6), the `25-100` band and small; Alabama later |
| CLB07 `.107` | CT220 | 80 GiB `/work` | 8 GiB | ≤ ~45 GB archives; the `5-25` and `<5` bands |
| CLB04 `.104` | CT216 (new, 2026-09-09 evening) | ~200-250 GiB dataset on `clb04-scratch` | 12-16 GiB | ≤ ~140 GB, `--jobs 4` |
| CLB02 `.102` | new container (2026-09-09 evening; recon → bring-up) | per recon | per memory policy | cap = scratch/1.6; ≤ 100 GB if the link is 1 GbE |

Rule of thumb: an archive of X GB needs ~1.25–1.6 X of scratch uncompressed; the worker's G2 probe
measures the real number before a byte moves and defers rather than fails. Trust the probe.

## Phase 1 (now): one study per host, then STOP and report

Deploy, gate, run **one** study from your band end-to-end through the chain, verify the record,
write the hostlog line, write the report, return. Do **not** claim a second study until the
coordinator says the queue is open — the four first records are compared before the batch starts.

Your report must end with: usable yes/no · study key, band, GB · wall seconds and MB/s · `memory.peak` ·
`deficiency_review` totals (reported/real/analysis_gap/unverifiable) · verdict line from the rendered
`_audit.md` · anything the chain needed that this brief did not say.

## Host flag sets for `pick_next.py` (capacity is the rule; the band column above is a guide)

| Host | Flags |
|---|---|
| CT214 | no cap (largest first; split by `--area` when G2 defers) |
| CT191 | `--max-gb 300 --jobs 6` (Phase 1 measured anon peak 629 MiB at 3 jobs on a 4-project study; re-check anon on the first ≥1,000-project study before going above 300) |
| CT215 | `--max-gb 140` |
| CT220 | `--max-gb 45` |
| CT216 (CLB04b) | `--max-gb 140 --jobs 4` |
| CLB02 | `--max-gb <scratch/1.6>` |
| CT215 (CLB03, 2 TB pool) | no cap, `--jobs 6` |

Multi-archive studies are not excluded by default; the worker probes and defers if they do not fit.

## Gate for the revised worker (build-20260909c)

The worker script of record gains a revision (case-folded relocation index and resolver; terrain
`critical_missing` only when the HDF itself is absent; `.vrt` tile lists in the absolute-path closure) and the
snapshot moves to `_worker/build-20260909c/`. Every host re-runs **its own Phase-1 study** through
`run_unit.sh` as the one-real-study gate (CT214 `12100202`, CT220 `12060204`, CT191 `13060009`; CT215 when it
returns), which replaces the record through the v2tmp/publish path and keeps the four-way comparison. The DSS
bridge must show `bridge=True` in that run. Only then does the queue open.

**Deploying a later worker revision mid-queue:** swap the script between units (never while one runs), run the
gate checks including the diff against the retired copy, and treat the next unit's verified record as the
one-real-study proof. The revision is recorded per record, so mixed revisions in the tree are legible.

## Phase 2 (after the coordinator's go): the loop

Loop: pick the largest not-done, not-in-flight study your host may take → chain → verify → hostlog →
next. One unit at a time per container. Stop on the first verification failure and report; never
skip a failed unit silently. Check `pgrep -f ebfe_worker.py` before every claim (one job per container).
