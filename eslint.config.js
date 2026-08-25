import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

// Flat config. ESLint reads this file itself, so it stays plain JavaScript.
//
// Prettier owns layout. No rule here reports a format problem, so the two
// tools never disagree about the same line.
//
// The type-aware rule set needs a TypeScript program. `projectService` builds
// one from tsconfig.json, which is why every linted TypeScript file must be
// inside that config's `include`.
export default tseslint.config(
  {
    // Nothing here is source. ESLint ignores `node_modules` on its own, but it
    // does descend into dot-directories, so the Python virtual environment and
    // the tool caches have to be named or `eslint .` reports rules against
    // third-party and generated JavaScript. `.gitignore` lists the same set.
    ignores: [
      // Build output of the web app, and generated data of the pipeline. Both
      // are written by a tool, and neither is edited by hand.
      "web/dist/**",
      "data/dist/**",
      "data/.cache/**",
      // Python side: the virtual environment and every tool cache.
      ".venv/**",
      ".mypy_cache/**",
      ".ruff_cache/**",
      ".pytest_cache/**",
      // Agent tooling, not project source.
      ".claude/**",
    ],
  },
  js.configs.recommended,
  {
    files: ["**/*.ts"],
    extends: [tseslint.configs.strictTypeChecked],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      // TypeScript does not report an unused local here, because ESLint does.
      // A leading underscore marks a binding that the signature needs and the
      // body does not.
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
    },
  },
  {
    // Browser code.
    files: ["web/**/*.ts"],
    languageOptions: {
      globals: globals.browser,
    },
  },
  {
    // Build configuration and the tests that cover it. Node runs these, not
    // the browser. `eslint.config.js` already matches `*.config.js`.
    files: ["*.config.ts", "*.config.js", "*.test.ts"],
    languageOptions: {
      globals: globals.node,
    },
  },
  {
    // This file is JavaScript, so it has no type information to lint with.
    files: ["**/*.js"],
    extends: [tseslint.configs.disableTypeChecked],
  },
);
