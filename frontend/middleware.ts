import { withAuth } from "next-auth/middleware";
import { NextRequest } from "next/server";

/**
 * Middleware for protecting routes and handling authentication
 * Redirects unauthenticated users to sign-in page
 */

export const middleware = withAuth(
  function middleware(req: NextRequest) {
    // Add custom logic here if needed
    return;
  },
  {
    callbacks: {
      authorized: ({ token }) => !!token,
    },
    pages: {
      signIn: "/auth/signin",
    },
  }
);

// Protect admin and dashboard routes
export const config = {
  matcher: [
    "/admin/:path*",
    "/dashboard/:path*",
    "/api/protected/:path*",
  ],
};