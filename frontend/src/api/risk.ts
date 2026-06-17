import { request } from './client';
import type { TradePlan } from '../types/risk';

export const assessRisk = (signalId: string) => request<unknown>(`/api/risk/assess/${signalId}`, { method: 'POST' });
export const createTradePlan = (signalId: string) => request<TradePlan>(`/api/risk/trade-plan/${signalId}`, { method: 'POST' });
export const listTradePlans = () => request<TradePlan[]>('/api/risk/trade-plans');
export const getTradePlan = (tradePlanId: string) => request<TradePlan>(`/api/risk/trade-plans/${tradePlanId}`);
