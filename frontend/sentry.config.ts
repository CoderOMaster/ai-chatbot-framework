import * as Sentry from "@sentry/nextjs";

/**
 * Sentry configuration for error monitoring and performance tracking
 * Captures unhandled exceptions, performance metrics, and user interactions
 */
const SENTRY_DSN = process.env.NEXT_PUBLIC_SENTRY_DSN;
const ENVIRONMENT = process.env.NODE_ENV || "development";

if (SENTRY_DSN) {
  Sentry.init({
    dsn: SENTRY_DSN,
    environment: ENVIRONMENT,
    tracesSampleRate: ENVIRONMENT === "production" ? 0.1 : 1.0,
    debug: ENVIRONMENT !== "production",

    // Capture performance metrics
    integrations: [
      new Sentry.Replay({
        maskAllText: true,
        blockAllMedia: true,
      }),
    ],

    // Capture session replays for 10% of all sessions in production
    replaysSessionSampleRate: ENVIRONMENT === "production" ? 0.1 : 1.0,
    replaysOnErrorSampleRate: 1.0,

    // Filter out certain errors
    beforeSend(event, hint) {
      // Filter out network errors from external services
      if (event.exception) {
        const error = hint.originalException;
        if (error instanceof Error && error.message.includes("NetworkError")) {
          return null;
        }
      }
      return event;
    },
  });
}

export default Sentry;