import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  env: {
    NEXT_PUBLIC_API_BASE_URL: process.env.API_BASE_URL || "http://localhost:3001",
  },
  rewrites: async () => {
    return {
      beforeFiles: [
        {
          source: "/api/:path*",
          destination: `${process.env.API_BASE_URL || "http://localhost:3001"}/api/:path*`,
        },
      ],
    };
  },
};

export default nextConfig;