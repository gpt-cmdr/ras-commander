# Conformance: pure-Rust readers against h5py on HEC-RAS files

## Byte-level agreement

The test compared every dataset's raw bytes (CRC32) between the reader and h5py, each reading
with the dataset's own on-disk type.

- **Files:** 80 HEC-RAS geometry and plan files, chosen for diversity, from versions 5.0.7, 6.1,
  6.2, 6.3 beta, 6.4, 6.4.1, 6.6, 6.7 beta, 7.0 and 7.0.1. They include 555–582 MB LWI plans.
- **Results:**

| Reader | Result |
|---|---|
| `hdf5-reader` 0.9.1 (crates.io) | No geometry or plan file can be walked (see the bugs below) |
| `hdf5-reader` with netcdf-rust#95 | **16,889 / 16,889 datasets identical** |
| `hdf5-pure` 0.47.0 | 16,889 / 16,889 identical |

## Bugs found and fixed upstream

Both are fixed in [roteiro-gis/netcdf-rust#95](https://github.com/roteiro-gis/netcdf-rust/pull/95),
with unit tests and fixtures.

1. **Compound member names (version 1 and 2 datatypes).**
   - The spec pads each name to a multiple of 8 bytes counted from the start of the name. The
     reader aligned the absolute cursor position instead.
   - After a member whose type description isn't a multiple of 8 bytes long (a 16-byte string,
     or a float's 20 bytes), the parse went off course: `unsupported datatype class 13`.
   - Every HEC-RAS attribute table hits this: `Geometry/2D Flow Areas/Attributes`,
     `Geometry/Structures/Attributes`, `Results/Summary/Compute Processes`, and land-cover
     `Raster Map`.
2. **Old fill value message (type 0x0004).**
   - The message is a 4-byte size followed by the value. The reader took the size as part of the
     value.
   - So an unallocated chunk of an int32 dataset with fill value `i32::MIN` read back as
     `[4, i32::MIN]`. Seen in `FacePoints Face and Orientation Values` of a BaldEagle g09.

## Known gaps

- **User blocks:** files with an HDF5 user block (e.g. NOAA VIIRS SDRs) fail in `hdf5-reader`.
  No HEC-RAS file seen has one.
- **Space-padded strings:** HEC-RAS stores many fixed-length strings space-padded. h5py returns
  the raw padding, so a backend must trim trailing spaces and NULs exactly as ras-commander does
  today.
- **Ghost cells:** time-series columns outnumber the real cells, because ghost cells follow the
  real ones. Align by cell index, as ras-commander does (#534).

## Conformance suite to build before shipping

- **h5py raw-byte CRCs** for every dataset in the fixture set.
- **ras-commander outputs:** mesh names, cell polygons, summaries, time series and timestamps
  must match within float tolerance, including ids and the dry/ghost semantics.
- **CI:** run on every crate update and every new HEC-RAS release, against the BaldEagle fixtures
  plus one large plan.
