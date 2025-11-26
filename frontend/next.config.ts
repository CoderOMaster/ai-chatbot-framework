import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  
  // Environment-specific configuration
  env: {
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:3001",
    NEXT_PUBLIC_ENVIRONMENT: process.env.NEXT_PUBLIC_ENVIRONMENT || "development",
  },

  // Rewrites for API route proxying
  async rewrites() {
    const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:3001";
    
    return {
      beforeFiles: [
        {
          source: "/api/:path*",
          destination: `${apiBaseUrl}/api/:path*`,
        },
      ],
    };
  },

  // Headers for security and CORS
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
          {
            key: "X-Frame-Options",
            value: "DENY",
          },
          {
            key: "X-XSS-Protection",
            value: "1; mode=block",
          },
        ],
      },
    ];
  },

  // Optimize for container deployment
  compress: true,
  poweredByHeader: false,
  productionBrowserSourceMaps: false,

  // Image optimization for microservice
  images: {
    unoptimized: process.env.NEXT_PUBLIC_ENVIRONMENT === "production" ? false : true,
  },
};

export default nextConfig;