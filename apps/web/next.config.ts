import type { NextConfig } from "next";
// The web build's own commit and build time, shown on About to signed-in
// sessions (components/app-version.tsx) so the frontend a browser or native
// shell has loaded can be told apart from the API build. Development builds
// only: a stable (production) build inlines empty values, matching the API,
// which keeps its build details behind sign-in.
const developmentBuild = process.env.MYKHAYA_BUILD_CHANNEL !== "stable";
const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  env: {
    MYKHAYA_WEB_COMMIT: developmentBuild ? (process.env.MYKHAYA_COMMIT_SHA ?? "unknown") : "",
    MYKHAYA_WEB_BUILD_TIME: developmentBuild ? (process.env.MYKHAYA_BUILD_TIME ?? "unknown") : "",
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.API_INTERNAL_URL ?? "http://api:8000"}/api/:path*`,
      },
    ];
  },
};
export default config;
