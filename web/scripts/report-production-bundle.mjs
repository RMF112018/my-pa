#!/usr/bin/env node
/**
 * Observational production-bundle census. Not a budget.
 *
 * WP28 records first-load JS sizes from a completed `next build`. Exit 0 when
 * `.next` exists. Do not fail the job on a numeric threshold; none is accepted.
 */
import { existsSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const root = join(process.cwd(), ".next");
if (!existsSync(root)) {
  console.error("report-production-bundle: .next is missing; run npm run build first");
  process.exit(1);
}

function walk(dir, acc = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    const st = statSync(path);
    if (st.isDirectory()) walk(path, acc);
    else if (name.endsWith(".js")) acc.push({ path, bytes: st.size });
  }
  return acc;
}

const staticJs = existsSync(join(root, "static")) ? walk(join(root, "static")) : [];
staticJs.sort((a, b) => b.bytes - a.bytes);
const total = staticJs.reduce((sum, row) => sum + row.bytes, 0);
const top = staticJs.slice(0, 15);
console.log(
  JSON.stringify(
    {
      kind: "observational_bundle_census",
      budget: null,
      static_js_file_count: staticJs.length,
      static_js_bytes: total,
      largest: top.map((row) => ({
        path: row.path.slice(root.length + 1),
        bytes: row.bytes,
      })),
    },
    null,
    2,
  ),
);
process.exit(0);
