import { request } from './client';

export type TradingMode = 'OFF' | 'DRY_RUN_PREVIEW' | 'LIVE';

export const getBitgetMode = () => request<Record<string, unknown>>('/api/bitget/mode');
export const switchBitgetMode = (mode: TradingMode, liveConfirmation?: string) =>
  request<Record<string, unknown>>('/api/bitget/mode', {
    method: 'POST',
    body: JSON.stringify({ mode, live_confirmation: liveConfirmation }),
  });
export const saveBitgetCredentials = (payload: {
  mode?: 'LIVE';
  api_key: string;
  api_secret: string;
  passphrase: string;
  environment?: string;
}) => request<Record<string, unknown>>('/api/bitget/credentials', { method: 'POST', body: JSON.stringify(payload) });
export const getBitgetCredentialStatus = () => request<Record<string, unknown>>('/api/bitget/credentials/status');
export const testLiveConnection = (symbol = 'BTCUSDT') =>
  request<Record<string, unknown>>('/api/bitget/connection/live', { method: 'POST', body: JSON.stringify({ symbol }), timeoutMs: 35000 });
export const dryRunPreview = (payload: Record<string, unknown>) =>
  request<Record<string, unknown>>('/api/bitget/orders/dry-run-preview', { method: 'POST', body: JSON.stringify(payload) });
export const runLiveAutomationOnce = () =>
  request<Record<string, unknown>>('/api/live-automation/run-once', { method: 'POST', body: JSON.stringify({}), timeoutMs: 35000 });
