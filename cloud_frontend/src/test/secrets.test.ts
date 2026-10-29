import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = join(__dirname, "..");
const FORBIDDEN = [
  /SUPABASE_SERVICE_ROLE/i,
  /SERVICE_ROLE_KEY/i,
  /VOYAGE_API_KEY/,
  /OPENAI_API_KEY/,
  /sk-[A-Za-z0-9]{20,}/,
];

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    if (name === "test" || name.startsWith(".")) continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.(ts|tsx|js|mjs)$/.test(name)) out.push(full);
  }
  return out;
}

describe("browser bundle must not contain private secrets", () => {
  it("keeps the production env guard in next.config", () => {
    const text = readFileSync(join(ROOT, "..", "next.config.ts"), "utf8");
    expect(text).toMatch(/assertPublicBrowserEnv/);
  });

  it("does not reference service-role or provider keys in frontend source", () => {
    const hits: string[] = [];
    for (const file of walk(ROOT)) {
      const text = readFileSync(file, "utf8");
      for (const pattern of FORBIDDEN) {
        if (pattern.test(text) && !file.endsWith("config.ts") && !file.endsWith("next.config.ts")) {
          hits.push(`${file}: ${pattern}`);
        }
      }
    }
    expect(hits).toEqual([]);
  });
});
