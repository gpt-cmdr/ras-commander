# Technical writing guide

RAS Commander is an independent open source project that complements and builds upon the work of the U.S. Army Corps of Engineers Hydrologic Engineering Center (HEC). Its documentation explains how to use the library with HEC-RAS. RAS Commander is not affiliated with, endorsed by, or supported by HEC or USACE.

This guide applies to RAS Commander’s repository-maintained documentation, notebook explanations, API docstrings, comments that explain technical behavior, user-facing messages, and release notes. The [extended writing standard](technical-writing-standard.md) supplies terminology, citation rules, examples, and the rationale for style choices. **Must** identifies a project requirement; **should** identifies a recommendation. These are RAS Commander editorial rules, not NASA, ASCE, or USACE requirements imposed on this project.

## Scope

This standard governs repository-maintained RAS Commander content and contributions intended for this repository. It does not govern users’ projects, scripts, notebooks, reports, papers, maps, websites, or other deliverables outside RAS Commander, including content created with the library or its agents. Using RAS Commander, loading its cognitive infrastructure, or requesting a modeling workflow does not opt a user into this editorial standard. An explicit request for writing advice on an external artifact permits scoped advice under the user’s requirements, not automatic enforcement of this repository’s rules.

## HEC sources and independent voice

1. **Use HEC's documentation as the primary source for HEC-RAS methods, terminology, interface labels, and HEC-RAS documented behavior.** Select the relevant manual and version. Consult the Hydraulic Reference Manual for theory, the User's Manual for operation, the Mapper and 2D manuals for their respective features, and release notes for changes. Start with the [HEC-RAS documentation portal](https://www.hec.usace.army.mil/confluence/rasdocs), which provides versioned manuals; the [software documentation page](https://www.hec.usace.army.mil/software/hec-ras/documentation.aspx) also lists manual categories and PDF alternatives.
2. Speak directly and confidently about RAS Commander's capabilities, implementation, and supported observations. Current source and reproducible project evidence are authoritative for those claims; HEC approval or a HEC citation is not required. Explain the library's inputs, operations, outputs, and limits first. Cite HEC for its methods and hydraulic assumptions. Identify project recommendations as such and support consequential advice with rationale and evidence. A manual citation does not prove that a particular API or project has been tested.
3. Preserve HEC's exact control names and quoted text. Use physically precise terms in surrounding prose. If a source, implementation, and observed result disagree, record the discrepancy, versions, and evidence. Do not silently reconcile them or assign a cause without evidence.
4. Use passive references: ordinary reader-activated links and citations to official documentation. Published references must not depend on fetching HEC pages at runtime, embedded HEC content, scraping, mirrored manuals, or automated contact with HEC. An agent may consult official sources during research. Existing software/data acquisition workflows have their own contracts; this rule governs documentation references.
5. Give HEC appropriate technical credit without speaking on its behalf. State the independent-project relationship in project-level introductory material. Keep technical pages objective and respectful; identify reproducible limitations plainly. Avoid implied certification, partnership, endorsement, or HEC support for the library.

## Select the register

| Surface | Writing style | Include |
|---|---|---|
| Quick start, tutorial, procedure | Direct instructions; imperative verbs; one main action per step | Prerequisites, mutation/cost, API call, expected result, relevant HEC reference |
| User guide, concept explanation | Neutral explanation, mechanics first | Purpose, terminology, inputs/outputs, limitations, links to technical authority |
| API or schema reference | Precise, compact, structured | Types, shapes, units, CRS/datum if applicable, defaults, mutation, returns, failure behavior, version limits |
| Qualification, comparison, technical report | Evidence-focused third-person prose | Question, setup, reference, metric, criterion, coverage, result, uncertainty |
| Release note, exception, log, UI text | Brief factual behavior or actionable diagnosis | Changed behavior or condition, impact, available next action |
| Contribution instructions, design decision | Direct and professional | Rationale and decisions; first person only with a clear project author |

Use present tense for current behavior, past tense for completed work, and explicit uncertainty for proposals. Prefer active voice where the actor matters. Passive grammatical voice is acceptable when the actor is irrelevant. “Passive reference” describes the link's function, not sentence grammar.

Match detail to the reader: explain prerequisites and interpretation for newcomers; emphasize assumptions, results, and engineering limits for modelers; give exact contracts and failure behavior for developers and agents. State demonstrated results plainly, with their conditions. Respect for HEC does not require apologetic language, unnecessary hedging, or presenting original capabilities and observations as tentative. Confidence follows the evidence; audience determines how that evidence is explained.

## Technical meaning comes first

- Use “HEC-RAS,” “RAS Mapper,” and “RAS Commander” in prose; preserve package names such as `ras_commander` and exact API identifiers.
- Prefer “discharge” for a volumetric rate. Retain HEC terms such as “steady flow,” “flow hydrograph,” and “Unsteady Flow Data.” Do not replace every occurrence of “flow.”
- Distinguish water surface elevation (WSE), depth, and gage stage. State the reference for water-level comparisons; retain HEC's “Stage Hydrograph” control name. An unknown vertical datum must stay unknown.
- Identify the modeled quantity when using annual exceedance probability (AEP). Rainfall AEP is not automatically peak-discharge or flood AEP. A design storm is valid terminology for precipitation. Define symbols such as Q100 if used; preserve source profile names.
- Name the check: schema validation, execution-completion check, numerical verification, model comparison, calibration, or validation against observations/experiments. State what passed and under which criteria. A successful run or matching file does not establish hydraulic accuracy or engineering approval.
- Use the source/project unit system. Place a space between a value and its unit (`0.01 ft`, `2 m³/s`); label table columns and plot axes. Define `cfs` when needed. Identify horizontal CRS and vertical datum independently. Preserve original numerical precision, signs, tolerances, and timestamps; document any conversion.
- Tie compatibility, accuracy, performance, and coverage claims to specific versions, methods, evidence, and scope. Label synthetic examples and proposed thresholds. Never invent a measurement or generalize one qualification case to universal support.

## Structure and mechanics

Lead with the reader's task or the result. Keep each paragraph on one topic. Explain a consequential API operation before its code. Put conditions before dependent steps and describe file changes, overwrite behavior, and cost where they affect the user's decision. Use ordered lists for sequences and tables for comparisons. Figures need readable labels, units, explanatory captions, and a text explanation of the result.

Use US spelling in authored prose and sentence-case headings, while preserving source titles and literal labels. Define abbreviations for the page's audience; introductory material may explain standard domain terms. Prefer concrete verbs and restrained emphasis. Avoid promotional superlatives, decorative emoji, and repeated claims of importance in technical prose. Sentence length and punctuation are judgment calls, not numerical pass/fail rules.

Protect identifiers, code, CLI flags, schema keys, paths, quoted output, saved notebook results, formulas, values, citations, and legal text. Flag a suspected defect in these items with evidence and route it to the relevant owner. Edit the source of generated text; do not rewrite historical output to make a result appear better.

## Review before submission

Confirm that the prose matches the implementation and the cited HEC version, that units and evidence make claims interpretable, and that sources are cited near the statements they support. Use descriptive links for ordinary docs and complete reference entries for substantial reports. Preserve the repository's canonical acknowledgment and citation records.

Use the shared `technical-writing-auditor` skill for a scoped editorial review or a broader audit. Its report must distinguish confirmed defects, unresolved technical questions, and style suggestions, with locations, evidence, proposed corrections, and coverage limits. An editorial pass cannot certify a hydraulic method or replace professional engineering review.
