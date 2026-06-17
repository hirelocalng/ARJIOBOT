export type ApiError = { code: string; message: string };
export type ApiResponse<T> = { success: true; data: T } | { success: false; error: ApiError };
export type BotStatus = {
  api_status: string;
  adapter_mode: string;
  live_trading_enabled: boolean;
  monitored_pairs_count: number;
  active_setups_count: number;
  generated_signals_count: number;
  approved_trade_plans_count: number;
  execution_records_count: number;
};
