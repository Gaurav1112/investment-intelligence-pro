import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { LlmStatus } from "../lib/types-llm";
import { LlmSettings, MODE_PRIVACY } from "./LlmSettings";

// Shapes follow backend/src/iip/api/routes_llm.py status() and put_config().
type Call = { url: string; method: string; body: unknown };
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });

const PROVIDERS = [
  { id: "groq", name: "Groq", base_url: "https://api.groq.com/openai/v1", data_use_note: "May train on prompts — redacted packet only.", data_use_status: "NOT VERIFIED — check provider terms", url_verification: "VERIFIED 2026-10-15 against the official docs" },
  { id: "mistral", name: "Mistral", base_url: "https://api.mistral.ai/v1", data_use_note: "May train on prompts — redacted packet only.", data_use_status: "NOT VERIFIED — check provider terms", url_verification: "VERIFIED 2026-10-15 against the official docs" },
];
const OFF: LlmStatus = {
  mode: "off", base_url: "", model: "", api_key_env: "", config_source: "env", api_key_present: false, provider: null,
  privacy_note: "Off.", config_error: null, last_error: null, rejected_count: 0, calls: 0, cache_hits: 0,
  default_local_url: "http://127.0.0.1:11434/v1", providers: PROVIDERS, probe: null,
};

function stubFetch(handler: (url: string, method: string, body: unknown) => Response) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      calls.push({ url, method, body });
      return handler(url, method, body);
    }),
  );
  return calls;
}
afterEach(() => vi.unstubAllGlobals());

describe("Optional AI wording settings", () => {
  it("defaults to off with the no-AI privacy text and no key input", async () => {
    stubFetch(() => json(OFF));
    render(<LlmSettings />);
    expect(await screen.findByRole("radio", { name: /Off — deterministic wording only/ })).toBeChecked();
    expect(screen.getByTestId("llm-privacy")).toHaveTextContent(MODE_PRIVACY.off);
    expect(screen.queryByLabelText(/Model/)).toBeNull();
    expect(document.querySelector('input[type="password"]')).toBeNull();
  });

  it("saves a local config with the loopback default and shows local privacy text", async () => {
    const calls = stubFetch((url, method) => (method === "PUT" ? json({ status: "saved" }) : json(OFF)));
    render(<LlmSettings />);
    await userEvent.click(await screen.findByRole("radio", { name: /Local model/ }));
    expect(screen.getByTestId("llm-privacy")).toHaveTextContent("never leave this machine");
    expect(screen.getByLabelText(/Base URL/)).toHaveValue("http://127.0.0.1:11434/v1");
    await userEvent.type(screen.getByLabelText("Model"), "llama3.2:3b");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.url).toBe("/api/llm/config");
    expect(put.body).toEqual({ mode: "local", base_url: "http://127.0.0.1:11434/v1", model: "llama3.2:3b", api_key_env: "" });
    expect(await screen.findByText(/Saved\. New Discovery runs/)).toBeInTheDocument();
  });

  it("cloud mode picks from the allowlist, shows the data-use note, and asks only for the env var NAME", async () => {
    const calls = stubFetch((url, method) => (method === "PUT" ? json({ status: "saved" }) : json(OFF)));
    render(<LlmSettings />);
    await userEvent.click(await screen.findByRole("radio", { name: /Free-tier cloud/ }));
    expect(screen.getByTestId("llm-privacy")).toHaveTextContent("Only a redacted packet is sent");
    await userEvent.selectOptions(screen.getByLabelText(/Provider/), "Mistral");
    expect(screen.getByText("https://api.mistral.ai/v1")).toBeInTheDocument();
    expect(screen.getByText("NOT VERIFIED — check provider terms")).toBeInTheDocument();
    expect(screen.getByText(/May train on prompts/)).toBeInTheDocument();
    expect(screen.getByLabelText(/API-key environment variable name/)).toHaveAttribute("placeholder", "e.g. GROQ_API_KEY");
    await userEvent.type(screen.getByLabelText("Model"), "mistral-small");
    await userEvent.type(screen.getByLabelText(/API-key environment variable name/), "MISTRAL_API_KEY");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({
      mode: "cloud", base_url: "https://api.mistral.ai/v1", model: "mistral-small", api_key_env: "MISTRAL_API_KEY",
    });
  });

  it("shows the backend's refusal when a config is rejected", async () => {
    stubFetch((url, method) =>
      method === "PUT" ? json({ code: "LLM_CONFIG_INVALID", message: "local LLM host '192.168.1.10' is not a loopback address" }, 422) : json(OFF),
    );
    render(<LlmSettings />);
    await userEvent.click(await screen.findByRole("radio", { name: /Local model/ }));
    const base = screen.getByLabelText(/Base URL/);
    await userEvent.clear(base);
    await userEvent.type(base, "http://192.168.1.10:11434/v1");
    await userEvent.type(screen.getByLabelText("Model"), "m");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Not saved\. .*not a loopback address/);
  });

  it("test connection uses the status endpoint's probe", async () => {
    const local = { ...OFF, mode: "local" as const, base_url: "http://127.0.0.1:11434/v1", model: "llama3.2:3b", config_source: "saved" as const };
    const calls = stubFetch((url) =>
      url.includes("probe=1") ? json({ ...local, probe: { ok: true, model_listed: true, detail: "reachable; model listed" } }) : json(local),
    );
    render(<LlmSettings />);
    await userEvent.click(await screen.findByRole("button", { name: "Test connection" }));
    expect(await screen.findByText("Connection OK: reachable; model listed")).toBeInTheDocument();
    expect(calls.map((c) => c.url)).toContain("/api/llm/status?probe=1");
  });

  it("degrades quietly when the status endpoint is unavailable", async () => {
    stubFetch(() => json({ code: "NOT_FOUND" }, 404));
    render(<LlmSettings />);
    expect(await screen.findByText(/AI wording settings are unavailable/)).toBeInTheDocument();
  });
});
