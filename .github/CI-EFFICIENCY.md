# CI efficiency: purpose and validation boundaries

Bill requested this implementation on 2026-11-26 after reviewing Vincent Koc's [OpenClaw CI assessment](https://vincent.build/openclaw-ci-cost-reduction/). The goal is shorter useful feedback, less repeated setup and lower Windows queue pressure, so burst machines return to engineering sooner. It is not a target for deleting tests or claiming OpenClaw's savings for this fleet.

## Repository behavior

Native DSS keeps its Linux native, Windows native and Windows Java-shadow owners, engine identity guard and minimum-passed guard. Only a proven documentation-only diff skips that matrix; any production, test, fixture, configuration, deleted or uncertain input runs the complete existing matrix. Superseded PR revisions cancel; main validation is not interrupted. This first selector deliberately does not infer Python import dependencies. Further subsystem narrowing needs historical-regression replay before adoption.

## Agent guidance

Run cheap local formatting/lint and focused checks before pushing, then retain the repository's normal CI and release evidence. Do not install hooks or change dependency versions merely to optimize CI. Record a named behavior contract before consolidating tests; preserve the only useful regression guard and platform/integration boundaries. Shared inputs, fixtures, lockfiles, workflow edits and unknown owners widen selection. CLB_CI_FULL=true is a repository-variable escape hatch for the conservative planner where present; scheduled/manual validation is broad. Main/release results qualify their exact revision, not a later commit.

Use command timing receipts and cache-hit evidence to distinguish setup from useful work. CI timing JSONL files are written under RUNNER_TEMP/ci-receipts and phase summaries appear in job summaries. Linux max_individual_child_rss_mib is a maximum individual child process, not aggregate parallel/container memory. Windows peak memory is explicitly unmeasured. Never shrink memory limits on that metric; qualify actual native peak memory and OOM/swap behavior independently. Shadow an unproven selector against the full suite before allowing it to omit tests.

Compare the same OS/toolchain, revision, selected inventory and warm/cold cache conditions. Track job creation-to-start delay, setup/test time, retries/cancellations and PR feedback time together. Fewer jobs or a smaller green suite alone do not establish savings or coverage. The shared clb-slurm CI usage reporter provides retrospective GitHub receipts; its creation-to-start interval may include workflow admission and is not pure runner wait.

No runner cap, guest memory profile, network isolation, credential scope or dedicated/burst policy changes here. Only CLB16/17 are dedicated; burst hosts finish active CI before yielding. Revert the workflow/script patch to roll back; retain required check names and inspect repository rules before changing them. Full native CI receipts and owner review remain the promotion gate; local static tests are not a claim that all platform tests passed.

Main pushes always retain full validation. Documentation-only narrowing is PR-only. Native DSS and FIM non-PR concurrency groups include the run ID, so a later push cannot replace an unvalidated pending revision.
