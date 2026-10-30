# Real RASMapper infiltration layer HDFs

Unmodified copies of five infiltration layer HDFs from the public
`gpt-cmdr/ras-hdf-test-corpus` (CC0 for CLB's contribution). They cover the
three ways HEC-RAS keys the class `Variables` table:

| File | Corpus id | Layout | Bytes | SHA-256 |
|---|---|---|---|---|
| `deficitconstant_701.hdf` | `layer701/infiltration.deficitconstant` | 7.0.1, land cover + soils dependencies, names `"<land cover> : <soil>"` | 10,976 | `429d2e21ab80d419a3e7f7659f2c3fc4ac91f78c696fdd600e418ae6ebb4c30c` |
| `greenampt_701.hdf` | `layer701/infiltration.greenampt` | 7.0.1, land cover + soils dependencies | 11,288 | `2541eb1584326e025e0da0a1970b29c2be9491f593da33596addbcdea821b012` |
| `scs_701.hdf` | `layer701/infiltration.scs` | 7.0.1, land cover + soils dependencies, `Properties` | 13,270 | `09518eb9391c7086b5d0db1c32f403c9a7386724d6ed1d507b74e0d88c484587` |
| `deficitconstant_soils_only_rbfs.hdf` | `layer/infiltration.deficitconstant.rbfs` | from a HEC-RAS 6.4.1 model, soils dependency only, names = soil class | 10,994 | `00987aa089c004c7b088a2356dcc1128b1797d250e057ad1a64316687185e0c4` |
| `greenampt_legacy_homewood.hdf` | `layer/infiltration.greenampt.homewood` | legacy layer with its own `Raster Map`, no `Dependency Classifications` | 11,896 | `92e7ec99c7a0e67ce423a28f153d1159b1fa5da76acd8ddc141792a7340fceae` |

Sources: the three 7.0.1 layers were authored by CLB with HEC-RAS 7.0.1
RasMapperLib from the HEC-RAS example project BaldEagleCrkMulti2D inputs
(Source: US Army Corps of Engineers, Hydrologic Engineering Center, HEC-RAS
example projects). `deficitconstant_soils_only_rbfs.hdf` is
`Land Classification/Infiltration_100yr.hdf` of the Downtown Corpus Christi
model (Source: Texas General Land Office, River Basin Flood Studies).
`greenampt_legacy_homewood.hdf` is from the Homewood model (Model by Jacob
Beatty, CLB Engineering Corporation; used with permission).

`tests/test_hdf_infiltration_parameters_real.py` reads them.
