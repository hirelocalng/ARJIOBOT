import { request } from './client';
import type { AccountStatusSummary } from '../types/accountStatus';

export const getAccountStatusSummary = () => request<AccountStatusSummary>('/api/account-status/summary');
export const refreshAccountStatus = () => request<AccountStatusSummary>('/api/account-status/refresh', { method: 'POST', body: JSON.stringify({}) });
export const getAccountBalanceStatus = () => request<Record<string, unknown>>('/api/account-status/balance');
export const getAccountPositionsStatus = () => request<AccountStatusSummary['open_positions']>('/api/account-status/positions');
export const getAccountOpenOrdersStatus = () => request<AccountStatusSummary['open_orders']>('/api/account-status/open-orders');
export const getAccountMarginModeStatus = () => request<Record<string, unknown>>('/api/account-status/margin-mode');
export const getAccountLeverageStatus = () => request<Record<string, unknown>>('/api/account-status/leverage');
export const getAccountRiskStatus = () => request<Record<string, unknown>>('/api/account-status/risk-status');
