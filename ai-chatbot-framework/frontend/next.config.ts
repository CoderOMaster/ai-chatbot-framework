import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  poweredByHeader: false,
  // Expose only NEXT_PUBLIC_ envs to the client
  env: {
    // Keep empty; rely on process.env at build/runtime
  },
  // If using images from external domains, configure here
  images: {
    dangerouslyAllowSVG: true,
    remotePatterns: [
      // { protocol: 'https', hostname: 'example.com' }
    ],
  },
};

export default nextConfig;