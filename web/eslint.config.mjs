import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const eslintConfig = [
  ...nextVitals,
  ...nextTypescript,
  {
    ignores: [
      "node_modules/**",
      ".next/**",
      "out/**",
      "build/**",
      "storybook-static/**",
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
