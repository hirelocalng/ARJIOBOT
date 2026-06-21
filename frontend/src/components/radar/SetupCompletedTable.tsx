import type { RadarSetup } from '../../types/radar';
import { DataTable } from '../tables/DataTable';
import { StatusBadge } from '../layout/StatusBadge';

// ENTRY_READY is the real, live-tradable setup automation will act on
// (_setup_from_trade); COMPLETED is the attempt-tracker's own "this swing's
// chain finished successfully" marker (_apply_one_attempt_trace) - a
// separate row for the same kind of event. Both reached 100%, so both land
// in this tab, but only ENTRY_READY rows are actually pending execution.
function actionLabel(status?: string): string {
  return status === 'ENTRY_READY' ? 'Pending execution' : 'Structural match';
}

export function SetupCompletedTable({ setups, onSelect }: { setups: RadarSetup[]; onSelect?: (setup: RadarSetup) => void }) {
  const sorted = [...setups].sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? ''));
  return (
    <DataTable
      rows={sorted}
      emptyLabel="NO COMPLETED SETUPS YET"
      columns={[
        { header: 'Pair', render: (row) => <button className="text-action font-semibold" onClick={() => onSelect?.(row)}>{row.symbol}</button> },
        { header: 'Timeframe', render: (row) => row.timeframe_profile ?? '-' },
        { header: 'Completed %', render: (row) => `${row.progress_percent.toFixed(0)}%` },
        { header: 'Entry Price', render: (row) => row.entry_price ?? '-' },
        { header: 'Type', render: (row) => row.direction },
        { header: 'Time Completed', render: (row) => row.updated_at?.replace('T', ' ').slice(0, 19) ?? '-' },
        { header: 'Action', render: (row) => <StatusBadge label={actionLabel(row.status)} tone={row.status === 'ENTRY_READY' ? 'ok' : 'neutral'} /> }
      ]}
    />
  );
}
