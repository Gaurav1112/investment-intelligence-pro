import { useEffect, useState, type FormEvent } from "react";
import { api } from "../lib/api";
import type { LlmConfigIn, LlmMode, LlmProbe, LlmStatus } from "../lib/types-llm";
import { useApi } from "../lib/useApi";
import { apiMessage } from "../pages/Watchlist";
import "../styles/llm.css";

export const MODE_PRIVACY: Record<LlmMode, string> = {
  off: "Off (default). Nothing is sent to any AI service. Every sentence and number comes from the deterministic engine and dated sources.",
  local:
    "A model running on this computer (Ollama, LM Studio or llama.cpp at 127.0.0.1). The rendered sentences — which can include your amount — go to that local model only and never leave this machine. Any other address is refused.",
  cloud:
    "A free-tier cloud provider from a fixed allowlist. Only a redacted packet is sent: sentences containing a rupee amount, a date, your amount or tax details are held back and shown unchanged. Free tiers may train on prompts. Holdings, tax profile, the access token and file paths are never sent.",
};

const MODE_LABEL: Record<LlmMode, string> = {
  off: "Off — deterministic wording only",
  local: "Local model on this computer",
  cloud: "Free-tier cloud provider (redacted)",
};

/** "Optional AI wording" section of Settings. The model only rewords sentences; it never produces a number. */
export function LlmSettings() {
  const status = useApi<LlmStatus>("/api/llm/status");
  const [form, setForm] = useState<LlmConfigIn>({ mode: "off", base_url: "", model: "", api_key_env: "" });
  const [saved, setSaved] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [probe, setProbe] = useState<LlmProbe | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    const s = status.data;
    if (s) setForm({ mode: s.mode, base_url: s.base_url, model: s.model, api_key_env: s.api_key_env });
  }, [status.data]);

  if (status.loading) return <p className="subtle">Loading AI wording settings…</p>;
  if (status.error || !status.data)
    return (
      <p className="small subtle" role="status">
        AI wording settings are unavailable ({apiMessage(status.error)}). The app works fully without them.
      </p>
    );
  const s = status.data;

  function setMode(mode: LlmMode) {
    setSaved(null);
    setProbe(null);
    setForm((f) => {
      if (mode === "local" && !f.base_url.startsWith("http://127.") && !f.base_url.includes("localhost"))
        return { ...f, mode, base_url: s.default_local_url };
      if (mode === "cloud" && !s.providers.some((p) => p.base_url === f.base_url))
        return { ...f, mode, base_url: s.providers[0]?.base_url ?? "" };
      return { ...f, mode };
    });
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setErr(null);
    setSaved(null);
    try {
      await api("/api/llm/config", { method: "PUT", body: form });
      setSaved(form.mode === "off" ? "Saved. AI wording is off." : "Saved. New Discovery runs will try the AI wording.");
      status.reload();
    } catch (ex) {
      setErr(`Not saved. ${apiMessage(ex)}`);
    } finally {
      setPending(false);
    }
  }

  async function test() {
    setPending(true);
    setProbe(null);
    setErr(null);
    try {
      const r = await api<LlmStatus>("/api/llm/status?probe=1");
      setProbe(r.probe ?? { ok: false, detail: r.config_error ?? "AI wording is off — save a local or cloud setting first" });
    } catch (ex) {
      setProbe({ ok: false, detail: apiMessage(ex) });
    } finally {
      setPending(false);
    }
  }

  const provider = s.providers.find((p) => p.base_url === form.base_url);
  return (
    <form className="card" onSubmit={save} noValidate aria-labelledby="llm-title">
      <h2 id="llm-title">Optional AI wording</h2>
      <p className="small">
        A language model can reword the analysis sentences in plainer English. It never ranks, scores or produces a number: its
        text is checked against the engine's facts and replaced by the deterministic wording if anything is added or changed.
      </p>
      <fieldset className="llm-modes">
        <legend>Mode</legend>
        {(["off", "local", "cloud"] as const).map((m) => (
          <label key={m} className="choice">
            <input type="radio" name="llm-mode" value={m} checked={form.mode === m} onChange={() => setMode(m)} /> {MODE_LABEL[m]}
          </label>
        ))}
      </fieldset>
      <p className="callout small llm-privacy" data-testid="llm-privacy">
        {MODE_PRIVACY[form.mode]}
      </p>

      {form.mode === "local" ? (
        <div className="field">
          <label htmlFor="llm-base">Base URL (loopback only)</label>
          <input id="llm-base" className="input-wide" value={form.base_url} spellCheck={false}
            onChange={(e) => setForm({ ...form, base_url: e.target.value })} aria-describedby="llm-base-hint" />
          <div id="llm-base-hint" className="hint">
            OpenAI-compatible endpoint, e.g. {s.default_local_url} (Ollama) or http://127.0.0.1:1234/v1 (LM Studio).
          </div>
        </div>
      ) : null}

      {form.mode === "cloud" ? (
        <div className="field">
          <label htmlFor="llm-provider">Provider (allowlist)</label>
          <select id="llm-provider" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })}>
            {s.providers.map((p) => (
              <option key={p.id} value={p.base_url}>
                {p.name}
              </option>
            ))}
          </select>
          {provider ? (
            <dl className="kv small">
              <dt>Endpoint</dt>
              <dd className="mono break">{provider.base_url}</dd>
              <dt>URL check</dt>
              <dd>{provider.url_verification}</dd>
              <dt>Data use</dt>
              <dd>
                {provider.data_use_note} <strong>{provider.data_use_status}</strong>
              </dd>
            </dl>
          ) : null}
        </div>
      ) : null}

      {form.mode !== "off" ? (
        <>
          <div className="field">
            <label htmlFor="llm-model">Model</label>
            <input id="llm-model" value={form.model} spellCheck={false} onChange={(e) => setForm({ ...form, model: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="llm-keyenv">API-key environment variable name {form.mode === "local" ? "(optional)" : ""}</label>
            <input id="llm-keyenv" value={form.api_key_env} spellCheck={false} autoComplete="off" placeholder="e.g. GROQ_API_KEY"
              onChange={(e) => setForm({ ...form, api_key_env: e.target.value })} aria-describedby="llm-keyenv-hint" />
            <div id="llm-keyenv-hint" className="hint">
              The NAME of an environment variable set before starting the app — never the key itself. The key is read at call time
              and is not stored. {s.api_key_env && s.api_key_env === form.api_key_env ? (s.api_key_present ? "It is set." : "It is not set.") : ""}
            </div>
          </div>
        </>
      ) : null}

      <div className="llm-actions">
        <button type="submit" className="btn" disabled={pending}>
          Save
        </button>
        <button type="button" className="btn" onClick={test} disabled={pending}>
          Test connection
        </button>
      </div>
      <div role="status" aria-live="polite">
        {saved ? <p className="small">{saved}</p> : null}
        {probe ? (
          <p className={`small${probe.ok ? "" : " callout callout--warn"}`}>
            {probe.ok ? "Connection OK" : "Connection failed"}: {probe.detail}
          </p>
        ) : null}
      </div>
      {err ? (
        <p className="callout callout--stale" role="alert">
          {err}
        </p>
      ) : null}
      <dl className="kv small llm-status">
        <dt>Active</dt>
        <dd>
          {s.mode}
          {s.model ? ` · ${s.model}` : ""} ({s.config_source === "saved" ? "saved here" : "from environment"})
        </dd>
        {s.config_error ? (
          <>
            <dt>Configuration problem</dt>
            <dd>{s.config_error}</dd>
          </>
        ) : null}
        {s.last_error ? (
          <>
            <dt>Last fallback reason</dt>
            <dd className="mono break">{s.last_error}</dd>
          </>
        ) : null}
        <dt>Rejected AI texts</dt>
        <dd>{s.rejected_count}</dd>
      </dl>
    </form>
  );
}
