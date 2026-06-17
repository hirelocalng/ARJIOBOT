export type AccountStatusSummary = {
  account_connection: Record<string, unknown>;
  balance: Record<string, unknown>;
  margin_mode: Record<string, unknown>;
  position_mode: Record<string, unknown>;
  order_type_price_type: Record<string, unknown>;
  leverage: Record<string, unknown>;
  open_positions: {
    status?: string;
    position_count?: number;
    positions?: Record<string, unknown>[];
    last_updated?: string;
  };
  open_orders: {
    status?: string;
    order_count?: number;
    orders?: Record<string, unknown>[];
    last_updated?: string;
  };
  risk_status: Record<string, unknown>;
  data_freshness: Record<string, unknown>;
};
