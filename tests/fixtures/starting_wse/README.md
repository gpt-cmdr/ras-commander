# Steady boundary-condition text fixtures

Unmodified files from the USACE HEC-RAS 7.0 example projects
(`Example_Projects_7_0.zip`, https://www.hec.usace.army.mil/software/hec-ras/download.aspx).
Source: US Army Corps of Engineers, Hydrologic Engineering Center.

| File | Example folder | SHA256 |
|---|---|---|
| `FLODENCR.F01` | Applications Guide/Example 6 - Floodway Determination | `1caca1726627ce1a2f3ba7ab45d1372feddb76ea6590dce8bc926c8e191a52d8` |
| `FLODENCR.F02` | Applications Guide/Example 6 - Floodway Determination | `6a05d624d7f1ef1e1f4ec8fd6882b051d579a3eb39f6ee691518b08a9bc207b5` |
| `FLODENCR.P02` | Applications Guide/Example 6 - Floodway Determination | `ec6466111515dc1d380c565a0b152c095d09ae854009e06698f0eb42023d1bc0` |
| `FLODENCR.p04` | Applications Guide/Example 6 - Floodway Determination | `895271dd9a1b81aab6897a6b253938dc42870cd3069acfb3b60fe4285b8d91c6` |
| `NIT.f01` | Applications Guide/Example 12 - Inline Structure | `52d9e756ab43fdeb7a91e0d9c2a5d7b78fa7e4b5a57a31e46365d99b28e32f14` |
| `NIT.p01` | Applications Guide/Example 12 - Inline Structure | `3fc32b531dafe2d0e384484c3a3b062d4002b7db07e140ae266f920d1af937d8` |
| `MIXED.f01` | 1D Steady Flow Hydraulics/Mixed Flow Regime Channel | `a0c50328fdf645d93b0d7bc1be7ac926fa1252505f7dce531ad37b925ad62e32` |
| `MIXED.P01` | 1D Steady Flow Hydraulics/Mixed Flow Regime Channel | `d9d7603042601db759779902b688dfb86581508cd5b58ac28770d176a3b07f0c` |

`tests/test_starting_wse_method_sources.py` reads them next to minimal plan HDFs
(and, when `RAS_ROUTE2_FIXTURES` lists them, next to the computed corpus plan
HDFs `FLODENCR.p02`/`FLODENCR.p04`).
