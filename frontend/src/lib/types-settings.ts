// C04 typed stubs for the Settings page (notifications, vocabulary, data rights).
//
// Wave B is built in parallel. These shapes follow the frozen design (docs/research/wave1/design-risk-first.md §2.1–2.2,
// §7.3, §9.4) and PLAN row B04 (IIP_NOTIFY=off by default; neutral vocabulary by default, U-11). Until the backend routes
// below exist, a failed GET is treated as "off" / "neutral" — the page fails closed and never claims a channel is on.

/** Wave-1 status labels (design-risk-first.md "Status labels and evidence tags"; registry.py SourceStatus). */
export type SourceStatusLabel = "VERIFIED" | "NOT VERIFIED" | "REQUIRES CONFIGURATION" | "BLOCKED";
export const STATUS_LABELS: readonly SourceStatusLabel[] = ["VERIFIED", "NOT VERIFIED", "REQUIRES CONFIGURATION", "BLOCKED"];

/** Provenance licence classes (design-risk-first.md §2.2; USER_OWNED is new there, the rest are registry.py LicenceClass). */
export type LicenceClass = "PERSONAL_USE_ONLY" | "PUBLIC_GOVT" | "LICENSED" | "USER_OWNED" | "UNKNOWN";

/** Notification channels (U-09 / design-risk-first.md §9.4). Email via app password and ntfy.sh public topics are rejected
 * and therefore not part of the type at all. */
export type NotifyChannel = "off" | "webpush" | "telegram";

/** GET /api/settings/notifications (stub; B04 owns notify.py). */
export interface NotificationSettings {
  channel: NotifyChannel;
  /** Channels this server can actually deliver on. "off" is always available. */
  available: NotifyChannel[];
  /** The exact ping text the channel would send (no amounts, scheme names or verbs — B04 sentinel test). */
  ping_template?: string;
}

/** PUT /api/settings/notifications. Telegram needs the explicit acknowledgement that Telegram stores the ping. */
export interface NotificationSettingsIn {
  channel: NotifyChannel;
  acknowledge_third_party_storage: boolean;
}

/** Private-view vocabulary (U-11 / design-risk-first.md §7.3). */
export type VocabularyMode = "neutral" | "badges";

/** GET /api/settings/vocabulary (stub). */
export interface VocabularySettings {
  mode: VocabularyMode;
}

/** PUT /api/settings/vocabulary. Opting in to badges needs the acknowledgement that it is private-view only. */
export interface VocabularySettingsIn {
  mode: VocabularyMode;
  acknowledge_private_only: boolean;
}

/** The decision (PLAN.md §3 U-ids) that unblocks a source, or why none can. */
export interface Unblock {
  /** Decision ids from PLAN.md §3, e.g. ["U-01", "U-17"]; empty when no decision of yours can unblock it. */
  decisions: string[];
  text: string;
}

/** One row of the data-rights panel. */
export interface DataRightsRow {
  id: string;
  name: string;
  feeds: string;
  licence: LicenceClass;
  licence_note: string;
  /** Rendered as plain text, never as a link, for hosts that forbid deep links (RBI disclaimer). */
  terms_url: string | null;
  status: SourceStatusLabel;
  /** Where the status comes from (probe, audit section, registry entry). */
  status_ref: string;
  unblock: Unblock;
  /** True when the row came from the server's live source registry (GET /api/data-health). */
  from_registry: boolean;
}
