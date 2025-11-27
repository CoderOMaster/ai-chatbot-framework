"use client";

import React, { ReactNode, ReactElement } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactElement;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Error Boundary component for catching React errors
 * Provides graceful error handling and user feedback
 */
export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    // Log to Sentry or other monitoring service
    console.error("Error caught by boundary:", error, errorInfo);

    // Send to monitoring service
    if (typeof window !== "undefined" && window.__SENTRY__) {
      window.__SENTRY__.captureException(error, { contexts: { react: errorInfo } });
    }
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        this.props.fallback || (
          <div className="flex items-center justify-center min-h-screen bg-gray-50">
            <div className="max-w-md w-full space-y-8">
              <div className="text-center">
                <h1 className="text-2xl font-bold text-gray-900">Something went wrong</h1>
                <p className="mt-2 text-sm text-gray-600">
                  {this.state.error?.message || "An unexpected error occurred"}
                </p>
              </div>
              <button
                onClick={() => window.location.reload()}
                className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition"
              >
                Reload Page
              </button>
            </div>
          </div>
        )
      );
    }

    return this.props.children;
  }
}