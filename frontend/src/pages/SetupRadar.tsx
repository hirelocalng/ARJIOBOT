import { SetupRadarTable } from '../components/radar/SetupRadarTable';
import { SetupHistoryTable } from '../components/radar/SetupHistoryTable';
import type { RadarSetup } from '../types/radar';

// COMPLETED belongs here, not in the Invalidated table below: it means the
// attempt walked every stage to a real entry signal (success), which is the
// opposite of invalidated. Lumping it in with INVALIDATED/EXPIRED is what
// produced setups that looked "100% done" yet displayed a leftover failure
// reason - see _apply_one_attempt_trace in live_setup_detection.py for the
// matching backend fix (stale invalidation_reason is now cleared on resolve).
const IN_PROGRESS_STATUSES = new Set(['ACTIVE', 'ENTRY_READY', 'COMPLETED']);

export function SetupRadar({ setups, history, onSelect }: { setups: RadarSetup[]; history: RadarSetup[]; onSelect: (setup: RadarSetup) => void }) {
  const inProgress = setups.filter((setup) => IN_PROGRESS_STATUSES.has(setup.status ?? ''));
  const entryReady = inProgress.filter((setup) => setup.status === 'ENTRY_READY');
  const invalidated = history.filter((setup) => !IN_PROGRESS_STATUSES.has(setup.status ?? ''));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-ink">Setup Radar</h1>
        <p className="text-sm text-muted">
          {inProgress.length} in progress ({entryReady.length} entry-ready) · {invalidated.length} invalidated (latest {history.length} of up to 100 tracked attempts)
        </p>
      </div>
      <div>
        <h2 className="mb-2 text-sm font-semibold uppercase text-muted">In Progress</h2>
        <SetupRadarTable setups={inProgress} onSelect={onSelect} />
      </div>
      <div>
        <h2 className="mb-2 text-sm font-semibold uppercase text-muted">Invalidated</h2>
        <SetupHistoryTable setups={invalidated} onSelect={onSelect} />
      </div>
    </div>
  );
}
