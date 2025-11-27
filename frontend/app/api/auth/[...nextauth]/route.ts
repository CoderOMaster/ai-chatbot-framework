import NextAuth, { type NextAuthOptions } from "next-auth";
import type { Provider } from "next-auth/providers";

/**
 * NextAuth configuration for authentication
 * Supports multiple providers: Cognito, Auth0, etc.
 */

const providers: Provider[] = [];

// Configure Cognito provider if credentials are available
if (
  process.env.NEXTAUTH_COGNITO_ID &&
  process.env.NEXTAUTH_COGNITO_SECRET &&
  process.env.NEXTAUTH_COGNITO_ISSUER
) {
  const CognitoProvider = require("next-auth/providers/cognito").default;
  providers.push(
    CognitoProvider({
      clientId: process.env.NEXTAUTH_COGNITO_ID,
      clientSecret: process.env.NEXTAUTH_COGNITO_SECRET,
      issuer: process.env.NEXTAUTH_COGNITO_ISSUER,
    })
  );
}

// Configure Auth0 provider if credentials are available
if (
  process.env.NEXTAUTH_AUTH0_ID &&
  process.env.NEXTAUTH_AUTH0_SECRET &&
  process.env.NEXTAUTH_AUTH0_ISSUER
) {
  const Auth0Provider = require("next-auth/providers/auth0").default;
  providers.push(
    Auth0Provider({
      clientId: process.env.NEXTAUTH_AUTH0_ID,
      clientSecret: process.env.NEXTAUTH_AUTH0_SECRET,
      issuer: process.env.NEXTAUTH_AUTH0_ISSUER,
    })
  );
}

const authOptions: NextAuthOptions = {
  providers,
  pages: {
    signIn: "/auth/signin",
    error: "/auth/error",
  },
  callbacks: {
    async jwt({ token, account }) {
      if (account) {
        token.accessToken = account.access_token;
        token.idToken = account.id_token;
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        (session.user as any).accessToken = token.accessToken;
        (session.user as any).idToken = token.idToken;
      }
      return session;
    },
  },
  session: {
    strategy: "jwt",
    maxAge: 24 * 60 * 60, // 24 hours
  },
  jwt: {
    secret: process.env.NEXTAUTH_SECRET,
    maxAge: 24 * 60 * 60, // 24 hours
  },
};

const handler = NextAuth(authOptions);

export { handler as GET, handler as POST };