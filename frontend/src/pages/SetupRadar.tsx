import { SetupRadarTable } from '../components/radar/SetupRadarTable';
import { SetupHistoryTable } from '../components/radar/SetupHistoryTable';
import type { RadarSetup } from '../types/radar';

const ACTIVE_STATUSES = new Set(['ACTIVE', 'ENTRY_READY']);

export function SetupRadar({ setups, history, onSelect }: { setups: RadarSetup[]; history: RadarSetup[]; onSelect: (setup: RadarSetup) => void }) {
  const active = setups.filter((setup) => ACTIVE_STATUSES.has(setup.status ?? ''));
  const entryReady = active.filter((setup) => setup.status === 'ENTRY_READY');
  const past = history.filter((setup) => !ACTIVE_STATUSES.has(setup.status ?? ''));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-ink">Setup Radar</h1>
        <p className="text-sm text-muted">
          {active.length} active attempt{active.length === 1 ? '' : 's'} ({entryReady.length} entry-ready) · {past.length} in history (latest {history.length} of up to 100 tracked attempts)
        </p>
      </div>
      <div>
        <h2 className="mb-2 text-sm font-semibold uppercase text-muted">Active &amp; Entry-Ready</h2>
        <SetupRadarTable setups={active} onSelect={onSelect} />
      </div>
      <div>
        <h2 className="mb-2 text-sm font-semibold uppercase text-muted">History (failed, expired, completed)</h2>
        <SetupHistoryTable setups={past} onSelect={onSelect} />
      </div>
    </div>
  );
}
