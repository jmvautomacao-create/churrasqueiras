---
name: implementation-strategy
description: Plan and structure implementation work by breaking down features, evaluating tradeoffs, and defining clear execution steps before writing code
---

# Implementation Strategy

## Overview

Before writing any code, define a clear implementation strategy that minimizes rework, surfaces tradeoffs early, and produces a predictable execution path.

## When to Use

- A new feature or significant change is requested
- The implementation requires touching multiple files or systems
- There are multiple valid approaches and a decision is needed
- The work spans more than ~50 lines of code across 2+ files

## Workflow

### 1. Understand the goal

- What is the desired end state (not the implementation)?
- What existing behavior must be preserved?
- What are the non-negotiable constraints (performance, security, compatibility)?

### 2. Surface the landscape

- Which files exist today that are relevant? Read them.
- What patterns are already used (libraries, conventions, styles)?
- Are there existing tests or test patterns to follow?

### 3. Generate options

For each plausible approach, briefly describe:
- Approach: high-level strategy
- Tradeoffs: complexity, risk, maintenance burden, performance
- Files touched: which files would change

### 4. Select and refine

- Choose the approach that minimizes risk while meeting constraints
- Break the work into ordered, independently verifiable steps
- Each step should produce a working state (no partial breakage)

### 5. Execute in order

Implement each step, verifying before moving to the next:
- Does it work as expected?
- Are existing behaviors preserved?
- Does the test suite still pass?

### 6. Review and validate

- Does the implementation match the plan?
- Are there edge cases the plan missed?
- Update the plan if new information emerged during implementation

## Output

Before starting implementation, produce a structured plan:

```markdown
## Implementation Plan

**Goal:** <one-sentence description>

**Approach:** <chosen strategy>

**Steps:**
1. <verifiable step>
2. <verifiable step>
...

**Files to modify:**
- <path>: <what changes>
- <path>: <what changes>

**Risks:**
- <risk and mitigation>
```

## Anti-patterns

- Starting implementation without reading the relevant existing code
- Choosing the first approach that comes to mind without considering alternatives
- Planning at a granularity that doesn't correspond to verifiable states
- Ignoring existing conventions (the codebase has a style, follow it)
- Over-planning trivial changes that could be implemented directly
