# ras-commander Publication Strategy

**Last Updated**: 2026-03-03

This document outlines a multi-channel publication strategy for ras-commander, targeting peer-reviewed journals, professional newsletters, conferences, and preprint servers -- all with no article processing charges (APCs).

---

## Publication Readiness Assessment

### Strengths for Publication

| Asset | Detail |
|-------|--------|
| **PyPI History** | 80+ releases since September 2024 (18 months of public development) |
| **Current Version** | v0.89.2 |
| **Scope** | Comprehensive: execution, HDF extraction, geometry parsing, USGS integration, remote execution, precipitation, terrain |
| **Documentation** | 47+ example notebooks, mkdocs site on GitHub Pages and ReadTheDocs |
| **Novel Contribution** | First Python library to provide full HEC-RAS 6.x automation without COM dependency |
| **LLM-Forward Philosophy** | Unique engineering methodology combining AI assistance with professional review |

### JOSS-Specific Readiness

JOSS updated its scope in January 2026 to emphasize **design thinking** and **research impact** over raw effort. Key requirements and how ras-commander meets them:

| JOSS Requirement | ras-commander Status |
|------------------|---------------------|
| 6+ months public history | 18 months (Sept 2024 - present) |
| Evidence of releases | 80+ PyPI releases |
| Research application | Hydraulic modeling, flood analysis, FEMA compliance |
| Design thinking | Static class pattern, DataFrame-first architecture, HDF abstraction layer |
| AI usage disclosure | Required -- see "JOSS AI Disclosure" section below |
| Reuse evidence | PyPI downloads, example notebooks, Australian Water School course |
| Open development | Public GitHub, issues, PRs |

---

## Tier 1: Peer-Reviewed Journal (Primary Target)

### Journal of Open Source Software (JOSS)

**URL**: https://joss.theoj.org
**Cost**: Free (no APC)
**Review**: Open peer review on GitHub
**Time to Publication**: ~4-12 weeks
**Impact**: DOI, indexed in Scopus, Web of Science

**Why JOSS is the right primary target**:
- Purpose-built for research software like ras-commander
- Free to publish, free to read
- Peer review improves software quality
- DOI makes library citable in academic work
- Indexed in major databases

**Paper Requirements**:
- Short paper (typically 1-2 pages of text + references)
- `paper.md` in repository with YAML metadata
- Statement of need, summary, key references
- Mention of related work and differentiation

**JOSS AI Disclosure Requirement**:

JOSS now requires disclosure of AI usage in development. For ras-commander, this must be transparent and thorough:

> "ras-commander was developed using AI coding assistants (Claude, GPT-4, Gemini) as described in its LLM-Forward development methodology. The human contributions include: problem framing for HEC-RAS automation gaps, architectural decisions (static class pattern, DataFrame-first principle, HDF abstraction layers), domain expertise encoding (fixed-width geometry parsing, session-based remote execution, FEMA compliance workflows), and sustained maintenance over 18 months with 80+ releases. AI tools were used for code generation, documentation, and testing support under continuous human review."

**Key Design Thinking to Highlight in Paper**:
1. **Static class pattern** -- Why no instantiation for HEC-RAS operations
2. **DataFrame-first architecture** -- Single source of truth for project metadata
3. **HDF abstraction layer** -- Hiding HEC-RAS HDF5 internal structure complexity
4. **Smart execution skip** -- File modification time-based currency checking
5. **Session-based remote execution** -- Why `session_id=2` matters for GUI applications
6. **Separation from COM** -- Full 6.x automation without HECRASController dependency

**Preparation Steps**:
1. Create `paper.md` and `paper.bib` in repository root
2. Write statement of need focusing on HEC-RAS automation gaps
3. Document architectural decisions as "design thinking"
4. Prepare AI usage disclosure statement
5. Identify 2-3 related tools for comparison (raspy, pyHecRas, HEC-Commander)
6. Submit via https://joss.theoj.org/papers/new

### pyOpenSci (Complementary to JOSS)

**URL**: https://www.pyopensci.org
**Cost**: Free
**Benefit**: JOSS partnership -- accepted pyOpenSci packages get fast-tracked through JOSS

pyOpenSci review focuses on software quality (packaging, testing, documentation, API design) rather than the paper. If ras-commander passes pyOpenSci review, JOSS will accept the software quality assessment and focus their review on the paper content.

**Preparation Steps**:
1. Review pyOpenSci packaging requirements
2. Ensure CI/CD passes (GitHub Actions)
3. Submit pre-submission inquiry to confirm scope
4. If accepted, opt into joint JOSS submission

---

## Tier 2: ASCE Professional Newsletters (Practitioner Audience)

### Texas Civil Engineer (ASCE Texas Section)

**URL**: https://www.texasce.org/submit-article/
**Cost**: Free
**Audience**: ~10,000 ASCE members in Texas
**Format**: Feature article (1,000-3,000 words)
**Submission**: Online form or email to editorial staff

**Article Angles for Texas**:
1. **"Automating HEC-RAS for Texas Flood Studies"** -- Focus on FEMA compliance, eBFE model organization, batch processing for regional studies
2. **"LLMs Forward: AI-Assisted Engineering That Keeps the Engineer in the Loop"** -- Philosophy piece with ras-commander as case study
3. **"Open Source Tools for H&H Modeling: A Practitioner's Guide to ras-commander"** -- Hands-on tutorial for Texas engineers

**Why Texas**:
- Major flood risk state (Harvey, 2017 lessons)
- Large HEC-RAS user community
- Active ASCE section with ~10,000 members
- FEMA Region 6 drives significant modeling demand

### Connecticut Society of Civil Engineers (CSCE) Newsletter

**URL**: https://sections.asce.org/connecticut/newsletter
**Contact**: info@csce.org or 860-879-2723
**Cost**: Free
**Audience**: CSCE membership (CT engineers)
**Format**: Newsletter article

**Article Angles for Connecticut**:
1. **"Python Automation for Connecticut Dam Safety Studies"** -- Breach analysis automation with ras-commander
2. **"Streamlining HEC-RAS Workflows for New England Flood Studies"** -- Regional applicability
3. **"Open Source Innovation in Connecticut Civil Engineering"** -- Broader technology adoption story

**Submission**: Email info@csce.org with article or article idea.

---

## Tier 3: Conferences (Presentations and Proceedings)

### EWRI World Environmental & Water Resources Congress 2026

**URL**: https://www.ewricongress.org/
**When**: April 26-29, 2026, Mobile, AL
**Status**: Abstract submission deadline has passed; paper deadline was November 2025
**Cost**: $50 abstract fee + conference registration
**Note**: Too late for 2026, but target for 2027 (may be part of ASCE2027 mega-event)

**Presentation Topics**:
- "ras-commander: Open-Source Python Automation for HEC-RAS 6.x"
- "LLM-Forward Engineering: Professional Responsibility in AI-Assisted Hydraulic Modeling"
- "Distributed HEC-RAS Execution via Python: Local, Remote, and Cloud Workflows"

### ASFPM National Conference

**URL**: https://www.floods.org/conference/
**2026 Conference**: May 31 - June 4, Milwaukee, WI (50th anniversary)
**Status**: Call for abstracts is CLOSED for 2026
**Note**: Already presented HEC-Commander at ASFPM 2024 in Salt Lake City -- strong precedent for ras-commander follow-up

**Target**: ASFPM 2027 -- submit abstract when call opens (typically fall of prior year)

**Presentation Topics**:
- "From HEC-Commander to ras-commander: Evolution of Open-Source HEC-RAS Automation"
- "Automated eBFE Model Organization: Fixing Broken FEMA Deliverables at Scale"
- "Parallel HEC-RAS Execution for Flood Insurance Studies"

### Floodplain Management Association (FMA)

**URL**: https://floodplain.org/
**Audience**: CA, NV, HI floodplain managers
**Cost**: Conference registration
**Note**: FMA hosts a 2026 "HEC RAS 2D and RAS Mapper" course (March 2-6, 2026) -- potential partnership opportunity

### Texas Floodplain Management Association (TFMA)

**URL**: https://www.tfma.org/
**Audience**: Texas floodplain managers (strong overlap with target audience)
**Note**: Watch for 2026-2027 call for presentations

### Australian Water School

**Existing Relationship**: ras-commander originated from the Australian Water School course "AI Tools for Modelling Innovation" (2024). Webinars were held in Feb 2024 and July 2024.

**Opportunity**: Updated webinar series covering ras-commander v0.89+ capabilities, remote execution, precipitation integration.

---

## Tier 4: Preprint Servers (Immediate Visibility)

### EarthArXiv

**URL**: https://eartharxiv.org/
**Cost**: Free
**DOI**: Yes
**Review**: Basic moderation only (not peer-reviewed)
**Time**: Days to publish

**Strategy**: Post a preprint BEFORE or SIMULTANEOUSLY with JOSS submission. This provides:
- Immediate citable reference while JOSS review proceeds
- Broader visibility in earth science community
- Establishes priority

**Content**: Same paper as JOSS submission (JOSS allows simultaneous preprints)

### ESS Open Archive (ESSOAr)

**URL**: https://www.essopenarchive.org/
**Cost**: Free
**Affiliation**: AGU-backed
**DOI**: Yes

**Strategy**: Alternative to EarthArXiv if targeting AGU-affiliated journals in the future.

---

## Tier 5: Additional Free Journals (Secondary Targets)

### Journal of Hydraulic Structures

**URL**: https://doaj.org/toc/2345-4156
**Cost**: No APC (confirmed)
**Publisher**: Shahid Chamran University of Ahvaz
**License**: CC BY
**Time**: ~4 weeks submission to publication
**Scope**: Hydraulic structures, water resources, modeling

**Possible Paper**: "Automated Hydraulic Property Table (HTAB) Optimization Using HEC-RAS Results: Implementation in ras-commander"

### Journal of Hydraulic and Water Engineering

**URL**: https://doaj.org/toc/2980-986X
**Cost**: No APC (confirmed)
**License**: Open access since 2023
**Time**: ~4 weeks

**Possible Paper**: "Integrating USGS Gauge Data with HEC-RAS Models: An Automated Workflow"

---

## Journals to AVOID (Charge APCs)

| Journal | APC | Notes |
|---------|-----|-------|
| SoftwareX (Elsevier) | $1,560 | Good scope but expensive |
| Geoscientific Model Development | ~$1,600 | Copernicus/EGU |
| Environmental Modelling & Software | ~$3,500+ | Elsevier hybrid |
| ASCE Journal of Hydrologic Engineering | $2,000+ | Traditional ASCE journal |
| Water (MDPI) | $2,600 | Where the Dysarz 2018 HEC-RAS Python paper was published |

---

## Recommended Publication Timeline

### Phase 1: Immediate (March-April 2026)

1. **Draft JOSS paper.md** -- Focus on statement of need, design thinking, AI disclosure
2. **Submit Texas Civil Engineer article** -- Practitioner-focused piece on HEC-RAS automation
3. **Post EarthArXiv preprint** -- Longer-form technical paper covering architecture and capabilities

### Phase 2: Spring 2026 (April-June 2026)

4. **Submit to JOSS** (or pyOpenSci + JOSS joint submission)
5. **Contact CSCE** (info@csce.org) about newsletter article
6. **Submit to Journal of Hydraulic Structures** -- Focused paper on HTAB optimization or geometry parsing

### Phase 3: Fall 2026

7. **Submit ASFPM 2027 abstract** when call opens
8. **Submit EWRI 2027 / ASCE2027 abstract** when call opens
9. **Propose Australian Water School webinar update**

### Phase 4: 2027

10. **Present at ASFPM 2027** and/or **ASCE2027**
11. **Submit TFMA presentation** if they have a conference
12. **Consider Journal of Hydraulic and Water Engineering** for a USGS integration paper

---

## Article Angles by Audience

### For Academics (JOSS, Preprints)

**Focus**: Software architecture, design decisions, comparison with alternatives, reproducibility

**Key Messages**:
- First comprehensive Python library for HEC-RAS 6.x without COM dependency
- DataFrame-first architecture for project metadata
- Extensible HDF abstraction layer
- 47+ example notebooks as reproducible documentation

### For Practitioners (ASCE Newsletters, ASFPM, FMA)

**Focus**: How it saves time, improves reliability, real-world examples

**Key Messages**:
- Automate repetitive HEC-RAS tasks (batch processing, sensitivity analysis)
- Fix broken eBFE/FEMA deliverables automatically
- Parallel execution cuts study timelines
- Works with existing HEC-RAS projects -- no migration needed

### For the LLM/AI Community (Blog Posts, Preprints)

**Focus**: LLM-Forward methodology, AI-assisted engineering, professional responsibility

**Key Messages**:
- Professional engineers using AI as a tool, not a replacement
- Multi-level verifiability: GUI review + visual outputs + code audit
- Human-in-the-loop workflows for safety-critical infrastructure
- The evolution from HEC-Commander prompts to ras-commander library

---

## JOSS Paper Outline

```yaml
title: "ras-commander: A Python Library for HEC-RAS Automation and Results Processing"
authors:
  - name: William Mark Katzenmeyer
    orcid: # TODO
    affiliation: CLB Engineering Corporation
tags:
  - Python
  - HEC-RAS
  - hydraulic modeling
  - flood analysis
  - open source
  - automation
date: # submission date
bibliography: paper.bib
```

### Suggested Sections

1. **Summary** (1 paragraph)
   - What ras-commander is and does

2. **Statement of Need** (2-3 paragraphs)
   - Gap: HEC-RAS 6.x has no official Python API; COM interface limited to 5.x
   - Need: Reproducible, scriptable hydraulic modeling workflows
   - Audience: Hydraulic engineers, researchers, automation developers

3. **Design and Architecture** (2-3 paragraphs)
   - Static class pattern and rationale
   - DataFrame-first principle
   - HDF abstraction layer
   - Smart execution skip
   - Remote execution architecture

4. **Key Features** (bulleted list)
   - Plan execution (single, parallel, remote)
   - HDF results extraction (18 classes)
   - Geometry parsing and modification
   - USGS gauge integration (14 modules)
   - Precipitation data (AORC + Atlas 14)
   - eBFE model organization

5. **Related Work** (1-2 paragraphs)
   - raspy (quantum-dan) -- COM-based, HEC-RAS 5.x focus
   - pyHecRas -- COM wrapper
   - Dysarz 2018 Water paper -- foundational Python/HEC-RAS work
   - HEC-Commander -- predecessor project (prompt-based, not library)

6. **AI Usage Disclosure**
   - Transparent statement per JOSS requirements

7. **Acknowledgements**

8. **References**

---

## Key References for paper.bib

```bibtex
@article{dysarz2018,
  title={Application of Python Scripting Techniques for Control and Automation of HEC-RAS Simulations},
  author={Dysarz, Tomasz},
  journal={Water},
  volume={10},
  number={10},
  pages={1382},
  year={2018},
  publisher={MDPI}
}

% HEC-RAS documentation
% raspy GitHub
% pyHecRas
% HEC-Commander GitHub
% Australian Water School course
```

---

## Contact Information for Submissions

| Venue | Contact |
|-------|---------|
| JOSS | https://joss.theoj.org/papers/new |
| pyOpenSci | https://github.com/pyOpenSci/software-submission |
| Texas Civil Engineer | https://www.texasce.org/submit-article/ |
| CSCE Newsletter | info@csce.org |
| EarthArXiv | https://eartharxiv.org/ |
| ASFPM | conference@floods.org |
| EWRI Congress | https://www.ewricongress.org/call-abstracts |
| TFMA | https://www.tfma.org/ |
| FMA | https://floodplain.org/ |

---

## NoAPC.com Resource

For discovering additional no-cost journals across engineering disciplines: https://noapc.com/
Currently lists 2,592 open-access journals indexed in Scopus and Web of Science with no article processing charges.
