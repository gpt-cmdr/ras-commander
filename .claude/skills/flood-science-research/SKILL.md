---
name: flood-science-research
description: Plan and coordinate long-running flood-science investigations with durable task records, bounded implementation and experiment subagents, and evidence-based synthesis. Use for hydraulic sensitivity, rainfall-runoff and infiltration studies, calibration, uncertainty, or flood-map research.
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
---

# Flood-science research

**Cardinal rule:** For professional model revisions, build the specification with the engineer/scientist, including report-quality, relevant figures/maps that are actually visually reviewed; the engineer may explicitly defer it. For research, **proceed with approval and document** within the agreed envelope. Follow the [shared specification and reporting workflow](../../references/model-revisions/specification.md), using ras2cng for rich maps when useful. Existing authorization remains valid; do not repeat routine approval requests.

Use the default **Grill the Flood Scientist** posture: be a constructive adversarial research partner in a human-in-the-loop arrangement. Challenge unsupported assumptions, identify competing explanations, and ask what observation would overturn the preferred conclusion. Do not confuse the scientist's authority to direct the investigation with evidence that a hypothesis is correct.

Turn the research question into a falsifiable hypothesis, comparison design, and durable task before launching experiments. Use this workflow for sustained investigations; a simple project inspection does not need a research campaign.

## Plan and preserve state

Create an authorized task directory, using the user's designated research workspace (repository work can use `agent_tasks/<date>-<study>/`). Start `TASK.md` from the [task template](references/task-template.md). Maintain `STATE.md` with current status, accepted decisions, evidence paths, active worker IDs, blockers, and the exact next action. Keep a dated `PROGRESS.md` and append-only experiment records under `experiments/`. Store large models and outputs in the authorized artifact location, linked from the task; never rely on chat or disposable scratch as the only record.

Read [study examples](references/study-examples.md) for relevant notebook mechanics and interpretation limits. During planning consult the applicable version/topic in [HEC planning references](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/development/hec-planning-references.md). HEC references inform methods; installed source/signatures establish available automation. Record engine, package and native backend versions separately.

Select the research lens: hydraulics/numerics; hydrometeorology and land-surface response; or inundation mapping. Define observations, comparison locations, time basis, datum, units, parameter bounds, controls, metrics, and acceptance criteria before runs. Separate exploratory and confirmatory experiments. Assign and freeze each event's exploratory, calibration, or held-out confirmation role before tuning or inspecting comparative scores; document any reassignment and the resulting loss of independence. Record changed hypotheses rather than rewriting earlier predictions.

## Agency and human direction

Within the scientist's stated objective, allowed changes, data access, and resource envelope, take initiative to investigate literature, design comparisons, implement methods, run experiments, inspect failures, and improve existing methods. Routine reversible work inside that envelope need not wait for repeated approval. Record consequential choices and surface evidence that changes the research direction. Seek the scientist's direction when changing the scientific objective, resolving an unprovided consequential modeling assumption, exceeding agreed resources, or making external/publication/production commitments. Present concrete options and evidence at those decision points; elapsed time does not supply consent.

At intake, challenge the question and baseline before optimizing them. Ask focused questions such as: Is the observed stage tied to the model datum? Are boundary histories appropriate for both storms? Does the metric hide spatial or timing errors? Can numerical effects explain the apparent physical sensitivity? Which independent event could falsify the result? Continue independent evidence gathering while awaiting needed input. Keep critique specific and respectful; seek disconfirming evidence, not agreement or endless objection.

## Delegate implementation and experiments

Use native subagents supported by the current harness. Give an implementation worker the bounded API/script change and an experiment worker the bounded scenario or batch. Delegate domain preparation to boundary, meteorological-forcing, gridded-precipitation, land-surface, mapping, or cloud-native-export skills as relevant. Do not launch all roles automatically or delegate recursively without scope.

Every task packet must identify the question, allowed project roots, exclusive write paths, immutable baseline, input identities, versions, allowed operations, expected artifacts, checks, resource/time/run limits, stop conditions, and result-file path. Tell workers they are not alone and must preserve others' edits. The coordinator owns durable task/state files; workers own separate result and experiment directories. When writing to shared storage, discover and follow the site's concurrency/lease policy if one exists; do not assume a CLB-specific tool is installed. Otherwise assign exclusive worker output directories and coordinate writes through the parent. Do not invent model settings merely to unblock a run.

Implementation acceptance requires targeted checks and a reviewable diff. Experiment acceptance requires input readback, confirmation of consumed/preprocessed values, run status and diagnostics, result identity, metrics and limitations. Use RAS Commander for all HEC-RAS execution and preprocessing; no raw executable invocation. Preserve source models. Real example projects establish mechanics; they do not automatically represent the research site's conditions.

Bound concurrency and total runs to the authorized resources. On numerical failure, missing observations, invalid boundaries, unavailable native capability, or exceeded budget, record the failure and stop dependent experiments. Do not silently replace a failed backend or expand a sweep. Successful execution is not evidence of hydraulic adequacy.

## Resume and synthesize

On resume read TASK, STATE, the latest progress and experiment receipts, then reconcile worker state with actual artifacts. Reuse only completed experiments whose input/configuration identities match. Interrupted or partial outputs remain incomplete. Checkpoint before handoff and after each accepted result; leave exact restart commands and dependencies without credentials.

Use [adversarial review and improvement](references/adversarial-review.md) before a major experiment campaign and before accepting substantial findings. Delegate a bounded independent review with the raw evidence and scientific question; do not seed it with the preferred answer. Reviewers challenge methods, data, numerical behavior, confounders, and interpretation. Record objections, their disposition and the scientist's unresolved decisions. An implementation worker must not be the sole reviewer of its own result.

Performance work, including Rust rewrites, is in scope when it serves the agreed investigation and modification envelope. Profile first; isolate a representative bottleneck, preserve a baseline/oracle, implement through supported package boundaries, test numerical and semantic parity, and measure end-to-end benefit including I/O/preparation. A faster kernel alone is not an improved scientific method. Retain failed approaches and portability limits. Do not bypass RAS Commander execution, replace a hydraulic method silently, or treat an optimization as authorized production deployment.

Synthesize positive, negative, and failed experiments; separate observed effects, interpretations, uncertainty, and untested hypotheses. Report applicability to the tested project/events and remaining professional judgments. Completion means the question is answered to its declared scope or explicitly reported unresolved, with reproducible artifacts and no unaccounted running workers. It does not authorize publication, deployment, or indefinite background execution.
