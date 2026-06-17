export type TradePlan = {
  trade_plan_id: string;
  signal_id: string;
  symbol: string;
  approval_status: string;
  risk_amount?: string;
  position_size?: string;
  notional_value?: string;
  leverage?: string;
  rr_ratio?: string;
  stop_loss_price?: string;
  take_profit_price?: string;
  rejection_reasons?: string[];
};
