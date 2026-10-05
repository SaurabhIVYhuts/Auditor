import type { NextConfig } from "next";

// Forward /api/v1/* to the FastAPI backend, so the browser needs no CORS setup.
const API_URL = process.env.AUDITOR_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${API_URL}/api/v1/:path*` }];
  },
};

export default nextConfig;
