import { request } from './client';
import type { SetupDetail, SetupHistoryItem } from '../types/setups';

export const listSetups = () => request<SetupDetail[]>('/api/setups');
export const getSetup = (setupId: string) => request<SetupDetail>(`/api/setups/${setupId}`);
export const getSetupHistory = (setupId: string) => request<SetupHistoryItem[]>(`/api/setups/${setupId}/history`);
export const listEntryReadySetups = () => request<SetupDetail[]>('/api/setups/entry-ready');
export const listSetupsAboveProgress = (percent: number) => request<SetupDetail[]>(`/api/setups/progress/${percent}`);
