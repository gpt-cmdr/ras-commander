# Floodway text-input fixtures

Unmodified files from the USACE HEC-RAS 7.0 example projects
(`Example_Projects_7_0.zip`, https://www.hec.usace.army.mil/software/hec-ras/download.aspx).
Source: US Army Corps of Engineers, Hydrologic Engineering Center.

| File | Example folder | SHA256 |
|---|---|---|
| `FLODENCR.F01` | Applications Guide/Example 6 - Floodway Determination | `1caca1726627ce1a2f3ba7ab45d1372feddb76ea6590dce8bc926c8e191a52d8` |
| `FLODENCR.F02` | Applications Guide/Example 6 - Floodway Determination | `6a05d624d7f1ef1e1f4ec8fd6882b051d579a3eb39f6ee691518b08a9bc207b5` |
| `FLODENCR.P02` | Applications Guide/Example 6 - Floodway Determination | `ec6466111515dc1d380c565a0b152c095d09ae854009e06698f0eb42023d1bc0` |
| `FLODENCR.p04` | Applications Guide/Example 6 - Floodway Determination | `895271dd9a1b81aab6897a6b253938dc42870cd3069acfb3b60fe4285b8d91c6` |
| `flodencr.p01` | Applications Guide/Example 6 - Floodway Determination | `a5f3d7b2fed6cbba52f98233a9574ece09b6fad3abd665bcb32a3c71bfa29eb3` |
| `Baxter.f01` | 1D Steady Flow Hydraulics/Baxter RAS Mapper/RAS Model | `87bdc0e6a4eb9ed155b2a81863c1d54e1a70c137d49d2e925c33d768d9db11c6` |

`tests/test_floodway_text_and_lateral_sources.py` places them next to minimal
plan HDFs and, when `RAS_ROUTE2_FIXTURES` lists them, next to the computed corpus
plan HDFs (`FLODENCR.p02`, `FLODENCR.p04`, `Baxter.p01`).
