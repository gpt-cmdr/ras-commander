---
name: technical-writing-auditor
description: Audit RAS Commander technical prose, documentation, notebook explanations, API docstrings, release notes, and user-facing messages for HEC terminology, passive citations, independent voice, technical meaning, evidence, and audience-appropriate style. Use for writing reviews and scoped editorial revisions; hydraulic approval and implementation qualification require their own evidence.
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
---

# Technical Writing Auditor

Review repository-maintained technical text and intended contributions across RAS Commander. HEC is the primary source for HEC-RAS terminology and documented behavior. RAS Commander is an independent open source project that complements HEC's work; it must not imply affiliation, endorsement, certification, or vendor support. Published HEC references are passive citations and links.

RAS Commander is authoritative about its own supported capabilities and reproducible observations. Match the explanation to the audience. Do not demand HEC endorsement or citations for project evidence, suppress original findings, or introduce unnecessary hedging into established results.

## Load the writing contract

Find the repository root and read the nearest `AGENTS.md` for the selected surface. Read [the concise guide](../../references/writing/technical-writing-guide.md). Read the relevant sections of [the extended standard](../../references/writing/technical-writing-standard.md) for terminology, technical claims, references, or content-specific review. These repository guides are canonical; do not maintain a second glossary inside this skill.

Use [the audit protocol](references/audit-protocol.md) for coverage, checks, findings, and output. Read it before an audit or editing pass. Existing repository contracts take precedence over imported style conventions; report a conflict rather than overriding protected behavior.

## Working boundaries

- Apply this standard only to repository-maintained RAS Commander content and intended contributions. Do not audit or enforce it on external user artifacts merely because they use RAS Commander or this skill is installed. If a user explicitly requests external writing assistance, follow their scope and editorial requirements; identify repository-derived suggestions as optional advice.

- Default to review of the requested diff/files. A broad audit must inventory surfaces and declare sampling; reading a sample does not establish whole-library compliance.
- Review authored prose, not every source token. Include notebook Markdown, docstrings, narrative comments, UI/log/exception text, and captions when they are in scope. Saved outputs, generated pages, vendor files, code literals, and legal text have separate source/compatibility constraints.
- Consult official HEC documents for consequential HEC claims. Use implementation/schema/evidence for library behavior and provider references for external data. Prefer the applicable version over a changing `latest` page. A search snippet or inaccessible source is not confirmed full-text evidence.
- Passive references are ordinary reader-activated links/citations. Research browsing is permitted. Do not introduce runtime HEC-page requests, live embeds, scraped/mirrored documentation, or automated HEC contact as part of a citation.
- Preserve identifiers, labels, values, units, formulas, signs, timestamps, citations, and uncertainty. Confirm a technical correction against evidence; otherwise report it as unresolved. Do not invent thresholds, compatibility, support, results, or source metadata.
- Select register by task. Direct instructions are appropriate in tutorials; objective technical prose is appropriate in reports. Do not globally replace flow, stage, storm, validation, SI units, or source titles using FIM-specific lexical rules.
- Review by default. When revision is authorized, edit the canonical source and make supported changes. Message/identifier/code changes require compatibility and behavior review. Do not execute HEC-RAS, run notebooks, publish, contact HEC, or merge as a side effect of a writing audit.

## Deliver the assessment

Prioritize factual meaning, HEC relationship/source discipline, and evidence over cosmetic preferences. Report each material finding with a stable rule ID, severity, location, brief excerpt, reader impact, evidence, and a proposed correction or decision needed. Distinguish confirmed defects, unresolved questions, and suggestions. Document appropriate exceptions and the actual coverage. Use `pass`, `pass with suggestions`, `needs revision`, or `incomplete` as an editorial disposition for the reviewed scope only; never call it hydraulic certification.
