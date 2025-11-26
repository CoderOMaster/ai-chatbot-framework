import { API_BASE_URL } from "./base";

export interface ChatLog {
  thread_id: string;
  user_message: {
    text: string;
    context: Record<string, unknown>;
  };
  bot_message: Array<{ text: string }>;
  timestamp: string;
}

export interface ChatThreadInfo {
  thread_id: string;
  date: string;
}

export interface ChatLogsResponse {
  total: number;
  page: number;
  limit: number;
  conversations: ChatThreadInfo[];
}

/**
 * Type guard to validate ChatLogsResponse structure
 */
function isChatLogsResponse(data: unknown): data is ChatLogsResponse {
  if (typeof data !== 'object' || data === null) return false;
  const obj = data as Record<string, unknown>;
  return (
    typeof obj.total === 'number' &&
    typeof obj.page === 'number' &&
    typeof obj.limit === 'number' &&
    Array.isArray(obj.conversations)
  );
}

/**
 * Type guard to validate ChatLog[] structure
 */
function isChatLogArray(data: unknown): data is ChatLog[] {
  if (!Array.isArray(data)) return false;
  return data.every(
    (item) =>
      typeof item === 'object' &&
      item !== null &&
      typeof (item as Record<string, unknown>).thread_id === 'string' &&
      typeof (item as Record<string, unknown>).timestamp === 'string'
  );
}

/**
 * Fetch paginated list of chat logs
 * @param page - Page number (1-indexed)
 * @param limit - Number of items per page
 * @returns ChatLogsResponse with paginated conversations
 * @throws Error if API request fails or response is invalid
 */
export async function listChatLogs(page: number, limit: number): Promise<ChatLogsResponse> {
  const response = await fetch(`${API_BASE_URL}chatlogs/?page=${page}&limit=${limit}`);

  if (!response.ok) {
    throw new Error(`Failed to fetch chat logs: ${response.status} ${response.statusText}`);
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch (error) {
    throw new Error(`Invalid JSON response from chatlogs API: ${error instanceof Error ? error.message : String(error)}`);
  }

  if (!isChatLogsResponse(data)) {
    throw new Error('Invalid chat logs response structure from backend');
  }

  return data;
}

/**
 * Fetch a specific chat thread by ID
 * @param threadId - The thread ID to fetch
 * @returns Array of ChatLog entries for the thread
 * @throws Error if API request fails or response is invalid
 */
export async function getChatThread(threadId: string): Promise<ChatLog[]> {
  const response = await fetch(`${API_BASE_URL}chatlogs/${threadId}`);

  if (!response.ok) {
    throw new Error(`Failed to fetch chat thread: ${response.status} ${response.statusText}`);
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch (error) {
    throw new Error(`Invalid JSON response from chat thread API: ${error instanceof Error ? error.message : String(error)}`);
  }

  if (!isChatLogArray(data)) {
    throw new Error('Invalid chat thread response structure from backend');
  }

  return data;
}

/**
 * Format a timestamp string to a localized date-time string
 * @param timestamp - ISO 8601 timestamp string
 * @returns Formatted date-time string
 */
export function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  });
}