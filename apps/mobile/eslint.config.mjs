import base from "@mykhaya/eslint-config";
export default [
  { ignores: [".expo/**", "expo-env.d.ts", "eslint.config.mjs"] },
  ...base,
];
