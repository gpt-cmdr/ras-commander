# Native reference-point connection regression

`bald_eagle_connection.g09` is a 2,864-byte text excerpt derived from the public
USACE HEC-RAS 6.6 example archive distributed by `RasExamples`:

- Asset: `Example_Projects_6_6.zip`, release `1.0.33`.
- Member: `2D Unsteady Flow Hydraulics/BaldEagleCrkMulti2D/BaldEagleDamBrk.g09`.
- Member SHA256: `8666056c38dfc0edfebdd27dcfd165495d37875c25ea034ec814dbd25eabe3d5`.

The geometry title, program version, storage-area declaration, Sayers Dam
connection (41 vertices, crest profile, and two gate openings), and LCMann
timestamp come from that public example. Its doubled CR line endings are
normalized to CRLF; numeric fields and connection records retain their source
text. No client data, local source paths, mesh, terrain, or results are included.
The retained excerpt consists of USACE example input records, not third-party
imagery or other externally licensed archive assets.

The three native point pairs are authored with
`GeomReferenceFeatures.add_reference_points` using notebook 207's Bald Eagle
coordinates and literal names. The `IC Point Name=Reference Point RP_Upper`
record, position, and elevation are explicit test additions for IC separation.
Native points immediately follow the connection, without intervening BC or
reference-line blocks, to reproduce the connection ownership regression.

This is a parser/editing fixture, not a complete or compute-ready model. Tests
copy it to pytest temporary directories and never preprocess or execute HEC-RAS.

## Retained native-output evidence

`qualification_evidence.json` anchors notebook 207's saved output to its retrievable
PR #553 head and records notebook/canonical-output checksums. The exact computed
HDF was recovered read-only from CLB-JACOB at:

`D:/CLB-Dev/ras-commander-refpoints/working/reference_points_207/computed_d8a51a03/BaldEagleDamBrk.p03.hdf`

The manifest records its whole-file SHA256, stored point names/coordinates/cell
IDs, 145 ten-minute timestamps over one day, signed reference-line flow, and
complete API-returned array fingerprints. Source and retained-copy hashes matched
before and after verification. Geometry, shapes, names, cadence and sampled values
match notebook cell 11's saved display at its printed precision.

Run the read-only retained-output test with `RAS_REFERENCE_POINT_HDF` pointing to
that exact file or a byte-identical copy. The large HDF remains outside Git. An
explicitly configured missing/wrong file fails; an unset path skips this optional
producer-evidence test.

This supersedes reliance on the unavailable historical commit cited in the PR
body. Recovery and inspection do not constitute a new solver run, hydraulic
acceptance or cross-version qualification. The recorded permalink retains the
notebook independently of the original workstation path.
