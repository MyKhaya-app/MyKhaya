import base from "@mykhaya/eslint-config";
export default [
  {
    ignores: [
      ".next/**",
      "next-env.d.ts",
      "eslint.config.mjs",
      "public/**",
      "scripts/**",
      "test-results/**",
    ],
  },
  ...base,
  {
    rules: {
      "@typescript-eslint/consistent-type-imports": "off",
      "@typescript-eslint/no-floating-promises": "off",
      "@typescript-eslint/no-misused-promises": [
        "error",
        { checksVoidReturn: { attributes: false } },
      ],
      "@typescript-eslint/require-await": "off",
    },
  },
];
