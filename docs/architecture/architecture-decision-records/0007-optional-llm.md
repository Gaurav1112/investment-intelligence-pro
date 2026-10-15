# ADR-0007: Optional LLM adapter

## Decision
- The LLM is **off by default**. The application is complete without it.
- When enabled, it uses a single OpenAI-compatible chat-completions adapter configured by `llm.base_url`, `llm.model` and `llm.api_key_env`.
- Provider classes:
  - `local`: Ollama, LM Studio or llama.cpp on 127.0.0.1. Preferred.
  - `free_cloud`: opt-in per provider. Candidates are listed in `open-free-llm-api/awesome-freellm-apis`.
- Cloud providers receive only a **redacted evidence packet**: public instrument facts and engine outputs. They never receive amounts, holdings, tax profile or identity.
- Temperature 0, a seed where the provider supports one, and responses memoised by prompt hash.
- Output must pass the numeric validator and the Compliance Guard (banned phrases). On any failure, the deterministic template is shown.
- AI-use disclosure is shown whenever LLM text is displayed.

## Evidence
User memory: vendor-neutral, no paid keys. requirements.md A6. threat-model.md (LLM boundary). regulatory-readiness.md (AI-use disclosure).
