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

This is a direct recovery API. `RasEbfeModels` validates every central-directory
path before extracting. When a complete ZIP contains Deflate64 members and the
optional decoder is absent, its verified extraction path can use a locally
installed 7-Zip CLI, then performs the same size and CRC32 audit before atomic
promotion. Without either decoder it fails without promoting files.
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

## Complete source reference

### RasEbfeModels source reference

::: ras_commander.sources.federal.ebfe_models.RasEbfeModels
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - available_models
        - download_model
        - download_source_asset
        - get_model_metadata
        - get_source_status
        - list_models
        - normalize_model_key
        - organize_amite
        - organize_austin_oyster
        - organize_bayou_darbonne
        - organize_boeuf
        - organize_cibolo
        - organize_east_galveston_bay
        - organize_double_mountain_fork_brazos
        - organize_eleven_point
        - organize_lake_maurepas
        - organize_lower_brazos
        - organize_lower_colorado_cummins
        - organize_lower_ouachita
        - organize_lower_ouachita_bayou_deloutre
        - organize_medina
        - organize_model
        - organize_models
        - organize_north_galveston_bay
        - organize_pedernales
        - organize_rio_hondo
        - organize_san_gabriel
        - organize_spring_creek
        - organize_spring_river
        - organize_tickfaw
        - organize_upper_guadalupe
        - repair_project_paths


### StreamingZipReader source reference

::: ras_commander.sources.federal.ebfe_extract.StreamingZipReader
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - probe
        - supported_methods
        - walk


### ArchiveSurvey source reference

::: ras_commander.sources.federal.ebfe_extract.ArchiveSurvey
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false


### ExtractStats source reference

::: ras_commander.sources.federal.ebfe_extract.ExtractStats
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - failures_of


### ZipMemberInfo source reference

::: ras_commander.sources.federal.ebfe_extract.ZipMemberInfo
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false


### load_audit_bundle source reference

::: ras_commander.sources.federal.ebfe_audit.load_audit_bundle
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false


### render_audit_markdown source reference

::: ras_commander.sources.federal.ebfe_audit.render_audit_markdown
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false


### actions_from_bundle source reference

::: ras_commander.sources.federal.ebfe_audit.actions_from_bundle
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false


### AuditBundle source reference

::: ras_commander.sources.federal.ebfe_audit.AuditBundle
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false


### RepairAction source reference

::: ras_commander.sources.federal.ebfe_audit.RepairAction
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - as_record
