import type { RadarSetup } from '../../types/radar';
import { DataTable } from '../tables/DataTable';
import { StatusBadge } from '../layout/StatusBadge';
import { SetupProgressBar } from './SetupProgressBar';
import { DEFAULT_PRODUCTION_PROFILE } from '../../utils/constants';

export function SetupRadarTable({ setups, onSelect }: { setups: RadarSetup[]; onSelect?: (setup: RadarSetup) => void }) {
  const sorted = [...setups].sort((a, b) => b.progress_percent - a.progress_percent);
  return (
    <DataTable
      rows={sorted}
      emptyLabel="NO ACTIVE TRACKED SETUPS"
      columns={[
        { header: 'Pair', render: (row) => <button className="text-action" onClick={() => onSelect?.(row)}>{row.symbol}</button> },
        { header: 'Type', render: (row) => row.direction },
        { header: 'Timeframe', render: (row) => row.timeframe_profile ?? '-' },
        { header: 'Profile', render: (row) => row.strategy_profile ?? DEFAULT_PRODUCTION_PROFILE },
        { header: 'Variant Range', render: (row) => row.expansion_min != null && row.expansion_max != null ? `${row.expansion_min}-${row.expansion_max}` : '-' },
        { header: '16M FVG', render: (row) => row.fvg_16m_status ?? 'WAITING' },
        { header: 'Expansion', render: (row) => row.expansion_ratio ?? 'WAITING' },
        { header: '12M FVG', render: (row) => row.fvg_12m_status ?? 'WAITING' },
        { header: '8M Count', render: (row) => row.eight_minute_candle_count_after_16m_fvg ?? 'WAITING' },
        { header: '12M Entry', render: (row) => row.entry_candle_boundary_respected === true ? 'READY' : row.first_candle_entered_12m_fvg === false ? 'WAITING' : 'WAITING' },
        { header: 'State', render: (row) => <StatusBadge label={row.current_state} tone={row.current_state === 'ENTRY_READY' ? 'ok' : row.progress_percent >= 70 ? 'warn' : 'neutral'} /> },
        { header: 'Current %', render: (row) => <div className="flex items-center gap-2"><SetupProgressBar value={row.progress_percent} /><span>{row.progress_percent.toFixed(0)}%</span></div> },
        { header: 'One/FVG', render: (row) => row.one_trade_per_fvg_status ?? 'N/A' },
        { header: 'Missing', render: (row) => row.missing_requirements.join(', ') || '-' },
        { header: 'Entry Price', render: (row) => row.entry_price ?? '-' },
        { header: 'Stop', render: (row) => row.stop_reference ?? '-' },
        { header: 'Target', render: (row) => row.target_reference ?? '-' },
        { header: 'Time Added', render: (row) => row.created_at?.replace('T', ' ').slice(0, 19) ?? '-' }
      ]}
    />
  );
}
