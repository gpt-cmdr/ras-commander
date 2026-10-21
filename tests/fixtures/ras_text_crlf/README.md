# Steady-flow newline regression canary

`canary_86.f01` is the unchanged 12,281-byte public-writer control retained at
`\\192.168.3.20\FIM-Commander\runs\12090301\native-writer-probes\wb-2430601\d30bcc9ff7de\model\gen2.f01`.
SHA256: `b0f0ae06953c12d6673090f79ece99785f61e525ef39d6090d64c95b79a6a5c1`.

Provenance: `H:/CLB-Repos/agent_tasks/fim-next-2026-10-01/I_1d_exec/REPORT.md`
and `WINDOWS86_WRITER_PROBE.json`, 2026-10-01. The otherwise identical LF input
failed the pinned HEC-RAS 6.6 Wine engine; this CRLF control passed with all 86
profiles and 2,236 result/flow comparisons. The fixture has 386 CRLF records.
These tests verify serialization and parsed equivalence; they do not execute
the engine or establish hydraulic acceptance of the derived ladder.
