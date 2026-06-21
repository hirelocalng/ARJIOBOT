export type LiveTrade = {
  symbol: string;
  direction: string;
  entry_price: string | null;
  market_price: string | null;
  margin: string | null;
  leverage: string | null;
  stop_loss: string | null;
  take_profit: string | null;
  risk_amount: string | null;
  floating_pnl: string | null;
  position_size: string | null;
  opened_time: string | null;
  bitget_order_id: string | null;
};

export type ClosedTrade = {
  symbol: string;
  direction: string;
  entry_price: string | null;
  exit_price: string | null;
  margin: string | null;
  leverage: string | null;
  realized_pnl: string | null;
  fees: string | null;
  close_reason: string | null;
  opened_time: string | null;
  closed_time: string | null;
  bitget_order_id: string | null;
};

export type PnlSummary = {
  total_profit: string;
  total_loss: string;
  net_profit: string;
  win_count: number;
  loss_count: number;
  win_ratio: number;
  win_percentage: number;
  average_win: string;
  average_loss: string;
  total_trades: number;
  open_floating_pnl: string;
  realized_pnl: string;
};
