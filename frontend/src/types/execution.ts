export type ExecutionRecord = {
  execution_id: string;
  trade_plan_id: string;
  symbol: string;
  status: string;
  paper_execution: boolean;
  fill_price?: string;
  filled_size?: string;
  stop_loss_price?: string;
  take_profit_price?: string;
  rejection_reason?: string | null;
};
