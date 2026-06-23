import type { RadarSetup } from '../../types/radar';
import { DataTable } from '../tables/DataTable';
import { StatusBadge } from '../layout/StatusBadge';
import { SetupProgressBar } from './SetupProgressBar';
import { DEFAULT_PRODUCTION_PROFILE } from '../../utils/constants';
import { friendlyStageLabel } from '../../utils/setupStage';

// A real ENTRY_READY setup (_setup_from_trade) stays here, not in Completed,
// for as long as live_automation hasn't yet confirmed a trade opened or
// explicitly rejected it - "Pending execution" is not a terminal state (see
// should_leave_in_progress, setup_tracker/setup_models.py), so it must keep
// showing its 100% progress bar in IN PROGRESS instead of disappearing.
function executionBadge(row: RadarSetup): { label: string; tone: 'ok' | 'warn' | 'neutral' } | null {
  if (row.status !== 'ENTRY_READY') return null;
  return { label: 'Pending execution', tone: 'ok' };
}

export function SetupRadarTable({ setups, onSelect }: { setups: RadarSetup[]; onSelect?: (setup: RadarSetup) => void }) {
  const sorted = [...setups].sort((a, b) => b.progress_percent - a.progress_percent);
  return (
    <DataTable
      rows={sorted}
      emptyLabel="NO ACTIVE TRACKED SETUPS"
      columns={[
        { header: 'Pair', render: (row) => <button className="text-action" onClick={() => onSelect?.(row)}>{row.symbol}</button> },
        { header: 'Direction', render: (row) => row.direction },
        { header: 'Stage', render: (row) => <StatusBadge label={friendlyStageLabel(row.current_stage ?? row.current_state, row.direction)} tone={row.current_state === 'ENTRY_READY' ? 'ok' : row.progress_percent >= 70 ? 'warn' : 'neutral'} /> },
        { header: 'Execution', render: (row) => { const badge = executionBadge(row); return badge ? <StatusBadge label={badge.label} tone={badge.tone} /> : '-'; } },
        { header: 'Progress', render: (row) => { const pct = row.progress_pct ?? row.progress_percent; return <div className="flex items-center gap-2"><SetupProgressBar value={pct} /><span>{pct.toFixed(0)}%</span></div>; } },
        { header: '16M Swing', render: (row) => row.swing_price ? `${row.direction === 'BULLISH' ? 'Low' : 'High'} @ ${row.swing_price}` : 'WAITING' },
        { header: '16M Expansion', render: (row) => row.expansion_ratio ?? 'WAITING' },
        { header: '16M FVG', render: (row) => row.fvg_16m_status ?? 'WAITING' },
        { header: '12M FVG', render: (row) => row.fvg_12m_status ?? 'WAITING' },
        { header: '8M FVG', render: (row) => row.eight_minute_candle_count_after_16m_fvg ?? 'WAITING' },
        { header: 'Retrace/Entry', render: (row) => row.entry_candle_boundary_respected === true ? 'READY' : 'WAITING' },
        { header: 'Strategy Profile', render: (row) => row.strategy_profile ?? DEFAULT_PRODUCTION_PROFILE },
        { header: 'Timeframe Profile', render: (row) => row.timeframe_profile ?? '-' },
        { header: 'RR/TP Profile', render: (row) => row.selected_tp_model ?? '-' },
        { header: 'Entry Price', render: (row) => row.entry_price ?? '-' },
        { header: 'Stop', render: (row) => row.stop_reference ?? '-' },
        { header: 'Target', render: (row) => row.target_reference ?? '-' },
        { header: 'Started', render: (row) => row.created_at?.replace('T', ' ').slice(0, 19) ?? '-' },
        { header: 'Last Updated', render: (row) => row.updated_at?.replace('T', ' ').slice(0, 19) ?? '-' }
      ]}
    />
  );
}
