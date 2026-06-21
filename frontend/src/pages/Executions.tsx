import { useEffect, useState } from 'react';
import { cancelExecution, paperExecute } from '../api/execution';
import { getClosedTrades, getLiveTrades, getPnlSummary } from '../api/trades';
import { DataTable } from '../components/tables/DataTable';
import type { ExecutionRecord } from '../types/execution';
import type { TradePlan } from '../types/risk';
import type { ClosedTrade, LiveTrade, PnlSummary } from '../types/trades';
import { compactId } from '../utils/formatters';
import { confirmDangerousAction } from '../utils/safety';

type Tab = 'LIVE_TRADES' | 'CLOSED_TRADES' | 'PNL';

function StatCard({ label, value, tone }: { label: string; value: string; tone?: 'ok' | 'danger' }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-panel p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-2 text-2xl font-semibold ${tone === 'ok' ? 'text-success' : tone === 'danger' ? 'text-danger' : 'text-ink'}`}>{value}</div>
    </div>
  );
}

export function Executions({
  executions,
  plans,
  onRefresh
}: {
  executions: ExecutionRecord[];
  plans: TradePlan[];
  onRefresh: () => Promise<void>;
}) {
  const [tab, setTab] = useState<Tab>('LIVE_TRADES');
  const [liveTrades, setLiveTrades] = useState<LiveTrade[]>([]);
  const [closedTrades, setClosedTrades] = useState<ClosedTrade[]>([]);
  const [pnl, setPnl] = useState<PnlSummary | null>(null);
  const [status, setStatus] = useState('Not loaded yet');
  const [loading, setLoading] = useState(false);

  async function loadRealTradeData() {
    setLoading(true);
    setStatus('Fetching real Bitget data...');
    try {
      const [live, closed, pnlSummary] = await Promise.all([getLiveTrades(), getClosedTrades(), getPnlSummary()]);
      setLiveTrades(live.trades);
      setClosedTrades(closed.trades);
      setPnl(pnlSummary);
      setStatus(`Loaded ${live.count} live, ${closed.count} closed trade(s) - ${new Date().toLocaleTimeString()}`);
    } catch (error) {
      setStatus(error instanceof Error ? `Failed to load: ${error.message}` : 'Failed to load real trade data');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadRealTradeData();
    // Real Bitget calls, on demand only - not part of the app-wide 5s poll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const approved = plans.find((plan) => plan.approval_status === 'APPROVED');
  const tabs: { id: Tab; label: string }[] = [
    { id: 'LIVE_TRADES', label: `Live Trades (${liveTrades.length})` },
    { id: 'CLOSED_TRADES', label: `Closed Trades (${closedTrades.length})` },
    { id: 'PNL', label: 'PnL' }
  ];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Executions</h1>
          <p className="text-sm text-muted">{status}</p>
        </div>
        <div className="flex gap-2">
          <button className="rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950 disabled:opacity-50" disabled={loading} onClick={() => void loadRealTradeData()}>
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
          <button className="rounded-md bg-slate-700 px-3 py-2 text-sm font-semibold text-slate-100 disabled:opacity-50" disabled={!approved} onClick={async () => { if (approved) { await paperExecute(approved.trade_plan_id); await onRefresh(); } }}>
            Paper Execute
          </button>
        </div>
      </div>

      <div className="flex gap-2">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`rounded-md border px-4 py-2 text-sm font-semibold transition-colors ${tab === t.id ? 'border-action bg-action/10 text-action' : 'border-slate-800 bg-panel text-muted hover:text-ink'}`}
          >
            {t.label.toUpperCase()}
          </button>
        ))}
      </div>

      {tab === 'LIVE_TRADES' && (
        <DataTable
          rows={liveTrades}
          emptyLabel="NO LIVE TRADES OPEN"
          columns={[
            { header: 'Pair', render: (row) => row.symbol },
            { header: 'Direction', render: (row) => row.direction },
            { header: 'Entry Price', render: (row) => row.entry_price ?? '-' },
            { header: 'Market Price', render: (row) => row.market_price ?? '-' },
            { header: 'Margin', render: (row) => row.margin ?? '-' },
            { header: 'Leverage', render: (row) => row.leverage ?? '-' },
            { header: 'Stop Loss', render: (row) => row.stop_loss ?? '-' },
            { header: 'Take Profit', render: (row) => row.take_profit ?? '-' },
            { header: 'Risk Amount', render: (row) => row.risk_amount ?? '-' },
            { header: 'Floating PnL', render: (row) => row.floating_pnl ?? '-' },
            { header: 'Position Size', render: (row) => row.position_size ?? '-' },
            { header: 'Opened', render: (row) => row.opened_time ?? '-' },
            { header: 'Order ID', render: (row) => <span title={row.bitget_order_id ?? ''}>{compactId(row.bitget_order_id ?? '')}</span> }
          ]}
        />
      )}

      {tab === 'CLOSED_TRADES' && (
        <DataTable
          rows={closedTrades}
          emptyLabel="NO CLOSED TRADES YET"
          columns={[
            { header: 'Pair', render: (row) => row.symbol },
            { header: 'Direction', render: (row) => row.direction },
            { header: 'Entry Price', render: (row) => row.entry_price ?? '-' },
            { header: 'Exit Price', render: (row) => row.exit_price ?? '-' },
            { header: 'Margin', render: (row) => row.margin ?? '-' },
            { header: 'Leverage', render: (row) => row.leverage ?? '-' },
            { header: 'Realized PnL', render: (row) => row.realized_pnl ?? '-' },
            { header: 'Fees', render: (row) => row.fees ?? '-' },
            { header: 'Close Reason', render: (row) => row.close_reason ?? '-' },
            { header: 'Opened', render: (row) => row.opened_time ?? '-' },
            { header: 'Closed', render: (row) => row.closed_time ?? '-' },
            { header: 'Order ID', render: (row) => <span title={row.bitget_order_id ?? ''}>{compactId(row.bitget_order_id ?? '')}</span> }
          ]}
        />
      )}

      {tab === 'PNL' && (
        <div className="grid gap-3 md:grid-cols-4">
          <StatCard label="Total Profit" value={pnl?.total_profit ?? '-'} tone="ok" />
          <StatCard label="Total Loss" value={pnl?.total_loss ?? '-'} tone="danger" />
          <StatCard label="Net Profit" value={pnl?.net_profit ?? '-'} tone={pnl && Number(pnl.net_profit) >= 0 ? 'ok' : 'danger'} />
          <StatCard label="Win Count" value={String(pnl?.win_count ?? 0)} />
          <StatCard label="Loss Count" value={String(pnl?.loss_count ?? 0)} />
          <StatCard label="Win Ratio" value={pnl ? pnl.win_ratio.toFixed(2) : '-'} />
          <StatCard label="Win Percentage" value={pnl ? `${pnl.win_percentage.toFixed(1)}%` : '-'} />
          <StatCard label="Total Trades" value={String(pnl?.total_trades ?? 0)} />
          <StatCard label="Average Win" value={pnl?.average_win ?? '-'} tone="ok" />
          <StatCard label="Average Loss" value={pnl?.average_loss ?? '-'} tone="danger" />
          <StatCard label="Open Floating PnL" value={pnl?.open_floating_pnl ?? '-'} />
          <StatCard label="Realized PnL" value={pnl?.realized_pnl ?? '-'} />
        </div>
      )}

      <div>
        <h2 className="mb-2 text-sm font-semibold uppercase text-muted">Paper Executions ({executions.length})</h2>
        <DataTable
          rows={executions}
          emptyLabel="No paper execution records"
          columns={[
            { header: 'Execution', render: (row) => compactId(row.execution_id) },
            { header: 'Symbol', render: (row) => row.symbol },
            { header: 'Status', render: (row) => row.status },
            { header: 'Fill', render: (row) => row.fill_price ?? '-' },
            { header: 'Size', render: (row) => row.filled_size ?? '-' },
            { header: 'Stop', render: (row) => row.stop_loss_price ?? '-' },
            { header: 'Target', render: (row) => row.take_profit_price ?? '-' },
            {
              header: 'Cancel',
              render: (row) => (
                <button className="text-warning" onClick={async () => { if (confirmDangerousAction('Cancel execution record?')) { await cancelExecution(row.execution_id); await onRefresh(); } }}>
                  Cancel
                </button>
              )
            }
          ]}
        />
      </div>
    </div>
  );
}
