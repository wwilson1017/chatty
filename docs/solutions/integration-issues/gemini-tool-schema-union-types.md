---
title: Gemini SDK crashes on JSON Schema union types in tool input_schema
date: 2026-07-02
category: integration-issues
module: core/providers/google_provider.py
tags: [gemini, tool-calling, json-schema, function-declaration, multi-provider]
problem_type: integration_bug
---

## Problem

Chatty tool `input_schema` definitions are plain JSON Schema consumed by five
providers. The Workspace Sheets tools used a union type for cell values —
`{"type": ["string", "number", "boolean", "null"]}` — which is valid JSON
Schema but crashes the classic `google.generativeai` SDK, breaking tool
registration for every agent on the Gemini provider.

## Symptoms

```
AttributeError: 'list' object has no attribute 'upper'
```

raised while constructing `FunctionDeclaration(parameters=...)`. Because tool
formatting happens once per turn, one bad schema kills ALL tools for the turn,
not just the offending one. Anthropic/OpenAI/Ollama/Together accept the same
schema fine, so the bug is invisible unless Gemini is the active provider.

## What Didn't Work

- `anyOf` (the OpenAPI 3.0-correct spelling): the classic SDK's Schema proto
  rejects it — `ValueError: Unknown field for Schema: anyOf`.
- Changing the tool definitions themselves to a single type: loses accurate
  typing for the four providers that handle union types correctly.

## Solution

Normalize at the provider boundary. `_clean_schema()` in
`core/providers/google_provider.py` (the existing Gemini-specific sanitizer
every tool schema routes through) collapses union types:

```python
if isinstance(result.get("type"), list):
    types = [t for t in result["type"] if t != "null"]
    result["type"] = types[0] if types else "string"
    if len(types) != len(schema["type"]):
        result["nullable"] = True
```

`["string", "number", "boolean", "null"]` → `type: "string", nullable: true`.
Gemini's proto has a single-enum `type` plus a `nullable` bool; it does not
validate call args against the schema strictly, so the first-concrete-type
approximation is safe guidance.

Verified empirically by constructing `FunctionDeclaration` for all 94 tool
schemas after cleaning (0 failures). Regression tests: `tests/test_gemini_schema.py`,
including a recursive sweep asserting no type lists survive cleaning of
`WORKSPACE_WRITE_TOOLS`.

## Why This Works

The Schema proto's `type` field is a single enum (`Type.STRING`, …); the SDK
calls `.upper()` on the value during dict→proto conversion, so a list crashes.
Handling it in `_clean_schema` fixes every current and future union-typed tool
in one place while `tool_definitions.py` stays valid JSON Schema for the other
providers.

## Prevention

When adding a tool `input_schema` using JSON Schema constructs beyond basic
single-typed properties (union `type` lists, `anyOf`, `additionalProperties`,
`default`, `examples`), confirm `_clean_schema` normalizes or strips the
construct, and smoke-test with
`FunctionDeclaration(parameters=_clean_schema(schema))`.
