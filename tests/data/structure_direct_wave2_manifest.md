# Retained direct-structure result evidence

`structure_direct_wave2_manifest.json` retains five public example result files
and 18 direct structure identities from the historical Wave 2 h5py oracle.
It records relative paths, whole-file SHA256 values, geometry table row IDs,
primary dataset shapes, dtypes, byte hashes, and stored `Variable_Unit` labels.
The file counts are BaldEagle 11, Beaver 1, Orleans 2, Inline_3Gates 1, and
JunctionHydraulics 3. All four supported direct families are represented.

The recovered source is:

`working/ras-native-engine-integration/runs/successor-parity-w2-20261020/evidence/oracle/oracle.json`

Source SHA256:
`7ae4c1ee0f0c5054de87793eb529ba4c30c6e7815b6077d9dfa56ad5f157b7c1`

The original implementation and review reports at
`working/ras-native-engine-integration/runs/successor-hdf-fixes-20261020/audit-struct/OUTPUT.md`
and `MAIN_REVIEW.md` report five files, 18 identities, and 54 exact maxima.
The recovered oracle supports those file and identity counts. It contains
array hashes rather than maxima. The original result HDFs and the author's
`F06-exact.json` were unavailable during this test addition. The delivered
oracle copy's byte identity to the author's separate scratch oracle was not
independently authenticated. Retaining this manifest does not constitute a
new producer or native-engine qualification run.

To verify relocated files, set `RAS_STRUCTURE_CORPUS_ROOT` to the directory
containing the manifest's relative paths, then run:

```text
python -m pytest tests/test_hdf_struc1d_direct_corpus.py -q
```

The opt-in test checks file and primary-array hashes, exact geometry identity,
stored labels, inventory membership, and 54 API maxima against independently
read raw columns. An unset root skips five corpus tests. An explicitly selected
corpus with missing files or wrong hashes fails. No solver or native engine is
invoked. The always-running tests in `test_hdf_struc1d_direct_families.py` use
small sanitized HDF format fixtures and establish schema behavior only.
