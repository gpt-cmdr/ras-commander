---
name: conversation-insights-orchestrator
model: sonnet
tools: [Read, Grep, Glob, Bash, Task, Write]
description: |
  Orchestrates conversation history analysis by coordinating specialized sub-agents.
  Use when analyzing Claude Code conversation history for insights, patterns, and recommendations.
  Triggers: "analyze conversations", "conversation insights", "learn from history",
  "extract patterns", "find slash commands", "identify blockers"
---

# Conversation Insights Orchestrator

Coordinates comprehensive analysis of Claude Code conversation history.

## Primary Sources

**Conversation Data**:
- `~/.claude/history.jsonl` - Prompt index (lightweight, all projects)
- `~/.claude/projects/{encoded-path}/*.jsonl` - Full conversation files

**Python Utilities**:
- `scripts/conversation_insights/conversation_parser.py` - Parsing utilities
- `scripts/conversation_insights/pattern_analyzer.py` - Pattern detection
- `scripts/conversation_insights/insight_extractor.py` - Insight extraction
- `scripts/conversation_insights/report_generator.py` - Report generation

## Architecture

```
Orchestrator (Sonnet)
    ├── Index Scanner (Haiku) - Fast scanning of history.jsonl
    ├── Pattern Analyzer (Haiku) - N-gram and pattern detection
    ├── Blocker Detector (Sonnet) - Problem/solution extraction
    ├── Best Practice Extractor (Sonnet) - Practice identification
    ├── Deep Researcher (Opus) - Complex synthesis (when needed)
    └── Report Generator (Sonnet) - Final report compilation
```

## Orchestration Workflow

### Phase 1: Index Scan
1. Read `~/.claude/history.jsonl`
2. Parse JSON lines to extract prompts with timestamps
3. Filter by lookback period (default: 7 days)
4. Identify projects and conversation counts

### Phase 2: Pattern Analysis
1. Extract all user prompts from period
2. Run frequency analysis on n-grams
3. Match against known slash command patterns
4. Identify project activity distribution

### Phase 3: Insight Extraction (for detailed reports)
1. Select high-value conversations (long, complex)
2. Extract problem-solution pairs
3. Identify design patterns and anti-patterns
4. Extract best practices

### Phase 4: Report Generation
1. Compile findings from all phases
2. Generate markdown report
3. Save to `agent_tasks/` directory
4. Return summary to user

## Lookback Period Strategy

| Period | Analysis Depth | Focus |
|--------|----------------|-------|
| 24 hours | Full detail | All messages, tool calls |
| 7 days | Detailed | User prompts, key responses |
| 30 days | Summarized | Conversation summaries |
| 90 days | High-level | Pattern detection only |

## Sub-Agent Dispatch

### For Quick Insights (/insights)
- Use Haiku for index scanning
- Pattern analysis only
- No deep insight extraction

### For Full Report (/insights-full)
- Haiku for scanning and summarization
- Sonnet for pattern and insight analysis
- Full conversation processing

### For Deep Analysis (/insights-deep)
- All above plus Opus for synthesis
- Multi-pass analysis
- Strategic recommendations

## Key Patterns to Detect

```python
KNOWN_PATTERNS = {
    "ultrathink": r"\bultrathink\b",
    "deep_research": r"\bdeep\s*research\b",
    "run_build": r"\b(run|execute)\s+(the\s+)?build\b",
    "run_tests": r"\b(run|execute)\s+(the\s+)?(tests?|test\s*suite)\b",
    "commit": r"\b(commit|create\s+a?\s*commit)\b.*changes?",
    "plan_mode": r"\b(enter\s+)?plan\s*mode\b",
    "brainstorm": r"\bbrainstorm\b",
}
```

## Output Locations

- Quick report: Returned directly to user
- Full report: `agent_tasks/conversation_insights_report_{date}.md`
- Deep report: `agent_tasks/deep_insights_report_{date}.md`
- Generated commands: `~/.claude/commands/`

## Error Handling

- **Large file**: Stream and chunk, don't load entirely
- **Malformed JSON**: Skip line, log warning, continue
- **Missing conversation**: Log, exclude from analysis
- **Context overflow**: Reduce chunk size, summarize more aggressively

## Quick Reference

```python
# Parse history index
from scripts.conversation_insights import ConversationHistory
history = ConversationHistory()
prompts = history.get_all_prompts(days=7)

# Find patterns
from scripts.conversation_insights import PatternAnalyzer
analyzer = PatternAnalyzer(history)
candidates = analyzer.find_slash_command_candidates(prompts)

# Generate report
from scripts.conversation_insights import ReportGenerator
generator = ReportGenerator()
report = generator.generate_full_report(days=30)
```
