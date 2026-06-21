export type RadarSetup = {
  setup_id: string;
  symbol: string;
  direction: string;
  status?: string;
  strategy_profile?: string;
  profile_variant_name?: string;
  inherited_base_profile?: string;
  timeframe_profile?: string | null;
  selected_tp_model?: string | null;
  expansion_min?: string | number;
  expansion_max?: string | number;
  retracement_window?: string | number;
  entry_model?: string;
  current_state: string;
  progress_percent: number;
  setup_percentage?: number;
  missing_requirements: string[];
  invalidation_reason: string | null;
  time_remaining: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  invalidated_at?: string | null;
  entry_price?: string | null;
  swing_16m_id?: string | null;
  expansion_16m_id?: string | null;
  fvg_16m_id?: string | null;
  fvg_12m_id?: string | null;
  fvg_8m_id?: string | null;
  watched_timeframes?: string[];
  latest_relevant_price?: string;
  stop_reference: string | null;
  target_reference: string | null;
  higher_timeframe_context_status?: string | null;
  fvg_16m_status?: string | null;
  expansion_ratio?: string | number | null;
  fvg_12m_status?: string | null;
  eight_minute_candle_count_after_16m_fvg?: string | number | null;
  retracement_within_3_8m_candles?: boolean | null;
  first_candle_entered_12m_fvg?: boolean | null;
  entry_candle_boundary_respected?: boolean | null;
  entry_ready?: boolean;
  one_trade_per_fvg_status?: string | null;
  rejection_reason?: string | null;
  source?: string | null;
  // Set when the real trade candidate for this same swing (a separate Setup
  // object - see _setup_from_trade vs _apply_one_attempt_trace) was found by
  // the shared strategy funnel but skipped by live automation for no longer
  // being fresh (entry candle older than the latest 1-2 live candles).
  stale_skip?: {
    swing_16m_id: string;
    symbol: string;
    direction: string;
    entry_timestamp: string;
    candles_past_window: number;
    seconds_past_window: number;
    skipped_at: string;
    seconds_since_monitoring_started: number | null;
    likely_restart_related: boolean;
  } | null;
  swing_price?: string | null;
  // Best-effort link to the real Bitget order live automation submitted for
  // this setup - null if no submitted attempt is found within the latest 50
  // automation attempts (see _related_execution in radar.py).
  related_execution?: {
    trade_plan_id: string | null;
    bitget_order_id: string | null;
    submitted_at: string | null;
  } | null;
};
