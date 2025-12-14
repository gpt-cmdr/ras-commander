# HEC-RAS Documentation Query Skill

Query official HEC-RAS Confluence documentation with full visual context (text + images + screenshots).

## Quick Start

```javascript
// Import the query engine
import { queryDocumentation } from './core/query_engine.mjs';

// Ask a question
const result = await queryDocumentation("Where is the Run Simulation button?");

// Result includes:
// - Selected manual (rasum, r2dum, rmum, etc.)
// - Extracted text content
// - Screenshot (if dev-browser available)
// - Images and sections found
```

## Features

### Phase 1: Core Query Engine ✅

- **Smart Manual Selection**: Automatically selects correct HEC-RAS manual from 6 options using weighted keyword scoring
- **Visual Mode**: Captures screenshots using dev-browser plugin for UI-related questions
- **Text Extraction**: Extracts documentation text, images, and section headings
- **Screenshot Caching**: MD5-based cache system to avoid redundant requests
- **Graceful Fallback**: Falls back to text-only mode when dev-browser unavailable

### Phase 2: Enhanced Search ✅

- **Documentation Index**: Pre-built searchable index of ~30 manual sections
- **Smart Search**: Combines manual selection with index search for comprehensive results
- **Multi-Page Queries**: Retrieves information from multiple documentation sections
- **Candidate Ranking**: Returns top N candidate manuals for complex questions

### Phase 2.5: Web Search Intelligence ✅ NEW

- **Site-Constrained Search**: Leverages search engines with `site:hec.usace.army.mil/confluence/rasdocs`
- **URL Pattern Extraction**: Extracts manual codes from Confluence URL patterns
- **Frequency-Based Scoring**: Counts manual occurrences in search results with confidence levels
- **Hybrid Selection**: Intelligently combines web search + keyword matching
- **Accuracy Improvement**: Increases manual selection accuracy from 76.5% to ~95%
- **Conflict Resolution**: Smart decision logic when web search and keywords disagree

## Covered Documentation

### Primary Manuals

1. **User's Manual (rasum)** - Core HEC-RAS functionality
   - Geometry data (cross sections, structures)
   - Steady flow analysis
   - Unsteady flow analysis
   - Dam breach modeling
   - Running simulations

2. **2D Modeling Manual (r2dum)** - 2D unsteady flow
   - 2D flow areas and mesh generation
   - Terrain processing
   - 2D boundary conditions
   - 2D/1D connections

3. **RASMapper Manual (rmum)** - Visualization and mapping
   - RASMapper interface
   - Terrain layers
   - Stored maps and flood mapping
   - Result visualization

4. **Hydraulic Reference Manual (ras1dtechref)** - Theory and equations
   - Basic hydraulic equations
   - Numerical methods
   - Structure hydraulics

5. **Release Notes (rasrn)** - Version history
   - New features by version
   - Changes and updates

6. **Known Issues (raski)** - Bugs and workarounds
   - 2D modeling issues
   - Computation errors
   - Interface problems

## Usage Examples

### Basic Query

```javascript
import { queryDocumentation } from './core/query_engine.mjs';

// Simple question
const result = await queryDocumentation("How do I create a 2D mesh?");

console.log(`Manual: ${result.manualInfo.name}`);
console.log(`URL: ${result.url}`);
console.log(`Screenshot: ${result.screenshot?.path}`);
console.log(`Content preview: ${result.content.text.substring(0, 200)}...`);
```

### Force Specific Manual

```javascript
// Query specific manual directly
const result = await queryDocumentation(
  "What are the mesh refinement options?",
  { manual: 'r2dum' }  // Force 2D Modeling Manual
);
```

### Search Mode (Phase 2)

```javascript
import { smartSearch } from './core/search_engine.mjs';

// Smart search across documentation
const search = await smartSearch("dam breach workflow", { topN: 5 });

console.log(`Primary manual: ${search.primaryManual.code}`);
console.log(`Relevant sections:`);
search.indexResults.forEach(r => {
  console.log(`  - [${r.manual}] ${r.section} (score: ${r.score})`);
});
```

### Multi-Page Query (Phase 2)

```javascript
import { multiPageQuery } from './core/search_engine.mjs';

// Complex workflow requiring multiple sections
const results = await multiPageQuery(
  "How do I set up and visualize a 2D unsteady flow simulation?",
  { maxPages: 3 }
);

results.pages.forEach(page => {
  console.log(`\n[${page.source}] ${page.manual}`);
  console.log(page.result.content.text.substring(0, 300));
});
```

### Web Search Mode (Phase 2.5)

```javascript
import { queryDocumentation } from './core/query_engine.mjs';

// With intelligent web search (requires Claude Code WebSearch tool)
const result = await queryDocumentation(
  "What are the known issues with 2D mesh generation?",
  {
    useWebSearch: true,
    webSearchFn: WebSearch  // Claude Code WebSearch tool
  }
);

// Result includes:
// - Manual selected by web search (extracts from URL patterns)
// - Confidence score (high/medium/low based on result frequency)
// - Method used (web-search, hybrid, keyword-fallback)
// - Top URLs from search results

console.log(`Selected manual: ${result.manualInfo.code}`);
console.log(`Method: ${result.manualSelection.method}`);
console.log(`Confidence: ${result.manualSelection.confidence}`);

// Without web search (faster, offline, keyword-based)
const result2 = await queryDocumentation(
  "How do I create a 2D mesh?",
  { useWebSearch: false }  // or omit - defaults to false
);
```

### When to Use Web Search

**Use web search for:**
- "Known issues" questions (e.g., "known issues with 2D mesh")
- Version history questions (e.g., "when was terrain layering added")
- Intent-heavy questions where keywords may conflict

**Skip web search for:**
- Clear feature questions (e.g., "how do I create a 2D mesh")
- Offline scenarios
- Speed-critical queries (<50ms needed)

**Trade-off:** 1-2 seconds latency for +18.5% accuracy improvement

### Understanding Web Search Results

**Selection Methods:**
| Method | Meaning |
|--------|---------|
| `web-search` | High confidence web search used |
| `web-keyword-agreement` | Web + keywords agree |
| `keyword-fallback` | Web failed/low, used keywords |

**Confidence Levels:**
| Level | Criteria |
|-------|----------|
| `high` | 60%+ frequency OR 3+ occurrences |
| `medium` | 40%+ OR 2 occurrences |
| `low` | Falls back to keywords |

## Architecture

```
querying-hecras-documentation/
├── core/
│   ├── manual_selector.mjs      # Smart manual selection + enhanced async wrapper
│   ├── query_engine.mjs         # Main query engine with web search support
│   ├── web_search_selector.mjs  # Site-constrained search (Phase 2.5) ← NEW
│   ├── fallback_handler.mjs     # Graceful degradation
│   ├── screenshot_manager.mjs   # Screenshot caching
│   ├── index_builder.mjs        # Documentation index (Phase 2)
│   └── search_engine.mjs        # Smart search (Phase 2)
├── data/
│   ├── keyword_mappings.json    # Weighted keyword scoring
│   ├── url_mappings.json        # Manual URLs
│   └── manual_index.json        # Searchable index (Phase 2)
├── screenshots/
│   └── cache/                   # Cached screenshots
├── tests/
│   ├── test_queries.json        # Test cases (17 tests)
│   ├── run_tests.mjs            # Manual selection test runner
│   ├── test_web_search.mjs      # Web search test suite (Phase 2.5) ← NEW
│   └── test_results/            # Test output
├── SKILL.md                     # Skill definition
├── README.md                    # This file
├── INSTALLATION.md              # Setup instructions
├── VALIDATION_REPORT.md         # Test validation results ← NEW
└── STATUS.md                    # Implementation status
```

## Query Modes

### Visual Mode (Recommended)

**Requirements**: dev-browser plugin installed and running

**Capabilities**:
- ✅ Full text extraction
- ✅ Screenshot capture
- ✅ Image visibility
- ✅ Section detection

**Setup**: See [INSTALLATION.md](INSTALLATION.md)

### Text-Only Mode (Fallback)

**Requirements**: None (WebFetch only)

**Capabilities**:
- ✅ Text extraction
- ✅ Manual selection
- ✅ URL provision
- ❌ No screenshots
- ❌ Limited visual context

**Activation**: Automatic when dev-browser unavailable

## Manual Selection Algorithm

The skill uses a weighted keyword scoring system to select the appropriate manual:

```
High-Weight Phrases (10 points):
- "2d flow area" → r2dum
- "stored map" → rmum
- "dam breach" → rasum

Medium-Weight Keywords (2-5 points):
- "mesh" → r2dum (5 points)
- "terrain" → rmum (3 points)
- "steady flow" → rasum (4 points)

Confidence Levels:
- High: Score ≥ 5 (strong keyword match)
- Low: Score < 5 (falls back to default)
```

**Synonym Expansion**: Questions are expanded with synonyms before scoring:
- "mesh" → ["grid", "discretization"]
- "dam breach" → ["dam break", "dam failure"]
- "boundary condition" → ["BC", "inflow", "outflow"]

## Screenshot Caching

Screenshots are cached using MD5 hash of `manual:url`:

```javascript
Cache Key: md5("r2dum:https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/latest")
Cache Path: screenshots/cache/a3f8b2c1e4d5...png
```

**Cache Management**:
```bash
# View cache statistics
node core/screenshot_manager.mjs stats

# Clear all cached screenshots
node core/screenshot_manager.mjs clear
```

## Testing

### Run Test Suite

```bash
# Selection-only tests (no dev-browser required)
node tests/run_tests.mjs

# Full query tests (requires dev-browser)
node tests/run_tests.mjs --full

# Verbose output
node tests/run_tests.mjs --verbose

# Specific category
node tests/run_tests.mjs --category=ui_location
```

### Test Categories

- **ui_location** (3 tests): UI element location questions
- **workflow** (3 tests): Complete workflow procedures
- **concepts** (3 tests): Hydraulic concepts and theory
- **version_specific** (3 tests): Release notes and version history
- **troubleshooting** (3 tests): Error messages and debugging
- **multi_manual** (2 tests): Complex questions spanning multiple manuals

### Test Report

Test results are saved to `tests/test_results/test_report_YYYY-MM-DD.json`:

```json
{
  "summary": {
    "total": 14,
    "passed": 13,
    "failed": 1,
    "pass_rate": "92.9%",
    "avg_duration_ms": 245
  },
  "categories": {
    "ui_location": { "passed": 3, "total": 3 },
    "workflow": { "passed": 3, "total": 3 }
  }
}
```

## CLI Usage

All core modules include CLI interfaces for testing:

```bash
# Test manual selection
node core/manual_selector.mjs "How do I create a 2D mesh?"

# Run query
node core/query_engine.mjs "Where is the Run Simulation button?"

# Check dev-browser status
node core/fallback_handler.mjs

# Search index
node core/index_builder.mjs search "dam breach"

# Smart search
node core/search_engine.mjs "complete 2D modeling workflow"
```

## Performance

### Typical Response Times

| Mode | First Query | Cached Query |
|------|-------------|--------------|
| Visual (dev-browser) | 2-5 seconds | 0.5-1 second |
| Text-only (WebFetch) | 1-3 seconds | N/A |

### Caching Benefits

- **First query**: Captures screenshot, caches for 24 hours
- **Subsequent queries**: Retrieves from cache (instant)
- **Cache size**: ~500KB per screenshot, ~10MB for 20 pages

## Troubleshooting

### Issue: "dev-browser module not found"

**Cause**: dev-browser plugin not installed

**Solution**: See [INSTALLATION.md](INSTALLATION.md) for setup instructions

### Issue: "dev-browser server not running on port 9222"

**Cause**: dev-browser server not started

**Solution**:
```bash
cd ~/.claude/plugins/cache/dev-browser-marketplace/dev-browser/*/skills/dev-browser
npx tsx scripts/start-server.ts
```

### Issue: Manual selection incorrect

**Cause**: Question doesn't contain strong keywords

**Solution**:
- Add more specific keywords to question
- Force manual with `{ manual: 'r2dum' }` option
- Check keyword mappings in `data/keyword_mappings.json`

### Issue: Screenshot not captured

**Possible causes**:
1. dev-browser not in visual mode (check with `node core/fallback_handler.mjs`)
2. Confluence page requires authentication (not common for public docs)
3. Page load timeout (increase timeout in query options)

## Development

### Adding New Keywords

Edit `data/keyword_mappings.json`:

```json
{
  "high_weight": {
    "r2dum": [
      ["my new phrase", 10]
    ]
  }
}
```

### Adding New Sections to Index

Edit `core/index_builder.mjs` in `createPrebuiltIndex()`:

```javascript
{
  title: "New Section",
  keywords: ["keyword1", "keyword2"],
  topics: ["topic1", "topic2"]
}
```

Or build index from actual documentation (future enhancement).

### Adding New Test Cases

Edit `tests/test_queries.json`:

```json
{
  "id": "new_001",
  "question": "Your test question?",
  "expected_manual": "rasum",
  "expected_confidence": "high",
  "validation": {
    "should_mention": ["keyword1", "keyword2"]
  }
}
```

## Integration with ras-commander

This skill is designed to help ras-commander users find documentation when:

1. **Error messages**: "What does 'unstable flow' mean?"
2. **Feature discovery**: "How do I use terrain layering?"
3. **Workflow guidance**: "Complete workflow for dam breach modeling"
4. **UI navigation**: "Where is the 2D mesh generator?"

Future integration (Phase 3+):
- Automatic documentation lookup from error messages
- Context-aware suggestions based on current operation
- Integration with community forums

## Limitations

### Current Limitations

- **Public documentation only**: Cannot access restricted/internal docs
- **English only**: HEC-RAS docs are in English
- **Manual-level granularity**: Selects manual, not specific page (Phase 2 enhances with index)
- **No forum integration**: Community forums not yet integrated (Phase 4)

### Known Issues

- Some UI questions may benefit from multiple screenshots (planned enhancement)
- Index is pre-built, not dynamically updated from documentation (enhancement)
- No support for HEC-RAS 7.x yet (when released)

## License

This skill is part of the ras-commander project. See repository root for license information.

## Support

For issues or questions:
1. Check [INSTALLATION.md](INSTALLATION.md) for setup help
2. Run test suite to validate installation
3. Check troubleshooting section above
4. File issue in ras-commander repository

## Changelog

### Phase 2.5 (2025-12-13) - Web Search Intelligence
- ✅ Site-constrained web search with URL pattern extraction
- ✅ Frequency-based manual scoring (high/medium/low confidence)
- ✅ Hybrid selection combining web search + keyword fallback
- ✅ Intelligent conflict resolution when methods disagree
- ✅ Accuracy improvement: 76.5% → ~95%
- ✅ Comprehensive test suite (39 tests, 100% pass rate)
- ✅ Optional opt-in via `useWebSearch` parameter

### Phase 2 (2025-12-13) - Enhanced Search
- ✅ Documentation index with ~30 sections
- ✅ Smart search combining selection + index
- ✅ Multi-page query capability
- ✅ Candidate ranking

### Phase 1 (2025-12-13) - Core Query Engine
- ✅ Smart manual selection with weighted keywords
- ✅ Visual mode with dev-browser integration
- ✅ Screenshot capture and caching
- ✅ Graceful fallback to text-only mode
- ✅ Comprehensive test suite

## Future Enhancements

### Phase 3: Context Integration
- Automatic documentation lookup from ras-commander error messages
- Integration with HEC-RAS log file parsing
- Context-aware suggestions

### Phase 4: Community Integration
- HEC-RAS forum search and integration
- CWMS Users Group archive access
- Stack Exchange integration
- Community-contributed solutions

## See Also

- [SKILL.md](SKILL.md) - Complete skill definition
- [INSTALLATION.md](INSTALLATION.md) - Setup instructions
- [ras-commander documentation](../../docs/) - Main project docs
- [Official HEC-RAS documentation](https://www.hec.usace.army.mil/confluence/rasdocs)
