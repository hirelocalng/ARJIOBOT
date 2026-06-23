import { request } from './client';

export const clearSetupHistory = () =>
  request<{ cleared_completed_count: number; cleared_invalidated_count: number; message: string }>(
    '/api/admin/clear-setup-history',
    { method: 'POST' }
  );
