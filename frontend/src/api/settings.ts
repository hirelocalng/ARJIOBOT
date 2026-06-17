import { request } from './client';
import type { BotSettings } from '../types/settings';

export const getSettings = () => request<BotSettings>('/api/settings');
export const updateSettings = (payload: Partial<BotSettings>) => request<BotSettings>('/api/settings', { method: 'PATCH', body: JSON.stringify(payload) });
