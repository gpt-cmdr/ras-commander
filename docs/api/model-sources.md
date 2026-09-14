# Model Source Utilities

Utilities for inspecting and recovering delivered model archives live under
`ras_commander.sources.federal`.

## Streaming ZIP Recovery

`StreamingZipReader` walks ZIP local-file headers in order, so it can survey or
extract archives whose central directory is missing. It verifies each extracted
member against its recorded CRC and reports truncation and unreadable members
instead of silently skipping them.

```python
from pathlib import Path

from ras_commander.sources.federal import StreamingZipReader

archive = StreamingZipReader(Path("delivered-model.zip"))
survey = archive.probe()
print(len(survey.members), survey.truncated)
```

When an archive has neither a central directory nor sizes in its local headers,
`probe()` must scan compressed member data to locate each trailing descriptor.
The per-member scan is bounded by `max_probe_member_size` (64 GiB by default).

Deflate and stored members use the Python standard library. FEMA deliveries
compressed with Deflate64 require the optional dependency:

```shell
pip install "ras-commander[ebfe]"
```

The `ebfe` extra installs the decoder on Python 3.10, the newest interpreter
for which its publisher provides wheels. It is intentionally excluded from
the broad `all` extra so Python 3.11+ installations do not depend on an
unqualified native source build.

Deflate64 members require an authoritative compressed size from a local or
central-directory record. Deferred-size Deflate64 members in archives with no
central directory are reported as unsupported because the dependency does not
expose the exact compressed boundary.

This is a direct recovery API. `RasEbfeModels` does not automatically invoke it.
Archive member names are untrusted input. A `sink_factory` must normalize each
name and verify that its output path remains below the intended destination.

## Audit Rendering

`ebfe_audit` turns an existing `_audit.json` bundle and its JSONL sidecars into
a consistent review document covering the delivery verdict, inventory,
supporting data, repair actions, missing inputs, acquisition needs, and
provenance. It renders captured audit evidence; it does not generate the audit
bundle itself.

```python
from pathlib import Path

from ras_commander.sources.federal.ebfe_audit import (
    load_audit_bundle,
    render_audit_markdown,
)

audit_folder = Path("model-audit")
bundle = load_audit_bundle(audit_folder)
(audit_folder / "AUDIT.md").write_text(
    render_audit_markdown(bundle),
    encoding="utf-8",
)
```
