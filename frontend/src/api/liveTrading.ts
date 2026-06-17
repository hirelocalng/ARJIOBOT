import { request } from './client';

export const toggleLiveTrading = (enabled: boolean, understandRealFunds: boolean, confirmationText: string) =>
  request<Record<string, unknown>>('/api/live-trading/toggle', {
    method: 'POST',
    body: JSON.stringify({ enabled, understand_real_funds: understandRealFunds, confirmation_text: confirmationText }),
  });

export const getLiveTradingStatus = () => request<Record<string, unknown>>('/api/live-trading/status');
