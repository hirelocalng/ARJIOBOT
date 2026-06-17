import { cancelExecution, paperExecute } from '../api/execution';
import { DataTable } from '../components/tables/DataTable';
import type { ExecutionRecord } from '../types/execution';
import type { TradePlan } from '../types/risk';
import { compactId } from '../utils/formatters';
import { confirmDangerousAction } from '../utils/safety';

export function Executions({ executions, plans, onRefresh }: { executions: ExecutionRecord[]; plans: TradePlan[]; onRefresh: () => Promise<void> }) {
  const approved = plans.find((plan) => plan.approval_status === 'APPROVED');
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Executions</h1>
          <p className="text-sm text-warning">PAPER MODE. No real orders placed.</p>
        </div>
        <button className="rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950" disabled={!approved} onClick={async () => { if (approved) { await paperExecute(approved.trade_plan_id); await onRefresh(); } }}>Paper Execute</button>
      </div>
      <DataTable
        rows={executions}
        emptyLabel="No execution records"
        columns={[
          { header: 'Execution', render: (row) => compactId(row.execution_id) },
          { header: 'Plan', render: (row) => compactId(row.trade_plan_id) },
          { header: 'Symbol', render: (row) => row.symbol },
          { header: 'Status', render: (row) => row.status },
          { header: 'Paper', render: (row) => row.paper_execution ? 'Yes' : 'No' },
          { header: 'Fill', render: (row) => row.fill_price ?? '—' },
          { header: 'Size', render: (row) => row.filled_size ?? '—' },
          { header: 'Stop', render: (row) => row.stop_loss_price ?? '—' },
          { header: 'Target', render: (row) => row.take_profit_price ?? '—' },
          { header: 'Cancel', render: (row) => <button className="text-warning" onClick={async () => { if (confirmDangerousAction('Cancel execution record?')) { await cancelExecution(row.execution_id); await onRefresh(); } }}>Cancel</button> }
        ]}
      />
    </div>
  );
}
