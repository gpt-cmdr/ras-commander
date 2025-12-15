---
name: querying-hecras-documentation
description: |
  Query official HEC-RAS Confluence documentation with full visual context (text + images + screenshots).

  Answers questions about HEC-RAS modeling workflows, UI locations, geometry concepts, 2D/1D modeling,
  RASMapper operations, hydraulic theory, version-specific features, error troubleshooting, and best practices.

  **Capabilities**:
  - Smart manual selection: Automatically identifies which HEC-RAS manual to query
  - Visual documentation: Captures screenshots showing UI, diagrams, and workflow illustrations
  - Search across manuals: Finds relevant sections in User's Manual, 2D Manual, Mapper Manual, Technical Reference
  - Multi-page synthesis: Combines information from multiple documentation pages
  - Version-specific guidance: Targets HEC-RAS 6.x features and changes
  - Graceful fallback: Works with or without dev-browser (visual vs text-only mode)

  **Trigger keywords**: HEC-RAS documentation, manual, user guide, RASMapper docs, 2D mesh, flow area,
  geometry file, cross section, dam breach, unsteady flow, steady flow, terrain data, stored maps,
  GIS integration, hydraulic equations, technical reference, release notes, known issues, error codes,
  troubleshooting, how to use HEC-RAS, where is button, what's new in version, RAS geometry,
  boundary conditions, initial conditions, plan computation, simulation setup, result mapping.

  **Primary Documentation Sources**:
  - User's Manual (rasum) - General workflows, UI guidance, data entry, simulations
  - 2D Modeling Manual (r2dum) - 2D flow areas, mesh generation, terrain processing
  - Mapper Manual (rmum) - GIS integration, result mapping, stored maps, layer management
  - Hydraulic Reference (ras1dtechref) - Technical equations, hydraulic theory, methodology
  - Release Notes (rasrn) - Version-specific features, changes, new capabilities
  - Known Issues (raski) - Bug tracking, workarounds, common problems

  **Usage**:
  Ask natural language questions like:
  - "How do I create a 2D mesh in HEC-RAS?"
  - "Where is the Run Simulation button?"
  - "What's new in HEC-RAS 6.6 for 2D modeling?"
  - "What does error code 123 mean?"
  - "How do I set up a dam breach simulation?"

  The skill automatically selects the appropriate manual, searches for relevant sections,
  and provides answers with screenshots (if dev-browser available) or text excerpts (fallback mode).
---

# Querying HEC-RAS Documentation

**Purpose**: Provide authoritative answers to HEC-RAS questions using official USACE Confluence documentation.

## Quick Start

### Prerequisites

**Optimal Mode (Visual Documentation)**:
- dev-browser plugin installed and server running
- Ports 9222 (HTTP) and 9223 (CDP) available
- Network access to hec.usace.army.mil

**Fallback Mode (Text-Only)**:
- WebFetch tool available
- Network access to hec.usace.army.mil

See `INSTALLATION.md` for dev-browser setup instructions.

### Basic Usage

Simply ask questions about HEC-RAS in natural language:

```
Q: "How do I create a 2D flow area?"
A: [Searches 2D Manual, provides step-by-step instructions with screenshots]

Q: "Where is the geometry editor?"
A: [Searches User's Manual, captures UI screenshot showing menu location]

Q: "What's new in version 6.6?"
A: [Searches Release Notes, summarizes new features]
```

## How It Works

### 1. Question Analysis

When you ask a question, the skill:
- Extracts key terms and concepts
- Identifies question category (UI, workflow, concept, troubleshooting, version)
- Determines which HEC-RAS manual is most relevant

### 2. Smart Manual Selection

**Weighted Keyword Scoring System**:

The skill uses a sophisticated scoring algorithm to select the right manual:

**High-weight phrases** (almost certainly indicate specific manual):
- "2D flow area", "2D mesh" → 2D Manual (r2dum)
- "RASMapper", "stored map" → Mapper Manual (rmum)
- "hydraulic equation", "theoretical derivation" → Technical Reference (ras1dtechref)
- "release notes", "version 6.6" → Release Notes (rasrn)
- "known issue", "error code" → Known Issues (raski)

**Medium-weight keywords** (likely but not certain):
- "2D", "mesh", "cell" → 2D Manual
- "map", "terrain", "GIS" → Mapper Manual
- "equation", "theory" → Technical Reference

**Default**: User's Manual (rasum) for general questions

### 3. Documentation Retrieval

**Visual Mode** (dev-browser available):
1. Navigate to selected manual
2. Search for relevant section
3. Extract text content
4. Identify and catalog images/diagrams
5. Capture full-page screenshot
6. Cache screenshot for future queries

**Text-Only Mode** (dev-browser not available):
1. Use WebFetch to retrieve manual page
2. Extract text content
3. Provide URLs for manual inspection
4. Note which images are referenced (but not visible)

### 4. Multi-Page Search (Phase 2)

For complex questions requiring multiple sections:
1. Build query from question keywords
2. Search documentation index
3. Rank results by relevance
4. Retrieve top N pages
5. Synthesize information from multiple sources
6. Provide combined answer with section references

## Manual Coverage

| Code | Manual | Best For |
|------|--------|----------|
| **rasum** | User's Manual | General usage, UI location, workflows, data entry |
| **r2dum** | 2D Modeling | 2D flow areas, mesh generation, terrain processing |
| **rmum** | Mapper Manual | RASMapper, stored maps, terrain layers, GIS |
| **ras1dtechref** | Hydraulic Reference | Equations, theory, methodology, algorithms |
| **rasrn** | Release Notes | Version features, "what's new", migration |
| **raski** | Known Issues | Errors, bugs, workarounds, troubleshooting |

**Base URL**: `https://www.hec.usace.army.mil/confluence/rasdocs/{code}/latest`

## Query Modes

| Mode | Requirements | Screenshots | Text | Performance |
|------|--------------|-------------|------|-------------|
| **Visual** | dev-browser running | ✅ Yes | ✅ Yes | 10-30s |
| **Text-Only** | WebFetch available | ❌ No | ✅ Yes | 3-10s |
| **Offline** | None | ❌ No | ❌ No | Error + instructions |

See `INSTALLATION.md` for dev-browser setup.

## Integration with ras-commander

This skill is designed to complement ras-commander library:

**Error Help**:
```python
try:
    RasCmdr.compute_plan("01")
except Exception as e:
    # Query documentation for error
    help = query_documentation(f"Error: {e}")
```

**Feature Discovery**:
```python
# "How do I use RasCmdr.compute_plan()?"
# Skill links to both:
# - ras-commander API docs
# - HEC-RAS User's Manual "Running Simulations"
```

**Best Practices**:
```python
# "What's the best practice for 2D mesh resolution?"
# Skill provides HEC-RAS manual guidance
# - r2dum: Mesh resolution recommendations
# - ras1dtechref: Stability criteria
```

## Limitations

### Current Limitations

1. **English Only**: HEC-RAS documentation is only available in English
2. **Version Coverage**: Primarily HEC-RAS 6.x (some 5.x coverage)
3. **No Code Examples**: Manuals don't include programming code (use ras-commander docs for that)
4. **Image OCR**: Doesn't extract text from diagram images (future enhancement)
5. **Offline Mode**: Requires internet access to query documentation

### Known Issues

1. **URL Changes**: Confluence URLs may change between versions
   - Mitigation: URL resolver with version-specific mappings

2. **Rate Limiting**: Unknown if USACE has rate limits
   - Mitigation: Aggressive caching, 2-second delays

3. **Authentication**: Some docs may require login (not currently supported)
   - Mitigation: Test and implement auth if needed

## Performance Optimization

### Caching Strategy

**What to Cache**:
- ✅ Screenshots (large, expensive to generate)
- ✅ Documentation index (slow to build)
- ✅ Recent queries (frequently repeated)
- ❌ Text content (small, fast to retrieve)

**Cache Invalidation**:
- Manual clear by user
- Version-specific (6.5 cache separate from 6.6)
- Time-based (optional, disabled by default)

### Response Time Targets

| Mode | Target | Acceptable | Poor |
|------|--------|------------|------|
| Visual (cached) | <5s | <10s | >20s |
| Visual (uncached) | <15s | <30s | >60s |
| Text-only | <5s | <10s | >20s |
| Multi-page | <20s | <45s | >90s |

## Future Enhancements

### Phase 3: Integration (Planned)

- Link ras-commander classes to documentation sections
- Map error messages to troubleshooting pages
- Context-aware help: `help_for_function("RasCmdr.compute_plan")`
- Annotate example notebooks with doc URLs

### Phase 4: Advanced Features (Planned)

- Visual search: "Find screenshot showing 2D mesh editor"
- Version comparison: "What changed in 6.6 vs 6.5?"
- Community integration: Kleinschmidt forum, Hydro School
- Pre-built visual knowledge base (500+ screenshots)
- Interactive tutorials with step-by-step screenshots

## See Also

- `README.md` - Quick reference and API usage
- `INSTALLATION.md` - dev-browser setup instructions
- `tests/test_queries.json` - Comprehensive test suite
- Official HEC-RAS documentation: https://www.hec.usace.army.mil/confluence/rasdocs

## Support

**Issues**:
- dev-browser not starting: See INSTALLATION.md
- Screenshots not capturing: Check port 9222/9223 availability
- Manual selection incorrect: Report to improve keyword mappings
- Documentation outdated: Rebuild index with latest manuals

**Contact**: See ras-commander repository issues
