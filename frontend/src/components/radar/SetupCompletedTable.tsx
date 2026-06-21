import type { RadarSetup } from '../../types/radar';
import { DataTable } from '../tables/DataTable';
import { StatusBadge } from '../layout/StatusBadge';
import { DEFAULT_PRODUCTION_PROFILE } from '../../utils/constants';
import { compactId } from '../../utils/formatters';

// ENTRY_READY is the real, live-tradable setup automation will act on
// (_setup_from_trade); COMPLETED is the attempt-tracker's own "this swing's
// chain finished successfully" marker (_apply_one_attempt_trace) - a
// separate row for the same kind of event. Both reached 100%, so both land
// in this tab, but only ENTRY_READY rows are actually pending execution.
// A COMPLETED row whose matching real trade candidate got skipped for being
// stale (see stale_skip) never got an ENTRY_READY counterpart at all - that
// case is called out explicitly rather than just labeled "Structural match",
// since otherwise there is no way to tell "fully passed, no trade attempted
// yet" apart from "fully passed, a trade was found and then missed".
function executionStatus(row: RadarSetup): string {
  if (row.related_execution) return 'Executed';
  if (row.status === 'ENTRY_READY') return 'Pending execution';
  if (row.stale_skip) return 'Skipped (stale)';
  return 'Structural match';
}

function executionTone(row: RadarSetup): 'ok' | 'warn' | 'neutral' {
  if (row.related_execution) return 'ok';
  if (row.status === 'ENTRY_READY') return 'ok';
  if (row.stale_skip) return 'warn';
  return 'neutral';
}

export function SetupCompletedTable({ setups, onSelect }: { setups: RadarSetup[]; onSelect?: (setup: RadarSetup) => void }) {
  const sorted = [...setups].sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? ''));
  return (
    <DataTable
      rows={sorted}
      emptyLabel="NO COMPLETED SETUPS YET"
      columns={[
        { header: 'Pair', render: (row) => <button className="text-action font-semibold" onClick={() => onSelect?.(row)}>{row.symbol}</button> },
        { header: 'Direction', render: (row) => row.direction },
        { header: 'Completed %', render: (row) => `${row.progress_percent.toFixed(0)}%` },
        { header: 'Time Completed', render: (row) => row.updated_at?.replace('T', ' ').slice(0, 19) ?? '-' },
        { header: 'Execution Status', render: (row) => <StatusBadge label={executionStatus(row)} tone={executionTone(row)} /> },
        { header: 'Strategy Profile', render: (row) => row.strategy_profile ?? DEFAULT_PRODUCTION_PROFILE },
        { header: 'Timeframe Profile', render: (row) => row.timeframe_profile ?? '-' },
        { header: 'RR/TP Profile', render: (row) => row.selected_tp_model ?? '-' },
        { header: 'Setup ID', render: (row) => <span title={row.setup_id}>{compactId(row.setup_id)}</span> },
        {
          header: 'Related Trade/Order ID',
          render: (row) =>
            row.related_execution ? (
              <span title={row.related_execution.bitget_order_id ?? row.related_execution.trade_plan_id ?? ''}>
                {compactId(row.related_execution.bitget_order_id ?? row.related_execution.trade_plan_id ?? '')}
              </span>
            ) : (
              '-'
            )
        },
        {
          header: 'Stale Skip Detail',
          render: (row) =>
            row.stale_skip ? (
              <div className="text-xs text-amber-200">
                <div>{row.stale_skip.candles_past_window} candle{row.stale_skip.candles_past_window === 1 ? '' : 's'} / {row.stale_skip.seconds_past_window}s past the freshness window</div>
                <div className="text-slate-400">skipped at {row.stale_skip.skipped_at.replace('T', ' ').slice(0, 19)}</div>
                <div className={row.stale_skip.likely_restart_related ? 'text-sky-300' : 'text-rose-300'}>
                  {row.stale_skip.likely_restart_related
                    ? `likely restart catch-up (${Math.round(row.stale_skip.seconds_since_monitoring_started ?? 0)}s into this session)`
                    : 'NOT near a restart - happened mid-session'}
                </div>
              </div>
            ) : (
              '-'
            )
        }
      ]}
    />
  );
}
