# Changelog

## Unreleased

- Preserve stock h5py caches on fresh reads; size caches automatically with
  opt-in handle reuse or explicit configuration. Raw caches cost up to64MiB
  per live dataset (six can retain roughly384MiB); repeated handles are needed
  for cross-call benefit. Reuse stays off by default.
- Suspend read-handle reuse throughout RasCmdr compute calls and close caches
  again before launch. Finish active reads and close cached handles before
  external writers, replacement or fork; concurrent writes are unsupported.
- Validate HDF cache environment settings with logged fallback to defaults.
