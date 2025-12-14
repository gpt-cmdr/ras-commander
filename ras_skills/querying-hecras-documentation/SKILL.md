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

### 1. User's Manual (rasum)

**Coverage**: General HEC-RAS usage, data entry, simulations

**Best for**:
- General "how to" questions
- UI location queries ("Where is...")
- Workflow guidance ("How do I...")
- Basic modeling concepts

**Example Questions**:
- "How do I enter cross section data?"
- "Where is the Run Simulation button?"
- "How do I set up an unsteady flow simulation?"

**URL**: https://www.hec.usace.army.mil/confluence/rasdocs/rasum/latest

### 2. 2D Modeling Manual (r2dum)

**Coverage**: 2D flow areas, mesh generation, terrain

**Best for**:
- 2D modeling questions
- Mesh generation and editing
- Terrain processing
- 2D/1D connections

**Example Questions**:
- "How do I create a 2D mesh?"
- "What is the difference between cell-centered and face-centered?"
- "How do I refine my 2D mesh near structures?"

**URL**: https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/latest

### 3. Mapper Manual (rmum)

**Coverage**: GIS integration, result mapping, visualization

**Best for**:
- RASMapper questions
- Stored maps and profiles
- Terrain layer management
- Result visualization

**Example Questions**:
- "How do I create a stored map?"
- "How do I import terrain data?"
- "What GIS formats does RASMapper support?"

**URL**: https://www.hec.usace.army.mil/confluence/rasdocs/rmum/latest

### 4. Hydraulic Reference (ras1dtechref)

**Coverage**: Technical equations, hydraulic theory

**Best for**:
- Technical/theoretical questions
- Equation derivations
- Methodology explanations
- Algorithm details

**Example Questions**:
- "What equation does HEC-RAS use for weir flow?"
- "How is the momentum equation discretized?"
- "What is the theoretical basis for the sediment transport?"

**URL**: https://www.hec.usace.army.mil/confluence/rasdocs/ras1dtechref/latest

### 5. Release Notes (rasrn)

**Coverage**: Version history, new features, changes

**Best for**:
- Version-specific questions
- "What's new" inquiries
- Feature availability by version
- Migration guidance

**Example Questions**:
- "What's new in HEC-RAS 6.6?"
- "When was terrain layering added?"
- "What changed between 5.x and 6.x?"

**URL**: https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/latest

### 6. Known Issues (raski)

**Coverage**: Bug tracking, workarounds, limitations

**Best for**:
- Error troubleshooting
- Known bugs and limitations
- Workarounds for issues
- "Why isn't it working" questions

**Example Questions**:
- "Why is my 2D mesh not computing?"
- "What does error code XYZ mean?"
- "Is there a workaround for..."

**URL**: https://www.hec.usace.army.mil/confluence/rasdocs/raski/latest

## Advanced Features (Phase 2)

### Documentation Index

The skill maintains a searchable index of all manual sections:

**Index Structure**:
```json
{
  "rasum": {
    "sections": [
      {
        "title": "Creating Cross Sections",
        "url": "https://...",
        "keywords": ["cross section", "geometry", "data entry"],
        "parent": "Geometric Data"
      }
    ]
  }
}
```

**Index Building**:
- Crawls all 6 manuals
- Extracts table of contents
- Identifies section titles and URLs
- Builds keyword associations
- Updates periodically (checks for changes)

### Smart Search

**Search Algorithm**:
1. Extract keywords from question
2. Match against index keywords
3. Rank results by:
   - Keyword frequency
   - Phrase matching
   - Section hierarchy
   - Manual relevance score
4. Return top N results

**Fuzzy Matching**:
- Handles typos: "mseh" → "mesh"
- Synonyms: "dam break" → "dam breach"
- Common variations: "2-D" → "2D"

### Multi-Page Queries

**When to Use**:
- Complex questions requiring multiple sources
- Workflow questions spanning multiple sections
- Comparison questions (e.g., "1D vs 2D modeling")

**How It Works**:
1. Identify all relevant sections
2. Retrieve content from each
3. Synthesize information
4. Provide combined answer with section references

**Example**:
```
Q: "How do I set up a complete 2D model from scratch?"

A: Combines information from:
   - r2dum: Creating 2D flow areas
   - r2dum: Mesh generation
   - rmum: Terrain data import
   - rasum: Boundary conditions
   - rasum: Running simulations
```

## Screenshot Management

### Caching Strategy

**Why Cache**:
- Avoid redundant requests to HEC-RAS server
- Faster response times for repeat questions
- Reduce network traffic

**Cache Key**: `{manual}_{page_hash}.png`

**Cache Location**: `screenshots/cache/`

**Cache Invalidation**:
- Manual clear (delete cache directory)
- Time-based (configurable, default: never expire)
- Version-specific (6.5 vs 6.6 screenshots are different)

### Screenshot Formats

**Full Page**: Captures entire documentation page
- Use for: Workflow diagrams, complete sections
- Size: Typically 1-3 MB

**Viewport Only**: Captures visible portion
- Use for: UI screenshots, specific elements
- Size: Typically 100-500 KB

**Element-Specific**: Captures individual diagrams
- Use for: Specific figures, equations
- Size: Typically 50-200 KB

## Fallback Modes

### Mode 1: Full Visual (Optimal)

**Requirements**: dev-browser running, screenshots enabled

**Capabilities**:
- ✅ Text extraction
- ✅ Image identification
- ✅ Screenshot capture
- ✅ Visual answer context

**Performance**: 10-30 seconds per query

### Mode 2: Text-Only Browser (Degraded)

**Requirements**: dev-browser running, screenshot disabled/failed

**Capabilities**:
- ✅ Text extraction
- ✅ Image identification (URLs only)
- ❌ Screenshot capture
- ⚠️ Limited visual context

**Performance**: 5-15 seconds per query

### Mode 3: WebFetch (Minimum)

**Requirements**: WebFetch tool available

**Capabilities**:
- ✅ Text extraction
- ❌ Image identification
- ❌ Screenshot capture
- ❌ No visual context

**Performance**: 3-10 seconds per query

### Mode 4: Offline (Error)

**Requirements**: None met

**Response**: Installation instructions + error message

**Example**:
```
Unable to access HEC-RAS documentation. To enable this skill:

1. Install dev-browser plugin (optimal):
   [Instructions in INSTALLATION.md]

2. OR install necessary dependencies for WebFetch

3. Verify network access to hec.usace.army.mil
```

## Testing and Validation

### Test Categories

**1. UI Location** (3 tests):
- "Where is the Run Simulation button?"
- "How do I access the 2D mesh editor?"
- "Where are the boundary condition tools?"

**2. Workflow** (2 tests):
- "How do I set up a dam breach simulation?"
- "What's the complete workflow for 2D modeling?"

**3. Concepts** (2 tests):
- "What is an ineffective flow area?"
- "What's the difference between 1D and 2D modeling?"

**4. Version-Specific** (2 tests):
- "What's new in HEC-RAS 6.6 for 2D?"
- "When was terrain layering added?"

**5. Troubleshooting** (1 test):
- "Why is my 2D mesh not computing?"

**Success Criteria**:
- Manual selection: 90%+ accuracy
- Response time: <30 seconds
- Screenshot quality: All relevant UI elements visible
- Text accuracy: No hallucinations, grounded in docs

## Common Use Cases

### Use Case 1: New User Learning

**Question**: "I'm new to HEC-RAS. How do I get started with 2D modeling?"

**Response**:
1. Selects User's Manual for general intro
2. Searches 2D Manual for 2D-specific guidance
3. Provides step-by-step workflow
4. Includes screenshots of key UI elements
5. Links to relevant manual sections

### Use Case 2: Troubleshooting Errors

**Question**: "I'm getting an error about unstable flow. What does this mean?"

**Response**:
1. Selects Known Issues manual
2. Searches for "unstable flow" errors
3. Explains common causes
4. Provides troubleshooting steps
5. Links to related documentation

### Use Case 3: Feature Discovery

**Question**: "Can HEC-RAS model sediment transport?"

**Response**:
1. Searches User's Manual for sediment capabilities
2. Checks Release Notes for when feature was added
3. Links to Technical Reference for methodology
4. Provides workflow guidance if available

### Use Case 4: UI Navigation

**Question**: "I can't find the terrain layer manager. Where is it?"

**Response**:
1. Selects Mapper Manual
2. Finds UI screenshot showing menu location
3. Provides step-by-step navigation
4. Captures screenshot highlighting the menu

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

- `README.md` - Quick reference and installation
- `INSTALLATION.md` - dev-browser setup instructions
- `STATUS.md` - Implementation status and roadmap
- `tests/test_queries.json` - Comprehensive test suite
- Official HEC-RAS documentation: https://www.hec.usace.army.mil/confluence/rasdocs

## Support

**Issues**:
- dev-browser not starting: See INSTALLATION.md
- Screenshots not capturing: Check port 9222/9223 availability
- Manual selection incorrect: Report to improve keyword mappings
- Documentation outdated: Rebuild index with latest manuals

**Contact**: See ras-commander repository issues
