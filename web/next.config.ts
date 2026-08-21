import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Next 16 takes an exclusive dev lock inside distDir. The browser harness
  // deliberately runs live- and dead-gateway servers together, so it supplies
  // separate disposable directories; ordinary dev/build keep the default.
  distDir: process.env.MYPA_NEXT_DIST_DIR ?? ".next",
};

export default nextConfig;
