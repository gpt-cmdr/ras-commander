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

`qualification_evidence.json` anchors notebook 207's saved outputs to the
retrievable PR #553 head, with notebook and canonical saved-output checksums.
It records the displayed 145 time steps, three literal native point names,
and signed reference-line flow without rerunning the solver. The notebook is
retained in Git at the manifest's immutable permalink. This supersedes reliance
on the unavailable historical commit cited in the original PR description.

The original computed HDF has not been independently located or hashed on this
review workstation. Its recorded relative path is included for recovery; a null
HDF checksum is an explicit evidence gap, not an empty or passing validation.
Saved notebook displays do not provide every source array. Keep that gap open
when assessing native qualification or issue #466; parser regressions and stored
notebook output alone do not establish hydraulic acceptance.
