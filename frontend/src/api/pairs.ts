import { request } from './client';
import type { MonitoredPair } from '../types/pairs';

export const listPairs = () => request<MonitoredPair[]>('/api/pairs');
export const addPair = (symbol: string) => request<MonitoredPair>('/api/pairs', { method: 'POST', body: JSON.stringify({ symbol }) });
export const updatePair = (symbol: string, enabled: boolean) => request<MonitoredPair>(`/api/pairs/${symbol}`, { method: 'PATCH', body: JSON.stringify({ enabled }) });
export const removePair = (symbol: string) => request<{ deleted: boolean }>(`/api/pairs/${symbol}`, { method: 'DELETE' });
export const importPairs = (symbols: string[]) => request<{ imported: string[] }>('/api/pairs/import', { method: 'POST', body: JSON.stringify({ symbols }) });
export const startMonitoring = () => request<Record<string, unknown>>('/api/monitoring/start', { method: 'POST', body: JSON.stringify({}), timeoutMs: 35000 });
export const stopMonitoring = () => request<Record<string, unknown>>('/api/monitoring/stop', { method: 'POST' });
