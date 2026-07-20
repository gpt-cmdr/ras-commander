# HEC-RAS TCU acceptance-state qualification

Date: 2026-07-18

Status: black-box behavior demonstrated on native Windows for the 15 installed
stable HEC-RAS 4.x–7.x builds and on Wine 11.0 for HEC-RAS 7.0.1. A
user-visible, exact-build Wine capture matrix is in progress. This is internal
compatibility evidence, not a vendor-supported interface, and it does not
qualify RAS Mapper, geometry preprocessing, solves, or Windows/Wine result
parity.

## Outcome

The proposed 7.0 → 7.0.1 technical inheritance hypothesis is false in
black-box testing.

- A verified 7.0 state starts 7.0 without the TCU.
- That state does not start the separately installed 7.0.1 build without the
  TCU, whether left in the 7.0 profile scope or copied into the 7.0.1 scope.
- An independently captured, exact-version 7.0.1 state starts 7.0.1 without
  the TCU.
- Missing and random invalid state both display the TCU.

This distinction matters:

- **Recorded user authority:** the user has recorded acceptance for the exact
  installed releases and authorized its use in the controlled Wine test
  environment.
- **Technical continuity:** HEC documents no version-to-version or
  Windows-to-Wine acceptance-state transfer. Every exact installation remains
  an independent black-box target and must pass a fail-closed runtime probe.

HEC describes 7.0.1 as primarily a bug-fix release, but also says it is
installed independently of 7.0. Project compatibility and bug-fix lineage are
not evidence of profile-state inheritance. Do not describe the internal
compatibility work as a USACE-supported Wine or headless-assent mechanism.

## Compliance boundary

HEC's published Terms and Conditions prohibit modification, decompilation,
disassembly, unobfuscation, and reverse engineering of HEC Software. HEC does
not document a registry setting, command-line switch, silent-install option, or
headless API for carrying or recording acceptance state.

Accordingly, publishable qualification must not contain or operationalize
binary-analysis addresses, algorithms, formulas, or derived payloads. It may
record only black-box outcomes for opaque exact-version state and the narrowly
authorized live-dialog workflow documented below. Any undocumented state-copy
implementation remains internal and requires compliance review before release.

## Cross-version matrix

| Release | Black-box status |
|---|---|
| 4.0 | Native exact-version positive/missing/wrong/restored passed |
| 4.1.0 | Native exact-version positive/missing/wrong/restored passed |
| 5.0.3 | Native exact-version positive/missing/wrong/restored passed |
| 5.0.6 | Native exact-version positive/missing/wrong/restored passed |
| 5.0.7 | Native exact-version positive/missing/wrong/restored passed |
| 6.0 | Native exact-version positive/missing/wrong/restored passed |
| 6.1 | Native exact-version positive/missing/wrong/restored passed |
| 6.2 | Native exact-version positive/missing/wrong/restored passed |
| 6.3 | Native exact-version positive/missing/wrong/restored passed |
| 6.3.1 | Native exact-version positive/missing/wrong/restored passed |
| 6.4.1 | Native exact-version positive/missing/wrong/restored passed |
| 6.5 | Native exact-version positive/missing/wrong/restored passed |
| 6.6 | Native exact-version positive/missing/wrong/restored passed |
| 7.0 | Native exact-version positive and cross-version negative passed |
| 7.0.1 | Native and Wine exact-version positive plus negative controls passed |

Patch/base payload reuse was also rejected live for 4.0 → 4.1.0,
5.0.3 → 5.0.6, 5.0.6 → 5.0.7, 6.0 → 6.1, and 6.3 → 6.3.1.
There is no general “minor bug-fix payload inheritance” rule.

### Portability warning

Earlier nonqualifying controls suggested that exact-version state for 4.0–6.0
may not be portable from the accepted Windows workstation to the Wine target,
but they do not settle that question under the compliant black-box evidence
rules. The captured-state diagnostic below is expected to determine
portability, not qualification. Do not calculate a replacement from
undocumented product behavior. Qualification for these builds still requires
an explicitly authorized, exact-version target-local live-dialog workflow,
followed by reversible positive and negative runtime tests. State captured for
6.1 and later must likewise remain opaque, version-bound data and be tested in
the final target.

The installed 6.7 beta builds are excluded from the stable qualification set.
They are governed by HEC's separate Beta Software User's Agreement and require
separately recorded beta authorization before any target-local acceptance flow.

### Captured-state portability diagnostic and qualified exact-build transfer lane

The native private-bundle capture and restoring diagnostic cover the following
exact installed stable builds:

```text
4.0, 4.1.0, 5.0.3, 5.0.6, 5.0.7, 6.0,
6.1, 6.2, 6.3, 6.3.1, 6.4.1, 6.5, 6.6
```

Persistent native-to-Wine transfer remains strictly limited to:

```text
6.1, 6.2, 6.3, 6.3.1, 6.4.1, 6.5, 6.6
```

`tests/qualification/run_capture_acceptance_bundle.py` performs a safe,
full-duration source probe and captures a private exact-version bundle. The raw
bundle necessarily contains product state and must stay outside the repository
in the private qualification artifact store. Console output and its companion
receipt expose only cryptographic hashes.

`tests/qualification/run_captured_acceptance_transfer.py --diagnostic-only`
accepts that bundle only with its separately pinned file hash, the same exact
version and executable SHA-256, and an explicitly disposable Wine target. It
temporarily applies the opaque captured state, runs one safe probe, and restores
the exact prior application subtree. The resulting receipt contains only hashes
and behavioral evidence, explicitly records that persistence was not performed,
and contains no restart probes. A stable main window produces `portable` with
`technical_effective: true`; a safely detected TCU produces the completed
negative result `not_portable` with `technical_effective: false`. In both cases,
top-level `passed: true` means the diagnostic test case completed safely, not
that the target is qualified. Unknown modals, crash/launch failure, timeout,
survivors, termination failure, or incomplete registry/subtree restoration
fail closed. This diagnostic is expected to determine portability, not
qualification; it cannot provision or promote a Wine prefix.

For 6.1–6.6 only, persistent mode additionally requires private authorization
and profile-token files. It runs the restoring diagnostic before persistence
and then requires two independent full-duration restart probes with zero
automated UI interaction, complete process-tree termination, and no survivors.
A post-restart whole-prefix fingerprint is required before read-only template
promotion. Persistent mode rejects 4.x–6.0 before loading private evidence. It
also requires the restoring diagnostic to reach the full-duration stable main
window; a safe `not_portable` result can never continue into provisioning.

Both harnesses reject 7.x and all betas. This constrained design neither derives
a value nor copies between releases. On 2026-07-18, all seven eligible exact
builds passed the dedicated private-runner gate with no critical skips. The
gate verified the self-hashed source and transfer receipts, pinned private-
bundle and prefix-fingerprint files, matching exact source/target version and
executable SHA-256, a successful restoring `captured_verified` diagnostic,
written disposable-prefix provisioning, two full-duration ready restarts with
zero interactions, complete process-tree termination with no survivors, exact
persisted state, and unique profile and prefix fingerprints. This qualifies
only this exact-build captured-state transfer mechanism in the controlled test
environment. It does not qualify cross-version inheritance, vendor support
under Wine, RAS Mapper, or overall native/Wine production parity, and it does
not contradict the failed 7.0 to 7.0.1 inheritance test. Earlier formula-
derived legacy receipts remain suspended and are not evidence for this lane.
For 4.x–6.0, diagnostic results inform the portability assessment only; the
authorized target-local live-dialog session remains the qualification path.
Betas remain separately governed and outside both stable paths.

The hash-only manifest builder, checked-in schema, and fail-closed gate are:

- `tests/qualification/build_portable_captured_transfer_manifest.py`;
- `tests/qualification/manifests/portable-captured-transfer-matrix.schema.json`;
  and
- `tests/qualification/test_portable_captured_transfer_receipts.py`.

The private manifest contains no absolute machine paths or product-state
values. The gate treats source bundles as opaque files, verifies their pinned
hashes, and never decodes or emits their contents.

### Authorized same-build legacy UI fallback

HEC-RAS 4.0, 4.1.0, 5.0.3, 5.0.6, 5.0.7, and 6.0 have a narrowly scoped
fallback for carrying an acceptance the user already completed for the same
exact installed build into a disposable Wine profile. This is not patch/base
inheritance, does not derive a product-state formula, and is not available for
6.1 or later releases or for betas.

The source capture must prove an accepted exact-version/executable-SHA source,
capture its opaque item privately, remove only that item in a restoring
transaction, observe the actual TCU with zero input, restore byte/type/existence
exactly, and repeat the accepted-source probe. The observed modal signature
pins the top-level title/class/body and the semantic Agree, Disagree, Next,
Cancel, Copy, and legal-textbox roles. The initial Agree option must be
unchecked and Next disabled. The source's valid initial Disagree selection is
part of the semantic contract hash and must match the target exactly; no
release-wide default is assumed. Native/Wine implementation-only child-control
differences are separated from semantic equality. Only hidden and disabled
extras are allowed, and each platform's adapter set and full child tree are
separately hashed and receipt-bound. A visible or enabled extra fails before
input.

The target transfer requires the separately pinned private bundle-file hash,
same exact version and executable SHA-256, a disposable destination, and
nonblank private authorization/profile tokens. Before input, its complete live
modal signature must equal the captured source signature. Unknown or ambiguous
windows and preflight mismatches send zero input. The only permitted messages
are `BM_CLICK` to the exact Agree option and, only after proving Agree checked,
Disagree unchecked, and Next enabled, `BM_CLICK` to exact Next. A mismatch after
Agree prevents the Next click and terminates the owned process tree. Success
requires exactly two interactions, no survivors, and two full restart probes,
each preceded by a verified 45-second target-quiet period.

Only the public methods
`RasAcceptanceState.capture_authorized_legacy_ui_transfer_source()` and
`RasAcceptanceState.run_authorized_legacy_ui_transfer()` may start the product
for this lane. The entry point is
`tests/qualification/run_authorized_legacy_ui_transfer.py`; private bundles
must remain outside the repository, and console output/receipts are hash-only.
The fallback remains unqualified build-by-build until the private live source
capture and Wine transfer receipts pass without critical skips.

## Live evidence

All acceptance probes launched the product only through
`RasAcceptanceState.probe()`. No test or orchestration script invoked
`Ras.exe` directly.

### Native Windows

- 4.x–6.x/beta matrix: 65/65 cases passed and 65/65 completed safely.
- 7.0/7.0.1 matrix: 7/7 cases passed and 7/7 completed safely.
- Every negative control detected the actual TCU; no timeout was accepted as a
  negative result.
- Every case recorded zero interactions, verified process-tree termination,
  no surviving tracked process, exact sentinel readback, post-launch sentinel
  content, and exact application-subtree restoration.

### Retained Wine 11.0 diagnostics

Five canonical cases ran in independent clones of the controlled unaccepted
7.0.1 prefix:

| Case | Result |
|---|---|
| Target sentinel missing | TCU detected; safe negative |
| Copied 7.0 state | TCU detected; safe cross-version negative |
| Captured exact-version 7.0.1 state | Stable main window for full 30-second observation |
| Target sentinel random invalid string | TCU detected; safe negative |
| Clean-subtree persistent candidate | Diagnostic plus two 30-second restarts passed technically; not promotion evidence |

All four reversible controls passed integrity validation, made zero UI
interactions, restored the cloned registry subtree, terminated the tracked Wine
process tree, and recorded no survivors. The persistent disposable case made
zero UI interactions during its diagnostic and restart probes. Because the
earlier candidate workflow is not the approved user-visible capture path, that
persistent case is retained only as technical diagnostic evidence and cannot
promote a template. The immutable source template was not modified.

Evidence is retained outside the repository under the private qualification
artifact root `diagnostics/acceptance-state-matrix-20260718`. Canonical report
hashes are embedded in each JSON receipt. The checked-in receipt gate validates
those hashes and all required content.

### 6.4.1 first-start stability

The exact acceptance state was not sufficient by itself for HEC-RAS 6.4.1:
some first starts reached a `RasPlotDriver.exe` time-series child and then a
Wine debugger window. Running the .NET native-image queue did not stabilize
that path. A documented Microsoft WPF configuration did:

```text
HKCU\Software\Microsoft\Avalon.Graphics\DisableHWAcceleration = 1 (DWORD)
```

With WPF software rendering scoped to each disposable prefix, one warm prefix
and two independently rebuilt fresh prefixes each passed missing and invalid
TCU negatives followed by three consecutive approximately 25-second ready
probes. All cases used zero dialog interactions, restored their test state,
terminated the process tree, left no survivors, and had no critical skips.
This qualifies a startup mitigation for the tested 6.4.1 environment; it does
not by itself qualify Mapper mesh/property-table workflows.

## ras-commander implementation

The supported paths in `ras_commander/RasAcceptanceState.py` now provide:

- exact PE version, architecture, path, and SHA-256 identity;
- fail-closed startup probing with full-interval stable-window observation;
- read-only inspection of all process-scoped top-level windows and child text;
- TCU and unknown-dialog blocking without clicking or closing a control;
- tracked descendant-process termination and survivor checks;
- an in-process and OS-wide transaction lock;
- an exact-version, user-driven acceptance session that waits for the actual
  TCU, emits `AWAITING_USER`, and sends no UI input;
- exactly two independent full-duration restart probes after the user completes
  the dialog;
- a separately allowlisted six-build source-capture and exact-two-click legacy
  VB6 fallback with complete source-target modal-signature equality; and
- provenance-bound receipts that hash authorization/profile references without
  reading or serializing the raw acceptance state.

`DialogWatchdog` no longer has a “click the first button” fallback. Generic
OK/Close dismissal requires an exact caller allowlist; current acceptance
qualification provides an empty allowlist. Nonstandard VB/Wine TCU forms are
recognized from title or child-control text even when the class is not
`#32770`. Enumeration/classification errors fail supervision instead of being
silently ignored.

Test assets:

- `tests/test_ras_acceptance_state.py`;
- `tests/test_ras_acceptance_user_session.py`;
- `tests/test_authorized_legacy_ui_transfer.py`;
- `tests/test_ras_dialog_watchdog.py`;
- `tests/qualification/run_acceptance_state_matrix.py`;
- `tests/qualification/run_capture_acceptance_bundle.py`;
- `tests/qualification/run_captured_acceptance_transfer.py`;
- `tests/qualification/run_authorized_legacy_ui_transfer.py`;
- `tests/qualification/run_user_acceptance_session.py`;
- `tests/qualification/run_wine_acceptance_version.sh`;
- `tests/test_wine_prefix_fingerprint.py`; and
- `tests/qualification/test_acceptance_state_receipts.py`.

Two non-canonical provisioning attempts are retained as failure evidence. The
receipts themselves establish only that those attempts did not complete safely;
more specific contemporaneous failure observations are not treated as receipt-
verified causes. Neither failed receipt is accepted by the canonical gate.

## Permitted exact-version user-session procedure

1. Record the user's applicable acceptance authorization separately from the
   technical evidence, and bind the session to the reviewed source-receipt
   SHA-256.
2. Bind the target to normalized PE version, architecture, absolute path, and
   executable SHA-256. The current stable scope is exactly the 15 installed
   builds listed above, not every historical 4.x–7.x release.
3. Use a fresh disposable Wine prefix. Fingerprint the whole prefix before the
   session. Never work in the immutable template or a shared writable prefix.
4. Expose that prefix's display through a loopback-only, access-controlled
   remote GUI and declare the display user-visible to the controlled runner.
5. Start `run_user_acceptance_session.py` through Windows Python under Wine.
   Only `RasAcceptanceState.run_user_driven_acceptance()` may launch the product.
6. Require the actual legal modal to remain stably observed with zero automated
   input. After the harness emits `AWAITING_USER`, the authorized user completes
   the exact-version TCU in the remote GUI.
7. Require an exact-version stable main window, verified process-tree
   termination, no survivors, and exactly two independent full-duration restart
   probes. Any legal/unknown modal, timeout, supervision loss, or survivor fails
   the session closed.
8. Fingerprint the resulting whole prefix and archive the immutable source
   fingerprint plus the self-hashed, provenance-bound session receipt. The
   receipt must not contain raw acceptance state.
9. Promote only the reviewed disposable prefix to a read-only template. Clone
   one prefix and one project copy per scheduler task; never share a writable
   prefix or active HDF model.
10. Keep 6.7 beta builds outside this flow unless a distinct beta authorization
    has been recorded under HEC's Beta Software User's Agreement.

## Standalone preprocess implication

Runtime tests show that the official standalone geometry preprocess executables
used by the qualified workflows do not present the GUI TCU. The current
`RasPreprocess -c` route can encounter the TCU because it launches the GUI
application.

Where the standalone HEC-compiled preprocessor supports the required stage,
ras-commander should invoke it directly and exclusively. TCU provisioning is
for the remaining `Ras.exe`/RAS Mapper compatibility gap, not for official
standalone compute or preprocess executables.

## Remaining qualification boundary

This work resolves the acceptance-state blocker and the unsafe dialog fallback.
It does not change the broader Windows-under-Wine status:

- the direct/unmitigated initial 2D seed-generation path still has
  nondeterministic CLR access violations and non-returning calls under Wine;
- the isolated managed-host path has separately passed exact mesh-count tests,
  but it has not yet closed the complete Mapper qualification lane;
- RAS Mapper property-table generation remains unqualified;
- compute/result parity still requires content-based native/Wine comparison;
  and
- no Wine template should be promoted for production engineering work until
  the full suite passes without critical skips.

## Official sources

- [HEC Software Terms and Conditions](https://www.hec.usace.army.mil/software/terms_and_conditions.aspx)
- [HEC Beta Software User's Agreement](https://www.hec.usace.army.mil/software/beta_user_agreement.aspx)
- [HEC-RAS 7.0.1 release notes](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/latest)
- [HEC-RAS downloads](https://www.hec.usace.army.mil/software/hec-ras/download.aspx)
- [Microsoft VB SaveSetting](https://learn.microsoft.com/en-us/office/vba/language/reference/user-interface-help/savesetting-statement)
- [Microsoft VB GetSetting](https://learn.microsoft.com/en-us/office/vba/language/reference/user-interface-help/getsetting-function)
- [Microsoft WPF graphics rendering registry settings](https://learn.microsoft.com/en-us/dotnet/desktop/wpf/graphics-multimedia/graphics-rendering-registry-settings)
