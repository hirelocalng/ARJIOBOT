import type { RadarSetup } from '../../types/radar';
import { DataTable } from '../tables/DataTable';
import { StatusBadge } from '../layout/StatusBadge';
import { DEFAULT_PRODUCTION_PROFILE } from '../../utils/constants';

// This table only ever receives INVALIDATED/EXPIRED rows now (SetupRadar.tsx
// routes COMPLETED/ENTRY_READY to the In Progress table instead), but tone by
// status rather than hardcoding 'danger' in case EXPIRED rows are added back.
function statusTone(status?: string): 'warn' | 'danger' | 'neutral' {
  if (status === 'EXPIRED') return 'warn';
  if (status === 'INVALIDATED') return 'danger';
  return 'neutral';
}

export function SetupHistoryTable({ setups, onSelect }: { setups: RadarSetup[]; onSelect?: (setup: RadarSetup) => void }) {
  const sorted = [...setups].sort((a, b) => (b.invalidated_at ?? b.updated_at ?? '').localeCompare(a.invalidated_at ?? a.updated_at ?? ''));
  return (
    <DataTable
      rows={sorted}
      emptyLabel="NO INVALIDATED SETUPS YET"
      columns={[
        { header: 'Pair', render: (row) => <button className="text-action font-semibold" onClick={() => onSelect?.(row)}>{row.symbol}</button> },
        { header: 'Type', render: (row) => row.direction },
        { header: 'Invalidation Reason', render: (row) => row.invalidation_reason ?? row.rejection_reason ?? '-' },
        { header: 'Completed %', render: (row) => `${row.progress_percent.toFixed(0)}%` },
        { header: 'Failed/Final Stage', render: (row) => <StatusBadge label={row.current_state} tone={statusTone(row.status)} /> },
        { header: 'Strategy Profile', render: (row) => row.strategy_profile ?? DEFAULT_PRODUCTION_PROFILE },
        { header: 'Timeframe Profile', render: (row) => row.timeframe_profile ?? '-' },
        { header: 'RR/TP Model', render: (row) => row.selected_tp_model ?? '-' },
        { header: 'Time Added', render: (row) => row.created_at?.replace('T', ' ').slice(0, 19) ?? '-' },
        { header: 'When Failed', render: (row) => (row.invalidated_at ?? row.updated_at)?.replace('T', ' ').slice(0, 19) ?? '-' }
      ]}
    />
  );
}
