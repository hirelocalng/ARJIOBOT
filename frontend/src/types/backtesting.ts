export type BacktestRun = {
  run_id: string;
  upload_id?: string;
  filename?: string;
  symbol: string;
  detected_symbol?: string;
  timeframe: string;
  timeframe_profile?: string;
  profile_id?: string;
  selected_profile_id?: string;
  applied_profile_id?: string;
  selected_strategy_profile?: string;
  research_mode?: boolean;
  candles_loaded?: number;
  candle_hash?: string;
  data_start_time?: string;
  data_end_time?: string;
  profile_applied?: Record<string, unknown>;
  profile_lock_verification?: Record<string, unknown>;
  warnings?: string[];
  status: string;
  trades: unknown[];
  equity_curve: { timestamp: string; equity: string }[];
  report: Record<string, unknown>;
};

export type CsvUpload = {
  upload_id: string;
  filename: string;
  candles_loaded: number;
  detected_symbol: string;
  start_time?: string;
  end_time?: string;
  candle_hash: string;
};

export type BacktestProfile = {
  profile_id: string;
  label: string;
  production_safe: boolean;
  expansion_ratio_min: number;
  expansion_ratio_max: number;
  retrace_window_8m_candles: number;
  fvg_delay_16m_candles: number;
  direct_12m_retrace_entry_enabled?: boolean;
  one_trade_per_12m_fvg?: boolean;
  require_1m_swing_confirmation?: boolean;
  require_1m_bearish_expansion?: boolean;
  require_1m_bearish_fvg?: boolean;
  require_1m_fvg_retest?: boolean;
  note: string;
};
