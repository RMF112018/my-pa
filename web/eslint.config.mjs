import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

const eslintConfig = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    ignores: [
      "node_modules/**",
      ".next/**",
      "out/**",
      "build/**",
      "next-env.d.ts",
      // Playwright's retained traces, screenshots and reports. Products of a
      // local browser run, never source; a trace can also carry rendered page
      // content, which is not something to feed to a linter or a commit.
      "test-results/**",
      "playwright-report/**",
      "blob-report/**",
    ],
  },
];

export default eslintConfig;
