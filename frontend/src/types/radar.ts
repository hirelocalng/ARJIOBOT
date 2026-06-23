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
  // Setup Radar spec field names - same data as current_state/progress_percent/
  // created_at/updated_at above, translated to the spec's stage labels and
  // 10/25/40/55/70/85/100 scale (see _display_current_stage in radar.py). Use
  // these for display; current_state/progress_percent remain for sorting/badge
  // tone logic that was already built around the internal 20/35/50/65/80/100 scale.
  current_stage?: string;
  progress_pct?: number;
  // The last stage successfully reached before invalidation, in the same
  // spec label set as current_stage (e.g. "16M_FVG_DETECTED") - null/undefined
  // for setups that were never invalidated.
  last_valid_stage?: string | null;
  swing_detected_at?: string | null;
  last_updated_at?: string | null;
  execution_id?: string | null;
  trade_id?: string | null;
  rr_tp_profile?: string | null;
  // The tap candle's own timestamp - the true moment this setup's chain
  // completed based on price action, not when a later poll happened to
  // evaluate/discover it. Only set once progress reaches 100%.
  completed_at?: string | null;
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
  // null while a real ENTRY_READY setup is still "pending execution" in
  // IN PROGRESS - one of 'trade_opened' | 'rejected' | 'risk_blocked' |
  // 'no_margin' | 'invalidated' | 'expired' once execution has resolved it
  // either way.
  execution_status?: string | null;
  one_trade_per_fvg_status?: string | null;
  rejection_reason?: string | null;
  source?: string | null;
  // Set only when more than one swing resolved to ENTRY_READY in the same
  // poll - this one was queued behind whichever was picked first, and will
  // be picked up automatically on a later poll. Not a permanent skip.
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
