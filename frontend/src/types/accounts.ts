export type ExchangeAccount = {
  account_id: string;
  account_name: string;
  exchange: string;
  api_key: string;
  permissions: string[];
  is_active: boolean;
  is_default: boolean;
  trading_enabled: boolean;
  verification_status: string;
  connection_status?: string;
  last_failed_check_time?: string;
  last_error_code?: string;
  balance?: string;
  available_margin?: string;
  last_successful_api_ping_time?: string;
  last_error?: string;
};

export type AccountPayload = {
  account_name: string;
  api_key: string;
  api_secret: string;
  passphrase: string;
  permissions: string[];
};
