import type { RadarSetup } from '../../types/radar';
import { DataTable } from '../tables/DataTable';
import { StatusBadge } from '../layout/StatusBadge';
import { DEFAULT_PRODUCTION_PROFILE } from '../../utils/constants';
import { compactId } from '../../utils/formatters';

// A real ENTRY_READY setup only ever reaches this table once live_automation
// has actually resolved it - execution_status is 'trade_opened' (a confirmed
// live trade) or 'rejected'/'risk_blocked'/'no_margin' (explicitly rejected) -
// see should_leave_in_progress (setup_tracker/setup_models.py) and
// live_automation.py's _process_setup/_resolve_rejected_setup. It is never
// 'Pending execution' here anymore - that stays in the In Progress table
// (SetupRadarTable.tsx) until execution resolves it.
// COMPLETED (attempt-tracker's own "this swing's chain finished successfully"
// marker, _apply_one_attempt_trace) never sets execution_status at all - a
// separate row for the same kind of event. Once a real ENTRY_READY setup is
// tracked for a swing, the backend removes that swing's COMPLETED row
// (_suppress_redundant_attempt_trace), so in steady state only one of the
// two ever lands here per swing.
// row.stale_skip is no longer "this trade was skipped and will never run" -
// it now only means "more than one swing resolved in the same poll, this
// one is queued and will be picked up automatically on a later poll" (see
// _stale_trade_candidates). It is a backlog-size signal, not a dead end.
const REJECTED_EXECUTION_STATUSES = new Set(['rejected', 'risk_blocked', 'no_margin']);

function executionStatus(row: RadarSetup): string {
  if (row.execution_status === 'trade_opened') return 'Executed';
  if (row.execution_status && REJECTED_EXECUTION_STATUSES.has(row.execution_status)) return `Rejected (${row.execution_status})`;
  if (row.related_execution) return 'Executed';
  if (row.stale_skip) return 'Queued (backlog)';
  return 'Structural match';
}

function executionTone(row: RadarSetup): 'ok' | 'warn' | 'danger' | 'neutral' {
  if (row.execution_status === 'trade_opened') return 'ok';
  if (row.execution_status && REJECTED_EXECUTION_STATUSES.has(row.execution_status)) return 'danger';
  if (row.related_execution) return 'ok';
  if (row.stale_skip) return 'neutral';
  return 'neutral';
}

export function SetupCompletedTable({ setups, onSelect }: { setups: RadarSetup[]; onSelect?: (setup: RadarSetup) => void }) {
  const sorted = [...setups].sort((a, b) => (b.completed_at ?? b.updated_at ?? '').localeCompare(a.completed_at ?? a.updated_at ?? ''));
  return (
    <DataTable
      rows={sorted}
      emptyLabel="NO COMPLETED SETUPS YET"
      columns={[
        { header: 'Pair', render: (row) => <button className="text-action font-semibold" onClick={() => onSelect?.(row)}>{row.symbol}</button> },
        { header: 'Direction', render: (row) => row.direction },
        { header: 'Completed %', render: (row) => `${row.progress_percent.toFixed(0)}%` },
        {
          header: 'Time Completed',
          // completed_at is the tap candle's own timestamp - the true moment
          // this setup's chain finished based on price action. updated_at is
          // only a fallback for any row from before this field existed.
          render: (row) => (row.completed_at ?? row.updated_at)?.replace('T', ' ').slice(0, 19) ?? '-'
        },
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
          header: 'Backlog Queue Detail',
          render: (row) =>
            row.stale_skip ? (
              <div className="text-xs text-amber-200">
                <div>{row.stale_skip.candles_past_window} candle{row.stale_skip.candles_past_window === 1 ? '' : 's'} / {row.stale_skip.seconds_past_window}s old when another candidate was picked first this poll</div>
                <div className="text-slate-400">queued at {row.stale_skip.skipped_at.replace('T', ' ').slice(0, 19)}</div>
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
