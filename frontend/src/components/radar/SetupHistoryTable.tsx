import type { RadarSetup } from '../../types/radar';
import { DataTable } from '../tables/DataTable';
import { StatusBadge } from '../layout/StatusBadge';
import { DEFAULT_PRODUCTION_PROFILE } from '../../utils/constants';

function statusTone(status?: string): 'ok' | 'warn' | 'danger' | 'neutral' {
  if (status === 'COMPLETED' || status === 'ENTRY_READY') return 'ok';
  if (status === 'EXPIRED') return 'warn';
  if (status === 'INVALIDATED') return 'danger';
  return 'neutral';
}

export function SetupHistoryTable({ setups, onSelect }: { setups: RadarSetup[]; onSelect?: (setup: RadarSetup) => void }) {
  const sorted = [...setups].sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? ''));
  return (
    <DataTable
      rows={sorted}
      emptyLabel="NO SETUP ATTEMPT HISTORY YET"
      columns={[
        { header: 'Symbol', render: (row) => <button className="text-action font-semibold" onClick={() => onSelect?.(row)}>{row.symbol}</button> },
        { header: 'Direction', render: (row) => row.direction },
        { header: 'Max Progress', render: (row) => `${row.progress_percent.toFixed(0)}%` },
        { header: 'Failed/Final Stage', render: (row) => <StatusBadge label={row.current_state} tone={statusTone(row.status)} /> },
        { header: 'Reason', render: (row) => row.invalidation_reason ?? row.rejection_reason ?? '-' },
        { header: 'Strategy Profile', render: (row) => row.strategy_profile ?? DEFAULT_PRODUCTION_PROFILE },
        { header: 'Timeframe Profile', render: (row) => row.timeframe_profile ?? '-' },
        { header: 'RR/TP Model', render: (row) => row.selected_tp_model ?? '-' },
        { header: 'Created', render: (row) => row.created_at?.replace('T', ' ').slice(0, 19) ?? '-' },
        { header: 'Updated', render: (row) => row.updated_at?.replace('T', ' ').slice(0, 19) ?? '-' }
      ]}
    />
  );
}
