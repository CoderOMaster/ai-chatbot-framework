/**
 * Base API configuration for frontend services.
 * API_BASE_URL is injected from environment variables at build time.
 */

export const API_BASE_URL: string = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000/api/';