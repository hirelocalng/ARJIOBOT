export type TradeSignal = {
  signal_id: string;
  setup_id: string;
  symbol: string;
  direction: string;
  action: string;
  status: string;
  validation_passed?: boolean;
  rejection_reason?: string | null;
  entry_reference_price?: string;
  stop_reference_price?: string;
  final_target_price?: string;
  created_at?: string;
};
