import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { REQUIRED } from "./Disclosures";

it("frontend disclosures match the backend compliance rule table verbatim", () => {
  const yaml = readFileSync(resolve(__dirname, "../../../backend/src/iip/rules/compliance_phrases.yaml"), "utf8");
  for (const [key, text] of Object.entries(REQUIRED)) {
    expect(yaml).toContain(`  ${key}: "${text}"`);
  }
});

it("no component uses dangerouslySetInnerHTML (threat-model SEC-24)", async () => {
  const { readdirSync, statSync } = await import("node:fs");
  const walk = (dir: string): string[] =>
    readdirSync(dir).flatMap((f: string) => {
      const p = resolve(dir, f);
      return statSync(p).isDirectory() ? walk(p) : [p];
    });
  const offenders = walk(resolve(__dirname, "..")).filter(
    (p) => /\.(tsx?|jsx?)$/.test(p) && !p.endsWith(".test.ts") && readFileSync(p, "utf8").includes("dangerouslySetInnerHTML"),
  );
  expect(offenders).toEqual([]);
});
