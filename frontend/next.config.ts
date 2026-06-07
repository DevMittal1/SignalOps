import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // Inside the docker network, the API is always accessible at api-server:8000
    return [
      {
        source: '/api/:path*',
        destination: `http://api-server:8000/api/:path*`, // Proxy to Backend
      },
    ];
  },
};

export default nextConfig;
