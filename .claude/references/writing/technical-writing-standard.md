# Technical writing standard

This standard defines RAS Commander's editorial choices for library documentation and public technical text. It is a companion to the [concise writing guide](technical-writing-guide.md). It applies to new and substantially revised text; existing material can be assessed in a scoped audit. Adoption does not assert compliance with an external publication standard or retroactive review of the entire library.

This standard governs repository-maintained RAS Commander content and contributions intended for this repository. It does not govern users’ projects, scripts, notebooks, reports, papers, maps, websites, or other deliverables outside RAS Commander, including content created with the library or its agents. Using RAS Commander, loading its cognitive infrastructure, or requesting a modeling workflow does not opt a user into this editorial standard. An explicit request for writing advice on an external artifact permits scoped advice under the user’s requirements, not automatic enforcement of this repository’s rules.

## Contents

- [Purpose and authority](#purpose-and-authority)
- [HEC relationship and references](#hec-relationship-and-references)
- [Style selection](#style-selection)
- [Terminology](#terminology)
- [Numbers, units, and spatial and temporal references](#numbers-units-and-spatial-and-temporal-references)
- [Evidence and quality claims](#evidence-and-quality-claims)
- [Content patterns](#content-patterns)
- [Citations and acknowledgment](#citations-and-acknowledgment)
- [Editing and auditing](#editing-and-auditing)
- [Source selection and adaptation](#source-selection-and-adaptation)

## Purpose and authority

The reader should be able to determine what an operation does, what it changes, what its output means, and what evidence supports the description. Documentation serves modelers learning Python, experienced hydraulic engineers, developers, researchers, and agents using the API. State the intended audience when it materially changes the explanation.

In this standard, **must** is a RAS Commander requirement and **should** is a recommendation with room for a justified exception. “May” grants an option when permission is the intended meaning; use “might” or a stated uncertainty when describing a possibility. Use ordinary present-tense statements for implemented behavior. Reserve “shall” for an accurately quoted requirement or an external deliverable whose governing standard requires it.

Use authority by subject:

| Subject | Primary evidence | Complementary evidence |
|---|---|---|
| HEC-RAS terminology, documented methods, controls, file semantics | Relevant official HEC manual, technical reference, release notes, or published guidance, selected by version | Original studies cited by HEC; reproducible qualification evidence |
| RAS Commander signature, default, return shape, mutation, supported operation | Current source, docstrings, declared schemas, and relevant qualification/test records | Runnable examples and release history |
| RAS Commander observations, experiments, benchmarks, and original findings | Reproducible project records, methods, conditions, and measured results | HEC documentation and independent studies for context or comparison |
| Measured data and external datasets | Provider metadata and methods, such as USGS or NOAA documentation | Applicable project and agency guidance |
| Regulatory or project acceptance | Governing jurisdiction, agency, project requirements, and responsible engineer | HEC technical documentation and independent research |
| Editorial presentation | This project standard | NASA KSC, ASCE, USACE/ERDC, and selected STE principles within their stated scope |

HEC remains the primary source for its documented HEC-RAS methods and terminology. RAS Commander speaks with authority about its own implemented capabilities and evidence-supported findings. Those claims do not require HEC approval or a HEC citation. Reproducible observations of HEC-RAS behavior may add information beyond a manual or establish a discrepancy with it; describe the observed conditions and scope directly. A RAS Commander description must distinguish documented behavior, implementation, observation, and interpretation. A source unavailable for inspection cannot be treated as verified evidence.

## HEC relationship and references

### Project identity

Use this relationship statement in introductory project material:

> RAS Commander is an independent open source project that complements and builds upon HEC's work by providing Python tools for HEC-RAS workflows. HEC-RAS is developed by the U.S. Army Corps of Engineers Hydrologic Engineering Center (HEC). RAS Commander is not affiliated with, endorsed by, or supported by HEC or USACE.

Do not imply that HEC authored, certified, approved, supports, or partnered on a RAS Commander feature. “HEC recommends” requires a source containing that recommendation, with its conditions intact. A local implementation choice must be identified as local. First-person institutional statements must have an unambiguous author; RAS Commander must not speak as HEC.

Credit the relevant HEC document at the point of a technical explanation. Preserve repository acknowledgment records for wider contributor recognition. Avoid praise in place of attribution, requests for recognition in every procedure, or statements implying HEC approval because a manual is linked.

### Passive references

HEC references in published RAS Commander content must be normal citations or reader-activated hyperlinks. A reference must stand on its written title, version, and locator even if the reader does not open the link. Prefer official deep links to relevant sections; use the documentation index as a fallback or general entry point.

Documentation references must not introduce:

- Runtime fetching of HEC pages to populate a help message or explain an API result.
- Embedded HEC pages, remotely loaded documentation previews, or live vendor content as a requirement for rendering a library page.
- Scraping, copied manual trees, or a documentation build that downloads HEC content to create citations.
- Automated issue submission, emails, or contact with HEC.

These are reference rules. They do not prohibit an agent from reading official documents during research or modify separately authorized software and example-data acquisition features. Link verification should be bounded and performed during review, not become a dependency for normal library execution. If a source is unreachable, retain correct known metadata, record the access limitation in the audit, and avoid invented replacement links.

“Passive” does not require grammatical passive voice. “HEC's User's Manual describes the control” is active prose with a passive reference.

### Respectful technical independence

Present demonstrated capabilities, results, and original contributions plainly. Respectful attribution does not require treating HEC documentation as exhaustive, subordinating project evidence to a manual, or hedging an established result. Give a project recommendation when the audience benefits from it, identify it as RAS Commander's recommendation, and explain its rationale, evidence, and applicability. HEC approval is not a prerequisite for an independent technical conclusion. Regulatory acceptance and professional engineering decisions retain their own authorities.

An objective third party can report a discrepancy without blaming an organization or treating documentation as infallible. Describe the relevant operation, versions, source section, expected and observed behavior, and what remains unknown. Separate a reproducible library problem, a source-model condition, and a suspected HEC-RAS behavior; do not assign causation from a symptom alone.

For example: “In this qualification case, the output differed from the behavior described in the cited manual. The cause has not been established.” Include the case evidence when using this form. Do not claim a software defect without a reproduction and appropriate review.

### Version discipline

Use the manual applicable to the documented engine version. Distinguish executable version, manual version, library version, and model-file declaration when they differ. A currently displayed manual or release is not proof that the library supports it.

Prefer versioned URLs for behavior-specific statements. If only a changing `latest` page is available, record the version shown and access date, and label its status. Read the document's actual title/front matter; a version-bearing filename can disagree with the internal edition. Use both printed page and PDF viewer page only when their mapping has been checked. Web references need section headings or anchors rather than fabricated page numbers.

## Style selection

Choose a style based on what the reader needs to do. A single expert-report register is too narrow for the whole library.

Audience determines the explanation, not whether a supported claim can be stated confidently. For newcomers, explain prerequisites, terms, and how to interpret a result. For hydraulic modelers, emphasize assumptions, engineering relevance, and applicability. For developers and agents, specify exact contracts, data structures, and failure behavior. For researchers and reviewers, expose the method, comparisons, uncertainty, and reproduction records. Mixed-audience pages can lead with a concise result and place detailed evidence in a later section or linked record. Use uncertainty where the evidence is uncertain; do not add tentative language merely because HEC has not documented or endorsed the finding.

| Content | Register and tense | Recommended structure | Authority emphasis |
|---|---|---|---|
| Installation and quick start | Direct, present tense, imperative instructions | Requirements; steps; expected output; common failures | Package and runtime contracts |
| Tutorial and notebook | Direct explanation with instructions; past tense for retained run results | Purpose; prerequisites; API operation; interpretation; limitations | Code/example evidence plus HEC method references |
| User guide | Neutral explanation; present tense | Task; operation; inputs/outputs; caveats; next reference | Mechanics first; HEC for hydraulic context |
| API and schema | Compact factual prose | Summary; types; parameters; returns; failures; notes; example | Exact source/signature/schema |
| Hydraulic concept or method | Neutral technical explanation | Scope; assumptions; relation to HEC method; library operation; limits | Relevant HEC technical reference |
| Qualification/benchmark/report | Third-person evidence-focused prose; past tense for work performed | Question; setup; criteria; results; limitations; references | Versioned records and test data |
| Release notes | Brief factual change statement | Behavior; affected scope; compatibility or migration | Diff and released behavior |
| UI/exception/log | Concise actionable language | Condition; consequence; available next action | Actual control flow and stable message contract |
| ADR or contribution guide | Direct professional prose; first person for attributable decisions | Decision/problem; reasons; consequences | Repository policy and recorded decisions |

Use active voice where it clarifies who does what. “The method writes the geometry file” is preferable to hiding the operation's actor. Passive voice can keep attention on the result when the actor is immaterial. Do not remove an author or reviewer merely to create impersonal prose.

An introductory tutorial can define normal depth, Manning's n, or WSE when its reader needs that explanation. A specialist API reference can link to a definition instead. Define project coinages locally and avoid unexplained abbreviations in headings. Definitions should clarify the task without copying a manual chapter.

## Terminology

Use consistent wording for a concept within its context. Consistency does not justify rewriting established HEC labels or treating distinct concepts as synonyms. The following are local editorial defaults informed by HEC usage; they are not claims that HEC universally mandates one form.

| Concept | Default in authored prose | Context and protected forms |
|---|---|---|
| Product/project | HEC-RAS; RAS Mapper; RAS Commander | Preserve `ras-commander`, `ras_commander`, `RasMap`, and actual assembly/API names |
| Discharge | Discharge or flow rate for volumetric rate; define Q | Retain steady flow, unsteady flow, flow regime, Flow Hydrograph, flow files, and exact input labels |
| Water level | Water surface elevation (WSE) when reporting elevation; state datum | HEC's Stage Hydrograph is a valid control name; gage stage has its own reference; do not infer that every stage is an absolute elevation |
| Depth | Water depth relative to the stated bed/terrain reference | Depth and WSE are different quantities; define aggregation/reference where it matters |
| Gage/gauge | Follow the cited provider/feature; use gage for USGS streamgage terminology | Preserve `gauge_id`, existing API names, quoted labels, and source titles |
| Reach | HEC-RAS reach, network reach, or named product reach when ambiguous | River/reach/station keys and source names retain their exact form |
| Project, plan, geometry, profile | Use the HEC object corresponding to the operation | A plan is not simply a project or a single water surface profile; avoid ambiguous “model” where an object can be named |
| Time step | Computation interval, output interval, or time step as applicable | Preserve HEC controls and parameter identifiers; do not collapse distinct intervals |
| Probability | Annual exceedance probability (AEP); identify the variable | Preserve source profile names; rainfall, discharge, stage, and consequence probabilities are not interchangeable |
| Comparison | Compared with a stated reference | Agreement between models alone does not demonstrate physical accuracy |
| Verification | Name the implementation/property being verified and criteria | Completion verification, equation verification, and numeric round-trip checks have different scope |
| Validation | Name the object and reference: schema validation or model validation, for example | `validate_*` APIs remain literal; laboratory/field observations and analytical benchmarks must be described for their actual purpose |
| Calibration | Adjustment of parameters using specified data/objective | A calibration fit does not by itself establish validation with independent data |
| Error, residual, difference | State sign convention and reference | A model difference is not necessarily an error relative to truth; preserve documented metric conventions |
| Convergence and stability | Name the solver criterion or statistical behavior | A flat hydrograph, completed process, and stable numerical solution are not interchangeable |
| Approval | Identify the actual reviewer and scope if approval occurred | Automated checks and agent recommendations do not constitute professional engineering approval |

### Frequency terminology

Use “1% AEP peak discharge” or “1% AEP precipitation depth for a 24-hour duration” when that is the quantity described. “100-year” may appear as a first-use gloss or exact source name. Explain average recurrence when the audience needs it; it is not a schedule for an event.

Use Q100 or Q500 only after defining the associated discharge convention. Do not assign a rainfall probability to simulated discharge without stating and supporting the modeling assumption. A rainfall-frequency design storm is legitimate terminology; do not change it into a flood event merely to follow a flood-mapping glossary. A uniform flow multiplier is not an AEP sample unless the actual method establishes that relationship.

### Verification and validation language

Prefer a statement of the performed check over an unqualified “validated.” Schema/path/input checks are software validation. Agreement with a known numerical solution can support verification under its tested conditions. Model assessment against suitable observations or experiments can support validation for a specified purpose. A comparison with another model should identify it as the reference and state the criteria and coverage.

HEC's own Verification and Validation documents cover several evidence types. Keep their titles and terminology intact while explaining the specific type of evidence used in a RAS Commander case. Do not impose an observations-only replacement rule on source titles or software validation APIs.

## Numbers, units, and spatial and temporal references

Use the unit system of the source, project, or documented API contract. Both SI and US customary examples are valid. Do not convert or round data as a prose cleanup. If dual units are needed, declare the primary system, use consistent order, and document the conversion. External deliverable rules control when a client or publication requires a specific presentation.

Put a space between a quantity and unit (`0.01 ft`, `12 m`, `3.2 m³/s`). `cfs` is acceptable in HEC-related material; define it as cubic feet per second when needed. Preserve exact unit strings in schemas, HDF attributes, source output, and controls. Label dimensional table columns and plot axes. State the denominator for normalized quantities and distinguish percent change from percentage points.

This project's prose uses `1% AEP` and comma groupings such as `4,194 cfs` for familiar engineering readability. Formal SI manuscripts may require `1 %` and thin-space digit grouping; follow the venue when preparing those manuscripts. These local typographic choices must not change machine data or numeric meaning.

State horizontal CRS and units independently from vertical datum and units. Identify a local reference as local. Do not infer NAVD 88 from an EPSG code, a projected CRS, feet, or a visually plausible elevation. If comparing gage stage and model WSE, document the datum relationship and any offset or transformation used; if it is unknown, flag the unresolved comparison.

Use precision justified by the data or computation. A fixed “WSE to 0.01 ft” or “discharge to three significant figures” rule is inappropriate across parsers, coordinates, round-trip tests, measured values, and engineering summaries. Display rounding can be specified for a report while retaining the underlying values and criteria. Never round away a failing tolerance.

Write dates unambiguously. Use ISO dates for records and identify timezone/offset for time series and timestamps when relevant. Distinguish instantaneous values from interval accumulations, rates, averages, and maxima. State time windows and sampling conventions for a reported metric. Preserve HEC-DSS and API time/interval literals.

## Evidence and quality claims

Every consequential claim must be supported and scoped. Describe what was checked, against which reference, under which versions and conditions, using which metric or acceptance criterion. Include coverage and exclusions when they affect interpretation. Do not invent a universal hydraulic tolerance or claim completeness from a list of available metrics.

| Claim | Evidence needed |
|---|---|
| Execution completed | Completion evidence and error/status policy used by the library |
| Compatible/supported | Operation, engine/library/platform versions, qualification scope, and known limits |
| Faster | Comparable tasks, setup, timing method, repetitions/variability as relevant, and measured results |
| Accurate/validated | Quantity, applicable reference/observations, criterion, coverage, uncertainty, intended purpose |
| Robust/reliable | Specific handled failure cases, invariants, or measured reliability scope |
| Comprehensive/complete | Defined scope and evidence of coverage; otherwise list the actual capabilities |
| Recommended/required | Source and authority, or an explicitly attributed project choice |

Use present tense for implemented behavior and past tense for an observed run. Proposed behavior should be labeled proposed; estimated times should be labeled estimates. Preserve uncertainty when evidence is incomplete and explain its reason. Do not replace “might” with certainty to make writing sound stronger.

An illustrative comparison can show the form “The computed elevations were compared with the reference at each cross section, using the recorded tolerance.” Real reporting must provide the actual reference, counts, values, and criteria. Synthetic demonstration data must be identified as synthetic and must not be presented as a completed qualification.

Separate process success, output integrity, numerical agreement, hydraulic adequacy, and engineering acceptance. A report can support one without establishing the others. Cite the relevant HEC assumptions and project requirements where they affect the decision. Explain the library's mechanics without turning an example into an endorsed engineering workflow.

## Content patterns

### User guides and procedures

Start with the task and resulting artifact. Identify prerequisites that affect execution, including data, platform, installed HEC-RAS version, optional dependencies, permissions, and substantial cost when relevant. Describe changes to files and overwrite/backup behavior before the operation that causes them.

Use numbered steps for sequences. Put a relevant condition before its command and keep one main action per step. Explain why a constraint matters when it changes the user's choice. Use a warning or caution for a real risk with a stated condition, consequence, and action, rather than as decoration.

A mechanics-focused page can show how to set a parameter and link to HEC's discussion of how to select it. Do not invent a default engineering recommendation merely to complete the tutorial. Separate a documented API default from a physically suitable value for a user's model.

### API docstrings and schemas

Keep the library's Google-style docstring convention. A public method's summary must state its operation accurately. Document consequential parameters and returns with their units, shape/schema, reference convention, defaults, and missing-data handling. Add CRS/datum context for spatial/elevation data. Describe mutation, written artifacts, backup/overwrite policy, dependencies, exceptions, and engine/version limitations when applicable.

Parameters and return names must match the implementation. Link related operations without copying a second signature or schema. Use `Notes` for method scope and a short HEC reference; substantial explanation belongs in the guide. Code examples must use real APIs and repository conventions. Preserve numerical formulas, sign conventions, enum values, and literal flags.

### Notebooks and generated text

Review explanatory Markdown cells and prose around operations. Describe the purpose before code and interpret the relevant result after it. State whether outputs are retained from a recorded run or generated by the current session. Do not alter saved output, benchmark times, images, or completion messages to satisfy a style preference.

Read the nearest notebook contract before editing. Title or import-cell changes must respect the repository's current convention; an imported FIM/NASA rule must not override it silently. For generated pages, summaries, or UI text, locate and update the generating source. Identify any derived pages needing regeneration and verify the build rather than maintaining divergent copies.

### Figures, maps, tables, and equations

Introduce a visual near the statement it supports and explain the conclusion the reader can draw. Label quantity, units, model/event, comparison sign, time window, and datum or spatial reference where consequential. Maps should identify layers and legend meanings; use scales/reference information appropriate to the comparison. Provide useful alt text or a nearby textual explanation. Do not rely solely on color, icons, or an unexplained screenshot.

Tables work for genuine comparisons or field contracts; ordered lists work for steps. Avoid redundant tables that make a simple explanation harder to read. Use descriptive titles/captions and consistent references. Do not impose printed-manual margins, chapter numbering, or figure-placement rules on responsive docs.

Introduce an equation, define its symbols and units, state assumptions, and cite its source. Distinguish a governing equation from a library transformation or metric. Preserve sign and unit conventions. Reproduced/adapted figures and substantial excerpts require provenance and applicable rights review; ordinary citation does not grant unrestricted reproduction.

### Diagnostics, comments, and release notes

Messages should state the condition and consequence and give an available next action. A message claiming that a file was written, restored, or a check passed must correspond to the actual code path. Preserve machine-consumed tokens, stable reason codes, and quoted HEC messages. A wording change in an exception/log is a compatibility decision if consumers depend on it.

Comments should explain a constraint, reason, or non-obvious behavior. Do not restate code with broad claims such as “guarantees accuracy.” Release notes should name the changed behavior, affected scope, and migration requirements. Keep attribution and version facts intact.

### Mechanics

Use US spelling for authored prose, sentence-case headings, and parallel list grammar. Preserve source titles, personal names, credentials, citation forms, literal UI text, and legal language. The guide does not impose FIM's blanket bans on professional credentials or explanations of standard terms.

Favor concrete verbs and one main idea per paragraph. Avoid filler, repeated importance claims, promotional comparisons, and decorative emoji in technical prose. Use emphasis to aid retrieval. Prefer full forms in formal reports and API references; contractions in direct instructional or contributor prose are an editorial judgment. Sentence length, dashes, bold lead-ins, and list length are review prompts, not automatic failures.

## Citations and acknowledgment

### Observed HEC conventions

HEC's manuals provide concrete presentation examples. The [6.6 Boundary Conditions page](https://www.hec.usace.army.mil/confluence/rasdocs/rasum/6.6/performing-a-1d-unsteady-flow-analysis/entering-and-editing-unsteady-flow-data/boundary-conditions) connects its explanation to labeled screenshots and figure references, including Figure 7-2. The [Hydraulic Reference Manual whose cover identifies Version 6.0 Beta, December 2020](https://www.hec.usace.army.mil/software/hec-ras/documentation/HEC-RAS_6.0_ReferenceManual.pdf) uses chapter-numbered equations with nearby symbol definitions and an alphabetized author/date bibliography in Appendix A. These are observed conventions in those artifacts, not a universal HEC editorial rule or a current-version recommendation.

For RAS Commander, retain that relationship between explanation, visual/equation, definitions, and source. Use descriptive links/anchors in web guides; use consistent figure/equation numbering in a substantial report when it helps retrieval. Do not transplant HEC's printed chapter layout or infer the document edition from its filename. The cited PDF illustrates format; select the appropriate versioned manual for a substantive hydraulic claim.

### Match citation detail to the document

For ordinary web guides and docstrings, use a descriptive link near the supported claim, naming the manual/version and section where relevant. For substantial reports or methods pages, add a reference list with author/institution, publication date or `n.d.` if genuinely unavailable, exact title, version/report identifier, section/page locator, publisher where useful, official URL or DOI, and access date for mutable web content.

Use an author-date system in formal reports when no client/venue system is specified. This is a local choice informed by engineering publication practice, not an assertion that every ASCE, USACE, or HEC document uses the same citation style. A submission's current venue requirements take precedence for its formatting.

Do not invent an author, publication year, report number, page, or DOI. A filename or search result date is not necessarily a publication date. Prefer the bibliographic identity printed in the document. Distinguish an official landing page from a directly inspected full document and record a paywall/access limitation when it affects support for a claim.

Example of a passive topic reference:

> For the corresponding interface terminology, see the HEC-RAS 6.6 User's Manual, [Boundary Conditions](https://www.hec.usace.army.mil/confluence/rasdocs/rasum/6.6/performing-a-1d-unsteady-flow-analysis/entering-and-editing-unsteady-flow-data/boundary-conditions), particularly “Flow Hydrograph” and “Stage Hydrograph.”

Example of a reference entry with known metadata:

> U.S. Army Corps of Engineers, Hydrologic Engineering Center. n.d. *HEC-RAS User's Manual*, version 6.6, “Boundary Conditions.” Official online documentation. Accessed October 3, 2026. [Official section](https://www.hec.usace.army.mil/confluence/rasdocs/rasum/6.6/performing-a-1d-unsteady-flow-analysis/entering-and-editing-unsteady-flow-data/boundary-conditions).

The date is intentionally `n.d.` because this example page does not establish a publication date. Its access date is not its publication date. Select the version appropriate to the feature being documented rather than copying this example version universally.

Example of a bibliographic entry using the inspected PDF's front matter:

> Brunner, G. W. 2020. *HEC-RAS River Analysis System: Hydraulic Reference Manual*. Version 6.0 Beta, December 2020. CPD-69. U.S. Army Corps of Engineers, Hydrologic Engineering Center. [Official PDF](https://www.hec.usace.army.mil/software/hec-ras/documentation/HEC-RAS_6.0_ReferenceManual.pdf).

This entry identifies an older edition for format illustration. It must not be cited as a current release or evidence that a RAS Commander operation has been qualified.

### Credit and licensing

HEC should receive appropriate acknowledgment for the software, methods, and documentation used. Third-party methods, code, datasets, and figures also need traceable attribution. Retain source repository/file/revision for adapted code and applicable copyright/license/NOTICE requirements. A citation, acknowledgment, and license obligation serve different purposes.

Use the existing [citation page](../../../docs/cite.md) and [acknowledgments](../../../docs/about/acknowledgments.md) as canonical project records. Do not duplicate incomplete contributor lists on method pages. Specific technical attribution belongs near a method explanation even when broader credits are centralized. Do not invent affiliations or an author's name; preserve documented credit.

## Editing and auditing

Read the applicable `AGENTS.md`, select the surface/register, and identify the authored source. Review factual and technical meaning before mechanics. Consult the applicable official HEC source and implementation records for consequential claims. If sources conflict or are unavailable, report the uncertainty and needed evidence rather than guessing.

Protected content includes code identifiers, paths, flags, schema keys, source names, UI literals, quotations, program output, formulas, numbers, signs, unit strings, hashes, citations, licenses, and saved notebook results. A confirmed defect may require correction, but that is an explicit technical/source change with appropriate evidence and review. Cosmetic rewriting must not silently alter it.

Use the shared `technical-writing-auditor` skill to review a diff, selected surface, or a declared broader corpus. The skill provides review coverage, severity, findings, and disposition rules. Broad audits must report actual files/surfaces reviewed and sampling limits. An unexamined file is not a passing file.

Report confirmed defects separately from unresolved technical questions and editorial suggestions. Each material finding needs its location, minimal excerpt, applicable rule, reader impact, evidence/source, and a proposed correction or decision needed. A useful audit recognizes correct exceptions as well as problematic text.

Meaning-preserving prose edits need document/skill validation and relevant rendering checks. Changes to executable strings, generated content, code examples, or technical statements require checks appropriate to their effects. An editorial review does not grant merge/deploy authority or certify a model, a method, or professional engineering acceptance.

## Source selection and adaptation

The guide uses the following sources selectively. The source's own scope determines its authority; this guide's implementation choices remain local. Sources were reviewed on October 3, 2026. Mutable pages must be rechecked when a future technical claim depends on their current state.

| Source | Verified scope and locator | Choice for RAS Commander |
|---|---|---|
| [HEC-RAS documentation portal](https://www.hec.usace.army.mil/confluence/rasdocs), [software documentation index](https://www.hec.usace.army.mil/software/hec-ras/documentation.aspx), and [6.6 introduction](https://www.hec.usace.army.mil/confluence/rasdocs/rasum/6.6/introduction-to-hec-ras) | Official manuals organized by technical subject; introduction's documentation table | Route HEC questions to the applicable manual; distinguish operation, theory, and application |
| [HEC-RAS 6.6 Boundary Conditions](https://www.hec.usace.army.mil/confluence/rasdocs/rasum/6.6/performing-a-1d-unsteady-flow-analysis/entering-and-editing-unsteady-flow-data/boundary-conditions) and [6.5 Steady Flow Data](https://www.hec.usace.army.mil/confluence/rasdocs/ras1dtechref/6.5/basic-data-requirements/steady-flow-data) | “Flow Hydrograph,” “Stage Hydrograph,” and “Discharge Information” | Preserve contextual HEC terminology; avoid global flow/stage substitutions |
| [HEC reference documents](https://www.hec.usace.army.mil/confluence/rasdocs/hgt/latest/reference-documents) | V&V description covers analytical, laboratory, and observed evidence; live page labels the 2020 report superseded and identifies a 7.0 update | Name evidence and check scope; verify edition before claiming current qualification |
| [HEC-DSS vertical datum appendix](https://www.hec.usace.army.mil/confluence/dssdocs/dsscprogrammer/appendix-vertical-datum-for-elevation-data) | Elevation datum handling and named/local references | Keep physical quantities and reference metadata explicit |
| [HEC-HMS Frequency Storm](https://www.hec.usace.army.mil/confluence/hmsdocs/hmstrm/meteorology/precipitation/frequency-storm) | Precipitation method, distinct from HEC-RAS hydraulic computation | Retain legitimate design-storm terminology; avoid assuming rainfall and discharge AEP are equal |
| [NASA KSC-DF-107 Rev F PDF](https://standards.nasa.gov/sites/default/files/standards/KSC/F/0/ksc-df-107_rev_f_07082017.pdf) and [official record](https://standards.nasa.gov/standard/KSC/KSC-DF-107) | Technical Documentation Style Guide; record date 2017-07-08, active, not NASA mandatory/endorsed; §§3.2–3.4, 3.11, 3.16–3.18 | Borrow consistency, reader-aware prose, modal clarity, and informative visuals. Its KSC production/layout and dual-unit order do not govern library docs |
| [ASCE Standards Writing Manual for ASCE Standards Committees](https://www.asce.org/-/media/asce-images-and-files/publications-and-news/codes-and-standards/documents/asce-standards-writing-manual.pdf) | Stated revision date February 8, 2019; §§1.1, 3, 5.1, 5.11–5.12, 6; governs ASCE standards committees | Borrow clear obligations and usable technical presentation; omit committee structure, mandatory dual units, and standards-only numbering |
| [ASCE Author Center](https://ascelibrary.org/author-center/preparing-manuscript) | Journal preparation guidance; direct retrieval was blocked during this research | Check current venue requirements for a real submission; do not derive mandatory library rules from inaccessible details |
| [USACE EP 25-40-1 PDF](https://publibrary.sec.usace.army.mil/api/download?filename=EP+25-40-1_Publishing+Program+Procedures_2026+05+18_Final.pdf&id=74f3e3fe-a670-4977-9ba-50de3f6ee9e1&preview=true&token=) and [publications catalog](https://www.publications.usace.army.mil/USACE-Publications/Engineer-Pamphlets/) | *Publishing Program Procedures*, June 1, 2026; chapter 4, §§4-1–4-5; full text inspected by a reviewer, subsequent retrieval failed in some environments | Borrow audience awareness and plain language; omit Corps approval, official series layout, and institutional voice |
| [ERDC/ITL SR-18-4 catalog](https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/8944/) and [ERDC editing services](https://www.erdc.usace.army.mil/Library/Editing-services/) | Wolfe, December 2018; ERDC publication guidance and local Chicago practice; catalog copy marked informational | Use as a formal-report reference with its institutional and access limits |
| [ASD-STE100 official description](https://www.asd-ste100.org/about_STE.html) | Issue 9, January 15, 2025; controlled language with writing rules and dictionary | Adapt procedural clarity and consistent technical terms. No claim of full STE compliance or dictionary adoption |
| [NIST SP 811 quantity conventions](https://www.nist.gov/pml/special-publication-811/nist-guide-si-chapter-7-rules-and-style-conventions-expressing-values) | §§7.2 and 7.10.2; SI spacing and percent notation | Use dimensional unit spacing; document the local AEP percent typography exception |
| [USGS streamgaging basics](https://www.usgs.gov/mission-areas/water-resources/science/streamgaging-basics) | Provider terminology for streamgage, stage/gage height, and discharge | Use provider definitions for observations and preserve the reference quantity |

FIM Commander's `fim-writing-voice` skill supplied a useful pattern: audience notes, terminology guidance, protected text, examples, and review reporting. Its flood-mapping glossary, expert-only assumptions, US-customary-only policy, fixed precision, and lexical prohibitions were not adopted wholesale. Its prose linter is not evidence of technical correctness and is not installed as a library-wide enforcement gate.

The sources disagree on some presentational choices. NASA places SI first for dual measurements; ASCE's standards manual places customary units first. This guide follows the data/API/project and documents conversions. Institutional guides differ on personal voice and printed layout; this guide selects register by reader task and uses the existing docs renderer. ASCE journal style differs from ASCE standards style; a journal submission follows that venue's actual rules.

The resulting standard complements HEC documentation with library-specific operations, source discipline, and evidence-aware writing. It makes no claim that HEC, NASA, ASCE, USACE, ERDC, or ASD has reviewed or endorsed these editorial choices.
