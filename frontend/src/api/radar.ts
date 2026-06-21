import { request } from './client';
import type { RadarSetup } from '../types/radar';

export const getRadar = () => request<RadarSetup[]>('/api/radar');
export const getRadarHistory = () => request<RadarSetup[]>('/api/radar/history');
export const getInProgressSetups = () => request<RadarSetup[]>('/api/setups/in-progress');
export const getCompletedSetups = () => request<RadarSetup[]>('/api/setups/completed');
export const getInvalidatedSetups = () => request<RadarSetup[]>('/api/setups/invalidated');
