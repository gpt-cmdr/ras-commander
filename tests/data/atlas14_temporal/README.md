# NOAA Atlas 14 temporal-distribution fixture

`tx_3_24h_temporal.csv` is the NOAA Atlas 14 Texas, region 3, 24-hour
temporal-distribution CSV used by the shared-pattern grid regression tests.

- Source: <https://hdsc.nws.noaa.gov/pub/hdsc/data/tx/tx_3_24h_temporal.csv>
- Accessed: 2026-10-03
- SHA-256: `541ab538bbcc839e5709a50567420b47429ba197032b0c8c204c7308822072e0`

The fixture is retained so tests select the known NOAA curve without requiring
network access. It is unmodified source text, not a storm-total grid or a
model-input file.
