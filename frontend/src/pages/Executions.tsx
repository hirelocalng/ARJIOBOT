import { cancelExecution, paperExecute } from '../api/execution';
import type { BitgetOrdersResponse } from '../api/bitget';
import { DataTable } from '../components/tables/DataTable';
import { StatusBadge } from '../components/layout/StatusBadge';
import type { ExecutionRecord } from '../types/execution';
import type { TradePlan } from '../types/risk';
import { compactId } from '../utils/formatters';
import { confirmDangerousAction } from '../utils/safety';

const TERMINAL_STATUSES = new Set(['CANCELLED', 'REJECTED', 'FAILED']);

export function Executions({
  executions,
  plans,
  bitgetOrders,
  onRefresh
}: {
  executions: ExecutionRecord[];
  plans: TradePlan[];
  bitgetOrders: BitgetOrdersResponse | null;
  onRefresh: () => Promise<void>;
}) {
  const approved = plans.find((plan) => plan.approval_status === 'APPROVED');
  const activeExecutions = executions.filter((row) => row.is_active ?? !TERMINAL_STATUSES.has(row.status));
  const closedExecutions = executions.filter((row) => !(row.is_active ?? !TERMINAL_STATUSES.has(row.status)));
  const liveOrders = bitgetOrders?.orders ?? [];
  const liveBlockedOrders = bitgetOrders?.blocked_orders ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Executions</h1>
          <p className="text-sm text-warning">PAPER MODE. No real orders placed unless live trading is armed.</p>
        </div>
        <button className="rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950" disabled={!approved} onClick={async () => { if (approved) { await paperExecute(approved.trade_plan_id); await onRefresh(); } }}>Paper Execute</button>
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold uppercase text-muted">Active Trades ({activeExecutions.length} paper, {liveOrders.length} live)</h2>
        <DataTable
          rows={[
            ...activeExecutions.map((row) => ({ kind: 'paper' as const, row })),
            ...liveOrders.map((row) => ({ kind: 'live' as const, row }))
          ]}
          emptyLabel="No active trades"
          columns={[
            { header: 'Source', render: (item) => <StatusBadge label={item.kind === 'live' ? 'LIVE' : 'PAPER'} tone={item.kind === 'live' ? 'warn' : 'neutral'} /> },
            { header: 'ID', render: (item) => item.kind === 'live' ? compactId(String(item.row.bitget_order_id || item.row.generated_at || '')) : compactId(item.row.execution_id) },
            { header: 'Symbol', render: (item) => item.row.symbol },
            { header: 'Side/Status', render: (item) => item.kind === 'live' ? String(item.row.side) : item.row.status },
            { header: 'Entry', render: (item) => item.kind === 'live' ? String(item.row.entry_price ?? '—') : (item.row.fill_price ?? '—') },
            { header: 'Size', render: (item) => item.kind === 'live' ? String(item.row.size ?? '—') : (item.row.filled_size ?? '—') },
            { header: 'Stop', render: (item) => item.kind === 'live' ? String(item.row.stop_reference ?? '—') : (item.row.stop_loss_price ?? '—') },
            { header: 'Target', render: (item) => item.kind === 'live' ? String(item.row.target_reference ?? '—') : (item.row.take_profit_price ?? '—') },
            { header: 'Leverage', render: (item) => item.kind === 'live' ? String(item.row.leverage ?? '—') : '—' },
            { header: 'Exchange Order ID', render: (item) => item.kind === 'live' ? compactId(String(item.row.bitget_order_id ?? '')) : compactId(item.row.exchange_order_id ?? '') },
            { header: 'Created', render: (item) => (item.kind === 'live' ? String(item.row.generated_at ?? '') : (item.row.created_at ?? '')).replace('T', ' ').slice(0, 19) || '—' },
            {
              header: 'Cancel',
              render: (item) =>
                item.kind === 'paper' ? (
                  <button className="text-warning" onClick={async () => { if (confirmDangerousAction('Cancel execution record?')) { await cancelExecution(item.row.execution_id); await onRefresh(); } }}>Cancel</button>
                ) : (
                  '—'
                )
            }
          ]}
        />
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold uppercase text-muted">Closed / Rejected Trades ({closedExecutions.length} paper, {liveBlockedOrders.length} live)</h2>
        <DataTable
          rows={[
            ...closedExecutions.map((row) => ({ kind: 'paper' as const, row })),
            ...liveBlockedOrders.map((row) => ({ kind: 'live-blocked' as const, row }))
          ]}
          emptyLabel="No closed or rejected trades"
          columns={[
            { header: 'Source', render: (item) => <StatusBadge label={item.kind === 'live-blocked' ? 'LIVE BLOCKED' : 'PAPER'} tone="danger" /> },
            { header: 'ID', render: (item) => item.kind === 'live-blocked' ? compactId(String(item.row.created_at ?? '')) : compactId(item.row.execution_id) },
            { header: 'Symbol', render: (item) => item.row.symbol },
            { header: 'Status/Mode', render: (item) => item.kind === 'live-blocked' ? `${item.row.selected_trade_mode} (needed ${item.row.required_trade_mode})` : item.row.status },
            { header: 'Reason', render: (item) => item.kind === 'live-blocked' ? item.row.reason : (item.row.rejection_reason ?? '—') },
            { header: 'Fill/Stop/Target', render: (item) => item.kind === 'live-blocked' ? '—' : `${item.row.fill_price ?? '—'} / ${item.row.stop_loss_price ?? '—'} / ${item.row.take_profit_price ?? '—'}` },
            { header: 'When', render: (item) => (item.kind === 'live-blocked' ? String(item.row.created_at ?? '') : (item.row.rejected_at ?? item.row.cancelled_at ?? item.row.created_at ?? '')).replace('T', ' ').slice(0, 19) || '—' }
          ]}
        />
      </div>
    </div>
  );
}
