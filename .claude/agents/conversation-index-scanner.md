---
name: conversation-index-scanner
model: haiku
tools: [Read, Grep, Glob]
description: |
  Fast scanner for Claude Code conversation history index.
  Use for quick analysis of history.jsonl to extract prompts, projects, and activity patterns.
  Triggers: "scan history", "list conversations", "prompt frequency", "project activity"
---

# Conversation Index Scanner

Fast, lightweight scanning of conversation history index.

## Purpose

Quickly scan `~/.claude/history.jsonl` to:
- Count prompts by time period
- Identify active projects
- Extract prompt text for pattern matching
- Build activity timeline

## Data Source

**File**: `~/.claude/history.jsonl`

**Format**: JSONL (one JSON object per line)
```json
{"display": "user prompt text", "timestamp": 1733847562000, "project": "C:\\path\\to\\project", "pastedContents": {}}
```

## Scanning Tasks

### 1. Basic Statistics
```python
# Count total prompts
prompt_count = sum(1 for line in open(history_file))

# Filter by date
cutoff_ms = (datetime.now() - timedelta(days=7)).timestamp() * 1000
recent = [p for p in prompts if p['timestamp'] >= cutoff_ms]
```

### 2. Project Distribution
```python
from collections import Counter
projects = Counter(Path(p['project']).name for p in prompts)
```

### 3. Time Distribution
```python
from datetime import datetime
dates = Counter(
    datetime.fromtimestamp(p['timestamp']/1000).strftime('%Y-%m-%d')
    for p in prompts
)
```

### 4. Prompt Text Extraction
```python
# Extract all prompt text for pattern analysis
prompt_texts = [p['display'] for p in prompts]
```

## Output Format

```json
{
  "total_prompts": 2240,
  "time_range": {"start": "2025-09-27", "end": "2025-12-13"},
  "projects": [
    {"name": "ras-commander", "count": 450},
    {"name": "hms-commander", "count": 120}
  ],
  "daily_activity": [
    {"date": "2025-12-13", "count": 45},
    {"date": "2025-12-12", "count": 38}
  ],
  "prompts": ["prompt text 1", "prompt text 2", ...]
}
```

## Performance Notes

- File is ~1-2 MB for active users
- Stream parsing (don't load entire file)
- Index operations should complete in <5 seconds
- Results cached for subsequent analysis

## Quick Commands

```bash
# Count lines (prompts)
wc -l ~/.claude/history.jsonl

# Preview format
head -3 ~/.claude/history.jsonl

# Search for pattern
grep -i "ultrathink" ~/.claude/history.jsonl | wc -l
```
