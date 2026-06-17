import { MetricCard } from '../components/cards/MetricCard';
import { WarningCard } from '../components/cards/WarningCard';
import type { ExchangeAccount } from '../types/accounts';
import type { BacktestRun } from '../types/backtesting';
import type { BotStatus } from '../types/common';
import type { ExecutionRecord } from '../types/execution';
import type { MonitoredPair } from '../types/pairs';
import type { RadarSetup } from '../types/radar';
import type { TradePlan } from '../types/risk';
import type { TradeSignal } from '../types/signals';
import type { ControlPlaneSnapshot } from '../types/controlPlane';

type Props = { status: BotStatus | null; accounts: ExchangeAccount[]; pairs: MonitoredPair[]; setups: RadarSetup[]; signals: TradeSignal[]; plans: TradePlan[]; executions: ExecutionRecord[]; runs: BacktestRun[]; apiError: string | null; controlPlane: ControlPlaneSnapshot | null };

export function Dashboard({ status, accounts, pairs, setups, signals, plans, executions, runs, apiError, controlPlane }: Props) {
  const entryReady = setups.filter((setup) => setup.current_state === 'ENTRY_READY').length;
  const above70 = setups.filter((setup) => setup.progress_percent >= 70).length;
  const approvedPlans = plans.filter((plan) => plan.approval_status === 'APPROVED').length;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-ink">Dashboard</h1>
        <p className="text-sm text-muted">Pipeline monitor for the private ArjioBot VPS.</p>
      </div>
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-5">
        <MetricCard label="Bot Status" value={status?.api_status ?? 'offline'} />
        <MetricCard label="Active Profile" value={String(controlPlane?.active_strategy.selected_profile ?? 'None')} detail={String(controlPlane?.active_strategy.profile_lock_status ?? 'UNKNOWN')} />
        <MetricCard label="Execution Mode" value={String(controlPlane?.active_exchange_mode.selected_trade_mode ?? status?.adapter_mode ?? 'OFF')} detail={`Environment lock ${String(controlPlane?.active_exchange_mode.environment_lock_verified ?? 'NO')}`} />
        <MetricCard label="Account" value={String(controlPlane?.active_account.connection_status ?? 'NOT CONNECTED')} detail={String(controlPlane?.active_account.account_name ?? 'None')} />
        <MetricCard label="Pairs" value={pairs.filter((pair) => pair.enabled).length} detail={`${pairs.length} configured`} />
        <MetricCard label="Active Setups" value={setups.length} />
        <MetricCard label="Setups Above 70%" value={above70} />
        <MetricCard label="Entry Ready" value={entryReady} />
        <MetricCard label="Signals" value={signals.length} />
        <MetricCard label="Approved Plans" value={approvedPlans} />
        <MetricCard label="Paper Executions" value={executions.length} />
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        {controlPlane?.execution_readiness.execution_ready !== 'YES' && <WarningCard title="Execution blocked" message={String(controlPlane?.execution_pathway_trace.blocked_reason ?? 'Control plane is not ready.')} />}
        {!status?.live_trading_enabled && <WarningCard title="Live trading disabled" message="Current active mode is not LIVE unless the control center says otherwise." />}
        {!accounts.some((account) => account.is_default) && <WarningCard title="No default Bitget account" message="Set a default account before future live workflows are enabled." />}
        {!pairs.length && <WarningCard title="No pairs monitored" message="Add BTCUSDT, ETHUSDT, SOLUSDT, or XRPUSDT to start radar monitoring." />}
        {apiError && <WarningCard title="API route unavailable" message={apiError} />}
      </div>
      <MetricCard label="Latest Backtest Result" value={runs[0]?.status ?? 'No runs'} detail={runs[0]?.run_id} />
    </div>
  );
}
