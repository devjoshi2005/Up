import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  experimental: {
    // This dashboard is intentionally client-rendered: every page fetches its
    // own data in the browser, so Next can't validate an "instant" server
    // segment and drops it ("Could not validate that a segment in your UI has
    // instant navigation"). That's information, not a bug — the `instant =
    // false` opt-out is illegal in Client Components, so we narrow validation
    // to segments that opt in explicitly instead of spamming the dev overlay.
    instantInsights: { validationLevel: "manual-warning" },
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
