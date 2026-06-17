import { request, setDashboardToken } from './client';

export type AuthStatus = { auth_required: boolean; method: string };
export type LoginResult = { token: string; auth_required: boolean };

export const getAuthStatus = () => request<AuthStatus>('/api/auth/status');

export async function login(password: string) {
  const result = await request<LoginResult>('/api/auth/login', { method: 'POST', body: JSON.stringify({ password }) });
  setDashboardToken(result.token);
  return result;
}

export function logout() {
  setDashboardToken('');
}
