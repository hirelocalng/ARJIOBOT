import { request } from './client';
import type { ExecutionRecord } from '../types/execution';

export const paperExecute = (tradePlanId: string) => request<ExecutionRecord>(`/api/execution/paper/${tradePlanId}`, { method: 'POST' });
export const listExecutions = () => request<ExecutionRecord[]>('/api/execution/records');
export const getExecution = (executionId: string) => request<ExecutionRecord>(`/api/execution/records/${executionId}`);
export const cancelExecution = (executionId: string) => request<ExecutionRecord>(`/api/execution/cancel/${executionId}`, { method: 'POST' });
