---
name: Feature Request
about: Suggest a new feature or enhancement
title: "[Feature] "
labels: enhancement
---

## Problem or Use Case

<!-- What problem does this solve? What workflow does it enable? -->

## Source Workflow

<!-- Which repo or workflow exposed this gap? Example: ras-agent watershed-to-geometry integration -->

## Why This Belongs In `ras-commander`

<!-- Explain the reusable HEC-RAS project/geometry/execution value of landing this here -->

## Proposed Solution

<!-- How should it work? Include API design if you have ideas -->

```python
# Example of how the feature would be used
from ras_commander import NewFeature

result = NewFeature.do_something(plan_number="01", ras_object=ras)
```

## Alternatives Considered

<!-- Other approaches you've thought about -->

## Downstream Impact

<!-- Which repos or workflows are blocked or enabled by this? Include issue links when relevant -->

## Additional Context

<!-- Related HEC-RAS features, example projects, references, etc. -->

---

> **Tip**: Consider prototyping with your LLM agent. Clone the repo, have your agent read the [style guide](../CONTRIBUTING.md) and `AGENTS.md` files, and submit a PR with a working implementation. We welcome LLM-assisted contributions.
