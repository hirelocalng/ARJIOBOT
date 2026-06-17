import { request } from './client';
import type { BotStatus } from '../types/common';

export const getHealth = () => request<{ status: string }>('/api/health');
export const getStatus = () => request<BotStatus>('/api/status');
