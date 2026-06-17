import { request } from './client';

export type ValidationReport = { report_name: string; path: string; exists: boolean };
export const listReports = () => request<ValidationReport[]>('/api/reports');
export const getReport = (reportName: string) => request<{ report_name: string; content: string }>(`/api/reports/${reportName}`);
