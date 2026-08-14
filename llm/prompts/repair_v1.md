---
prompt_id: repair
version: v1
agent: system
model_tier: small
updated_at: 2026-08-01
---
The previous response was supposed to be a single JSON object matching a schema,
and it did not parse or did not validate.

Return only corrected JSON. No explanation, no code fence, no trailing text.
Preserve the original content and meaning; change only what is needed to satisfy
the schema. Do not invent values for fields that had none — use null, an empty
string, or an empty array as the schema allows.

Required schema:
{{schema}}

Validation error:
{{error}}

Original output:
"""
{{output}}
"""
