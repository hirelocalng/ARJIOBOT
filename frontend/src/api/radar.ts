import { request } from './client';
import type { RadarSetup } from '../types/radar';

export const getRadar = () => request<RadarSetup[]>('/api/radar');
export const getRadarHistory = () => request<RadarSetup[]>('/api/radar/history');
