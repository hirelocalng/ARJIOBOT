import { request } from './client';
import type { ClosedTrade, LiveTrade, PnlSummary } from '../types/trades';

// All three hit a real Bitget endpoint server-side (fetch_positions /
// fetch_position_history) - call on demand (mount + manual refresh), not on
// a polling timer, the same way AccountStatus's "Refresh Positions" button
// works.
export const getLiveTrades = () => request<{ trades: LiveTrade[]; count: number; fetched_at: string | null }>('/api/trades/live', { timeoutMs: 35000 });
export const getClosedTrades = () => request<{ trades: ClosedTrade[]; count: number; fetched_at: string | null }>('/api/trades/closed', { timeoutMs: 35000 });
export const getPnlSummary = () => request<PnlSummary>('/api/trades/pnl', { timeoutMs: 35000 });
