import { generateSignal } from '../api/signals';
import { DataTable } from '../components/tables/DataTable';
import type { RadarSetup } from '../types/radar';
import type { TradeSignal } from '../types/signals';
import { compactId } from '../utils/formatters';

export function Signals({ signals, setups, onRefresh }: { signals: TradeSignal[]; setups: RadarSetup[]; onRefresh: () => Promise<void> }) {
  const readySetup = setups.find((setup) => setup.current_state === 'ENTRY_READY');
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-ink">Signals</h1>
        <button className="rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950" disabled={!readySetup} onClick={async () => { if (readySetup) { await generateSignal(readySetup.setup_id); await onRefresh(); } }}>Generate From ENTRY_READY</button>
      </div>
      <DataTable
        rows={signals}
        emptyLabel="No generated signals"
        columns={[
          { header: 'Signal', render: (row) => compactId(row.signal_id) },
          { header: 'Setup', render: (row) => compactId(row.setup_id) },
          { header: 'Symbol', render: (row) => row.symbol },
          { header: 'Direction', render: (row) => row.direction },
          { header: 'Action', render: (row) => row.action },
          { header: 'Status', render: (row) => row.status },
          { header: 'Rejection', render: (row) => row.rejection_reason ?? '—' }
        ]}
      />
    </div>
  );
}
