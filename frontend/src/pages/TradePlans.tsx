import { createTradePlan } from '../api/risk';
import { DataTable } from '../components/tables/DataTable';
import type { TradePlan } from '../types/risk';
import type { TradeSignal } from '../types/signals';
import { compactId, formatMoney } from '../utils/formatters';

export function TradePlans({ plans, signals, onRefresh }: { plans: TradePlan[]; signals: TradeSignal[]; onRefresh: () => Promise<void> }) {
  const signal = signals[0];
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-ink">Trade Plans</h1>
        <button className="rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950" disabled={!signal} onClick={async () => { if (signal) { await createTradePlan(signal.signal_id); await onRefresh(); } }}>Create Trade Plan</button>
      </div>
      <DataTable
        rows={plans}
        emptyLabel="No trade plans"
        columns={[
          { header: 'Plan', render: (row) => compactId(row.trade_plan_id) },
          { header: 'Signal', render: (row) => compactId(row.signal_id) },
          { header: 'Symbol', render: (row) => row.symbol },
          { header: 'Status', render: (row) => row.approval_status },
          { header: 'Risk', render: (row) => formatMoney(row.risk_amount) },
          { header: 'Size', render: (row) => row.position_size ?? '—' },
          { header: 'Leverage', render: (row) => row.leverage ?? '—' },
          { header: 'RR', render: (row) => row.rr_ratio ?? '—' },
          { header: 'Stop', render: (row) => row.stop_loss_price ?? '—' },
          { header: 'Target', render: (row) => row.take_profit_price ?? '—' }
        ]}
      />
    </div>
  );
}
