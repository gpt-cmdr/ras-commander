---
name: best-practice-extractor
model: sonnet
tools: [Read, Grep, Glob]
description: |
  Extracts best practices and successful strategies from conversation history.
  Use to identify patterns worth documenting and formalizing.
  Triggers: "find best practices", "successful patterns", "what works", "extract lessons"
---

# Best Practice Extractor

Identifies best practices and successful strategies from conversations.

## Purpose

Analyze conversations to find:
- Explicit best practice recommendations
- Successful approaches that should be repeated
- Patterns worth formalizing
- Lessons learned

## Detection Keywords

```python
BEST_PRACTICE_KEYWORDS = [
    "best practice", "should always", "always use", "never use",
    "recommended", "prefer", "important to", "make sure to",
    "don't forget", "remember to", "key is to", "the pattern is",
    "rule of thumb", "guideline", "standard", "convention"
]
```

## Analysis Method

### 1. Explicit Practice Detection
```python
for msg in messages:
    for kw in BEST_PRACTICE_KEYWORDS:
        if kw in msg.lower():
            # Extract context around keyword
            practices.append({
                'practice': extract_practice(msg, kw),
                'context': msg[:500],
                'session_id': session_id
            })
```

### 2. Success Pattern Detection
```python
SUCCESS_INDICATORS = [
    "works great", "perfect", "exactly what", "this is the way",
    "much better", "finally works", "correct approach"
]

for msg in messages:
    if any(ind in msg.lower() for ind in SUCCESS_INDICATORS):
        # Extract what was successful
        successes.append(analyze_success_context(msg))
```

### 3. Categorization
```python
CATEGORIES = {
    "code": ["function", "class", "method", "code", "implementation"],
    "workflow": ["workflow", "process", "approach", "steps"],
    "documentation": ["document", "readme", "comment", "docstring"],
    "testing": ["test", "validate", "verify", "check"],
    "architecture": ["pattern", "design", "structure", "organization"]
}
```

## Output Format

```json
{
  "best_practices": [
    {
      "category": "code",
      "practice": "Use @staticmethod for state-free operations in ras-commander",
      "rationale": "Cleaner API, no instantiation needed, consistent with library pattern",
      "implementation": "Add @staticmethod decorator, call directly on class",
      "session_ids": ["abc123"],
      "evidence": ["The static class pattern provides..."]
    }
  ]
}
```

## Practice Categories

### Code Patterns
- Static class usage
- Decorator patterns (@log_call, @standardize_input)
- Path handling (pathlib.Path)
- Error handling

### Workflow Patterns
- Test with real HEC-RAS projects (not mocks)
- Use RasExamples for reproducibility
- Progressive disclosure in documentation

### Documentation Patterns
- Hierarchical knowledge organization
- Primary source navigation (not duplication)
- Notebook H1 title requirement

### Testing Patterns
- TDD with real projects
- Environment management (rascmdr_local vs RasCommander)

## Formalization Recommendations

For each best practice, suggest:
1. Rule file location (`.claude/rules/`)
2. CLAUDE.md section to update
3. Example code/usage to include
4. Anti-pattern to document
