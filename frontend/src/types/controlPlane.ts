import type { BotSettings } from './settings';

export type ControlPlaneSnapshot = {
  generated_at: string;
  source_of_truth: string;
  active_strategy: Record<string, unknown>;
  active_exchange_mode: Record<string, unknown>;
  active_account: Record<string, unknown>;
  active_pairs: ControlPlanePair[];
  active_risk_settings: Record<string, unknown>;
  execution_readiness: Record<string, unknown>;
  live_execution_readiness_checklist?: {
    title: string;
    checks: Record<string, { ready: string; reason: string }>;
    overall_status: string;
    blockers: string[];
    setup_radar_source: string;
  };
  backtest_to_live_config: Record<string, unknown>;
  connection_diagnostics: Record<string, unknown>;
  execution_pathway_trace: Record<string, unknown>;
  live_setup_detection?: Record<string, unknown>;
  live_automation?: Record<string, unknown>;
  last_order_preview?: Record<string, unknown>;
  system_health: Record<string, unknown>;
  settings: BotSettings;
};

export type ControlPlanePair = {
  symbol: string;
  enabled: boolean;
  detected_by_exchange: string;
  market_data_stream_active: string;
  contract_config_loaded?: string;
  last_price: string;
  bid_price?: string;
  ask_price?: string;
  mark_price?: string;
  last_price_update_time: string;
  next_scheduled_refresh_time?: string;
  live_candle_count?: number | string;
  monitoring_status: string;
  timeframe_subscription_status: string;
  active_timeframes: string[];
  last_error: string;
};
