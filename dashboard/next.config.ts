import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output: dashboard/Dockerfile ships only .next/standalone (self-contained server)
  // + static assets, instead of a full node_modules copy. Dev/CI (`next build --turbopack`) is
  // unaffected — standalone is produced by the Docker stage's plain `next build` too.
  output: "standalone",
};

export default nextConfig;
