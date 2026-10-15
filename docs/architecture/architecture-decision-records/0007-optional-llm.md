# ADR-0007: Optional LLM adapter

## Status
**Implemented** (2026-10-15). `backend/src/iip/llm/` (adapter, config, prompt, providers), `backend/src/iip/api/routes_llm.py`,
Settings → "Optional AI wording", and the Discovery "AI-generated wording" label. Tests: `tests/security/test_llm_boundary.py`
(SEC-70…76) and `tests/api/test_llm_api.py`. Not verified against a live model: no local server was running when it was built.

## Decision
- The LLM is **off by default**. The application is complete without it.
- When enabled, it uses a single OpenAI-compatible chat-completions adapter (plain `httpx`, no vendor SDK) configured by
  `IIP_LLM=off|local|cloud`, `IIP_LLM_BASE_URL`, `IIP_LLM_MODEL` and `IIP_LLM_API_KEY_ENV` (the **name** of an env var holding a
  key; the key itself is never in configuration or the database). A configuration saved from Settings (`settings` key `llm.config`)
  overrides the env.
- Provider classes:
  - `local`: Ollama, LM Studio or llama.cpp on 127.0.0.1. Preferred. The base URL's host must be a loopback literal, `localhost`, or a
    name that resolves **only** to loopback addresses; otherwise startup is refused (SEC-75). The resolution is re-checked before every
    call, proxy env vars are ignored (`trust_env=False`) and redirects are not followed.
  - `cloud` (free tier): explicit opt-in, and the base URL must exactly match a **code-defined allowlist** (`llm/providers.py`): Groq,
    Google Gemini (OpenAI-compatible endpoint), Mistral, Cerebras, OpenRouter, NVIDIA NIM. Every base URL was checked against the
    provider's official docs on 2026-10-15. Each entry records the data-use note "May train on prompts — redacted packet only" and a
    data-use status of "NOT VERIFIED — check provider terms": terms were not reviewed and must be checked by the user.
- Cloud providers receive only a **redacted packet**: the rendered claim lines and two fixed disclosures. Any line containing a
  rupee amount, a lakh/crore figure, a date, the user's amount or withdrawal date, or a tax-slab/holding reference is **held back**:
  it is never sent and is shown verbatim from the template. Exclusion was chosen over placeholders because models mangle, reorder or
  drop placeholder tokens, which could silently attach a sentence to the wrong figure, and a substitution table is a second path for
  personal values. Local mode sends all claim lines (they never leave the machine). Neither mode ever sends holdings, the tax profile,
  the access token, env values or file paths (SEC-74).
- Temperature 0, a seed where the provider documents one (`seed`, or Mistral's `random_seed`; none for Gemini and NVIDIA), `max_tokens`
  600, a 60 s timeout (5 s connect), one call at a time, and replies memoised by prompt hash in the settings table
  (`llm.cache:<sha256>`; erased by "Erase all my data").
- No tools or function calling. A reply with a tool-call structure, markup, links, oversize output, a truncated finish, an
  instrument name not present in the input, or numbering that does not match the input lines is rejected (SEC-73).
- Output must then pass the numeric validator and the Compliance Guard (banned phrases). On any failure — including timeout,
  connection refused and non-200 — the deterministic template is shown, the request still succeeds, and the report carries
  `writer: "template"` with a `rejected_llm_reasons` entry (SEC-76). `GET /api/llm/status` shows the last reason and a rejection count.
- The ranking is computed before the LLM is called. `run.ranking_hash` (everything except the LLM wording, writer and AI disclosure)
  is identical with and without the LLM (SEC-70).
- AI-use disclosure is shown whenever LLM text is displayed, with an "AI-generated wording" label and a toggle to the deterministic text.

## Evidence
User memory: vendor-neutral, no paid keys. requirements.md A6. threat-model.md (LLM boundary). regulatory-readiness.md (AI-use disclosure).
