import { request } from './client';
import type { TradeSignal } from '../types/signals';

export const listSignals = () => request<TradeSignal[]>('/api/signals');
export const getSignal = (signalId: string) => request<TradeSignal>(`/api/signals/${signalId}`);
export const generateSignal = (setupId: string) => request<TradeSignal>(`/api/signals/generate/${setupId}`, { method: 'POST' });
export const listRejectedSignals = () => request<TradeSignal[]>('/api/signals/rejected');
