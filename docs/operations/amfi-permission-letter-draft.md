# DRAFT — letter to AMFI asking permission for private hosted storage of NAV data (decisions U-01, U-17)

**Status: DRAFT. Not sent.** The owner reviews it, fills every `[placeholder]`, and sends it himself, if he chooses
to. No agent or script sends it. Until AMFI answers in writing, the app stays local-first (ADR-0017): the hosted copy
stores only rows for schemes the owner holds or watches.

**Before sending, check (NOT VERIFIED in this repo):**
- the correct AMFI contact for data or website-terms permissions — look it up on https://www.amfiindia.com (contact
  page); no address or email is assumed here;
- that the quoted terms still read the same at https://www.amfiindia.com/terms-of-use (quotes below were read on
  2026-10-15, `docs/data/source-registry.md` §2.1);
- the counts in `[brackets]`, from your own app, not from this draft.

Keep a copy of what you send and of any reply. Add the reply date and outcome to `docs/product/decisions-register.md`.
Do not attach screenshots of data, scheme names or your holdings; the request does not need them.

---

[Your full name]
[Your postal address]
[Your email address]
[Date]

To: [AMFI contact — name/department, from the AMFI website]
Association of Mutual Funds in India
[AMFI address, from the AMFI website]

**Subject: Request for permission — private, non-commercial storage of NAV data in a personal cloud database**

Dear Sir/Madam,

I am an individual investor in Indian mutual funds. For my own use only, I have written a small personal application
that helps me track my own mutual-fund holdings and check them against rules I set for myself (asset allocation,
emergency fund, tax timing). It is not offered to anyone else, has no other users, carries no advertising and earns
no money.

The application reads the daily NAV file and NAV history published on the AMFI website. I have read your Terms of Use,
which grant a right to use the site "for your personal and non-commercial use only" and say: "You shall not store
electronically any significant portion of any part of the Site", and that users may not "create derivative works".

To stay within these terms, the application currently works as follows:

1. On my own computer, it keeps NAVs for the schemes I hold or watch, plus a small fixed list of about
   [number, at most 30] broad index and debt schemes I use for comparison.
2. A private copy of the application runs on a personal cloud account (a hosting service and a database service) so
   that I can read it on my phone. That copy stores NAVs **only** for the [number] schemes I hold or watch. It is
   protected by a login that only I have, and it is not indexed or shared.
3. It fetches the daily NAV file at most [a few] times a day, identifies itself honestly, and does not republish,
   display publicly or redistribute any AMFI data.

I would be grateful if you could confirm in writing whether:

(a) storing, in my private cloud database, the NAV history of the schemes I hold or watch (about [number] schemes),
    for my personal and non-commercial use, is acceptable under your Terms of Use; and
(b) storing in the same private cloud database the NAV history of the small comparison list described in point 1
    (about [number] schemes) would also be acceptable.

If either is not acceptable, I will keep that data only on my own computer, as I do now. If AMFI offers a licence or
a preferred method of access for individuals, I would be glad to know of it.

Thank you for publishing this data and for your time.

Yours faithfully,

[Your full name]
