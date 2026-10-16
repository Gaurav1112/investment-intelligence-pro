// Deterministic display formatting (ux-design.md §4.2). Values arrive from the API as decimal STRINGS;
// we never parse money into a JS float for arithmetic — only for display formatting of already-final values.

const MINUS = "−"; // U+2212 minus sign
const NNBSP = " "; // narrow no-break space before %
const THIN = " ";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Split a decimal string into sign / integer digits / fraction digits without float conversion. */
function parts(value: string): { neg: boolean; int: string; frac: string } {
  const s = value.trim();
  if (!/^-?\d+(\.\d+)?$/.test(s)) throw new Error(`not a decimal string: ${value}`);
  const neg = s.startsWith("-");
  const [int = "0", frac = ""] = s.replace("-", "").split(".");
  return { neg, int: int.replace(/^0+(?=\d)/, ""), frac };
}

/** Round a decimal string half-up to `dp` places using string arithmetic (no floats). */
export function roundHalfUp(value: string, dp: number): string {
  const { neg, int, frac } = parts(value);
  const padded = (frac + "0".repeat(dp + 1)).slice(0, dp + 1);
  let digits = (int + padded.slice(0, dp)).split("").map(Number);
  if (Number(padded[dp] ?? "0") >= 5) {
    let i = digits.length - 1;
    while (i >= 0) {
      const d = (digits[i] ?? 0) + 1;
      if (d < 10) {
        digits[i] = d;
        break;
      }
      digits[i] = 0;
      i -= 1;
    }
    if (i < 0) digits = [1, ...digits];
  }
  const all = digits.join("");
  const intPart = dp > 0 ? all.slice(0, all.length - dp) : all;
  const fracPart = dp > 0 ? all.slice(all.length - dp) : "";
  const body = `${intPart || "0"}${dp > 0 ? `.${fracPart}` : ""}`;
  const isZero = /^0(\.0*)?$/.test(body);
  return neg && !isZero ? `-${body}` : body;
}

/** Indian digit grouping: 1234567 → 12,34,567 */
export function groupIndian(int: string): string {
  if (int.length <= 3) return int;
  const tail = int.slice(-3);
  let head = int.slice(0, -3);
  const groups: string[] = [];
  while (head.length > 2) {
    groups.unshift(head.slice(-2));
    head = head.slice(0, -2);
  }
  if (head) groups.unshift(head);
  return `${groups.join(",")},${tail}`;
}

/** ₹12,34,567.89 — exact, paise, half-up (matches the backend money() policy). */
export function inr(value: string, opts: { paise?: boolean } = {}): string {
  const paise = opts.paise ?? true;
  const r = roundHalfUp(value, paise ? 2 : 0);
  const { neg, int, frac } = parts(r);
  return `${neg ? MINUS : ""}₹${groupIndian(int)}${paise ? `.${frac.padEnd(2, "0")}` : ""}`;
}

/** Compact lakh/crore: ₹12.35 L, ₹1.23 Cr. The exact value must always be available alongside (tooltip/drawer). */
export function inrCompact(value: string): string {
  const { neg, int } = parts(value);
  const sign = neg ? MINUS : "";
  const n = int.length;
  const crore = () => `${sign}₹${roundHalfUp(shift(value, -7), 2).replace("-", "")}${THIN}Cr`;
  if (n >= 8) return crore();
  if (n >= 6) {
    const lakh = roundHalfUp(shift(value, -5), 2).replace("-", "");
    // 99,99,999 rounds to "100.00" lakh — that is 1 crore; switch units after rounding, not before.
    return parts(lakh).int.length >= 3 ? crore() : `${sign}₹${lakh}${THIN}L`;
  }
  return inr(value);
}

/** Shift the decimal point by `k` places (negative = divide by 10^|k|), string-only. */
function shift(value: string, k: number): string {
  const { neg, int, frac } = parts(value);
  const point = int.length + k;
  // Pad with zeros when the point moves past the last digit: "0.5" shifted by 2 is "50", not "5".
  const digits = (int + frac).padEnd(point, "0");
  const whole = point <= 0 ? "0" : digits.slice(0, point) || "0";
  const rest = point <= 0 ? "0".repeat(-point) + digits : digits.slice(point);
  return `${neg ? "-" : ""}${whole}.${rest || "0"}`;
}

/** Fraction string → percentage with sign: "0.0534" → "+5.34 %"; "-0.004" → "−0.40 %". */
export function pct(fraction: string, dp = 2, signed = true): string {
  const r = roundHalfUp(shift(fraction, 2), dp);
  const { neg } = parts(r);
  const abs = r.replace("-", "");
  const isZero = /^0(\.0*)?$/.test(abs);
  const sign = !signed || isZero ? "" : neg ? MINUS : "+";
  return `${sign}${abs}${NNBSP}%`;
}

/** ISO date → 15-Apr-2027 (unambiguous). */
export function dateLabel(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) throw new Error(`not an ISO date: ${iso}`);
  const [, y, mo, d] = m;
  return `${d}-${MONTHS[Number(mo) - 1]}-${y}`;
}

/** ISO timestamp → "15-Oct-2026 05:34 UTC". */
export function utcStamp(iso: string): string {
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) throw new Error(`bad timestamp ${iso}`);
  const p = (x: number) => String(x).padStart(2, "0");
  return `${p(t.getUTCDate())}-${MONTHS[t.getUTCMonth()]}-${t.getUTCFullYear()} ${p(t.getUTCHours())}:${p(t.getUTCMinutes())} UTC`;
}

/** Exact decimal-point shift on a non-negative decimal string, normalised ("012.500" → "12.5"). */
export function shiftPoint(value: string, k: number): string {
  const t = value.trim();
  if (!/^\d+(\.\d+)?$/.test(t)) throw new Error(`not a non-negative decimal string: ${value}`);
  const [i = "0", f = ""] = t.split(".");
  const digits = i + f;
  const point = i.length + k;
  let whole: string;
  let frac: string;
  if (point <= 0) {
    whole = "0";
    frac = "0".repeat(-point) + digits;
  } else if (point >= digits.length) {
    whole = digits + "0".repeat(point - digits.length);
    frac = "";
  } else {
    whole = digits.slice(0, point);
    frac = digits.slice(point);
  }
  whole = whole.replace(/^0+(?=\d)/, "");
  frac = frac.replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : whole;
}

/** "20" (%) → "0.2"; returns null for empty input and "invalid" for non-decimal text. */
export function percentToFraction(text: string): string | null {
  const t = text.trim();
  if (!t) return null;
  if (!/^\d+(\.\d+)?$/.test(t)) return "invalid";
  return shiftPoint(t, -2);
}

/** "0.125" → "12.5" (for editing a stored fraction as a percentage). */
export function fractionToPercent(fraction: string | null): string {
  return fraction ? shiftPoint(fraction, 2) : "";
}

// ------------------------------------------------------------------ exact decimal-string arithmetic (no floats)
// Used only to VALIDATE user input (e.g. allocation weights must sum to exactly 100 %), never to compute a financial
// result. BigInt on scaled integers keeps it exact: 0.1 + 0.2 is exactly 0.3 here.

function scaled(value: string): { n: bigint; scale: number } {
  const t = value.trim();
  if (!/^-?\d+(\.\d+)?$/.test(t)) throw new Error(`not a decimal string: ${value}`);
  const neg = t.startsWith("-");
  const [i = "0", f = ""] = t.replace("-", "").split(".");
  const n = BigInt(i + f);
  return { n: neg ? -n : n, scale: f.length };
}

function unscale(n: bigint, scale: number): string {
  const neg = n < 0n;
  const digits = (neg ? -n : n).toString().padStart(scale + 1, "0");
  const whole = digits.slice(0, digits.length - scale) || "0";
  const frac = scale ? digits.slice(digits.length - scale).replace(/0+$/, "") : "";
  const body = frac ? `${whole}.${frac}` : whole;
  return neg && body !== "0" ? `-${body}` : body;
}

function aligned(a: string, b: string): [bigint, bigint, number] {
  const x = scaled(a);
  const y = scaled(b);
  const scale = Math.max(x.scale, y.scale);
  return [x.n * 10n ** BigInt(scale - x.scale), y.n * 10n ** BigInt(scale - y.scale), scale];
}

/** Exact sum of two decimal strings, normalised ("33.33" + "33.34" → "66.67"; "0.10" + "0.20" → "0.3"). */
export function addDecimals(a: string, b: string): string {
  const [x, y, scale] = aligned(a, b);
  return unscale(x + y, scale);
}

/** Exact sum of a list of decimal strings ("0" for an empty list). */
export function sumDecimals(values: readonly string[]): string {
  return values.reduce((acc, v) => addDecimals(acc, v), "0");
}

/** Exact comparison of two decimal strings: −1, 0 or 1 ("1.0" equals "1"). */
export function compareDecimals(a: string, b: string): -1 | 0 | 1 {
  const [x, y] = aligned(a, b);
  return x < y ? -1 : x > y ? 1 : 0;
}
