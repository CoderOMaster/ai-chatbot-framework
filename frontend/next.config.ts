import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Use standalone output for minimal Docker image size
  output: "standalone",

  // Enable SWR (Stale-While-Revalidate) for better caching
  swcMinify: true,

  // Image optimization for CDN caching
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "**",
      },
    ],
    // Cache images for 1 year in CDN
    minimumCacheTTL: 31536000,
  },

  // Headers for CDN caching and security
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=3600, s-maxage=86400",
          },
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
          {
            key: "X-Frame-Options",
            value: "SAMEORIGIN",
          },
          {
            key: "X-XSS-Protection",
            value: "1; mode=block",
          },
        ],
      },
      {
        source: "/static/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },
      {
        source: "/_next/static/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },
    ];
  },

  // Redirects for API routes to backend
  async redirects() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8080"}/:path*`,
        permanent: false,
      },
    ];
  },

  // Environment variables
  env: {
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL || "/api",
    NEXT_PUBLIC_AUTH_DOMAIN: process.env.NEXT_PUBLIC_AUTH_DOMAIN || "",
    NEXT_PUBLIC_PUBLIC_URL: process.env.NEXT_PUBLIC_PUBLIC_URL || "http://localhost:3000",
  },

  // Experimental features for performance
  experimental: {
    optimizePackageImports: ["@heroicons/react", "flowbite-react"],
  },

  // Webpack bundle analysis (optional, enable via ANALYZE=true npm run build)
  webpack: (config, { isServer }) => {
    if (!isServer) {
      config.optimization = {
        ...config.optimization,
        splitChunks: {
          chunks: "all",
          cacheGroups: {
            default: false,
            vendors: false,
            // Vendor chunk
            vendor: {
              filename: "chunks/vendor.js",
              test: /node_modules/,
              priority: 10,
              reuseExistingChunk: true,
              name: "vendor",
            },
            // Common chunk
            common: {
              minChunks: 2,
              priority: 5,
              reuseExistingChunk: true,
              name: "common",
            },
          },
        },
      };
    }
    return config;
  },
};

export default nextConfig;