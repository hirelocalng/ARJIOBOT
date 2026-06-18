import { request } from './client';
import type { AccountPayload, ExchangeAccount } from '../types/accounts';

export const listAccounts = () => request<ExchangeAccount[]>('/api/accounts');
export const createAccount = (payload: AccountPayload) => request<ExchangeAccount>('/api/accounts', { method: 'POST', body: JSON.stringify(payload) });
export const testAndSaveBitgetAccount = (payload: AccountPayload & { nickname?: string; symbol?: string }) =>
  request<ExchangeAccount>('/api/accounts/bitget/test-and-save', { method: 'POST', body: JSON.stringify(payload) });
export const getActiveAccount = () => request<ExchangeAccount | { account_id: null; connection_status: string; live_trading_blocked: boolean }>('/api/accounts/active');
export const getVaultKeyStatus = () => request<{ configured: boolean; source: string; secret_returned: boolean }>('/api/accounts/vault-key');
export const saveVaultKey = (encryptionKey: string) =>
  request<{ configured: boolean; source: string; secret_returned: boolean }>('/api/accounts/vault-key', { method: 'POST', body: JSON.stringify({ encryption_key: encryptionKey }) });
export const generateVaultKey = () => request<{ configured: boolean; source: string; secret_returned: boolean }>('/api/accounts/vault-key/generate', { method: 'POST', body: JSON.stringify({}) });
export const updateAccount = (accountId: string, payload: AccountPayload) => request<ExchangeAccount>(`/api/accounts/${accountId}`, { method: 'PATCH', body: JSON.stringify(payload) });
export const deleteAccount = (accountId: string) => request<{ deleted: boolean }>(`/api/accounts/${accountId}`, { method: 'DELETE' });
export const setDefaultAccount = (accountId: string) => request<ExchangeAccount>(`/api/accounts/${accountId}/default`, { method: 'POST' });
export const selectActiveAccount = (accountId: string) => request<ExchangeAccount>('/api/accounts/select-active', { method: 'POST', body: JSON.stringify({ account_id: accountId }) });
export const testConnection = (accountId: string) => request<ExchangeAccount>(`/api/accounts/${accountId}/test-connection`, { method: 'POST', timeoutMs: 35000 });
export const testBitgetConnection = (symbol = 'BTCUSDT') =>
  request<{ connected: boolean; credential_source: string; error?: string; available_balance?: string; available_margin?: string }>(
    '/api/accounts/bitget/test',
    { method: 'POST', body: JSON.stringify({ symbol }), timeoutMs: 35000 }
  );
export const refreshAccount = (accountId: string) => request<ExchangeAccount>(`/api/accounts/${accountId}/refresh`, { method: 'POST', timeoutMs: 35000 });
export const reconnectAccount = (accountId: string, payload: AccountPayload & { nickname?: string; symbol?: string }) =>
  request<ExchangeAccount>(`/api/accounts/${accountId}/reconnect`, { method: 'POST', body: JSON.stringify(payload) });
export const enableTrading = (accountId: string) => request<ExchangeAccount>(`/api/accounts/${accountId}/enable-trading`, { method: 'POST' });
export const disableTrading = (accountId: string) => request<ExchangeAccount>(`/api/accounts/${accountId}/disable-trading`, { method: 'POST' });
export const getBalance = (accountId: string) => request<unknown[]>(`/api/accounts/${accountId}/balance`);
export const getPositions = (accountId: string) => request<unknown[]>(`/api/accounts/${accountId}/positions`);
