import type { ApiResponse } from '../types/common';

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';
export const DASHBOARD_TOKEN_KEY = 'arjiobot_dashboard_token';
type RequestOptions = RequestInit & { timeoutMs?: number };

export function getDashboardToken() {
  return window.localStorage.getItem(DASHBOARD_TOKEN_KEY) ?? '';
}

export function setDashboardToken(token: string) {
  if (token) window.localStorage.setItem(DASHBOARD_TOKEN_KEY, token);
  else window.localStorage.removeItem(DASHBOARD_TOKEN_KEY);
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = getDashboardToken();
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? 12000;
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const headers = options.body instanceof FormData
    ? token ? { Authorization: `Bearer ${token}` } : undefined
    : { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) };
  let response: Response;
  try {
    const { timeoutMs: _timeoutMs, ...fetchOptions } = options;
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers,
      ...fetchOptions,
      signal: fetchOptions.signal ?? controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(`API request timed out after ${Math.round(timeoutMs / 1000)}s: ${path}`);
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
  const bodyText = await response.text();
  if (!bodyText.trim()) {
    throw new Error(response.ok ? 'Backend returned empty response.' : `HTTP ${response.status}: backend returned empty response.`);
  }
  let payload: ApiResponse<T> | { detail?: unknown; error?: { message?: string }; success?: boolean; data?: T };
  try {
    payload = JSON.parse(bodyText) as ApiResponse<T>;
  } catch {
    throw new Error(response.ok ? 'Backend returned invalid JSON.' : `HTTP ${response.status}: backend returned invalid JSON.`);
  }
  if (!response.ok || !payload.success) {
    const message = extractErrorMessage(payload, response.status);
    throw new Error(message);
  }
  return payload.data as T;
}

function extractErrorMessage(payload: { detail?: unknown; error?: { message?: string }; success?: boolean }, status: number) {
  if (payload.error?.message) return payload.error.message;
  if (payload.detail && typeof payload.detail === 'object' && 'error' in payload.detail) {
    const nested = payload.detail as { error?: { message?: string }; detail?: unknown };
    if (nested.error?.message) return nested.error.message;
    if (typeof nested.detail === 'string') return nested.detail;
  }
  if (typeof payload.detail === 'string') return payload.detail;
  if (Array.isArray(payload.detail)) return payload.detail.map((item) => typeof item === 'object' ? JSON.stringify(item) : String(item)).join('; ');
  if (payload.detail && typeof payload.detail === 'object') return JSON.stringify(payload.detail);
  return `HTTP ${status}`;
}
