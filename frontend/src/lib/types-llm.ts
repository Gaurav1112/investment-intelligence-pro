// Optional AI wording (ADR-0007). Shapes mirror backend/src/iip/api/routes_llm.py and the Discovery report fields
// added by services/discovery.py. Kept apart from lib/types.ts so parallel tracks do not collide.

export type LlmMode = "off" | "local" | "cloud";

export interface LlmProviderEntry {
  id: string;
  name: string;
  base_url: string;
  data_use_note: string;
  data_use_status: string;
  url_verification: string;
}

export interface LlmProbe {
  ok: boolean;
  model_listed?: boolean;
  detail: string;
}

export interface LlmStatus {
  mode: LlmMode;
  base_url: string;
  model: string;
  api_key_env: string;
  config_source: "env" | "saved";
  api_key_present: boolean;
  provider: {
    id: string;
    name: string;
    data_use_note: string;
    data_use_status: string;
    url_verification: string;
    docs_url: string;
  } | null;
  privacy_note: string;
  config_error: string | null;
  last_error: string | null;
  rejected_count: number;
  calls: number;
  cache_hits: number;
  default_local_url: string;
  providers: LlmProviderEntry[];
  probe: LlmProbe | null;
}

/** PUT /api/llm/config body. There is deliberately no field for a key: only the NAME of an env var. */
export interface LlmConfigIn {
  mode: LlmMode;
  base_url: string;
  model: string;
  api_key_env: string;
}

/** The report fields the wording layer adds (present on every Discovery report). */
export interface LlmReportFields {
  narrative: string;
  writer: string; // "template" | "llm"
  template_narrative?: string;
  rejected_llm_reasons?: string[];
  disclosures: string[];
}
