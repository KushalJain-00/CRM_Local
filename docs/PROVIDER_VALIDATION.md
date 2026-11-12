# Provider validation — release 1.0.0

## Verified by automated tests (this build)

Suite: 332 passed, 1 xfailed (`pytest tests/ -q`). Provider coverage:

- `tests/test_providers.py` (16 tests) — registry completeness, request
  shapes per protocol (openai/openrouter/groq/deepseek via openai protocol,
  gemini, anthropic, ollama, custom), model discovery URL + parsing,
  Anthropic version header, Gemini model-name guard, transient-vs-permanent
  HTTP classification, network classification, no fabricated metadata.
- `tests/test_llm_failover.py` (19 tests) — priority order respected,
  disabled entries never called, transient retries with backoff+jitter,
  Retry-After honoured, overall deadline enforced, failover on failure,
  circuit breaker opens after repeated failures and recovers, malformed JSON
  repair attempt, aggregate diagnostics with credential redaction.
- `tests/test_llm_validation.py` (8 tests) — contract validation of model
  output: valid payloads accepted; schema/contract/BANNED_DB_KEYS violations
  rejected; `contact_indices` scope; missing evidence; malformed types.
- `tests/test_chunking.py` (6 tests) — multi-chunk merge, dedup, conflict
  preservation, total-failure degradation.

**These are mocked protocol tests. No live provider call was made.**
Live validation is **NOT VERIFIED**.

## How to validate a live provider (owner procedure, ~5 minutes per provider)

Prerequisite: a real API key for the provider and the CRM Local app running.

1. Settings → AI providers → Add provider → select the provider.
2. Paste the key; press **Test** (makes one minimal real request; the key
   never appears in any response).
3. Press **Discover models**; pick a current model from the returned list
   (or type one manually).
4. Save; enable it; keep other providers disabled for an isolated check.
5. Extract → import a small PDF or CSV with 1–2 contacts.
6. Staged review: confirm rows appear and values look right.
7. Settings → Prompts → save a deliberately invalid prompt (delete the
   contract markers) — it must be rejected; valid custom prompt must save.
8. Record the result in the table below and keep `config.json` private.

## Result record (owner to complete)

| Provider | Model | Test (pass/fail) | Extraction OK | Notes |
|---|---|---|---|---|
| OpenAI | | | | |
| OpenRouter | | | | |
| Groq | | | | |
| Gemini | | | | |
| Anthropic | | | | |
| DeepSeek | | | | |
| Ollama (local) | | | | |
| Custom endpoint | | | | |

If any provider fails at step 6 while Test + Discover succeed, the issue is
prompt/contract-related, not credentials — capture the staged warnings
verbatim and file a support issue with the file attached (never with the
key).

## Error-handling contract (what you should observe on failure)

- Dead endpoint → extraction proceeds on deterministic Layer-1; warnings
  list the failure (visible in History and the import result). No 5xx.
- Invalid key (401/403) → not retried; permanent classification; failover to
  the next enabled provider.
- Rate limit (429) → retried within limits, honoring Retry-After.
- Provider returns garbage → one controlled repair attempt, then rejected;
  deterministic results retained; never partially accepted.
