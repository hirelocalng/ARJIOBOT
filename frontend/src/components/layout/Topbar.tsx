import type { BotStatus } from '../../types/common';
import type { ExchangeAccount } from '../../types/accounts';
import { StatusBadge } from './StatusBadge';

type Props = { status: BotStatus | null; defaultAccount?: ExchangeAccount };

export function Topbar({ status, defaultAccount }: Props) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 bg-slate-950/70 px-3 py-3 sm:px-6 sm:py-4">
      <div>
        <div className="text-sm text-muted">System Status</div>
        <div className="text-base font-semibold text-ink">{status?.api_status ?? 'loading'}</div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge label={`Adapter ${status?.adapter_mode ?? 'MOCK'}`} tone="neutral" />
        <StatusBadge label={status?.live_trading_enabled ? 'Live enabled' : 'Live disabled'} tone={status?.live_trading_enabled ? 'danger' : 'ok'} />
        <StatusBadge label={`Active Account ${defaultAccount?.account_name ?? 'NONE'}`} tone={defaultAccount ? 'ok' : 'warn'} />
        <StatusBadge label={`Account ${defaultAccount?.connection_status ?? defaultAccount?.verification_status ?? 'NOT CONNECTED'}`} tone={defaultAccount?.connection_status === 'CONNECTED' ? 'ok' : 'warn'} />
        <StatusBadge label={`${status?.monitored_pairs_count ?? 0} pairs`} tone="neutral" />
      </div>
    </header>
  );
}
