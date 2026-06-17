import { request } from './client';

export type MobileControlStatus = {
  engine_host: string;
  phone_role: string;
  trading_mode: string;
  live_trading_enabled: boolean;
  environment_lock_verified: string;
  selected_profile: string;
  visible_profile: string;
  starting_balance: string;
  fixed_risk_amount: string;
  max_leverage: string;
  max_daily_loss: string;
  max_weekly_loss: string;
  enabled_pairs: string[];
  trade_plans_count: number;
  execution_records_count: number;
  open_positions_count: number;
  recent_logs: Record<string, unknown>[];
};

export const getMobileControlStatus = () => request<MobileControlStatus>('/api/mobile/control-status');
export const emergencyStop = () => request<Record<string, unknown>>('/api/mobile/emergency-stop', { method: 'POST' });
