import { getSession } from "next-auth/react";

/**
 * API client utility for making authenticated requests to backend
 * Handles token injection, error handling, and retry logic
 */

interface RequestOptions extends RequestInit {
  timeout?: number;
  retry?: number;
}

interface ApiResponse<T> {
  data?: T;
  error?: string;
  status: number;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "/api";
const DEFAULT_TIMEOUT = 30000; // 30 seconds
const DEFAULT_RETRY = 3;

/**
 * Make an authenticated API request
 */
export async function apiRequest<T>(
  endpoint: string,
  options: RequestOptions = {}
): Promise<ApiResponse<T>> {
  const {
    timeout = DEFAULT_TIMEOUT,
    retry = DEFAULT_RETRY,
    ...fetchOptions
  } = options;

  const url = `${API_BASE_URL}${endpoint}`;
  let lastError: Error | null = null;

  for (let attempt = 0; attempt < retry; attempt++) {
    try {
      // Get session and inject token
      const session = await getSession();
      const headers: HeadersInit = {
        "Content-Type": "application/json",
        ...fetchOptions.headers,
      };

      if (session?.user && (session.user as any).accessToken) {
        headers.Authorization = `Bearer ${(session.user as any).accessToken}`;
      }

      // Create abort controller for timeout
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeout);

      const response = await fetch(url, {
        ...fetchOptions,
        headers,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        return {
          error: error.message || `HTTP ${response.status}`,
          status: response.status,
        };
      }

      const data = await response.json();
      return { data, status: response.status };
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));

      // Don't retry on client errors (4xx)
      if (error instanceof Error && error.name === "AbortError") {
        return {
          error: "Request timeout",
          status: 408,
        };
      }

      // Retry on network errors
      if (attempt < retry - 1) {
        await new Promise((resolve) => setTimeout(resolve, 1000 * (attempt + 1)));
        continue;
      }
    }
  }

  return {
    error: lastError?.message || "Request failed",
    status: 0,
  };
}

/**
 * GET request
 */
export async function apiGet<T>(
  endpoint: string,
  options?: RequestOptions
): Promise<ApiResponse<T>> {
  return apiRequest<T>(endpoint, { ...options, method: "GET" });
}

/**
 * POST request
 */
export async function apiPost<T>(
  endpoint: string,
  data?: unknown,
  options?: RequestOptions
): Promise<ApiResponse<T>> {
  return apiRequest<T>(endpoint, {
    ...options,
    method: "POST",
    body: data ? JSON.stringify(data) : undefined,
  });
}

/**
 * PUT request
 */
export async function apiPut<T>(
  endpoint: string,
  data?: unknown,
  options?: RequestOptions
): Promise<ApiResponse<T>> {
  return apiRequest<T>(endpoint, {
    ...options,
    method: "PUT",
    body: data ? JSON.stringify(data) : undefined,
  });
}

/**
 * DELETE request
 */
export async function apiDelete<T>(
  endpoint: string,
  options?: RequestOptions
): Promise<ApiResponse<T>> {
  return apiRequest<T>(endpoint, { ...options, method: "DELETE" });
}