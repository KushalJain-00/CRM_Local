# Plan — Unified AI provider, prompts & reliability system

Branch: `feat/provider-reliability` (off main @ 8760b31). Baseline: 256 passed, 1 xfailed.

## Phase A — Audit (done)
- Production AI path: `llm.py` (EML only, compact prompt, [1,2] backoff, chain failover, `test_entry`).
- `services/prompts/contact_extraction.py` + `services/contract.py` = master prompt + crm-extraction.v1 gate (spec-stage; `build_prompt` not yet consumed by production).
- `api/settings.py`: masked chain, write-only keys; latent bug: `ProviderIn` lacks `api_key` (add_provider crashes).
- DB: unified `crm.db`, mig train v10 gated by CRM_APPLY_MIGRATIONS=1, `extraction_runs`/`processed_files` exist. No schema change needed for this task (reliability + prompts go in config.json).
- Preserve: SEC-01 masking, D-007 local-wins, D-011 settings-only surface, D-028/29/30, SEC-10 caps, eml_processor byte-mirror (file NOT modified).

## Phase B — providers.py (new)
- `PROVIDERS` registry: openai, openrouter, groq, gemini, anthropic, deepseek, ollama + `custom` (OpenAI-compatible generic incl. LM Studio/vLLM/Mistral/xAI/together via base_url).
- Protocol-per-provider request build/response parse; error classification (transient / permanent / output); `list_models` discovery per provider; no credentials hardcoded.

## Phase C — llm.py engine
- Public API kept: `extract(chain, prompt)` + `test_entry`; gains optional `system=`, `reliability=` params.
- Bounded retries + exp backoff + jitter + Retry-After; total deadline; output-repair (1 attempt, feedback = validation errors); failover strictly in chain order; in-memory circuit breaker; aggregate error report (no keys); `llm.LAST_RUN` diagnostics.

## Phase D — prompts store (`services/prompts/store.py`)
- Two kinds: `contact`, `eml`. Defaults: contact = MASTER_SYSTEM_PROMPT (+ source extensions per type); eml = current llm.SYSTEM_PROMPT contract.
- Stored in config.json `prompts.{kind}` (text/null=use default, updated_at, default_version). Validation: non-empty + required contract markers. API: GET/PUT /api/prompts/{kind}, POST /api/prompts/{kind}/reset, GET /api/prompts.

## Phase E — Settings UI
- Sections: AI Providers & Models (provider select from catalog, base URL, model dropdown + refresh + manual entry, masked key, Test button w/ result, enable, reorder), Reliability (timeout/attempts/backoff/max/deadline/repair/cooldown), Prompts ×2 editors.

## Phase F — Integration
- `intake.py` + `pipeline.py` EML paths pass configured EML prompt + reliability.
- `pipeline._process_doc`: when header mapping confidence is low and chain configured → one contact-prompt AI assist, gated by `validate_extraction_result`.
- Fix `ProviderIn.api_key` bug (500 → 422-free behavior).

## Phase G/H — Tests & verification
- tests/test_providers.py, tests/test_llm_failover.py, tests/test_prompts_store.py, additions to settings API tests. Mocked HTTP only.
- Full suite green; manual API smoke (uvicorn) for UI verify; Windows build unchanged (no new deps).
