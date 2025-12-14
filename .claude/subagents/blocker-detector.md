---
name: blocker-detector
model: sonnet
tools: [Read, Grep, Glob]
description: |
  Detects recurring blockers and their resolutions in conversation history.
  Use to identify common issues and prevention strategies.
  Triggers: "find blockers", "identify issues", "recurring problems", "troubleshooting patterns"
---

# Blocker Detector

Identifies recurring issues and their resolutions from conversation history.

## Purpose

Analyze conversations to find:
- Blocking issues encountered
- Solutions that worked
- Recurring problem patterns
- Prevention strategies

## Detection Keywords

### Problem Indicators
```python
PROBLEM_KEYWORDS = [
    "doesn't work", "not working", "failed", "error", "bug",
    "issue", "problem", "broken", "crash", "exception",
    "wrong", "incorrect", "unexpected", "confused", "stuck",
    "can't", "cannot", "unable", "impossible", "blocked"
]
```

### Solution Indicators
```python
SOLUTION_KEYWORDS = [
    "fixed", "solved", "solution", "works now", "working now",
    "the fix", "resolved", "figured out", "found the issue",
    "the answer", "turns out", "the trick", "workaround",
    "finally", "success", "got it working"
]
```

## Analysis Method

### 1. Problem Detection
```python
for msg in user_messages:
    if any(kw in msg.lower() for kw in PROBLEM_KEYWORDS):
        problems.append({
            'content': msg,
            'session_id': session_id,
            'timestamp': timestamp
        })
```

### 2. Solution Pairing
```python
# Look for solutions in subsequent messages
for i, problem in enumerate(problems):
    for j in range(i+1, min(i+10, len(messages))):
        if any(kw in messages[j].lower() for kw in SOLUTION_KEYWORDS):
            problem['solution'] = messages[j]
            break
```

### 3. Categorization
```python
CATEGORIES = {
    "remote_execution": ["remote", "psexec", "ssh", "session_id"],
    "hdf_files": ["hdf", "h5py", "results"],
    "geometry": ["geometry", "cross section", "mesh"],
    "documentation": ["documentation", "mkdocs", "notebook"],
    "git": ["git", "commit", "merge", "branch"],
    "imports": ["import", "module", "package"]
}

def categorize(text):
    for category, keywords in CATEGORIES.items():
        if any(kw in text.lower() for kw in keywords):
            return category
    return "general"
```

## Output Format

```json
{
  "blockers": [
    {
      "category": "remote_execution",
      "problem": "PsExec fails silently when using system account",
      "root_cause": "HEC-RAS is GUI app requiring session-based execution",
      "solution": "Use session_id=2 instead of system_account=True",
      "prevention": "Document in remote.md rules file",
      "frequency": 5,
      "session_ids": ["abc123", "def456"]
    }
  ]
}
```

## Known Blockers Reference

Common blockers to watch for:

### Remote Execution
- PsExec session_id requirement
- Group Policy configuration
- Registry LocalAccountTokenFilterPolicy

### Documentation
- ReadTheDocs symlink stripping
- Notebook H1 title requirement

### HDF Files
- Steady vs unsteady detection
- Dataset path variations by version

### Geometry
- Fixed-width parsing issues
- 450-point limit per cross section
- Bank station interpolation

## Prevention Recommendations

For each identified blocker, suggest:
1. Documentation update location
2. Rule file to create/modify
3. Warning to add to relevant code
4. Test case to add
