# ADR-0018: Private wording, surfaces and notifications

Status: **Proposed (2026-10-16), awaiting the owner's acceptance.** The owner decided U-11 (neutral wording) on
2026-10-16; U-09 and U-15 use the PLAN §3 defaults. Built by B04 (compliance guard, notifications), A16 (templates and
linter), C01–C04 (UI). Not legal advice.

## Context

- Personal use falls outside the SEBI RA/IA regimes on a plain reading: both need a person who, "for consideration, is
  engaged in the business of" advising or researching for others (`docs/research/wave1/research-regulation.md` §1, §2).
- "The method does not matter; the audience does." Buy/sell calls from technical analysis are not exempt (RA FAQ 5), and
  a non-personalised recommendation is a "trading call" (§1 items 2–3).
- Anyone who recommends a security "through public media" picks up RA duties (RA Reg. 21(2)).
- There is no family exemption in the RA/IA regulations (§7).
- The existing compliance guard BLOCKs `(buy|sell) now`, `target price` and `stop[- ]?loss` (`regulatory-readiness.md`
  §7). A signal feature needs some action vocabulary.

## Decision

1. **Neutral vocabulary (U-11, decided 2026-10-16).**
   - Policy cards say "your rule says" and use only the verbs redirect, invest, redeem, switch, wait and review.
   - An accepted signal (if one ever exists) says "**entry condition met**" / "**exit condition met**", always next to
     the rule id, version, backtest card and as-of date.
   - No BUY/SELL badges. Never "buy now", "strong buy", "target price", "stop-loss", "recommended for you", "proven" or
     "sure-shot".
   - A template linter rejects forecast language in policy-card text (A16).
2. **Surface-aware compliance guard (B04).** The BLOCK phrases stay blocked on every export, share and unauthenticated
   surface. Inside the logged-in view only the neutral labels above are allowed.
3. **One principal, authenticated surfaces only (U-15 default: only you).** Signals, ranked lists of named securities
   and backtest results exist only behind login, in both modes. No invitations, second users, share links, public view
   toggle or one-click image export. Exports carry a "private, not for distribution" watermark and strip raw AMFI data.
4. **Notifications are pings only (U-09 default: off).** When enabled (Web Push preferred, v2), the only content is
   "IIP: daily report ready (data as of <date>). Open the app." — no ₹ amounts, scheme names, verbs or prices. A
   sentinel test enforces this (B04). ntfy.sh public topics and Gmail app passwords are rejected; Telegram only if the
   owner accepts that Telegram stores the ping.
5. **Disclaimer on every page with cards:** "Personal decision-support tool. Output of rules you configured. Not
   investment advice or research; not registered with SEBI."
6. **No forecast fields on cards.** The ActionCard has no `expected_return` or "probability of profit" field (ADR-0010;
   A16 test). Any optional LLM paraphrase is labelled "AI-generated text", may contain no digits, and never produces or
   alters a number (ADR-0007).
7. **Public repo:** no real signal outputs, backtest results on named securities, screenshots or market-data files; the
   README makes no performance or return claims. Any demo uses synthetic data.

## Consequences

- If a screen ever leaks, it reads as one person's private rule output, not as a call to readers.
- Showing the app to family members is not covered by this ADR; per `research-regulation.md` §7 that needs a lawyer's
  review first.

## Not verified

- Search-engine exclusion (`X-Robots-Tag: noindex`, disallow-all `robots.txt`) on the hosted origin is not shown in the
  current code (`research-regulation.md` §8.1 item 6).
- Whether the s.87A / basic-exemption questions change any tax-card wording (verify BT-10) — CA review.

## Evidence

`docs/research/wave1/research-regulation.md` §1, §7, §8; `design-risk-first.md` §7.3, §9.4;
`design-judgement.md` §2.2 item 11, §2.4; PLAN §3 (U-09, U-11, U-15), §6, §8.
