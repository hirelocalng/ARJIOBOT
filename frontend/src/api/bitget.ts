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

export type BitgetSubmittedOrder = Record<string, unknown> & {
  symbol: string;
  side: string;
  entry_price: string;
  stop_reference: string;
  target_reference: string;
  size: string;
  leverage: string;
  bitget_order_id: string;
  network_submitted: boolean;
  generated_at: string;
};

export type BitgetBlockedOrder = Record<string, unknown> & {
  symbol: string;
  reason: string;
  selected_trade_mode: string;
  required_trade_mode: string;
  created_at: string;
};

export type BitgetOrdersResponse = {
  orders: BitgetSubmittedOrder[];
  blocked_orders: BitgetBlockedOrder[];
  mode_events: Record<string, unknown>[];
  last_dry_run_preview: Record<string, unknown> | null;
};

// Local audit log of orders this bot has placed/attempted on Bitget - reads
// in-memory state only (no live exchange call), unlike /api/account-status/
// positions, so it is safe to poll on every refresh cycle.
export const getBitgetOrders = () => request<BitgetOrdersResponse>('/api/bitget/orders');
