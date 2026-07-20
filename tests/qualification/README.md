# HEC-RAS 7.0.1 Windows/Wine qualification gate

This directory contains the fail-closed acceptance gate for real HEC-RAS
7.0.1 execution. The gate does not launch a substitute Linux solver and does
not treat a zero process exit code as qualification evidence. It compares
receipts from the native-Windows golden run and the same Windows HEC-RAS build
executed under the pinned Wine image.

The runner must supply:

- `RAS_COMMANDER_RUN_HECRAS_QUALIFICATION=1`
- `RAS_COMMANDER_NATIVE_701_RECEIPT=/absolute/path/native-receipt.json`
- `RAS_COMMANDER_WINE_701_RECEIPT=/absolute/path/wine-receipt.json`
- `RAS_COMMANDER_701_PARITY_TOLERANCES=/absolute/path/tolerances.json`

Run the gate with:

```text
pytest -m "hecras_qualification and qualification_critical" \
  tests/qualification/test_hecras_701_windows_wine.py
```

When qualification is enabled, missing configuration and missing evidence are
failures. A receipt with any missing, failed, or skipped required operation is
also a failure. Skipping the module is only valid for development machines on
which the opt-in variable is absent.

The tolerance file is an engineering-controlled input. It must contain
`volume_accounting`, hydrograph and WSE `series` comparisons, and
`depth_raster`.
Example shape (values are placeholders, not approved thresholds):

```json
{
  "volume_accounting": {
    "max_abs_error_percent": "ENGINEERING_APPROVAL_REQUIRED",
    "max_abs_difference_percent": "ENGINEERING_APPROVAL_REQUIRED"
  },
  "series": {
    "outflow": {
      "key_columns": ["time"],
      "columns": {
        "flow": {
          "max_abs": "ENGINEERING_APPROVAL_REQUIRED",
          "rmse": "ENGINEERING_APPROVAL_REQUIRED",
          "peak_relative": "ENGINEERING_APPROVAL_REQUIRED"
        }
      }
    },
    "wse_cells": {
      "key_columns": ["time", "cell_id"],
      "columns": {
        "wse": {
          "max_abs": "ENGINEERING_APPROVAL_REQUIRED",
          "rmse": "ENGINEERING_APPROVAL_REQUIRED"
        }
      }
    }
  },
  "depth_raster": {
    "max_abs": "ENGINEERING_APPROVAL_REQUIRED",
    "rmse": "ENGINEERING_APPROVAL_REQUIRED",
    "minimum_wet_overlap": "ENGINEERING_APPROVAL_REQUIRED",
    "wet_threshold": "ENGINEERING_APPROVAL_REQUIRED"
  }
}
```

## Executing a lane manifest

The process-isolated runner is separate from the final parity gate. Start with
`manifests/hecras-701-native.template.json`, replace every
`ENGINEERING_*_REQUIRED` value with approved fixture data, and run:

```text
python -m ras_commander.RasQualificationRunner run native-701.json
```

Every action runs in a new process with its own timeout and retained stdout,
stderr, result JSON, and pre/post project fingerprint. The receipt is
checkpointed after every action. Missing handlers, missing fixture parameters,
timeouts, and absent evidence are recorded as failures.

The default handler drives public ras-commander APIs for project lifecycle,
projection/terrain, RAS Mapper mesh generation and mutation, BC association
and repair, Manning's n/land-cover/infiltration/property tables, preprocessing,
unsteady compute, result-layer registration, map export, restart execution,
failed-run diagnostics, and Wine-prefix isolation. Project-lock contention is
fixture/application specific and the template deliberately requires a private
handler; it cannot pass through a generic file-lock substitute.

The restart action is an equivalence test, not merely a second successful
solve. It requires a distinct continuous-run baseline plan, a qualified
restart file, a common comparison time window, profile-line flow and mesh-cell
WSE specifications, engineering-approved series tolerances, and a maximum
volume-accounting difference. The map-export action similarly requires every
requested map type to exist and every raster result to have CRS, shape, and
valid-value content. Land-cover and infiltration actions require both RAS
Mapper registration and exact persisted geometry association before property
tables are computed.

For the Wine lane, use the same approved action list and immutable source
fingerprint, change the profile and receipt, and add an explicit Wine-hosted
Windows Python executor plus prefix template:

```json
{
  "profile": "linux_wine_windows_ras",
  "receipt_path": "/node-local/receipts/wine-701.json",
  "executor": {
    "worker_command": ["/opt/wine/bin/wine64", "C:\\Python311\\python.exe"],
    "payload_path_mode": "wine",
    "winepath_executable": "/opt/wine/bin/winepath",
    "environment": {
      "PYTHONUTF8": "1"
    }
  },
  "wine": {
    "wine_executable": "/opt/wine/bin/wine64",
    "template_prefix": "/opt/ras-wine-prefix-template",
    "prefix_root": "/node-local/wine-prefixes",
    "stage_inside_prefix": true,
    "initialize": true
  }
}
```

The host runner clones the immutable prepared prefix, runs `wineboot --update`,
stages the project under that task's `drive_c`, and only then starts Windows
Python workers under Wine. Host paths in worker payloads and returned evidence
are translated with the configured `winepath`; native Linux Python is not used
as a surrogate for RAS Mapper/pythonnet actions.

Do not put HEC-RAS installers, binaries, Wine prefixes, active HDF files, or
generated receipts in this source directory.

## Acceptance-state qualification

The TCU-state suite is separate from the model/result parity gate. It proves
the fail-closed dialog detector and black-box exact-version behavior across
installed 4.x–7.x builds. Normal probes never click, type, or close a legal
dialog. HEC documents no headless acceptance-state interface and prohibits
reverse engineering, so publishable qualification must use a user-visible,
exact-version acceptance session with recorded authorization and source
evidence. It must not derive or publish product formulas or acceptance-state
payloads.

The stable matrix is the following 15 exact builds installed on the controlled
runner; it is not a claim about every historical point release:

```text
4.0, 4.1.0, 5.0.3, 5.0.6, 5.0.7, 6.0, 6.1, 6.2, 6.3, 6.3.1,
6.4.1, 6.5, 6.6, 7.0, 7.0.1
```

The installed `6.7 Beta 4a` and `6.7 Beta 5` builds are outside the stable
gate. They require a distinct authorization under HEC's Beta Software User's
Agreement and separate evidence. The stable wrapper rejects them.

HEC describes 7.0.1 as primarily a 7.0 bug-fix release, but also says that it
installs independently. Black-box controls reject technical TCU-state
inheritance: a verified 7.0 state did not start 7.0.1 without its TCU, including
after copying it into the 7.0.1 profile scope. Only an independently completed,
exact-version 7.0.1 session passed. Project compatibility and release lineage
must not be treated as acceptance-state inheritance.

Generate the stable native black-box receipt with:

```text
python tests/qualification/run_acceptance_state_matrix.py \
  --output /private/receipts/native-stable-4x-7x.json
```

The runner captures each exact version's already accepted native state in
memory, verifies missing and synthetic-invalid negatives, then verifies only
that same version's captured positive. It accepts no state value on the command
line and performs no cross-version provisioning. The receipt is black-box
behavior evidence, not a supported mechanism for generating or transferring
acceptance state. Optional beta diagnostics require both an explicit beta list
and a separately recorded beta-authorization hash:

```text
python tests/qualification/run_acceptance_state_matrix.py \
  --versions "6.7 Beta 4a,6.7 Beta 5" \
  --include-betas \
  --beta-authorization-sha256 <64-lowercase-hex-authorization-hash> \
  --output /private/receipts/native-beta.json
```

### Captured-state portability diagnostics and the 6.1–6.6 transfer lane

Private source bundles may be captured for this installed stable diagnostic
set:

```text
4.0, 4.1.0, 5.0.3, 5.0.6, 5.0.7, 6.0,
6.1, 6.2, 6.3, 6.3.1, 6.4.1, 6.5, 6.6
```

Only these exact installed stable builds are eligible for persistent native-to-
Wine transfer after the restoring diagnostic passes:

```text
6.1, 6.2, 6.3, 6.3.1, 6.4.1, 6.5, 6.6
```

`run_capture_acceptance_bundle.py` first performs a full-duration, zero-input
source probe and writes an opaque exact-version bundle plus a hash-only receipt
for any build in the 13-build diagnostic set.
The bundle necessarily contains the raw product state: write it only to the
private qualification artifact store, outside the repository, pin its reported
SHA-256 separately, and never print, commit, or redistribute it.

`run_captured_acceptance_transfer.py --diagnostic-only` consumes that private
bundle and its pinned hash inside a fresh disposable Wine target. It fails
unless the target has the same exact version and executable SHA-256 as the
verified source. It temporarily applies the opaque state, runs one safe probe,
and restores the exact prior application subtree. It emits a hash-only receipt
with `persistence_performed: false` and no restart probes. This diagnostic is
expected to determine portability, not qualification: even a passing receipt
cannot provision a prefix, promote a template, or satisfy either qualification
gate. A full-duration stable main window is reported as `status: portable` and
`technical_effective: true`. A safely detected TCU is a completed negative
test case reported as `status: not_portable`, `technical_effective: false`, and
top-level `passed: true`; that means the test case completed safely, not that
the state worked. Unknown modals, launch failure, timeout, survivors,
termination failure, or incomplete registry/subtree restoration fail the
harness and produce no passing receipt.

Run one older-build portability diagnostic with:

```text
python tests/qualification/run_captured_acceptance_transfer.py \
  --ras-executable "C:/Program Files (x86)/HEC/HEC-RAS/4.0/Ras.exe" \
  --expected-version 4.0 \
  --source-bundle /private/bundles/hecras-4.0.json \
  --source-bundle-sha256 <separately-pinned-64-lowercase-hex-digest> \
  --output /private/receipts/hecras-4.0-wine-diagnostic.json \
  --destination-is-disposable \
  --diagnostic-only
```

For 6.1–6.6 only, omitting `--diagnostic-only` selects the persistent lane. It
runs the same restoring check before persistence, provisions only the captured
same-build state, and then requires two independently terminated,
full-duration, zero-interaction restart probes. Authorization and prefix tokens
are required from private files. Capture a whole-prefix fingerprint after the
restarts before promoting a read-only template. Persistent mode rejects every
4.x–6.0 build before loading its private bundle or authorization files and
never treats the diagnostic lane's safe `not_portable` result as authority to
provision.

Both harnesses reject 7.x and all betas. On 2026-07-18, all seven eligible
exact builds passed the dedicated private-runner content gate: each source
capture receipt and private-bundle hash matched the same exact target version
and executable SHA-256; each restoring diagnostic passed; persistent
provisioning was written only to a disposable prefix; both full-duration
restart probes were ready with zero interactions; every process tree was
terminated with no survivors; exact persisted state was confirmed; and every
post-restart prefix fingerprint and profile instance was unique. There were no
critical skips. This qualifies only the captured-state transfer mechanism for
these seven installed exact builds in the controlled test environment. It does
not establish cross-version inheritance, vendor support under Wine, or overall
HEC-RAS/Mapper production parity, and it does not weaken the demonstrated 7.0
to 7.0.1 negative result. Earlier formula-derived legacy receipts remain
suspended and cannot satisfy the gate. For 4.x–6.0, a diagnostic pass only
informs the portability assessment; use the user-visible target-local workflow
for qualification. For 7.x, use that user-visible workflow directly. The 6.7
betas remain outside both stable paths and require separate beta authorization.

The seven-build manifest is generated outside the repository with
`build_portable_captured_transfer_manifest.py`. Its checked-in schema is
`manifests/portable-captured-transfer-matrix.schema.json`; the fail-closed gate
is `test_portable_captured_transfer_receipts.py`. The manifest contains only
relative artifact names, hashes, and non-sensitive qualification metadata. The
gate hashes each private bundle as an opaque file and never decodes or emits
its product state. Run the pinned gate only on the private runner:

```text
python tests/qualification/build_portable_captured_transfer_manifest.py \
  --evidence-root /private/portable-transfer-evidence

RAS_COMMANDER_RUN_PORTABLE_CAPTURED_TRANSFER_QUALIFICATION=1
RAS_COMMANDER_PORTABLE_CAPTURED_TRANSFER_EVIDENCE_ROOT=/private/portable-transfer-evidence
RAS_COMMANDER_PORTABLE_CAPTURED_TRANSFER_MANIFEST_SHA256=<reviewed-manifest-sha256>
pytest -m "hecras_qualification and qualification_critical" \
  tests/qualification/test_portable_captured_transfer_receipts.py
```

### Authorized exact-UI fallback for 4.0–6.0

The only automated TCU fallback is limited to these six exact installed stable
builds:

```text
4.0, 4.1.0, 5.0.3, 5.0.6, 5.0.7, 6.0
```

This is an authorized transfer of an acceptance already completed for the same
exact version, not cross-version inheritance and not a derived product-state
formula. `RasAcceptanceState.capture_authorized_legacy_ui_transfer_source()`
first proves an already accepted source with a full zero-input probe, captures
the original opaque item, removes only that observed item in a restoring
transaction, and observes the actual legacy VB6 TCU without input. It restores
the item byte/type/existence-exactly and repeats the accepted-source probe. A
failure at any point returns no usable capture; the restoring transaction still
must restore the source state.

The captured semantic contract pins the exact top-level title/class/body and
the Agree, Disagree, Next, Cancel, Copy, and legal-textbox roles: control IDs,
classes, canonical caption hashes, visibility, enabled state, and option
selection. Initially, Agree must be unchecked and Next must be disabled. The
exact valid source Disagree selection is included in the semantic hash and the
target must match it; it is not assumed to be the same for every build. After
the exact Agree option is clicked, the only accepted state is Agree checked,
Disagree unchecked, and Next enabled. Platform-specific extra children are
kept out of semantic equality, but only hidden and disabled extras are allowed;
the source and target adapter sets and full child trees are separately hashed,
pinned, and receipt-bound. Any visible or enabled extra fails before input.

`RasAcceptanceState.run_authorized_legacy_ui_transfer()` requires the pinned
private bundle-file hash, the same exact version and executable SHA-256, a fresh
disposable target, and nonblank private authorization/profile tokens. Before
input, the live target modal must equal the source modal signature exactly. An
unknown window, ambiguity, changed handle, or contract mismatch sends zero
input and terminates the owned process tree. The only permitted inputs are
`BM_CLICK` to the exact Agree control and then `BM_CLICK` to the exact Next
control. If any mismatch appears after Agree, Next is not clicked. A successful
session has exactly two interactions, verified termination with no survivors,
and two full restart probes, each preceded by a verified 45-second quiet
period.

Capture and transfer only through the public qualification CLI:

```text
python tests/qualification/run_authorized_legacy_ui_transfer.py capture-source \
  --ras-executable <accepted-native-exact-build-Ras.exe> \
  --expected-version <one-of-the-six-exact-builds> \
  --output-original-bundle /private/tcu/<version>/original.json \
  --output-extended-bundle /private/tcu/<version>/extended.json \
  --output-receipt /private/tcu/<version>/source-receipt.json \
  --private-output-authorized

python tests/qualification/run_authorized_legacy_ui_transfer.py transfer \
  --ras-executable <disposable-Wine-exact-build-Ras.exe> \
  --expected-version <same-exact-version> \
  --source-bundle /private/tcu/<version>/extended.json \
  --source-bundle-sha256 <separately-pinned-file-sha256> \
  --authorization-reference-file /private/tcu/authorization.txt \
  --profile-instance-token-file /private/tcu/profile-token.txt \
  --destination-is-disposable \
  --output /private/tcu/<version>/transfer-receipt.json
```

Private bundles contain opaque product state and must remain outside the
repository. The source and transfer receipts contain hashes and behavioral
evidence only. The fallback remains unqualified for any exact build until its
private live source capture and target transfer complete without critical
skips. It rejects 6.1 and later releases and every beta before identity probing
or launch; those builds use their separately documented lanes.

### Supported Wine capture workflow

Create one fresh disposable Wine prefix per exact build and expose its display
through a loopback-only, access-controlled remote GUI. The user completes the
actual HEC-RAS TCU dialog. The harness only observes windows and process state;
it never sends mouse, keyboard, or dialog messages.

On the controlled runner, set the per-session evidence and authorization
references, then run the stable-build wrapper:

```text
export RAS_COMMANDER_TCU_SOURCE_EVIDENCE_SHA256=<64-lowercase-hex-source-receipt-hash>
export RAS_COMMANDER_TCU_AUTHORIZATION_REFERENCE=<recorded-authorization-id>
export RAS_COMMANDER_TCU_PROFILE_INSTANCE_TOKEN=<unique-disposable-prefix-id>
export RAS_COMMANDER_TCU_DISPLAY=:<user-visible-display>
export RAS_COMMANDER_TCU_USER_VISIBLE=1
export RAS_COMMANDER_TCU_CONTROLLED_ROOT=/absolute/path/to/private-tcu-evidence
export RAS_COMMANDER_TCU_SOURCE_ROOT=/absolute/path/to/ras-commander-checkout
export RAS_COMMANDER_TCU_WINDOWS_SOURCE_ROOT='Z:\mapped\path\to\ras-commander-checkout'

bash tests/qualification/run_wine_acceptance_version.sh \
  "$RAS_COMMANDER_TCU_CONTROLLED_ROOT/manual-user-acceptance/<case>/prefix" \
  <exact-stable-version> \
  "$RAS_COMMANDER_TCU_CONTROLLED_ROOT/manual-user-acceptance/receipts/<case>.json"
```

When the harness prints `AWAITING_USER`, the user completes the displayed TCU
and leaves the session connected. `RasAcceptanceState.run_user_driven_acceptance()`
then requires an exact-version stable main window, terminates the owned process
tree, verifies no survivors, and performs exactly two independent 45-second
full-duration restart probes with a 20-second stable-main-window requirement.
The wrapper refuses prior output, non-disposable paths, builds outside the
15-build stable allowlist, absent source evidence, or a display not explicitly
declared user-visible.

`run_wine_acceptance_case.sh` is a fail-closed tombstone. Its former
hard-coded candidate/provision cases are not an approved acceptance workflow.

`run_user_acceptance_session.py` writes only a provenance-bound receipt. It
hashes authorization/profile references and does not read, print, or serialize
the raw product acceptance state. The private runner must separately retain
whole-prefix fingerprints, the immutable source fingerprint, the exact
executable identity, and the self-hashed receipt before promoting a read-only
template. Never share a writable prefix between builds or scheduler tasks.

### User-driven 15-build receipt gate

The private evidence index for the supported capture workflow is
`user-driven-wine-tcu-matrix.json`. Its checked-in schema is
`manifests/user-driven-wine-tcu-matrix.schema.json`. The schema deliberately
has no field for an acceptance-state value or a derivation rule. Each stable
entry references a self-hashed, exact-version native source-evidence case, the
hash-only user-session receipt, and the whole-prefix fingerprint captured
after both restart probes. The prefix digest covers all normal prefix content;
Wine's external `dosdevices` mappings are excluded from the content root and
represented by the fingerprint helper's separate privacy-preserving digest.

The manifest must contain all 15 installed stable builds in the documented
order. Every profile-token hash and prefix root hash must be unique. The two
installed beta builds may appear only in `beta_receipts`, where the underlying
session receipt must carry a distinct beta-authorization hash. They never
count toward stable completion.

Pin the reviewed manifest's canonical SHA-256 outside the evidence directory,
then run the fail-closed gate on the private integration runner:

```text
RAS_COMMANDER_RUN_USER_DRIVEN_WINE_TCU_QUALIFICATION=1
RAS_COMMANDER_USER_DRIVEN_WINE_TCU_RECEIPT_DIR=/private/receipts
RAS_COMMANDER_USER_DRIVEN_WINE_TCU_MANIFEST_SHA256=<reviewed-manifest-sha256>
pytest -m "hecras_qualification and qualification_critical" \
  tests/qualification/test_user_driven_wine_tcu_receipts.py
```

With the opt-in set, a missing artifact, a source case that is not an opaque
verified exact-version native capture, any critical skip, any automated UI
interaction, incomplete process-tree termination, a survivor, fewer or more
than two strict full-duration restart probes, or a missing post-restart prefix
fingerprint is a hard failure. Development machines may skip the module only
when the opt-in variable is absent. Earlier seven-receipt candidate evidence is
historical, nonqualifying material and must not promote a Wine template.

### Hybrid stable-matrix gate

The all-user-driven gate above remains the strongest uniform control. A
separate hybrid gate permits each exact stable build to use either that same
`user_driven` receipt or a sanitized `captured_verified_transfer` receipt when
the exact-version transfer lane has actually passed. The transfer method does
not accept cross-version evidence: native source and Wine target version and
executable SHA-256 must match. It also requires an explicit authority hash, a
restoring diagnostic, persistent provisioning into a disposable prefix, exact
readback, two strict full-duration zero-interaction restarts, verified process-
tree termination with no survivors, and a post-restart whole-prefix
fingerprint.

The hybrid receipt schema permits registry path/type metadata needed to audit
the restoring transaction, but acceptance-bearing values, authorization
references, and profile tokens are representable only as opaque hashes. Its
exact-version transfer source is bound to the hash-only native capture receipt
and private-bundle file hash; user-driven entries use the hash-only schema-v2
native matrix. Raw or derivation-based receipt evidence is rejected. Current
operational transfer eligibility and its private-bundle handling rules remain
those documented in the 6.1–6.6 transfer lane above.

The checked-in schema is
`manifests/hybrid-wine-tcu-matrix.schema.json`, and the pinned private manifest
is `hybrid-wine-tcu-matrix.json`. Run its fail-closed gate with:

```text
RAS_COMMANDER_RUN_HYBRID_WINE_TCU_QUALIFICATION=1
RAS_COMMANDER_USER_DRIVEN_WINE_TCU_RECEIPT_DIR=/private/receipts
RAS_COMMANDER_HYBRID_WINE_TCU_MANIFEST_SHA256=<reviewed-manifest-sha256>
pytest -m "hecras_qualification and qualification_critical" \
  tests/qualification/test_hybrid_wine_tcu_receipts.py
```

The manifest must still cover all 15 installed stable exact builds with no
critical skips and unique disposable-profile and prefix fingerprints. Optional
betas remain separate and require a distinct beta-authorization hash. A failed
or absent transfer receipt does not become a skip; that build must use the
user-driven method or the stable matrix fails.
