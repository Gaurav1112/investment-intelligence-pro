// A06 (audit-perf-frontend F4): a page module must not statically import another page module, or Vite links the page
// chunks together and the landing page downloads code for pages the user has not opened. Shared helpers live in
// components/ or lib/. Dynamic import() of a non-route panel (e.g. the lazily loaded CAS import) is allowed.
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..");

/** Pages this package owns; every one of them must be free of static cross-page imports. */
const CHECKED_PAGES = ["Risk", "Scenarios", "FixedIncome", "Overview", "Watchlist", "Today", "Settings", "Signals", "RuleDetail", "Goals"];
/** Shared modules created to hold what pages used to export to each other: they must never import a page either. */
const SHARED = ["components/analysisCommon.tsx", "components/fiCommon.tsx", "components/watchCommon.tsx", "lib/useApi.ts", "lib/api.ts"];

const pageNames = new Set(
  readdirSync(here)
    .filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f))
    .map((f) => f.replace(/\.tsx?$/, "")),
);

/** Module specifiers of static `import … from "x"` and `export … from "x"` statements (dynamic import() excluded). */
function staticSpecifiers(code: string): string[] {
  const out: string[] = [];
  const re = /^\s*(?:import|export)\s[^;]*?\sfrom\s+["']([^"']+)["']|^\s*import\s+["']([^"']+)["']/gms;
  for (const m of code.matchAll(re)) out.push((m[1] ?? m[2])!);
  return out;
}

describe("no cross-page module imports (A06)", () => {
  it("the specifier scanner sees static imports and re-exports but not dynamic import()", () => {
    const code = 'import { a } from "./A";\nexport { b } from "../components/b";\nimport "./side";\nconst C = lazy(() => import("./C"));\n';
    expect(staticSpecifiers(code)).toEqual(["./A", "../components/b", "./side"]);
  });

  it.each(CHECKED_PAGES)("pages/%s imports no other page", (page) => {
    const code = readFileSync(join(here, `${page}.tsx`), "utf8");
    const pageImports = staticSpecifiers(code).filter((s) => s.startsWith("./") && pageNames.has(s.slice(2)));
    expect(pageImports).toEqual([]);
  });

  it.each(SHARED)("%s imports no page", (file) => {
    const code = readFileSync(join(src, file), "utf8");
    expect(staticSpecifiers(code).filter((s) => s.includes("pages/"))).toEqual([]);
  });
});
